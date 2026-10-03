from datetime import datetime, timedelta, timezone

import pytest

from app.tools import carregar_tools
from app.tools.registry import spec_de, specs_registradas
from app.tools.sync import sincronizar
from tests.test_f5_analista_tools import CUTOFF
from tests.test_fq5_integration_db import _executar, fq5_mundo

carregar_tools()


async def _issuer(conn, name: str, cnpj: str) -> str:
    cur = await conn.execute(
        "insert into market.issuers (name, cnpj, kind) values (%s,%s,'empresa') returning id::text",
        (name, cnpj),
    )
    return (await cur.fetchone())[0]


async def _action(conn, issuer_id: str, ticker: str) -> str:
    cur = await conn.execute(
        """insert into market.instruments
               (kind,name,ticker,issuer_id,is_in_universe,source_code)
           values ('acao',%s,%s,%s,true,'b3') returning id::text""",
        (ticker, ticker, issuer_id),
    )
    return (await cur.fetchone())[0]


async def _copy_prices(conn, source_id: str, target_id: str, multiplier: float) -> None:
    await conn.execute(
        """insert into market.prices
               (price_date,instrument_id,kind,value,currency,source_code,ingestion_batch_id)
           select price_date,%s,kind,value * %s,currency,source_code,ingestion_batch_id
             from market.prices where instrument_id=%s""",
        (target_id, multiplier, source_id),
    )


async def _fundamentals(
    conn,
    cnpj: str,
    class_shares: list[tuple[str, float]],
    *,
    latest_revenue: float,
    latest_ebitda: float,
    latest_income: float,
    prior_revenue: float,
    prior_ebitda: float,
    prior_income: float,
) -> None:
    prior_ref = CUTOFF.replace(year=CUTOFF.year - 2, month=12, day=31)
    latest_ref = CUTOFF.replace(year=CUTOFF.year - 1, month=12, day=31)
    prior_avail = CUTOFF.replace(year=CUTOFF.year - 1, month=3, day=1)
    latest_avail = CUTOFF - timedelta(days=10)

    for ref, avail, metrics in (
        (
            prior_ref,
            prior_avail,
            {
                "revenue": prior_revenue,
                "ebitda": prior_ebitda,
                "net_income": prior_income,
            },
        ),
        (
            latest_ref,
            latest_avail,
            {
                "revenue": latest_revenue,
                "ebitda": latest_ebitda,
                "net_income": latest_income,
                "total_equity": latest_revenue * 0.5,
                "gross_debt": latest_revenue * 0.25,
                "cash_and_equivalents": latest_revenue * 0.10,
                "free_cash_flow": latest_income * 0.8,
            },
        ),
    ):
        for metric, value in metrics.items():
            await conn.execute(
                """insert into market.fundamentals
                       (company_cnpj,reference_date,availability_date,document_type,scope,
                        period_label,metric,value,value_unit,currency,is_derived,source_code)
                   values (%s,%s,%s,'DFP','consolidated','FY',%s,%s,'brl','BRL',false,'cvm_fundos')""",
                (cnpj, ref, avail, metric, value),
            )

    for iid, shares in class_shares:
        await conn.execute(
            """insert into market.fundamentals
                   (company_cnpj,instrument_id,reference_date,availability_date,document_type,scope,
                    period_label,metric,value,value_unit,currency,is_derived,source_code)
               values (%s,%s,%s,%s,'DFP','consolidated','FY',
                       'shares_outstanding',%s,'shares',null,false,'cvm_fundos')""",
            (cnpj, iid, latest_ref, latest_avail, shares),
        )


async def _sector_batch(conn, suffix: str) -> str:
    finished = datetime.combine(CUTOFF, datetime.min.time(), tzinfo=timezone.utc)
    cur = await conn.execute(
        """insert into market.ingestion_batches
               (source_code,dataset,reference_date,file_hash,status,finished_at,rows_ingested)
           values ('b3','b3.sector_classification@1',%s,%s,'succeeded',%s,1)
           returning id::text""",
        (CUTOFF - timedelta(days=1), (suffix * 64)[:64], finished),
    )
    return (await cur.fetchone())[0]


async def _sector(conn, iid: str, batch: str, *, subsector: str) -> None:
    await conn.execute(
        """insert into market.sector_classification
               (instrument_id,source_code,reference_date,economic_sector,subsector,segment,
                listing_segment,ingestion_batch_id)
           values (%s,'b3',%s,'Energia',%s,null,null,%s)""",
        (iid, CUTOFF - timedelta(days=1), subsector, batch),
    )


@pytest.mark.asyncio
async def test_peer_comparison_shadow_reuses_canonical_metrics_and_dedupes_company(db, fq5_mundo):
    ids = fq5_mundo["ids"]
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="6" * 40)

        peer_a = await _issuer(conn, "Peer Alpha", "44000000000101")
        pa3 = await _action(conn, peer_a, "PEAA3")
        pa4 = await _action(conn, peer_a, "PEAA4")
        peer_b = await _issuer(conn, "Peer Beta", "44000000000102")
        pb3 = await _action(conn, peer_b, "PEBB3")
        broad = await _issuer(conn, "Peer Setorial", "44000000000103")
        ps3 = await _action(conn, broad, "PSET3")

        await _copy_prices(conn, ids["FQ5ON"], pa3, 0.70)
        await _copy_prices(conn, ids["FQ5ON"], pa4, 0.75)
        await _copy_prices(conn, ids["FQ5ON"], pb3, 1.20)
        await _copy_prices(conn, ids["FQ5ON"], ps3, 0.90)

        await _fundamentals(
            conn,
            "44000000000101",
            [(pa3, 1_000_000_000.0), (pa4, 500_000_000.0)],
            latest_revenue=100_000_000_000.0,
            latest_ebitda=20_000_000_000.0,
            latest_income=8_000_000_000.0,
            prior_revenue=80_000_000_000.0,
            prior_ebitda=16_000_000_000.0,
            prior_income=6_000_000_000.0,
        )
        await _fundamentals(
            conn,
            "44000000000102",
            [(pb3, 1_200_000_000.0)],
            latest_revenue=120_000_000_000.0,
            latest_ebitda=30_000_000_000.0,
            latest_income=12_000_000_000.0,
            prior_revenue=100_000_000_000.0,
            prior_ebitda=24_000_000_000.0,
            prior_income=10_000_000_000.0,
        )
        await _fundamentals(
            conn,
            "44000000000103",
            [(ps3, 800_000_000.0)],
            latest_revenue=90_000_000_000.0,
            latest_ebitda=18_000_000_000.0,
            latest_income=7_000_000_000.0,
            prior_revenue=75_000_000_000.0,
            prior_ebitda=15_000_000_000.0,
            prior_income=6_000_000_000.0,
        )

        batch = await _sector_batch(conn, "a")
        for iid in (ids["FQ5ON"], ids["FQ5PN"], pa3, pa4, pb3):
            await _sector(conn, iid, batch, subsector="Petroleo")
        await _sector(conn, ps3, batch, subsector="Distribuicao")

    out = (
        await _executar(
            db,
            fq5_mundo,
            "quant.comparaveis_setor",
            {
                "ticker": "FQ5ON",
                "metricas": ["pe", "revenue_yoy_pct", "ebitda_margin_pct"],
                "max_exemplos": 1,
            },
        )
    ).output
    assert out.nivel == "subsetor"
    assert out.classificacao == "Petroleo"
    assert out.peer_count_total == 2
    assert len(out.peer_examples) == 1
    assert out.peer_examples_criterion == "ordem_alfabetica"
    assert out.peer_examples[0].issuer_name == "Peer Alpha"

    target_val = (await _executar(db, fq5_mundo, "quant.valor_mercado", {"ticker": "FQ5ON"})).output
    pa_val = (await _executar(db, fq5_mundo, "quant.valor_mercado", {"ticker": "PEAA3"})).output
    pb_val = (await _executar(db, fq5_mundo, "quant.valor_mercado", {"ticker": "PEBB3"})).output
    pe = next(x for x in out.comparacoes if x.metric == "pe")
    assert pe.target_value == pytest.approx(target_val.multiples.pe)
    assert pe.n_valid == 2
    assert pe.median == pytest.approx((pa_val.multiples.pe + pb_val.multiples.pe) / 2)
    assert pe.delta_target_vs_median == pytest.approx(pe.target_value - pe.median)

    target_trend = (
        await _executar(
            db,
            fq5_mundo,
            "quant.tendencias_fundamentais",
            {"ticker": "FQ5ON", "periodos": 2, "metricas": ["revenue", "ebitda", "net_income"]},
        )
    ).output
    revenue = next(x for x in out.comparacoes if x.metric == "revenue_yoy_pct")
    target_revenue = next(x for x in target_trend.metricas if x.metric == "revenue")
    assert revenue.target_value == pytest.approx(target_revenue.growth_pct)
    assert revenue.n_valid == 2
    assert revenue.delta_unit == "p.p."
    assert out.evidencia.suficiente is True

    broad_out = (
        await _executar(
            db,
            fq5_mundo,
            "quant.comparaveis_setor",
            {"ticker": "FQ5ON", "nivel": "setor", "metricas": ["pe"]},
        )
    ).output
    assert broad_out.classificacao == "Energia"
    assert broad_out.peer_count_total == 3


def test_peer_comparison_promoted_without_changing_existing_public_contracts():
    spec = spec_de("quant.comparaveis_setor")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    assert spec.requires_market_data is True
    assert spec_de("quant.valor_mercado").semver == "1.0.0"
    assert spec_de("quant.tendencias_fundamentais").semver == "1.0.1"
    assert spec_de("quant.dependencia").semver == "2.0.0"
