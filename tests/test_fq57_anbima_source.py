from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path

import pytest

from app.market.anbima_yield_curve_source import (
    AnbimaYieldCurveCsvParseError,
    parse_anbima_yield_curve_csv,
)
from app.market.yield_curve_ingest import AnbimaYieldCurvePoint


FIXTURE = Path(__file__).parent / "fixtures" / "market" / "anbima_ettj_2026-10-02.csv"
EXPECTED_SHA256 = "a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7"


def test_official_anbima_fixture_hash_layout_and_coverage():
    data = FIXTURE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA256

    snapshot = parse_anbima_yield_curve_csv(data)
    assert snapshot.reference_date == date(2026, 10, 2)
    assert snapshot.ipca_vertices == 65
    assert snapshot.pre_vertices == 19
    assert snapshot.implied_vertices == 19
    assert snapshot.points[0].business_days == 252
    assert snapshot.points[0].ipca_rate_pct == Decimal("6.5624")
    assert snapshot.points[0].pre_rate_pct == Decimal("13.3811")
    assert snapshot.points[0].implied_inflation_pct == Decimal("6.3987")
    assert snapshot.points[-1].business_days == 8316
    assert snapshot.points[-1].ipca_rate_pct == Decimal("6.7918")
    assert snapshot.points[-1].pre_rate_pct is None
    assert snapshot.points[-1].implied_inflation_pct is None


def test_official_snapshot_maps_losslessly_to_semantic_ingest_contract():
    snapshot = parse_anbima_yield_curve_csv(FIXTURE.read_bytes())
    semantic = [
        AnbimaYieldCurvePoint(
            reference_date=snapshot.reference_date,
            business_days=point.business_days,
            pre_rate_pct=float(point.pre_rate_pct) if point.pre_rate_pct is not None else None,
            ipca_rate_pct=float(point.ipca_rate_pct),
            implied_inflation_pct=(
                float(point.implied_inflation_pct)
                if point.implied_inflation_pct is not None
                else None
            ),
        )
        for point in snapshot.points
    ]
    assert len(semantic) == 65
    assert sum(point.pre_rate_pct is not None for point in semantic) == 19
    assert sum(point.ipca_rate_pct is not None for point in semantic) == 65
    assert sum(point.implied_inflation_pct is not None for point in semantic) == 19


def test_parser_fails_closed_on_header_drift_duplicate_and_partial_pair():
    raw = FIXTURE.read_bytes().decode("cp1252")
    with pytest.raises(AnbimaYieldCurveCsvParseError, match="cabecalho_ettj_invalido"):
        parse_anbima_yield_curve_csv(
            raw.replace("ETTJ PREF", "ETTJ PRE", 1).encode("cp1252")
        )

    duplicate = raw.replace(
        "378;7,1121;13,5400;6,0010",
        "252;7,1121;13,5400;6,0010",
        1,
    )
    with pytest.raises(AnbimaYieldCurveCsvParseError, match="vertice_ettj_duplicado"):
        parse_anbima_yield_curve_csv(duplicate.encode("cp1252"))

    partial = raw.replace(
        "252;6,5624;13,3811;6,3987",
        "252;6,5624;13,3811;",
        1,
    )
    with pytest.raises(AnbimaYieldCurveCsvParseError, match="pre_implicita_desalinhados"):
        parse_anbima_yield_curve_csv(partial.encode("cp1252"))
