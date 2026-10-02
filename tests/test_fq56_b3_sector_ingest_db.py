from datetime import date

import pytest

from app.market.b3_sector_source import B3SectorDownloadRecord
from app.market.sector_ingest_b3_download import (
    B3SectorCodeAmbiguity,
    ingest_b3_sector_download_records,
    resolve_b3_sector_records,
)


async def _issuer(conn, name: str, cnpj: str | None) -> str:
    cur = await conn.execute(
        "insert into market.issuers (name,cnpj,kind) values (%s,%s,'empresa') returning id::text",
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


@pytest.mark.asyncio
async def test_b3_company_code_resolves_one_issuer_and_reuses_canonical_ingest(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, 'Companhia Teste B3', '33333333000101')
        on = await _action(conn, issuer, 'TSTX3')
        pn = await _action(conn, issuer, 'TSTX4')

        record = B3SectorDownloadRecord(
            company_code='TSTX', economic_sector='Financeiro', subsector='Bancos'
        )
        resolved, resolution = await resolve_b3_sector_records(conn, [record])
        assert resolution.resolved_codes == 1
        assert resolution.unresolved_codes == []
        assert resolved[0].issuer_cnpj == '33333333000101'
        assert resolved[0].segment is None

        report = await ingest_b3_sector_download_records(
            conn,
            [record],
            reference_date=date.today(),
            file_hash='c' * 64,
        )
        assert report.ingest.source_code == 'b3'
        assert report.ingest.matched_issuers == 1
        assert report.ingest.classes_targeted == 2
        assert report.ingest.rows_inserted == 2

        cur = await conn.execute(
            """select instrument_id::text,economic_sector,subsector,segment,listing_segment
                 from market.sector_classification
                where source_code='b3' and reference_date=%s and instrument_id=any(%s::uuid[])
                order by instrument_id""",
            (date.today(), [on, pn]),
        )
        rows = await cur.fetchall()
        assert len(rows) == 2
        assert all(row[1:3] == ('Financeiro', 'Bancos') for row in rows)
        assert all(row[3] is None and row[4] is None for row in rows)


@pytest.mark.asyncio
async def test_b3_company_code_reports_unmatched_and_missing_cnpj(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, 'Sem CNPJ', None)
        await _action(conn, issuer, 'NOCJ3')
        records = [
            B3SectorDownloadRecord('NOCJ', 'Outros', 'Outros'),
            B3SectorDownloadRecord('MISS', 'Saúde', 'Serviços'),
        ]
        resolved, report = await resolve_b3_sector_records(conn, records)
        assert resolved == []
        assert report.unresolved_codes == ['MISS']
        assert report.codes_without_cnpj == ['NOCJ']
        assert 'codigo_b3_sem_issuer' in report.warnings
        assert 'codigo_b3_issuer_sem_cnpj' in report.warnings


@pytest.mark.asyncio
async def test_b3_company_code_fails_closed_if_root_spans_two_issuers(db):
    async with db.service_session() as conn:
        a = await _issuer(conn, 'Amb A', '33333333000102')
        b = await _issuer(conn, 'Amb B', '33333333000103')
        await _action(conn, a, 'AMBX3')
        await _action(conn, b, 'AMBX4')
        record = B3SectorDownloadRecord('AMBX', 'Industrial', 'Máquinas')

        resolved, report = await resolve_b3_sector_records(conn, [record])
        assert resolved == []
        assert report.ambiguous_codes == ['AMBX']
        with pytest.raises(B3SectorCodeAmbiguity, match='AMBX'):
            await ingest_b3_sector_download_records(
                conn,
                [record],
                reference_date=date.today(),
                file_hash='d' * 64,
            )
