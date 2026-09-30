"""Integração PostgreSQL do FQ5 Fundamentals + Valuation + Macro Factors.

Prova migrations, unidade de fundamentos, multi-classe, cutoff PIT, executor/cache e o adapter
USD/BRL sem tocar em dados remotos. Toda massa vive na transação do fixture `db`.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.config.policies import PolicyStore
from app.db.repos import policies as policies_repo
from app.jobs import tasks
from app.tools import carregar_tools
from app.tools.executor import executar_tool
from app.tools.registry import spec_de, specs_registradas
from app.tools.sync import sincronizar
from tests.test_f5_analista import POLICY_INGESTAO, fixture_cotahist_unica
from tests.test_f5_analista_tools import ANALISE_PARAMS, CUTOFF

carregar_tools()


@pytest.fixture
async def fq5_mundo(db, escopos, tmp_path):
    e = escopos
    ids: dict[str, str] = {}
    cnpj = "33000167000101"

    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="5" * 40)
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", ANALISE_PARAMS)
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=e.u1)
        await policies_repo.set_policy(conn, "MERCADO_INGESTAO", POLICY_INGESTAO)

        cur = await conn.execute(
            "insert into market.issuers (name, cnpj, kind) values ('FQ5 Energia SA', %s, 'empresa') returning id::text",
            (cnpj,),
        )
        issuer_id = (await cur.fetchone())[0]

        for ticker, nome, issuer in (
            ("F5PETR", "Doador F5 Petróleo", None),
            ("F5VALE", "Doador F5 Mineração", None),
            ("F5BOVA", "Doador F5 ETF", None),
            ("FQ5ON", "FQ5 Energia ON", issuer_id),
            ("FQ5PN", "FQ5 Energia PN", issuer_id),
        ):
            kind = "etf" if ticker == "F5BOVA" else "acao"
            cur = await conn.execute(
                """insert into market.instruments
                       (kind, name, ticker, issuer_id, is_in_universe, source_code)
                   values (%s::market.instrument_kind, %s, %s, %s, true, 'b3') returning id::text""",
                (kind, nome, ticker, issuer),
            )
            ids[ticker] = (await cur.fetchone())[0]

        await conn.execute(
            """insert into market.index_definitions
                   (code, display_name, unit, source_code, sgs_series_id)
               values ('fq5_selic', 'Selic variável FQ5', 'taxa_aa', 'bacen_sgs', 1178)"""
        )

    ing = await tasks.ingerir_cotahist(
        {"db": db, "policies": PolicyStore(db, ttl_s=0)},
        arquivo=str(fixture_cotahist_unica(tmp_path)),
    )
    assert ing["rows_ingested"] == 34

    async with db.service_session() as conn:
        for ticker, multiplier in (("FQ5ON", 1.0), ("FQ5PN", 1.1)):
            await conn.execute(
                """insert into market.prices
                       (price_date, instrument_id, kind, value, currency, source_code, ingestion_batch_id)
                   select p.price_date, %s, p.kind, p.value * %s, p.currency, p.source_code, p.ingestion_batch_id
                     from market.prices p
                     join market.instruments i on i.id = p.instrument_id
                    where i.ticker = 'F5PETR' and p.ingestion_batch_id = %s""",
                (ids[ticker], multiplier, ing["batch_id"]),
            )

        cur = await conn.execute(
            "select distinct price_date from market.prices where instrument_id = %s order by price_date",
            (ids["FQ5ON"],),
        )
        datas = [row[0] for row in await cur.fetchall()]
        assert len(datas) == 12
        selic = [10.00, 10.25, 10.10, 10.40, 10.20, 10.55, 10.35, 10.70, 10.45, 10.80, 10.60, 10.95]
        usdbrl = [4.90, 4.93, 4.91, 4.97, 4.95, 5.01, 4.99, 5.06, 5.03, 5.10, 5.07, 5.14]
        for d, rate, fx in zip(datas, selic, usdbrl):
            await conn.execute(
                "insert into market.index_values (index_code, value_date, value) values ('fq5_selic', %s, %s)",
                (d, rate),
            )
            await conn.execute(
                """insert into market.fx_rates
                       (base_currency, quote_currency, rate_date, rate, source_code)
                   values ('USD', 'BRL', %s, %s, 'bacen_sgs')""",
                (d, fx),
            )

        common = (cnpj, date(2023, 12, 31), "DFP", "consolidated", "FY")
        company_metrics = (
            ("net_income", 12_000_000_000.0),
            ("ebitda", 30_000_000_000.0),
            ("total_equity", 80_000_000_000.0),
            ("gross_debt", 50_000_000_000.0),
            ("cash_and_equivalents", 20_000_000_000.0),
            ("free_cash_flow", 10_000_000_000.0),
        )
        for metric, value in company_metrics:
            await conn.execute(
                """insert into market.fundamentals
                       (company_cnpj, reference_date, availability_date, document_type, scope,
                        period_label, metric, value, value_unit, currency, is_derived, source_code)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, 'brl', 'BRL', false, 'cvm_fundos')""",
                (*common[:2], date(2024, 1, 10), *common[2:], metric, value),
            )
        for iid, shares in ((ids["FQ5ON"], 2_000_000_000.0), (ids["FQ5PN"], 3_000_000_000.0)):
            await conn.execute(
                """insert into market.fundamentals
                       (company_cnpj, instrument_id, reference_date, availability_date, document_type, scope,
                        period_label, metric, value, value_unit, currency, is_derived, source_code)
                   values (%s, %s, %s, %s, 'DFP', 'consolidated', 'FY',
                           'shares_outstanding', %s, 'shares', null, false, 'cvm_fundos')""",
                (cnpj, iid, date(2023, 12, 31), date(2024, 1, 10), shares),
            )
        await conn.execute(
            """insert into market.fundamentals
                   (company_cnpj, reference_date, availability_date, document_type, scope,
                    period_label, metric, value, value_unit, currency, is_derived, source_code)
               values (%s, %s, %s, 'DFP', 'consolidated', 'FY',
                       'net_income', 99000000000, 'brl', 'BRL', false, 'cvm_fundos')""",
            (cnpj, date(2023, 12, 31), date(2024, 2, 20)),
        )

    return {"e": e, "ids": ids, "cnpj": cnpj, "batch_id": ing["batch_id"]}


async def _executar(db, mundo, code: str, params: dict):
    e = mundo["e"]
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        return await executar_tool(
            conn,
            code,
            params,
            scope_id=e.s1,
            conversation_id=None,
            cutoff_date=CUTOFF,
        )


def test_fq5_promovido_registrado_sem_alterar_fq4_publico():
    for code in (
        "dados.fundamentos_empresa",
        "quant.valor_mercado",
        "quant.cenario_sensibilidade",
    ):
        spec = spec_de(code)
        assert spec.semver == "1.0.0"
        assert spec.exposed_to_llm is True
        assert spec.requires_market_data is True
    assert spec_de("quant.sensibilidade").semver == "1.0.1"
    assert spec_de("quant.dependencia").semver == "2.0.0"
    macro = spec_de("quant.dependencia_macro")
    assert macro.semver == "1.0.1" and macro.exposed_to_llm is False


async def test_fq5_fundamentos_e_valuation_multiclasse_pit(db, fq5_mundo):
    fundamentals = await _executar(db, fq5_mundo, "dados.fundamentos_empresa", {"ticker": "FQ5ON"})
    assert fundamentals.output.company_cnpj == fq5_mundo["cnpj"]
    assert fundamentals.output.evidencia.suficiente is True
    lucro = [x for x in fundamentals.output.fundamentos if x.metric == "net_income"]
    assert len(lucro) == 1
    assert lucro[0].value == 12_000_000_000.0
    assert lucro[0].availability_date == date(2024, 1, 10)
    shares = [x for x in fundamentals.output.fundamentos if x.metric == "shares_outstanding"]
    assert {(x.instrument_id, x.value) for x in shares} == {
        (fq5_mundo["ids"]["FQ5ON"], 2_000_000_000.0),
        (fq5_mundo["ids"]["FQ5PN"], 3_000_000_000.0),
    }

    valuation = await _executar(db, fq5_mundo, "quant.valor_mercado", {"ticker": "FQ5ON"})
    out = valuation.output
    assert out.requested_price_brl is not None
    assert out.requested_price_date == CUTOFF
    assert len(out.classes) == 2 and all(x.complete for x in out.classes)
    expected_cap = sum((x.price_brl or 0) * (x.shares_outstanding or 0) for x in out.classes)
    assert out.market_cap_brl == pytest.approx(expected_cap)
    assert out.net_debt_brl == pytest.approx(30_000_000_000.0)
    assert out.net_debt_source == "derived_gross_debt_minus_cash"
    assert out.enterprise_value_brl == pytest.approx(expected_cap + 30_000_000_000.0)
    assert out.multiples.pe == pytest.approx(expected_cap / 12_000_000_000.0)
    assert out.multiples.ev_ebitda == pytest.approx((expected_cap + 30_000_000_000.0) / 30_000_000_000.0)
    assert out.intrinsic_value_produced is False
    assert out.evidencia.suficiente is True


async def test_fq5_cenario_juros_e_dependencia_cambio_end_to_end(db, fq5_mundo):
    scenario = await _executar(
        db, fq5_mundo, "quant.cenario_sensibilidade",
        {"ticker": "FQ5ON", "indice_driver": "fq5_selic", "choque_driver": 1.0},
    )
    assert scenario.output.driver == "fq5_selic"
    assert scenario.output.unidade_choque == "pontos_percentuais"
    assert scenario.output.base_price_date == CUTOFF
    assert scenario.output.n >= 5
    assert scenario.output.sensibilidade is not None
    assert scenario.output.impacto_incremental_pct == pytest.approx(scenario.output.sensibilidade)
    assert scenario.output.scenario_price_brl is not None
    assert "cenario_associacional_nao_previsao" in scenario.output.evidencia.avisos

    fx = await _executar(
        db, fq5_mundo, "quant.dependencia",
        {"ticker_a": "FQ5ON", "serie_b": {"tipo": "cambio", "codigo": "USD/BRL"}},
    )
    assert fx.output.tipo_b == "cambio"
    assert fx.output.par == "FQ5ON × USD/BRL"
    assert fx.output.n_pares >= 5
    assert fx.output.coeficiente is not None
    assert -1 <= fx.output.coeficiente <= 1
    assert "fx_observation_date_cutoff_sem_vintage" in fx.output.evidencia.avisos
    assert "bacen_sgs" in fx.output.evidencia.fonte

    ids = [scenario.execution_id, fx.execution_id]
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select count(*) from tools.tool_executions where id = any(%s::uuid[]) and status = 'succeeded'",
            (ids,),
        )
        assert (await cur.fetchone())[0] == 2


async def test_fq5_executor_cacheia_valor_mercado(db, fq5_mundo):
    params = {"ticker": "FQ5ON"}
    first = await _executar(db, fq5_mundo, "quant.valor_mercado", params)
    second = await _executar(db, fq5_mundo, "quant.valor_mercado", params)
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.execution_id != first.execution_id
    assert second.output.model_dump(mode="json") == first.output.model_dump(mode="json")
