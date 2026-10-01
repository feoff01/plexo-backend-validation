from datetime import date

import pytest

from app.market.sectors import (
    SectorClassificationConflict,
    SectorLevel,
    SectorRow,
    _latest_consistent,
)


def row(*, instrument="i1", issuer="e1", ticker="AAA3", ref=date(2026, 9, 26),
        sector="Energia", subsector="Petroleo", segment="Exploracao",
        listing="NM", availability=date(2026, 9, 27)):
    return SectorRow(
        instrument_id=instrument,
        issuer_id=issuer,
        issuer_name="Empresa A",
        ticker=ticker,
        reference_date=ref,
        economic_sector=sector,
        subsector=subsector,
        segment=segment,
        listing_segment=listing,
        source_code="b3",
        ingestion_batch_id="batch-1",
        availability_date=availability,
    )


def test_sector_row_level_values():
    r = row()
    assert r.value_for(SectorLevel.SETOR) == "Energia"
    assert r.value_for(SectorLevel.SUBSETOR) == "Petroleo"
    assert r.value_for(SectorLevel.SEGMENTO) == "Exploracao"


def test_latest_consistent_uses_latest_snapshot():
    old = row(ref=date(2026, 1, 1), sector="Antigo")
    new = row(ref=date(2026, 9, 26), sector="Novo")
    selected, warnings = _latest_consistent([old, new])
    assert selected is not None
    assert selected.reference_date == date(2026, 9, 26)
    assert selected.economic_sector == "Novo"
    assert warnings == []


def test_latest_consistent_accepts_multiple_classes_same_company():
    on = row(instrument="i3", ticker="PETR3", listing="N2")
    pn = row(instrument="i4", ticker="PETR4", listing="N2")
    selected, warnings = _latest_consistent([pn, on])
    assert selected is not None
    assert selected.ticker == "PETR3"
    assert warnings == []


def test_latest_consistent_fails_closed_on_class_divergence():
    on = row(instrument="i3", ticker="PETR3", sector="Petroleo")
    pn = row(instrument="i4", ticker="PETR4", sector="Financeiro")
    with pytest.raises(SectorClassificationConflict, match="classificacao_setorial_divergente"):
        _latest_consistent([on, pn])


def test_latest_consistent_does_not_compare_old_snapshot_with_new_snapshot():
    old = row(instrument="i3", ticker="PETR3", ref=date(2025, 12, 31), sector="Antigo")
    new = row(instrument="i4", ticker="PETR4", ref=date(2026, 9, 26), sector="Novo")
    selected, warnings = _latest_consistent([old, new])
    assert selected is not None
    assert selected.economic_sector == "Novo"
    assert warnings == []


def test_empty_rows_return_none():
    selected, warnings = _latest_consistent([])
    assert selected is None
    assert warnings == []
