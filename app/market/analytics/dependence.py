"""Dependência estatística pura entre séries de retorno.

Sem acesso a banco, policy, LLM ou registry. Correlação é associação, nunca causalidade.
As convenções de lag/rolling/condicionamento estão documentadas em `.ai/FQ2_3_DEPENDENCE_DESIGN.md`.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence

from app.market.analytics.models import (
    ConditionalDependenceEstimate,
    DependenceDirection,
    DependenceEstimate,
    DependenceMethod,
    PairedReturnObservation,
    ReturnObservation,
    RollingDependenceObservation,
)
from app.market.analytics.statistics import finite_values


def _validated_return_observations(observations: Sequence[ReturnObservation]) -> list[ReturnObservation]:
    out = list(observations)
    previous_date = None
    for obs in out:
        if previous_date is not None and obs.data <= previous_date:
            raise ValueError("datas de retorno devem ser estritamente crescentes e únicas")
        previous_date = obs.data
    return out


def _paired_finite_values(x: Iterable[float], y: Iterable[float]) -> tuple[list[float], list[float]]:
    xs = finite_values(x)
    ys = finite_values(y)
    if len(xs) != len(ys):
        raise ValueError("x e y devem ter o mesmo tamanho")
    return xs, ys


def _is_constant(values: Sequence[float]) -> bool:
    return bool(values) and min(values) == max(values)


def pearson_correlation(x: Iterable[float], y: Iterable[float]) -> float | None:
    """Pearson compatível com `statistics.correlation`; indefinido => ``None``."""
    xs, ys = _paired_finite_values(x, y)
    if len(xs) < 2 or _is_constant(xs) or _is_constant(ys):
        return None
    try:
        result = statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None
    if not math.isfinite(result):
        raise ValueError("correlação de Pearson não finita")
    # Proteção apenas para drift microscópico: o modelo de saída deve respeitar [-1, 1].
    if result > 1.0 and result <= 1.0 + 1e-15:
        return 1.0
    if result < -1.0 and result >= -1.0 - 1e-15:
        return -1.0
    if not -1.0 <= result <= 1.0:
        raise ValueError("correlação de Pearson fora de [-1, 1]")
    return result


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Ranks 1-based crescentes; empates recebem a média dos ranks ocupados."""
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        value = indexed[start][1]
        while end < len(indexed) and indexed[end][1] == value:
            end += 1
        # posições start..end-1 correspondem a ranks 1-based start+1..end
        average_rank = ((start + 1) + end) / 2.0
        for position in range(start, end):
            ranks[indexed[position][0]] = average_rank
        start = end
    return ranks


def spearman_correlation(x: Iterable[float], y: Iterable[float]) -> float | None:
    """Spearman como Pearson sobre ranks médios, incluindo tratamento explícito de empates."""
    xs, ys = _paired_finite_values(x, y)
    if len(xs) < 2:
        return None
    return pearson_correlation(_average_ranks(xs), _average_ranks(ys))


def align_returns(
    x: Sequence[ReturnObservation],
    y: Sequence[ReturnObservation],
    *,
    lag_observations: int = 0,
) -> list[PairedReturnObservation]:
    """Alinha retornos por interseção de datas e aplica lag assinado sobre as datas comuns.

    ``lag > 0``: X antecede Y. ``lag < 0``: Y antecede X. Nenhum padding/interpolação é feito.
    """
    xs = _validated_return_observations(x)
    ys = _validated_return_observations(y)
    x_by_date = {obs.data: obs.value for obs in xs}
    y_by_date = {obs.data: obs.value for obs in ys}
    common_dates = sorted(set(x_by_date) & set(y_by_date))
    n = len(common_dates)
    lag = int(lag_observations)
    distance = abs(lag)
    if distance >= n:
        return []

    pairs: list[PairedReturnObservation] = []
    if lag >= 0:
        indices = ((i, i + lag) for i in range(n - lag))
    else:
        indices = ((i + distance, i) for i in range(n - distance))

    for x_index, y_index in indices:
        x_date = common_dates[x_index]
        y_date = common_dates[y_index]
        pairs.append(PairedReturnObservation(
            x_date=x_date,
            y_date=y_date,
            as_of_date=max(x_date, y_date),
            x_value=x_by_date[x_date],
            y_value=y_by_date[y_date],
        ))
    return pairs


def dependence_estimate(
    pairs: Sequence[PairedReturnObservation],
    *,
    method: DependenceMethod | str,
    lag_observations: int = 0,
) -> DependenceEstimate:
    """Calcula uma estimativa sobre pares já alinhados."""
    resolved_method = DependenceMethod(method)
    xs = [pair.x_value for pair in pairs]
    ys = [pair.y_value for pair in pairs]
    x_constant = _is_constant(xs)
    y_constant = _is_constant(ys)
    if resolved_method is DependenceMethod.PEARSON:
        coefficient = pearson_correlation(xs, ys)
    else:
        coefficient = spearman_correlation(xs, ys)
    return DependenceEstimate(
        method=resolved_method,
        coefficient=coefficient,
        n_pairs=len(pairs),
        lag_observations=int(lag_observations),
        x_constant=x_constant,
        y_constant=y_constant,
    )


def rolling_dependence(
    x: Sequence[ReturnObservation],
    y: Sequence[ReturnObservation],
    *,
    window: int,
    method: DependenceMethod | str = DependenceMethod.PEARSON,
    lag_observations: int = 0,
) -> list[RollingDependenceObservation]:
    """Dependência em janela móvel de pares alinhados, sem padding/interpolação."""
    if window < 2:
        raise ValueError("window deve ser >= 2")
    resolved_method = DependenceMethod(method)
    pairs = align_returns(x, y, lag_observations=lag_observations)
    if len(pairs) < window:
        return []
    out: list[RollingDependenceObservation] = []
    for end in range(window, len(pairs) + 1):
        chunk = pairs[end - window:end]
        estimate = dependence_estimate(
            chunk,
            method=resolved_method,
            lag_observations=lag_observations,
        )
        out.append(RollingDependenceObservation(
            data=chunk[-1].as_of_date,
            method=resolved_method,
            coefficient=estimate.coefficient,
            n_pairs=estimate.n_pairs,
            lag_observations=int(lag_observations),
        ))
    return out


def _conditional_market_dependence(
    asset: Sequence[ReturnObservation],
    market: Sequence[ReturnObservation],
    *,
    direction: DependenceDirection,
    threshold: float,
    method: DependenceMethod | str,
    lag_observations: int,
) -> ConditionalDependenceEstimate:
    threshold_value = float(threshold)
    if not math.isfinite(threshold_value):
        raise ValueError("threshold deve ser finito")
    resolved_method = DependenceMethod(method)
    pairs = align_returns(asset, market, lag_observations=lag_observations)
    if direction is DependenceDirection.UP:
        selected = [pair for pair in pairs if pair.y_value > threshold_value]
    else:
        selected = [pair for pair in pairs if pair.y_value < threshold_value]
    estimate = dependence_estimate(
        selected,
        method=resolved_method,
        lag_observations=lag_observations,
    )
    return ConditionalDependenceEstimate(
        direction=direction,
        threshold=threshold_value,
        method=resolved_method,
        coefficient=estimate.coefficient,
        n_pairs=estimate.n_pairs,
        lag_observations=int(lag_observations),
        x_constant=estimate.x_constant,
        y_constant=estimate.y_constant,
    )


def up_market_dependence(
    asset: Sequence[ReturnObservation],
    market: Sequence[ReturnObservation],
    *,
    threshold: float = 0.0,
    method: DependenceMethod | str = DependenceMethod.PEARSON,
    lag_observations: int = 0,
) -> ConditionalDependenceEstimate:
    """Dependência nos pares em que o retorno da série de mercado está acima do threshold."""
    return _conditional_market_dependence(
        asset,
        market,
        direction=DependenceDirection.UP,
        threshold=threshold,
        method=method,
        lag_observations=lag_observations,
    )


def down_market_dependence(
    asset: Sequence[ReturnObservation],
    market: Sequence[ReturnObservation],
    *,
    threshold: float = 0.0,
    method: DependenceMethod | str = DependenceMethod.PEARSON,
    lag_observations: int = 0,
) -> ConditionalDependenceEstimate:
    """Dependência nos pares em que o retorno da série de mercado está abaixo do threshold."""
    return _conditional_market_dependence(
        asset,
        market,
        direction=DependenceDirection.DOWN,
        threshold=threshold,
        method=method,
        lag_observations=lag_observations,
    )
