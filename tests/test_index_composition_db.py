from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.market.b3_index_source import B3IndexPortfolioRecord
from app.market.index_compositions import load_index_composition
from app.market.index_portfolios import IBRA_DATASET, ingest_b3_index_portfolio
from app.tools.analista.composicao_indice import (
    ComposicaoIndiceResolvida,
    montar_composicao_indice,
)


async def _issuer(conn, name: str, cnpj: str):
    cur = await conn.execute(
        "insert into market.issuers (name, cnpj, kind) values (%s, %s, 'empresa') returning id::text",
        (name, cnpj),
    )
    return (await cur.fetchone())[0]


async def _action(conn, issuer_id: str, ticker: str):
    cur = await conn.execute(
        """insert into market.instruments
               (kind, name, ticker, issuer_id, is_in_universe, source_code)
           values ('acao', %s, %s, %s, false, 'b3') returning id::text""",
        (ticker, ticker, issuer_id),
    )
    return (await cur.fetchone())[0]


def _record(ticker: str, weight: str, qty: str):
    return B3IndexPortfolioRecord(
        ticker=ticker,
        name=ticker,
        security_type="ON NM",
        theoretical_qty=Decimal(qty),
        weight_pct=Decimal(weight),
    )


@pytest.mark.asyncio
async def test_index_composition_loader_reuses_official_snapshot_and_tool_is_compact(db):
    ref = date(2026, 10, 2)
    async with db.service_session() as conn:
        a = await _issuer(conn, "Index A", "44444444000101")
        b = await _issuer(conn, "Index B", "44444444000102")
        c = await _issuer(conn, "Index C", "44444444000103")
        await _action(conn, a, "IDXA3")
        await _action(conn, b, "IDXB3")
        await _action(conn, c, "IDXC3")

        await ingest_b3_index_portfolio(
            conn,
            [
                _record("IDXA3", "60.000", "1000"),
                _record("IDXB3", "30.000", "2000"),
                _record("IDXC3", "10.000", "3000"),
            ],
            index_code="ibra",
            reference_date=ref,
            file_hash="e" * 64,
            dataset=IBRA_DATASET,
        )

        resolved = await load_index_composition(
            conn,
            "ibra",
            cutoff=date(2026, 10, 3),
            strict_pit=True,
        )
        assert resolved.reference_date == ref
        assert resolved.display_name == "Índice Brasil Amplo B3"
        assert resolved.total_weight_pct == pytest.approx(100.0)
        assert [m.ticker for m in resolved.members] == ["IDXA3", "IDXB3", "IDXC3"]
        assert resolved.provenance.source_codes == ["b3"]
        assert resolved.provenance.strict_pit is True

        out = montar_composicao_indice(
            ComposicaoIndiceResolvida(
                composition=resolved,
                requested_tickers=["IDXB3", "MISS3"],
                limite=10,
            )
        )
        assert [m.ticker for m in out.componentes] == ["IDXB3"]
        assert "ticker_fora_da_carteira:MISS3" in out.provenance.warnings


@pytest.mark.asyncio
async def test_index_composition_strict_pit_hides_late_batch_and_explicit_date_does_not_fallback(db):
    ref = date(2026, 9, 20)
    available_late = datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)
    async with db.service_session() as conn:
        issuer = await _issuer(conn, "Late Index", "44444444000104")
        iid = await _action(conn, issuer, "LATE3")
        cur = await conn.execute(
            """insert into market.ingestion_batches
                   (source_code,dataset,reference_date,file_hash,status,finished_at,rows_ingested)
               values ('b3',%s,%s,%s,'succeeded',%s,1)
               returning id::text""",
            (IBRA_DATASET, ref, "f" * 64, available_late),
        )
        batch = (await cur.fetchone())[0]
        await conn.execute(
            """insert into market.index_weights
                   (index_code,reference_date,instrument_id,weight_pct,theoretical_qty,ingestion_batch_id)
               values ('ibra',%s,%s,100,1000,%s)""",
            (ref, iid, batch),
        )

        hidden = await load_index_composition(
            conn,
            "ibra",
            cutoff=date(2026, 9, 30),
            reference_date=ref,
            strict_pit=True,
        )
        assert hidden.members == []
        assert "composicao_indice_indisponivel" in hidden.provenance.warnings

        visible = await load_index_composition(
            conn,
            "ibra",
            cutoff=date(2026, 10, 3),
            reference_date=ref,
            strict_pit=True,
        )
        assert [m.ticker for m in visible.members] == ["LATE3"]
        assert visible.provenance.availability_date == date(2026, 10, 2)

        missing_exact = await load_index_composition(
            conn,
            "ibra",
            cutoff=date(2026, 10, 3),
            reference_date=date(2026, 9, 21),
            strict_pit=True,
        )
        assert missing_exact.reference_date == date(2026, 9, 21)
        assert missing_exact.members == []
        assert "composicao_indice_indisponivel" in missing_exact.provenance.warnings
