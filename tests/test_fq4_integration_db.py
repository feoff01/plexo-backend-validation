"""Integração PostgreSQL das quatro tools FQ4 em shadow mode.

Este arquivo prova o caminho real do backend contra PostgreSQL: sync de tool_versions, policies,
MarketSeriesLoader/views, preparar(), hash/cache, calcular(), tool_executions e output final.
Toda massa nasce dentro da transação externa do fixture `db` e é rollbackada ao fim do teste.
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
async def fq4_mundo(db, escopos, tmp_path):
    """Universo controlado usando schema/views/loaders reais do Postgres.

    Reutiliza a pequena fixture COTAHIST do F5 e cria um índice de taxa variável para exercitar
    condição, sensibilidade e regimes. Nada depende de Aiven/produção.
    """
    e = escopos
    ids: dict[str, str] = {}

    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="4" * 40)
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", ANALISE_PARAMS)
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=e.u1)
        await policies_repo.set_policy(conn, "MERCADO_INGESTAO", POLICY_INGESTAO)

        # F5* são os tickers presentes na fixture COTAHIST; F4* são os instrumentos usados pelos
        # asserts deste gate. Manter ambos deixa a ingestão real intacta e permite copiar a mesma
        # trajetória para um namespace exclusivo do FQ4.
        for ticker, nome, kind in (
            ("F5PETR", "Doador F5 Petróleo", "acao"),
            ("F5VALE", "Doador F5 Mineração", "acao"),
            ("F5BOVA", "Doador F5 ETF", "etf"),
            ("F4PETR", "F4 Petróleo PN", "acao"),
            ("F4VALE", "F4 Mineração ON", "acao"),
            ("F4BOVA", "F4 ETF Ibovespa", "etf"),
        ):
            cur = await conn.execute(
                "insert into market.instruments (kind, name, ticker, is_in_universe, source_code) "
                "values (%s::market.instrument_kind, %s, %s, true, 'b3') returning id::text",
                (kind, nome, ticker),
            )
            ids[ticker] = (await cur.fetchone())[0]

        await conn.execute(
            "insert into market.index_definitions (code, display_name, unit, source_code, sgs_series_id) "
            "values ('f4_selic', 'Selic variável de teste', 'taxa_aa', 'bacen_sgs', 1178)"
        )

    # A fixture COTAHIST usa tickers F5*. Projetamos a mesma sequência de preços nos F4* para
    # manter este teste independente dos asserts/catalogo exato do F5.
    ing = await tasks.ingerir_cotahist(
        {"db": db, "policies": PolicyStore(db, ttl_s=0)},
        arquivo=str(fixture_cotahist_unica(tmp_path)),
    )
    assert ing["rows_ingested"] == 34

    async with db.service_session() as conn:
        # Copia os fechamentos canários já ingeridos para os instrumentos F4*.
        for destino, origem in (("F4PETR", "F5PETR"), ("F4VALE", "F5VALE"), ("F4BOVA", "F5BOVA")):
            await conn.execute(
                """insert into market.prices
                       (price_date, instrument_id, kind, value, source_code, ingestion_batch_id)
                   select p.price_date, %s, p.kind, p.value, p.source_code, p.ingestion_batch_id
                     from market.prices p
                     join market.instruments i on i.id = p.instrument_id
                    where i.ticker = %s and p.ingestion_batch_id = %s""",
                (ids[destino], origem, ing["batch_id"]),
            )

        cur = await conn.execute(
            "select distinct price_date from market.prices where instrument_id = %s order by price_date",
            (ids["F4PETR"],),
        )
        datas = [r[0] for r in await cur.fetchall()]
        # Alterna subida/queda de nível para garantir os dois regimes e variância no driver.
        valores = [10.00, 10.25, 10.10, 10.40, 10.20, 10.55, 10.35, 10.70, 10.45, 10.80, 10.60, 10.95]
        assert len(datas) == len(valores)
        await conn.executemany(
            "insert into market.index_values (index_code, value_date, value) values ('f4_selic', %s, %s)",
            list(zip(datas, valores)),
        )

    return {"e": e, "ids": ids, "batch_id": ing["batch_id"]}


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


def test_fq4_shadows_estao_registradas_mas_ocultas() -> None:
    for code in (
        "quant.analise_condicional",
        "quant.sensibilidade",
        "quant.regimes",
        "quant.event_study_v2",
    ):
        spec = spec_de(code)
        assert spec.exposed_to_llm is False
        assert spec.family == "quant"
        assert spec.requires_market_data is True


async def test_fq4_shadow_tools_executam_end_to_end_no_postgres(db, fq4_mundo):
    cond = await _executar(
        db,
        fq4_mundo,
        "quant.analise_condicional",
        {
            "ticker": "F4PETR",
            "indice_condicao": "f4_selic",
            "direcao": "alta",
        },
    )
    assert cond.output.ticker == "F4PETR"
    assert cond.output.evidencia.index_codes == ["f4_selic"]
    assert cond.output.evidencia.n_observacoes >= 10
    assert cond.output.condicional.n > 0

    sens = await _executar(
        db,
        fq4_mundo,
        "quant.sensibilidade",
        {
            "ticker": "F4PETR",
            "indice_driver": "f4_selic",
        },
    )
    assert sens.output.ticker == "F4PETR"
    assert sens.output.driver == "f4_selic"
    assert sens.output.beta is not None
    assert sens.output.n_pares >= 3
    assert "sensibilidade" in sens.output.evidencia.estimativas

    regimes = await _executar(
        db,
        fq4_mundo,
        "quant.regimes",
        {
            "ticker": "F4PETR",
            "indice_driver": "f4_selic",
            "criterio": "direcao",
        },
    )
    assert regimes.output.ticker == "F4PETR"
    assert regimes.output.regime_a.n > 0
    assert regimes.output.regime_b.n > 0
    assert regimes.output.n_total >= regimes.output.regime_a.n + regimes.output.regime_b.n

    evento = await _executar(
        db,
        fq4_mundo,
        "quant.event_study_v2",
        {
            "ticker": "F4PETR",
            "benchmark": "F4BOVA",
            "data_evento": "2024-01-15",
            "janela_estimacao_observacoes": 6,
            "pre_observacoes": 1,
            "pos_observacoes": 1,
            "inferencia": "classic_iid_normal",
        },
    )
    assert evento.output.ticker == "F4PETR"
    assert evento.output.benchmark == "F4BOVA"
    assert evento.output.data_evento_efetiva is not None
    assert evento.output.car_pct is not None
    assert evento.output.janela_estimacao.n == 6
    assert evento.output.janela_evento.n >= 2
    assert evento.output.car_estimate is not None

    # O caminho passou pelo executor real e persistiu uma execução por tool dentro da transação.
    ids = [cond.execution_id, sens.execution_id, regimes.execution_id, evento.execution_id]
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select count(*) from tools.tool_executions where id = any(%s::uuid[]) and status = 'succeeded'",
            (ids,),
        )
        assert (await cur.fetchone())[0] == 4


async def test_fq4_executor_cacheia_mesmo_input_resolvido(db, fq4_mundo):
    params = {"ticker": "F4PETR", "indice_driver": "f4_selic"}
    primeiro = await _executar(db, fq4_mundo, "quant.sensibilidade", params)
    segundo = await _executar(db, fq4_mundo, "quant.sensibilidade", params)

    assert primeiro.cache_hit is False
    assert segundo.cache_hit is True
    assert segundo.output.model_dump(mode="json") == primeiro.output.model_dump(mode="json")
    assert segundo.execution_id != primeiro.execution_id
