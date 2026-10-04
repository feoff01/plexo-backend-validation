"""FQ2.2 — contratos puros do Risk Engine.

Sem banco, policy ou LLM. Estes testes congelam a semântica antes da migração da tool legacy.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

import pytest

from app.market.analytics.models import ReturnObservation
from app.market.analytics.risk import (
    annualized_downside_deviation,
    annualized_volatility,
    downside_deviation,
    drawdown_series,
    maximum_drawdown,
    maximum_drawdown_episode,
    rolling_volatility,
)
from app.market.analytics.returns import InvalidPricePath
from app.market.analytics.statistics import NonFiniteSample
from app.market.series import MarketPoint


def _points(*values: float) -> list[MarketPoint]:
    start = date(2024, 1, 2)
    return [MarketPoint(data=start + timedelta(days=i), valor=v) for i, v in enumerate(values)]


def _returns(*values: float) -> list[ReturnObservation]:
    start = date(2024, 1, 3)
    return [ReturnObservation(data=start + timedelta(days=i), value=v) for i, v in enumerate(values)]


def test_annualized_volatility_preserves_sample_stddev_legacy_semantics():
    values = [0.01, -0.02, 0.03, 0.005]
    expected = statistics.stdev(values) * math.sqrt(252)
    assert annualized_volatility(values, periods_per_year=252) == pytest.approx(expected)
    assert annualized_volatility([], periods_per_year=252) is None
    assert annualized_volatility([0.01], periods_per_year=252) is None
    assert annualized_volatility([0.01, 0.01], periods_per_year=252) == pytest.approx(0.0)


def test_annualized_volatility_requires_explicit_positive_base_and_finite_sample():
    with pytest.raises(ValueError):
        annualized_volatility([0.01, 0.02], periods_per_year=0)
    with pytest.raises(NonFiniteSample):
        annualized_volatility([0.01, float("nan")], periods_per_year=252)


def test_rolling_volatility_uses_window_ending_date_without_padding():
    obs = _returns(0.01, -0.01, 0.02, 0.00)
    out = rolling_volatility(obs, window=3, periods_per_year=252)
    assert [x.data for x in out] == [obs[2].data, obs[3].data]
    assert [x.window_observations for x in out] == [3, 3]
    assert out[0].value == pytest.approx(statistics.stdev([0.01, -0.01, 0.02]) * math.sqrt(252))
    assert out[1].value == pytest.approx(statistics.stdev([-0.01, 0.02, 0.00]) * math.sqrt(252))
    assert rolling_volatility(obs[:2], window=3, periods_per_year=252) == []


def test_rolling_volatility_rejects_invalid_window_or_non_increasing_dates():
    with pytest.raises(ValueError):
        rolling_volatility(_returns(0.01, 0.02), window=1, periods_per_year=252)
    duplicate = [
        ReturnObservation(data=date(2024, 1, 3), value=0.01),
        ReturnObservation(data=date(2024, 1, 3), value=0.02),
    ]
    with pytest.raises(ValueError):
        rolling_volatility(duplicate, window=2, periods_per_year=252)


def test_downside_deviation_definition_uses_all_observations_in_denominator():
    values = [0.02, -0.01, -0.03, 0.04]
    expected = math.sqrt((0.0**2 + (-0.01)**2 + (-0.03)**2 + 0.0**2) / 4)
    assert downside_deviation(values, target_return=0.0) == pytest.approx(expected)
    assert annualized_downside_deviation(values, target_return=0.0, periods_per_year=252) == pytest.approx(
        expected * math.sqrt(252)
    )
    assert downside_deviation([0.01, 0.02], target_return=0.0) == pytest.approx(0.0)
    assert downside_deviation([], target_return=0.0) is None


def test_downside_deviation_supports_nonzero_target_and_fails_closed_on_nonfinite():
    values = [0.01, 0.03]
    expected = math.sqrt(((-0.01) ** 2 + 0.0**2) / 2)
    assert downside_deviation(values, target_return=0.02) == pytest.approx(expected)
    with pytest.raises(NonFiniteSample):
        downside_deviation([0.01, float("inf")], target_return=0.0)
    with pytest.raises(ValueError):
        downside_deviation([0.01], target_return=float("nan"))


def test_drawdown_series_and_maximum_drawdown_match_running_peak_definition():
    points = _points(100, 102, 101, 104, 103)
    out = drawdown_series(points)
    assert [x.value for x in out] == pytest.approx([0.0, 0.0, 101 / 102 - 1, 0.0, 103 / 104 - 1])
    assert [x.running_peak for x in out] == pytest.approx([100, 102, 102, 104, 104])
    assert maximum_drawdown(points) == pytest.approx(101 / 102 - 1)


def test_drawdown_empty_single_and_monotonic_paths_have_explicit_contract():
    assert drawdown_series([]) == []
    assert maximum_drawdown([]) is None
    assert maximum_drawdown(_points(100)) == pytest.approx(0.0)
    assert maximum_drawdown(_points(100, 101, 102, 103)) == pytest.approx(0.0)
    assert maximum_drawdown_episode([]) is None
    assert maximum_drawdown_episode(_points(100, 101, 102, 103)) is None


def test_maximum_drawdown_episode_records_peak_trough_and_recovery():
    points = _points(100, 120, 108, 90, 100, 120, 125)
    ep = maximum_drawdown_episode(points)
    assert ep is not None
    assert ep.peak_date == points[1].data and ep.peak_value == 120
    assert ep.trough_date == points[3].data and ep.trough_value == 90
    assert ep.recovery_date == points[5].data and ep.recovery_value == 120
    assert ep.depth == pytest.approx(90 / 120 - 1)
    assert ep.time_to_trough_intervals == 2
    assert ep.recovery_intervals == 2
    assert ep.duration_intervals == 4
    assert ep.recovered is True


def test_unrecovered_drawdown_episode_uses_end_of_sample_only_for_duration():
    points = _points(100, 120, 90, 95, 110)
    ep = maximum_drawdown_episode(points)
    assert ep is not None
    assert ep.depth == pytest.approx(90 / 120 - 1)
    assert ep.trough_date == points[2].data
    assert ep.recovery_date is None and ep.recovery_value is None
    assert ep.recovery_intervals is None
    assert ep.duration_intervals == 3  # peak index 1 -> sample end index 4
    assert ep.recovered is False


def test_multiple_drawdown_episodes_choose_deepest_and_ties_choose_earliest():
    # primeiro episódio -20%, segundo episódio também -20%; o primeiro deve vencer o empate.
    points = _points(100, 80, 100, 110, 88, 110)
    ep = maximum_drawdown_episode(points)
    assert ep is not None
    assert ep.peak_date == points[0].data
    assert ep.trough_date == points[1].data
    assert ep.depth == pytest.approx(-0.20)


def test_drawdown_is_scale_invariant_and_never_positive_over_many_paths():
    import random

    rng = random.Random(20260921)
    for _ in range(500):
        n = rng.randint(1, 60)
        price = rng.uniform(1.0, 1000.0)
        values = [price]
        for _ in range(n - 1):
            price *= 1.0 + rng.uniform(-0.30, 0.30)
            values.append(price)
        points = _points(*values)
        scaled = [MarketPoint(data=p.data, valor=p.valor * 31.7) for p in points]
        dd = drawdown_series(points)
        dd_scaled = drawdown_series(scaled)
        assert all(x.value <= 1e-15 for x in dd)
        assert [x.value for x in dd_scaled] == pytest.approx([x.value for x in dd], rel=1e-12, abs=1e-12)
        assert maximum_drawdown(points) == pytest.approx(min((x.value for x in dd), default=0.0))


def test_drawdown_reuses_price_path_validation_fail_closed():
    with pytest.raises(InvalidPricePath):
        drawdown_series(_points(100, 0, 90))
    duplicate = [
        MarketPoint(data=date(2024, 1, 2), valor=100),
        MarketPoint(data=date(2024, 1, 2), valor=90),
    ]
    with pytest.raises(InvalidPricePath):
        drawdown_series(duplicate)


def test_drawdown_duration_and_recovery_helpers_are_interval_based():
    from app.market.analytics.risk import drawdown_duration, recovery_time

    recovered = _points(100, 120, 90, 100, 120)
    assert drawdown_duration(recovered) == 3  # pico idx 1 -> recuperação idx 4
    assert recovery_time(recovered) == 2      # fundo idx 2 -> recuperação idx 4

    unrecovered = _points(100, 120, 90, 100, 110)
    assert drawdown_duration(unrecovered) == 3  # pico idx 1 -> fim idx 4
    assert recovery_time(unrecovered) is None

    monotonic = _points(100, 101, 102)
    assert drawdown_duration(monotonic) is None
    assert recovery_time(monotonic) is None


def test_equal_peak_before_fall_uses_most_recent_equal_peak_for_episode_duration():
    points = _points(100, 100, 80, 100)
    ep = maximum_drawdown_episode(points)
    assert ep is not None
    assert ep.peak_date == points[1].data
    assert ep.depth == pytest.approx(-0.20)
    assert ep.time_to_trough_intervals == 1
    assert ep.recovery_intervals == 1
    assert ep.duration_intervals == 2


def test_risk_core_matches_legacy_max_drawdown_across_many_paths():
    import random

    from app.tools.analista import _comum

    rng = random.Random(2026092102)
    for _ in range(750):
        n = rng.randint(1, 80)
        price = rng.uniform(1.0, 2000.0)
        values = [price]
        for _ in range(n - 1):
            price *= 1.0 + rng.uniform(-0.40, 0.40)
            values.append(price)
        market = _points(*values)
        legacy = [_comum.Ponto(data=p.data, valor=p.valor) for p in market]
        assert maximum_drawdown(market) == pytest.approx(_comum.max_drawdown(legacy), rel=1e-15, abs=1e-15)


def test_risk_core_volatility_matches_legacy_formula_across_many_samples():
    import random

    rng = random.Random(2026092103)
    for _ in range(750):
        n = rng.randint(2, 100)
        values = [rng.uniform(-0.15, 0.15) for _ in range(n)]
        base = rng.choice([12, 52, 252, 365])
        expected = statistics.stdev(values) * math.sqrt(base)
        assert annualized_volatility(values, periods_per_year=base) == pytest.approx(expected, rel=1e-15, abs=1e-15)
