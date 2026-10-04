"""Regimes históricos explícitos e auditáveis.

A v1 usa somente regras determinísticas (`level`/`direction`). Não faz clustering, HMM, busca de
threshold ótimo, causalidade ou previsão. O driver define intervalos; a resposta é medida nos mesmos
intervalos sem look-ahead.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
import math
import statistics

from pydantic import BaseModel, ConfigDict, Field

from app.market.analytics import conditional as quant_conditional
from app.market.analytics import statistics as quant_statistics
from app.market.analytics.models import ConditionMeasure, ReturnSampleSummary
from app.market.analytics.returns import validate_price_path
from app.market.series import MarketPoint


class RegimeCriterion(StrEnum):
    LEVEL = "level"
    DIRECTION = "direction"


class ThresholdSource(StrEnum):
    EXPLICIT = "explicit"
    SAMPLE_MEDIAN = "sample_median"
    ZERO_DEFAULT = "zero_default"


class RegimeLabel(StrEnum):
    HIGH = "high"
    LOW = "low"
    UP = "up"
    DOWN = "down"


class RegimeDriverObservation(BaseModel):
    """Estatística do driver associada a um intervalo [start,end]."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    start_date: date
    end_date: date
    driver_value: float = Field(allow_inf_nan=False)


class RegimeResponsePair(BaseModel):
    """Driver + resposta observados no mesmo intervalo econômico."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    driver_start_date: date
    driver_end_date: date
    response_start_date: date
    response_end_date: date
    driver_value: float = Field(allow_inf_nan=False)
    response_return: float = Field(ge=-1, allow_inf_nan=False)


class RegimeGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: RegimeLabel
    summary: ReturnSampleSummary


class RegimeAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    criterion: RegimeCriterion
    threshold: float | None = Field(default=None, allow_inf_nan=False)
    threshold_source: ThresholdSource
    n_total: int = Field(ge=0)
    n_neutral: int = Field(ge=0)
    group_1: RegimeGroup
    group_2: RegimeGroup
    mean_difference: float | None = Field(default=None, allow_inf_nan=False)
    sample_stddev_difference: float | None = Field(default=None, allow_inf_nan=False)


def _validated_level_path(points: Sequence[MarketPoint]) -> list[MarketPoint]:
    out = list(points)
    previous: date | None = None
    for point in out:
        if previous is not None and point.data <= previous:
            raise ValueError("datas do driver devem ser estritamente crescentes e únicas")
        previous = point.data
        if not math.isfinite(float(point.valor)):
            raise ValueError(f"valor do driver deve ser finito em {point.data}")
    return out


def driver_observations(
    points: Sequence[MarketPoint],
    *,
    criterion: RegimeCriterion | str,
    direction_measure: ConditionMeasure | str,
) -> list[RegimeDriverObservation]:
    """Constrói a estatística do driver para cada intervalo.

    Em `level`, usa o nível conhecido no INÍCIO do intervalo. Em `direction`, usa a transformação
    canônica já testada pelo Conditional Core: retorno para níveis de mercado e mudança de nível para
    taxa/percentual.
    """
    resolved = RegimeCriterion(criterion)
    measure = ConditionMeasure(direction_measure)
    if resolved is RegimeCriterion.LEVEL:
        path = _validated_level_path(points)
        return [
            RegimeDriverObservation(start_date=start.data, end_date=end.data, driver_value=start.valor)
            for start, end in zip(path, path[1:])
        ]

    changes = quant_conditional.condition_changes(points, measure=measure)
    return [
        RegimeDriverObservation(
            start_date=obs.start_date,
            end_date=obs.end_date,
            driver_value=obs.value,
        )
        for obs in changes
    ]


def align_response_intervals(
    response_points: Sequence[MarketPoint],
    driver_observations: Sequence[RegimeDriverObservation],
    *,
    max_endpoint_gap_days: int | None = None,
) -> list[RegimeResponsePair]:
    """Alinha a resposta aos intervalos do driver com as-of backward e sem look-ahead."""
    if max_endpoint_gap_days is not None and max_endpoint_gap_days < 0:
        raise ValueError("max_endpoint_gap_days deve ser >= 0")
    response = validate_price_path(response_points)
    if not response:
        return []
    dates = [point.data for point in response]
    out: list[RegimeResponsePair] = []
    previous_end: date | None = None
    for obs in driver_observations:
        if obs.end_date <= obs.start_date:
            raise ValueError("intervalo do driver deve ter fim posterior ao início")
        if previous_end is not None and (obs.start_date < previous_end or obs.end_date <= previous_end):
            raise ValueError("observações do driver devem estar em ordem cronológica e sem sobreposição")
        previous_end = obs.end_date

        start_idx = bisect_right(dates, obs.start_date) - 1
        end_idx = bisect_right(dates, obs.end_date) - 1
        if start_idx < 0 or end_idx < 0 or end_idx <= start_idx:
            continue
        start = response[start_idx]
        end = response[end_idx]
        if max_endpoint_gap_days is not None:
            if ((obs.start_date - start.data).days > max_endpoint_gap_days
                    or (obs.end_date - end.data).days > max_endpoint_gap_days):
                continue
        ret = end.valor / start.valor - 1.0
        if not math.isfinite(ret):
            raise ValueError("retorno da resposta não finito")
        out.append(RegimeResponsePair(
            driver_start_date=obs.start_date,
            driver_end_date=obs.end_date,
            response_start_date=start.data,
            response_end_date=end.data,
            driver_value=obs.driver_value,
            response_return=ret,
        ))
    return out


def _return_summary(values: Sequence[float]) -> ReturnSampleSummary:
    described = quant_statistics.describe(values)
    if described.count == 0:
        return ReturnSampleSummary(count=0)
    positive = sum(1 for value in values if value > 0) / described.count
    return ReturnSampleSummary(
        count=described.count,
        mean=described.mean,
        median=described.median,
        sample_stddev=described.sample_stddev,
        minimum=described.minimum,
        maximum=described.maximum,
        positive_fraction=positive,
    )


def analyze_regimes(
    pairs: Sequence[RegimeResponsePair],
    *,
    criterion: RegimeCriterion | str,
    threshold: float | None = None,
) -> RegimeAnalysis:
    """Particiona pares em dois regimes e neutros, sem inferência causal.

    - `level`: `high > threshold`, `low < threshold`; default = mediana retrospectiva do driver.
    - `direction`: `up > +threshold`, `down < -threshold`; default = zero.
    """
    resolved = RegimeCriterion(criterion)
    sample = list(pairs)
    for pair in sample:
        if not math.isfinite(pair.driver_value) or not math.isfinite(pair.response_return):
            raise ValueError("pares de regime devem conter valores finitos")

    if threshold is not None:
        threshold_value = float(threshold)
        if not math.isfinite(threshold_value):
            raise ValueError("threshold deve ser finito")
        if resolved is RegimeCriterion.DIRECTION and threshold_value < 0:
            raise ValueError("threshold de direção deve ser >= 0")
        source = ThresholdSource.EXPLICIT
    elif resolved is RegimeCriterion.LEVEL:
        threshold_value = statistics.median([p.driver_value for p in sample]) if sample else None
        source = ThresholdSource.SAMPLE_MEDIAN
    else:
        threshold_value = 0.0
        source = ThresholdSource.ZERO_DEFAULT

    if resolved is RegimeCriterion.LEVEL:
        high = [p for p in sample if threshold_value is not None and p.driver_value > threshold_value]
        low = [p for p in sample if threshold_value is not None and p.driver_value < threshold_value]
        neutral = [p for p in sample if threshold_value is None or p.driver_value == threshold_value]
        label_1, label_2 = RegimeLabel.HIGH, RegimeLabel.LOW
        first, second = high, low
    else:
        assert threshold_value is not None
        up = [p for p in sample if p.driver_value > threshold_value]
        down = [p for p in sample if p.driver_value < -threshold_value]
        neutral = [p for p in sample if -threshold_value <= p.driver_value <= threshold_value]
        label_1, label_2 = RegimeLabel.UP, RegimeLabel.DOWN
        first, second = up, down

    summary_1 = _return_summary([p.response_return for p in first])
    summary_2 = _return_summary([p.response_return for p in second])
    mean_diff = (
        summary_1.mean - summary_2.mean
        if summary_1.mean is not None and summary_2.mean is not None
        else None
    )
    vol_diff = (
        summary_1.sample_stddev - summary_2.sample_stddev
        if summary_1.sample_stddev is not None and summary_2.sample_stddev is not None
        else None
    )
    return RegimeAnalysis(
        criterion=resolved,
        threshold=threshold_value,
        threshold_source=source,
        n_total=len(sample),
        n_neutral=len(neutral),
        group_1=RegimeGroup(label=label_1, summary=summary_1),
        group_2=RegimeGroup(label=label_2, summary=summary_2),
        mean_difference=mean_diff,
        sample_stddev_difference=vol_diff,
    )
