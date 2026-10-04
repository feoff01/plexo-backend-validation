from datetime import date

import pytest

from app.market.sector_ingest import (
    SectorIngestConflict,
    SectorSourceRecord,
    ingest_sector_records,
    measure_sector_coverage,
)
from app.market.sectors import classification_for_instrument


async def _issuer(conn, name: str, cnpj: str) -> str:
    cur = await conn.execute(
        "insert into market.issuers (name, cnpj, kind) values (%s, %s, 'empresa') returning id::text",
        (name, cnpj),
    )
    return (await cur.fetchone())[0]


async def _action(conn, issuer_id: str, ticker: str, *, in_universe: bool = True) -> str:
    cur = await conn.execute(
        """insert into market.instruments
               (kind, name, ticker, issuer_id, is_in_universe, source_code)
           values ('acao', %s, %s, %s, %s, 'b3') returning id::text""",
        (ticker, ticker, issuer_id, in_universe),
    )
    return (await cur.fetchone())[0]


def _record(cnpj: str, *, sector="Petroleo", subsector="Petroleo e Gas", segment="Exploracao", listing="N2"):
    return SectorSourceRecord(
        issuer_cnpj=cnpj,
        economic_sector=sector,
        subsector=subsector,
        segment=segment,
        listing_segment=listing,
    )


@pytest.mark.asyncio
async def test_sector_ingest_expands_company_to_all_equity_classes_and_loader_reads_pit(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, "Petroleo Teste", "33000167000101")
        on = await _action(conn, issuer, "TSTA3")
        pn = await _action(conn, issuer, "TSTA4")
        report = await ingest_sector_records(
            conn,
            [_record("33000167000101")],
            reference_date=date(2026, 9, 29),
            file_hash="a" * 64,
            storage_key="b3/listed-companies/sample.zip",
        )
        assert report.matched_issuers == 1
        assert report.classes_targeted == 2
        assert report.rows_inserted == 2
        assert report.unmatched_cnpjs == []

        resolved = await classification_for_instrument(
            conn, on, cutoff=date.today(), strict_pit=True
        )
        assert resolved.found is True
        assert resolved.segment == "Exploracao"
        assert resolved.provenance.ingestion_batch_ids == [report.batch_id]

        cur = await conn.execute(
            "select count(*) from market.sector_classification where instrument_id in (%s, %s)",
            (on, pn),
        )
        assert (await cur.fetchone())[0] == 2


@pytest.mark.asyncio
async def test_sector_ingest_reports_unmatched_and_issuer_without_equity(db):
    async with db.service_session() as conn:
        await _issuer(conn, "Sem Acao", "11111111000101")
        report = await ingest_sector_records(
            conn,
            [_record("11111111000101"), _record("99999999000199")],
            reference_date=date(2026, 9, 29),
            file_hash="b" * 64,
        )
        assert report.matched_issuers == 0
        assert report.rows_inserted == 0
        assert report.issuers_without_equity == ["11111111000101"]
        assert report.unmatched_cnpjs == ["99999999000199"]
        assert report.warnings == ["cnpj_setorial_sem_issuer", "issuer_setorial_sem_acao"]


@pytest.mark.asyncio
async def test_sector_ingest_same_file_hash_is_idempotent(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, "Idempotente SA", "22222222000102")
        await _action(conn, issuer, "IDEM3")
        first = await ingest_sector_records(
            conn,
            [_record("22222222000102")],
            reference_date=date(2026, 9, 29),
            file_hash="c" * 64,
        )
        second = await ingest_sector_records(
            conn,
            [_record("22222222000102")],
            reference_date=date(2026, 9, 29),
            file_hash="c" * 64,
        )
        assert first.reused_existing_batch is False
        assert second.reused_existing_batch is True
        assert second.batch_id == first.batch_id
        assert second.warnings == ["arquivo_setorial_ja_ingerido"]
        cur = await conn.execute(
            "select count(*) from market.sector_classification where ingestion_batch_id = %s",
            (first.batch_id,),
        )
        assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_sector_ingest_fails_closed_if_same_snapshot_key_has_different_content(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, "Conflito SA", "33333333000103")
        iid = await _action(conn, issuer, "CNFL3")
        await ingest_sector_records(
            conn,
            [_record("33333333000103", sector="Energia")],
            reference_date=date(2026, 9, 29),
            file_hash="d" * 64,
        )
        with pytest.raises(SectorIngestConflict, match="classificacao_setorial_conflitante_mesma_chave"):
            await ingest_sector_records(
                conn,
                [_record("33333333000103", sector="Financeiro")],
                reference_date=date(2026, 9, 29),
                file_hash="e" * 64,
            )
        cur = await conn.execute(
            "select economic_sector from market.sector_classification where instrument_id = %s",
            (iid,),
        )
        assert (await cur.fetchone())[0] == "Energia"
        cur = await conn.execute(
            "select status, rows_ingested from market.ingestion_batches where file_hash = %s",
            ("e" * 64,),
        )
        assert await cur.fetchone() == ("failed", 0)


@pytest.mark.asyncio
async def test_sector_coverage_counts_company_once_across_multiple_classes(db):
    async with db.service_session() as conn:
        covered = await _issuer(conn, "Coberta SA", "44444444000104")
        await _action(conn, covered, "COVR3")
        await _action(conn, covered, "COVR4")
        uncovered = await _issuer(conn, "Descoberta SA", "55555555000105")
        await _action(conn, uncovered, "DESC3")
        await ingest_sector_records(
            conn,
            [_record("44444444000104")],
            reference_date=date(2026, 9, 29),
            file_hash="f" * 64,
        )
        coverage = await measure_sector_coverage(conn, cutoff=date.today())
        assert coverage.eligible_issuers >= 2
        assert coverage.classified_issuers >= 1
        assert coverage.classified_issuers <= coverage.eligible_issuers
        assert "Descoberta SA" in coverage.unclassified_issuers
        assert "DESC3" in coverage.unclassified_tickers
        assert "cobertura_setorial_incompleta" in coverage.warnings
