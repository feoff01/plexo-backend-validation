"""FQ2.1 — contratos puros do Quant Core.

Estes testes não usam banco, policy nem LLM. O objetivo é congelar a matemática e os edge cases
antes de conectá-los às tools públicas.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.market.series import MarketPoint
from app.market.analytics.models import IndexUnit, ReturnMethod
from app.market.analytics.returns import (
    InvalidPricePath,
    InvalidRateSeries,
    NonFiniteReturnResult,
    annualized_price_return,
    calculate_index_returns,
    calculate_returns,
    compound_simple_returns,
    cumulative_price_return,
)
from app.market.analytics.statistics import NonFiniteSample, describe, sample_stddev


def _points(*values: float) -> list[MarketPoint]:
    start = date(2024, 1, 2)
    return [MarketPoint(data=start + timedelta(days=i), valor=v) for i, v in enumerate(values)]


def test_simple_returns_are_dated_on_the_ending_observation():
    out = calculate_returns(_points(100, 110, 99), ReturnMethod.SIMPLE)
    assert [x.data for x in out] == [date(2024, 1, 3), date(2024, 1, 4)]
    assert [x.value for x in out] == pytest.approx([0.10, -0.10])


def test_log_returns_compound_back_to_endpoint_price_return():
    points = _points(100, 110, 99, 120)
    out = calculate_returns(points, ReturnMethod.LOG)
    assert math.exp(sum(x.value for x in out)) - 1 == pytest.approx(0.20)
    assert cumulative_price_return(points) == pytest.approx(0.20)


def test_cumulative_and_annualized_return_match_legacy_semantics():
    points = _points(100, 110, 121)
    assert cumulative_price_return(points) == pytest.approx(0.21)
    assert annualized_price_return(points, periods_per_year=2) == pytest.approx(0.21)
    assert annualized_price_return(points, periods_per_year=1) == pytest.approx(0.10)


def test_empty_and_single_point_paths_have_no_return_instead_of_nan():
    assert calculate_returns([], ReturnMethod.SIMPLE) == []
    assert calculate_returns(_points(100), ReturnMethod.SIMPLE) == []
    assert cumulative_price_return([]) is None
    assert cumulative_price_return(_points(100)) is None
    assert annualized_price_return(_points(100), periods_per_year=252) is None


def test_return_functions_fail_closed_on_non_positive_or_non_increasing_price_path():
    with pytest.raises(InvalidPricePath):
        calculate_returns(_points(100, 0), ReturnMethod.LOG)
    duplicate_date = [
        MarketPoint(data=date(2024, 1, 2), valor=100),
        MarketPoint(data=date(2024, 1, 2), valor=101),
    ]
    with pytest.raises(InvalidPricePath):
        calculate_returns(duplicate_date, ReturnMethod.SIMPLE)


def test_annualized_return_requires_positive_periods_per_year():
    with pytest.raises(ValueError):
        annualized_price_return(_points(100, 110), periods_per_year=0)


def test_compound_simple_returns_and_minus_100_percent_edge_case():
    assert compound_simple_returns([0.10, -0.10]) == pytest.approx(-0.01)
    assert compound_simple_returns([-1.0, 0.50]) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        compound_simple_returns([-1.01])


def test_sample_stddev_matches_python_sample_definition_and_small_samples_return_none():
    values = [0.10, -0.10, 0.20]
    assert sample_stddev(values) == pytest.approx(0.15275252316519466)
    assert sample_stddev([]) is None
    assert sample_stddev([0.1]) is None


def test_describe_has_explicit_empty_contract_and_finite_validation():
    empty = describe([])
    assert empty.count == 0
    assert empty.mean is None and empty.median is None and empty.sample_stddev is None
    assert empty.minimum is None and empty.maximum is None

    summary = describe([1.0, 2.0, 3.0])
    assert summary.count == 3
    assert summary.mean == pytest.approx(2.0)
    assert summary.median == pytest.approx(2.0)
    assert summary.sample_stddev == pytest.approx(1.0)
    assert summary.minimum == 1.0 and summary.maximum == 3.0

    with pytest.raises(NonFiniteSample):
        describe([1.0, float("nan")])


def test_core_models_are_immutable_and_forbid_extra_fields():
    summary = describe([1.0, 2.0])
    with pytest.raises(Exception):
        summary.count = 99


def test_index_return_conversion_preserves_current_market_unit_semantics():
    annual = calculate_index_returns(
        _points(10.0, 10.0, 10.0), IndexUnit.ANNUAL_RATE, periods_per_year=252, method=ReturnMethod.SIMPLE
    )
    expected_daily = (1.10 ** (1 / 252)) - 1
    assert [x.value for x in annual] == pytest.approx([expected_daily, expected_daily])

    monthly = calculate_index_returns(
        _points(0.3, -0.2, 0.5), IndexUnit.MONTHLY_RATE, periods_per_year=252, method=ReturnMethod.SIMPLE
    )
    assert [x.value for x in monthly] == pytest.approx([-0.002, 0.005])

    percentage = calculate_index_returns(
        _points(1.0, 2.5, -1.0), IndexUnit.PERCENTAGE, periods_per_year=252, method=ReturnMethod.SIMPLE
    )
    assert [x.value for x in percentage] == pytest.approx([0.025, -0.01])

    points = calculate_index_returns(
        _points(100, 110, 99), IndexUnit.POINTS, periods_per_year=252, method=ReturnMethod.SIMPLE
    )
    assert [x.value for x in points] == pytest.approx([0.10, -0.10])


def test_index_return_conversion_fails_closed_on_impossible_rates():
    with pytest.raises(InvalidRateSeries):
        calculate_index_returns(
            _points(0.0, -101.0), IndexUnit.PERCENTAGE, periods_per_year=252, method=ReturnMethod.SIMPLE
        )


def test_index_rate_dates_must_be_strictly_increasing():
    duplicate = [
        MarketPoint(data=date(2024, 1, 2), valor=10.0),
        MarketPoint(data=date(2024, 1, 2), valor=10.5),
    ]
    with pytest.raises(InvalidRateSeries):
        calculate_index_returns(
            duplicate, IndexUnit.ANNUAL_RATE, periods_per_year=252, method=ReturnMethod.SIMPLE
        )


def test_new_return_core_matches_legacy_return_and_stddev_semantics():
    from app.tools.analista import _comum

    legacy_points = [
        _comum.Ponto(data=p.data, valor=p.valor) for p in _points(100, 103, 101, 110, 109)
    ]
    market_points = [MarketPoint(data=p.data, valor=p.valor) for p in legacy_points]
    for method in (ReturnMethod.LOG, ReturnMethod.SIMPLE):
        legacy = _comum.retornos(legacy_points, method.value)
        new = calculate_returns(market_points, method)
        assert [(x.data, x.value) for x in new] == pytest.approx(legacy)
        assert sample_stddev([x.value for x in new]) == pytest.approx(
            _comum.desvio([value for _, value in legacy])
        )


def test_return_core_properties_across_many_synthetic_paths():
    import random

    rng = random.Random(20260921)
    for _ in range(500):
        n = rng.randint(2, 40)
        price = rng.uniform(1.0, 1000.0)
        values = [price]
        for _ in range(n - 1):
            # Retorno simples sempre > -100%; preços continuam positivos.
            price *= 1.0 + rng.uniform(-0.35, 0.35)
            values.append(price)
        points = _points(*values)

        simple = calculate_returns(points, ReturnMethod.SIMPLE)
        log_returns = calculate_returns(points, ReturnMethod.LOG)
        endpoint = cumulative_price_return(points)
        assert endpoint is not None

        # Três formas independentes de reconstruir o mesmo retorno total.
        assert compound_simple_returns([x.value for x in simple]) == pytest.approx(endpoint, rel=1e-12, abs=1e-12)
        assert math.exp(sum(x.value for x in log_returns)) - 1.0 == pytest.approx(endpoint, rel=1e-12, abs=1e-12)

        # Retornos são invariantes à escala monetária da cotação.
        scaled = [MarketPoint(data=p.data, valor=p.valor * 17.3) for p in points]
        assert [x.value for x in calculate_returns(scaled, ReturnMethod.SIMPLE)] == pytest.approx(
            [x.value for x in simple], rel=1e-12, abs=1e-12
        )

        # Se periods_per_year == número de intervalos, anualizado == retorno do caminho.
        assert annualized_price_return(points, periods_per_year=n - 1) == pytest.approx(
            endpoint, rel=1e-12, abs=1e-12
        )


def test_legacy_return_tool_fingerprint_covers_quant_core_dependencies():
    from pathlib import Path

    from app.tools import carregar_tools
    from app.tools.registry import spec_de

    carregar_tools()
    spec = spec_de("quant.retorno_volatilidade")
    names = {Path(path).name for path in spec.source_files}
    assert {"retorno_volatilidade.py", "_comum.py", "series.py", "models.py", "returns.py", "risk.py", "statistics.py"} <= names
    assert spec.semver == "1.0.4"


def test_return_core_uses_stable_log_math_and_fails_closed_when_simple_return_overflows():
    extreme = _points(1e-308, 1e308)
    log_result = calculate_returns(extreme, ReturnMethod.LOG)
    assert math.isfinite(log_result[0].value)
    with pytest.raises(NonFiniteReturnResult):
        calculate_returns(extreme, ReturnMethod.SIMPLE)
    with pytest.raises(NonFiniteReturnResult):
        cumulative_price_return(extreme)


def test_index_rates_validate_even_the_first_observation():
    bad_first = [
        MarketPoint(data=date(2024, 1, 2), valor=float("nan")),
        MarketPoint(data=date(2024, 1, 3), valor=10.0),
    ]
    with pytest.raises(InvalidRateSeries):
        calculate_index_returns(
            bad_first, IndexUnit.ANNUAL_RATE, periods_per_year=252, method=ReturnMethod.SIMPLE
        )
