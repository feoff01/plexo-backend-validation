from __future__ import annotations

from datetime import date, timedelta
import random

import pytest

from app.market.analytics import regimes
from app.market.series import MarketPoint


def _pair(i: int, x: float, y: float) -> regimes.RegimeResponsePair:
    d0 = date(2020, 1, 1) + timedelta(days=i)
    d1 = d0 + timedelta(days=1)
    return regimes.RegimeResponsePair(
        driver_start_date=d0,
        driver_end_date=d1,
        response_start_date=d0,
        response_end_date=d1,
        driver_value=x,
        response_return=y,
    )


def test_property_level_partition_and_translation_invariance_400_paths():
    rng = random.Random(20260921)
    for _ in range(400):
        n = rng.randint(3, 41)
        xs = [rng.uniform(-20, 40) for _ in range(n)]
        ys = [rng.uniform(-0.25, 0.25) for _ in range(n)]
        pairs = [_pair(i, x, y) for i, (x, y) in enumerate(zip(xs, ys))]
        base = regimes.analyze_regimes(pairs, criterion=regimes.RegimeCriterion.LEVEL)
        assert base.group_1.summary.count + base.group_2.summary.count + base.n_neutral == n

        shift = rng.uniform(-1000, 1000)
        shifted = regimes.analyze_regimes(
            [_pair(i, x + shift, y) for i, (x, y) in enumerate(zip(xs, ys))],
            criterion=regimes.RegimeCriterion.LEVEL,
        )
        assert shifted.threshold == pytest.approx(base.threshold + shift)
        assert shifted.group_1.summary.model_dump() == base.group_1.summary.model_dump()
        assert shifted.group_2.summary.model_dump() == base.group_2.summary.model_dump()
        assert shifted.n_neutral == base.n_neutral


def test_property_direction_sign_reversal_swaps_regimes_400_paths():
    rng = random.Random(20260922)
    for _ in range(400):
        n = rng.randint(3, 41)
        xs = [rng.uniform(-0.2, 0.2) for _ in range(n)]
        ys = [rng.uniform(-0.25, 0.25) for _ in range(n)]
        threshold = rng.uniform(0, 0.05)
        base = regimes.analyze_regimes(
            [_pair(i, x, y) for i, (x, y) in enumerate(zip(xs, ys))],
            criterion=regimes.RegimeCriterion.DIRECTION,
            threshold=threshold,
        )
        mirrored = regimes.analyze_regimes(
            [_pair(i, -x, y) for i, (x, y) in enumerate(zip(xs, ys))],
            criterion=regimes.RegimeCriterion.DIRECTION,
            threshold=threshold,
        )
        assert mirrored.group_1.summary.model_dump() == base.group_2.summary.model_dump()
        assert mirrored.group_2.summary.model_dump() == base.group_1.summary.model_dump()
        assert mirrored.n_neutral == base.n_neutral
        if base.mean_difference is None:
            assert mirrored.mean_difference is None
        else:
            assert mirrored.mean_difference == pytest.approx(-base.mean_difference)


def test_property_response_price_scale_does_not_change_aligned_returns_300_paths():
    rng = random.Random(20260923)
    start = date(2024, 1, 1)
    for _ in range(300):
        n = rng.randint(3, 25)
        values = [100.0]
        for _i in range(n - 1):
            values.append(values[-1] * (1.0 + rng.uniform(-0.08, 0.08)))
        points = [MarketPoint(data=start + timedelta(days=i), valor=v) for i, v in enumerate(values)]
        obs = [
            regimes.RegimeDriverObservation(
                start_date=start + timedelta(days=i),
                end_date=start + timedelta(days=i + 1),
                driver_value=rng.uniform(-1, 1),
            )
            for i in range(n - 1)
        ]
        base = regimes.align_response_intervals(points, obs)
        scale = 10 ** rng.uniform(-4, 6)
        scaled = regimes.align_response_intervals(
            [MarketPoint(data=p.data, valor=p.valor * scale) for p in points], obs
        )
        assert [p.response_return for p in scaled] == pytest.approx([p.response_return for p in base])
