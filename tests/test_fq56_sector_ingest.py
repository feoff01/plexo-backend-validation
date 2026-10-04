from datetime import date

import pytest
from pydantic import ValidationError

from app.market.sector_ingest import (
    SectorIngestConflict,
    SectorSourceRecord,
    _coalesce_records,
)


def rec(cnpj="33000167000101", *, sector="Petroleo", subsector="Exploracao", segment="Exploracao", listing="N2"):
    return SectorSourceRecord(
        issuer_cnpj=cnpj,
        economic_sector=sector,
        subsector=subsector,
        segment=segment,
        listing_segment=listing,
    )


def test_source_record_requires_normalized_cnpj():
    with pytest.raises(ValidationError):
        SectorSourceRecord(issuer_cnpj="33.000.167/0001-01", economic_sector="Petroleo")


def test_source_record_trims_optional_fields():
    r = SectorSourceRecord(
        issuer_cnpj="33000167000101",
        economic_sector="  Petroleo  ",
        subsector=" ",
        segment=None,
        listing_segment=" N2 ",
    )
    assert r.economic_sector == "Petroleo"
    assert r.subsector is None
    assert r.listing_segment == "N2"


def test_coalesce_deduplicates_identical_company_rows():
    rows, received = _coalesce_records([rec(), rec()])
    assert received == 2
    assert len(rows) == 1
    assert rows[0].issuer_cnpj == "33000167000101"


def test_coalesce_fails_closed_on_same_cnpj_with_divergence():
    with pytest.raises(SectorIngestConflict, match="fonte_setorial_divergente_mesmo_cnpj"):
        _coalesce_records([rec(sector="Petroleo"), rec(sector="Financeiro")])


@pytest.mark.asyncio
async def test_ingest_rejects_empty_snapshot_before_touching_db():
    from app.market.sector_ingest import ingest_sector_records
    with pytest.raises(ValueError, match="snapshot_setorial_vazio"):
        await ingest_sector_records(
            None, [], reference_date=date(2026, 9, 29), file_hash="a" * 64
        )


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_hash_before_touching_db():
    from app.market.sector_ingest import ingest_sector_records
    with pytest.raises(ValueError, match="file_hash_setorial_invalido"):
        await ingest_sector_records(
            None, [rec()], reference_date=date(2026, 9, 29), file_hash="nao-e-hash"
        )


@pytest.mark.asyncio
async def test_ingest_rejects_non_b3_source_in_v1_before_touching_db():
    from app.market.sector_ingest import ingest_sector_records
    with pytest.raises(ValueError, match="somente source_code=b3"):
        await ingest_sector_records(
            None,
            [rec()],
            reference_date=date(2026, 9, 29),
            file_hash="b" * 64,
            source_code="manual",
        )
