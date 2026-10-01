from decimal import Decimal

import pytest

from app.market.economatica_coverage import measure_economatica_catalog_coverage
from app.market.economatica_sector_source import EconomaticaSectorRecord


async def _issuer(conn, name: str, cnpj: str) -> str:
    cur = await conn.execute(
        "insert into market.issuers (name,cnpj,kind) values (%s,%s,'empresa') returning id::text",
        (name, cnpj),
    )
    return (await cur.fetchone())[0]


async def _action(conn, issuer_id: str | None, ticker: str, in_universe: bool) -> str:
    cur = await conn.execute(
        """insert into market.instruments
               (kind,name,ticker,issuer_id,is_in_universe,source_code)
           values ('acao',%s,%s,%s,%s,'b3') returning id::text""",
        (ticker, ticker, issuer_id, in_universe),
    )
    return (await cur.fetchone())[0]


@pytest.mark.asyncio
async def test_coverage_is_company_level_and_separates_catalog_gaps(db):
    async with db.service_session() as conn:
        issuer_a = await _issuer(conn, "Coverage A", "22222222000101")
        issuer_b = await _issuer(conn, "Coverage B", "22222222000102")
        issuer_d = await _issuer(conn, "Coverage D", "22222222000104")

        await _action(conn, issuer_a, "CVA3", True)
        await _action(conn, issuer_a, "CVA4", False)
        await _action(conn, issuer_b, "CVB3", False)
        await _action(conn, None, "CVC3", False)
        await _action(conn, issuer_d, "CVD3", True)

        report = await measure_economatica_catalog_coverage(
            conn,
            [
                EconomaticaSectorRecord("CVA4", "Energia", "Petróleo"),
                EconomaticaSectorRecord("CVB3", "Financeiro", "Bancos"),
                EconomaticaSectorRecord("CVC3", "Outros", "Outros"),
                EconomaticaSectorRecord("MISSING3", "Saúde", "Serviços"),
            ],
        )

        assert report.records_received == 4
        assert report.economic_sector_filled == 4
        assert report.subsector_filled == 4
        assert report.matched_tickers == 3
        assert report.unmatched_tickers == ["MISSING3"]
        assert report.tickers_without_issuer == ["CVC3"]
        assert report.matched_issuers == 2
        assert report.matched_issuers_in_universe == 1
        assert report.issuers_outside_universe == 1
        # seed dev já possui ações no universo sem issuer; o denominador é somente issuer ligado.
        assert report.eligible_universe_issuers: == 2
        assert report.covered_universe_issuers == 1
        assert report.uncovered_universe_issuers == 1
        assert report.universe_coverage_pct == Decimal("50.00")
        assert report.issuer_outside_universe_examples == ["Coverage B"]
        assert report.uncovered_universe_examples == ["Coverage D"]
        assert "economatica_tickers_nao_encontrados" in report.warnings
        assert "economatica_tickers_sem_issuer" in report.warnings
        assert "economatica_issuers_fora_do_universo" in report.warnings
        assert "economatica_cobertura_universo_incompleta" in report.warnings


@pytest.mark.asyncio
async def test_coverage_deduplicates_same_ticker_input(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, "Coverage Unique", "22222222000105")
        await _action(conn, issuer, "CVU3", True)
        record = EconomaticaSectorRecord("cvu3", "Industrial", "Máquinas")
        report = await measure_economatica_catalog_coverage(conn, [record, record])
        assert report.records_received == 1
        assert report.matched_tickers == 1
        assert report.matched_issuers == 1
