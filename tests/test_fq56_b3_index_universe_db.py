from datetime import date
from decimal import Decimal

import pytest

from app.market.b3_index_source import B3IndexPortfolioRecord
from app.market.index_portfolios import (
    IBRA_DATASET,
    IndexPortfolioConflict,
    ingest_b3_index_portfolio,
    project_current_equity_universe,
)


async def _issuer(conn, name: str, cnpj: str):
    cur = await conn.execute(
        "insert into market.issuers (name, cnpj, kind) values (%s, %s, 'empresa') returning id::text",
        (name, cnpj),
    )
    return (await cur.fetchone())[0]


async def _action(conn, issuer_id: str, ticker: str, in_universe: bool = False):
    cur = await conn.execute(
        """insert into market.instruments
               (kind, name, ticker, issuer_id, is_in_universe, source_code)
           values ('acao', %s, %s, %s, %s, 'b3') returning id::text""",
        (ticker, ticker, issuer_id, in_universe),
    )
    return (await cur.fetchone())[0]


def _record(ticker: str, weight: str, qty: str) -> B3IndexPortfolioRecord:
    return B3IndexPortfolioRecord(
        ticker=ticker,
        name=ticker,
        security_type="ON NM",
        theoretical_qty=Decimal(qty),
        weight_pct=Decimal(weight),
    )


@pytest.mark.asyncio
async def test_ibra_ingest_and_projection_define_current_equity_universe(db):
    ref = date(2026, 10, 2)
    async with db.service_session() as conn:
        cur = await conn.execute("select source_code from market.index_definitions where code='ibra'")
        assert (await cur.fetchone())[0] == "b3"

        a = await _issuer(conn, "Universe A", "33333333000101")
        b = await _issuer(conn, "Universe B", "33333333000102")
        c = await _issuer(conn, "Universe C", "33333333000103")
        a3 = await _action(conn, a, "UVRA3", False)
        b3 = await _action(conn, b, "UVRB3", False)
        c3 = await _action(conn, c, "UVRC3", True)
        cur = await conn.execute(
            """insert into market.instruments
                   (kind, name, ticker, is_in_universe, source_code)
               values ('etf', 'Universe ETF', 'UVRE11', true, 'b3') returning id::text"""
        )
        etf_id = (await cur.fetchone())[0]

        report = await ingest_b3_index_portfolio(
            conn,
            [_record("UVRA3", "60.000", "1000"), _record("UVRB3", "40.000", "2000")],
            index_code="ibra",
            reference_date=ref,
            file_hash="c" * 64,
            dataset=IBRA_DATASET,
        )
        assert report.matched_instruments == 2
        assert report.rows_inserted == 2

        projection = await project_current_equity_universe(conn, reference_date=ref)
        assert projection.members == 2
        assert projection.set_true == 2
        assert projection.set_false >= 1

        cur = await conn.execute(
            "select id::text, is_in_universe from market.instruments where id = any(%s::uuid[]) order by id",
            ([a3, b3, c3],),
        )
        state = {iid: flag for iid, flag in await cur.fetchall()}
        assert state[a3] is True
        assert state[b3] is True
        assert state[c3] is False
        cur = await conn.execute("select is_in_universe from market.instruments where id=%s", (etf_id,))
        assert (await cur.fetchone())[0] is True

        projection_again = await project_current_equity_universe(conn, reference_date=ref)
        assert projection_again.set_true == 0
        assert projection_again.set_false == 0

        again = await ingest_b3_index_portfolio(
            conn,
            [_record("UVRA3", "60.000", "1000"), _record("UVRB3", "40.000", "2000")],
            index_code="ibra",
            reference_date=ref,
            file_hash="c" * 64,
            dataset=IBRA_DATASET,
        )
        assert again.reused_existing_batch is True


@pytest.mark.asyncio
async def test_ibra_ingest_fails_before_weights_if_any_ticker_is_missing(db):
    ref = date(2026, 10, 2)
    async with db.service_session() as conn:
        issuer = await _issuer(conn, "Universe D", "33333333000104")
        await _action(conn, issuer, "UVRD3", False)

        with pytest.raises(IndexPortfolioConflict, match="ticker_sem_instrumento"):
            await ingest_b3_index_portfolio(
                conn,
                [_record("UVRD3", "50.000", "100"), _record("MISS3", "50.000", "100")],
                index_code="ibra",
                reference_date=ref,
                file_hash="d" * 64,
                dataset=IBRA_DATASET,
            )
        cur = await conn.execute(
            "select count(*) from market.index_weights where index_code='ibra' and reference_date=%s",
            (ref,),
        )
        assert (await cur.fetchone())[0] == 0
