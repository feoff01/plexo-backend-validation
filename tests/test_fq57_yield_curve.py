from datetime import date

import pytest
from pydantic import ValidationError

from app.market.yield_curve_ingest import (
    AnbimaYieldCurvePoint,
    _expanded_rows,
    _normalize_points,
)


def test_anbima_yield_curve_point_requires_vertex_and_at_least_one_rate():
    point = AnbimaYieldCurvePoint(
        reference_date=date(2026, 10, 2),
        business_days=21,
        pre_rate_pct=14.1234567,
    )
    assert point.business_days == 21

    with pytest.raises(ValidationError):
        AnbimaYieldCurvePoint(
            reference_date=date(2026, 10, 2),
            business_days=0,
            pre_rate_pct=14.0,
        )
    with pytest.raises(ValidationError, match="vertice_ettj_sem_taxa"):
        AnbimaYieldCurvePoint(
            reference_date=date(2026, 10, 2),
            business_days=21,
        )


def test_snapshot_requires_one_reference_date_and_unique_business_days():
    p1 = AnbimaYieldCurvePoint(
        reference_date=date(2026, 10, 2),
        business_days=21,
        pre_rate_pct=14.0,
    )
    p2 = AnbimaYieldCurvePoint(
        reference_date=date(2026, 10, 1),
        business_days=42,
        pre_rate_pct=13.9,
    )
    with pytest.raises(ValueError, match="multiplas_datas"):
        _normalize_points([p1, p2])

    p3 = AnbimaYieldCurvePoint(
        reference_date=date(2026, 10, 2),
        business_days=21,
        ipca_rate_pct=7.0,
    )
    with pytest.raises(ValueError, match="vertice_ettj_duplicado"):
        _normalize_points([p1, p3])


def test_expansion_maps_three_official_curves_and_normalizes_db_precision():
    point = AnbimaYieldCurvePoint(
        reference_date=date(2026, 10, 2),
        business_days=252,
        pre_rate_pct=12.3456789,
        ipca_rate_pct=6.1111114,
        implied_inflation_pct=5.9999996,
    )
    rows = _expanded_rows([point])
    assert [(curve, du, str(rate)) for curve, _ref, du, rate in rows] == [
        ("ettj_pre", 252, "12.345679"),
        ("ettj_ipca", 252, "6.111111"),
        ("inflacao_implicita", 252, "6.000000"),
    ]
