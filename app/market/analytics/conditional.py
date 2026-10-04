"""Análise condicional descritiva sobre intervalos definidos por uma série condicionante.

Sem banco, policy, LLM ou inferência causal. A condicionante define os intervalos; o ativo-resposta
é medido no mesmo intervalo usando somente o último preço disponível em ou antes de cada endpoint.
"""
from __future__ import annotations

from bisect import bisect_right
import math
from collections.abc import Sequence

from app.market.analytics import statistics as quant_statistics
from app.market.analytics.models import (
    ConditionChangeObservation,
    ConditionDirection,
    ConditionMeasure,
    ConditionalResponsePair,
    ConditionalReturnAnalysis,
    ReturnSampleSummary,
)
from app.market.analytics.returns import validate_price_path
from app.market.series import MarketPoint


def _validated_level_path(points: Sequence[MarketPoint]) -> list[MarketPoint]:
    out = list(points)
    previous = None
    for point in out:
        if previous is not None and point.data <= previous:
            raise ValueError("datas da condicionante devem ser estritamente crescentes e únicas")
        previous = point.data
        if not math.isfinite(float(point.valor)):
            raise ValueError(f"valor da condicionante deve ser finito em {point.data}")
    return out


def condition_changes(
    points: Sequence[MarketPoint],
    *,
    measure: ConditionMeasure | str,
) -> list[ConditionChangeObservation]:
    """Transforma níveis consecutivos em mudanças auditáveis com início/fim explícitos.

    `return` exige níveis positivos e calcula retorno simples. `level_change` aceita níveis
    negativos e calcula diferença absoluta na unidade original da série.
    """
    resolved = ConditionMeasure(measure)
    path = (validate_price_path(points) if resolved is ConditionMeasure.RETURN
            else _validated_level_path(points))
    out: list[ConditionChangeObservation] = []
    for start, end in zip(path, path[1:]):
        value = (end.valor / start.valor - 1.0
                 if resolved is ConditionMeasure.RETURN
                 else end.valor - start.valor)
        if not math.isfinite(value):
            raise ValueError(f"mudança da condicionante não finita em {end.data}")
        out.append(ConditionChangeObservation(
            start_date=start.data,
            end_date=end.data,
            value=value,
        ))
    return out


def align_response_intervals(
    response_points: Sequence[MarketPoint],
    condition_observations: Sequence[ConditionChangeObservation],
    *,
    max_endpoint_gap_days: int | None = None,
) -> list[ConditionalResponsePair]:
    """Mede o retorno simples do ativo nos intervalos da condicionante sem look-ahead.

    Para cada endpoint usa o último preço do ativo em ou antes da data. Se início/fim resolvem para o
    mesmo fechamento, o intervalo não contém retorno observável e é descartado.
    """
    if max_endpoint_gap_days is not None and max_endpoint_gap_days < 0:
        raise ValueError("max_endpoint_gap_days deve ser >= 0")
    response = validate_price_path(response_points)
    if not response:
        return []
    dates = [point.data for point in response]
    out: list[ConditionalResponsePair] = []
    previous_end = None
    for obs in condition_observations:
        if obs.end_date <= obs.start_date:
            raise ValueError("intervalo da condicionante deve ter fim posterior ao início")
        if previous_end is not None and (obs.start_date < previous_end or obs.end_date <= previous_end):
            raise ValueError("observações condicionantes devem estar em ordem cronológica e sem sobreposição")
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
        value = end.valor / start.valor - 1.0
        if not math.isfinite(value):
            raise ValueError("retorno da resposta não finito")
        out.append(ConditionalResponsePair(
            condition_start_date=obs.start_date,
            condition_end_date=obs.end_date,
            response_start_date=start.data,
            response_end_date=end.data,
            condition_change=obs.value,
            response_return=value,
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


def analyze_conditional_returns(
    pairs: Sequence[ConditionalResponsePair],
    *,
    direction: ConditionDirection | str,
    threshold: float = 0.0,
) -> ConditionalReturnAnalysis:
    """Compara retorno do ativo nos intervalos selecionados contra todos os intervalos válidos.

    `threshold` é simétrico e não negativo: alta seleciona `change > threshold`; queda seleciona
    `change < -threshold`. Valores dentro de `[-threshold, +threshold]` são neutros.
    """
    resolved_direction = ConditionDirection(direction)
    threshold_value = float(threshold)
    if not math.isfinite(threshold_value) or threshold_value < 0:
        raise ValueError("threshold deve ser finito e >= 0")
    sample = list(pairs)
    for pair in sample:
        if not math.isfinite(pair.condition_change) or not math.isfinite(pair.response_return):
            raise ValueError("par condicional deve conter valores finitos")

    if resolved_direction is ConditionDirection.UP:
        selected = [p for p in sample if p.condition_change > threshold_value]
    else:
        selected = [p for p in sample if p.condition_change < -threshold_value]
    neutral = [p for p in sample if -threshold_value <= p.condition_change <= threshold_value]

    selected_summary = _return_summary([p.response_return for p in selected])
    baseline_summary = _return_summary([p.response_return for p in sample])
    condition_summary = quant_statistics.describe([p.condition_change for p in selected])
    mean_difference = (
        selected_summary.mean - baseline_summary.mean
        if selected_summary.mean is not None and baseline_summary.mean is not None
        else None
    )
    return ConditionalReturnAnalysis(
        direction=resolved_direction,
        threshold=threshold_value,
        n_total=len(sample),
        n_selected=len(selected),
        n_neutral=len(neutral),
        selected=selected_summary,
        baseline=baseline_summary,
        selected_condition=condition_summary,
        mean_difference=mean_difference,
    )
