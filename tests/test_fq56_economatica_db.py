from datetime import date

import pytest

from app.market.economatica_sector_source import EconomaticaSectorRecord
from app.market.sector_ingest_economatica import ingest_economatica_sector_records


async def _issuer(conn, name, cnpj):
    cur=await conn.execute("insert into market.issuers (name,cnpj,kind) values (%s,%s,'empresa') returning id::text",(name,cnpj))
    return (await cur.fetchone())[0]

async def _action(conn, issuer_id, ticker):
    cur=await conn.execute("""insert into market.instruments
        (kind,name,ticker,issuer_id,is_in_universe,source_code)
        values ('acao',%s,%s,%s,true,'b3') returning id::text""",(ticker,ticker,issuer_id))
    return (await cur.fetchone())[0]


@pytest.mark.asyncio
async def test_economatica_ingest_exact_ticker_expands_to_all_classes_and_is_idempotent(db):
    async with db.service_session() as conn:
        cur=await conn.execute("select display_name from market.data_sources where code='economatica'")
        assert await cur.fetchone() is not None
        issuer=await _issuer(conn,'Petroleo Teste','11111111000101')
        p3=await _action(conn,issuer,'PETX3')
        p4=await _action(conn,issuer,'PETX4')
        report=await ingest_economatica_sector_records(
            conn,[EconomaticaSectorRecord('PETX4','Petróleo gás e biocombustíveis','Petróleo gás e biocombustíveis')],
            observed_at=date.today(),file_hash='a'*64,
        )
        assert report.matched_tickers==1
        assert report.issuers_matched==1
        assert report.classes_targeted==2
        assert report.rows_inserted==2
        cur=await conn.execute("""select instrument_id::text,economic_sector,subsector,segment,listing_segment,source_code
          from market.sector_classification where source_code='economatica' and reference_date=%s order by instrument_id""",(date.today(),))
        rows=await cur.fetchall()
        assert {r[0] for r in rows}=={p3,p4}
        assert all(r[3] is None and r[4] is None and r[5]=='economatica' for r in rows)
        again=await ingest_economatica_sector_records(
            conn,[EconomaticaSectorRecord('PETX4','Petróleo gás e biocombustíveis','Petróleo gás e biocombustíveis')],
            observed_at=date.today(),file_hash='a'*64,
        )
        assert again.reused_existing_batch is True


@pytest.mark.asyncio
async def test_economatica_ingest_reports_unmatched_and_never_strips_old(db):
    async with db.service_session() as conn:
        report=await ingest_economatica_sector_records(
            conn,[
                EconomaticaSectorRecord('MISSING3','Financeiro','Bancos'),
                EconomaticaSectorRecord('OLD3-old','Outros','Outros'),
            ],observed_at=date.today(),file_hash='b'*64,
        )
        assert report.matched_tickers==0
        assert report.unmatched_tickers==('MISSING3',)
        assert report.rows_inserted==0
