"""Métricas puras de risco sobre retornos e níveis de preço.

Sem acesso a banco, policy ou LLM. Toda base de anualização/target é input explícito.
Convenções relevantes são documentadas em `.ai/FQ2_2_RISK_DESIGN.md`.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from app.market.analytics.models import (
    DrawdownEpisode,
    DrawdownObservation,
    ReturnObservation,
    RollingMetricObservation,
)
from app.market.analytics.returns import validate_price_path
from app.market.analytics.statistics import finite_values, sample_stddev
from app.market.series import MarketPoint


class NonFiniteRiskResult(ValueError):
    """Uma métrica de risco excedeu/violou a representação numérica finita."""


def _positive_periods_per_year(periods_per_year: int) -> None:
    if periods_per_year <= 0:
        raise ValueError("periods_per_year deve ser positivo")


def _finite_target(target_return: float) -> float:
    target = float(target_return)
    if not math.isfinite(target):
        raise ValueError("target_return deve ser finito")
    return target


def _validated_return_observations(observations: Sequence[ReturnObservation]) -> list[ReturnObservation]:
    out = list(observations)
    previous_date = None
    for obs in out:
        if previous_date is not None and obs.data <= previous_date:
            raise ValueError("datas de retorno devem ser estritamente crescentes e únicas")
        previous_date = obs.data
    return out


def annualized_volatility(values: Iterable[float], *, periods_per_year: int) -> float | None:
    """Volatilidade anualizada = desvio-padrão AMOSTRAL × sqrt(base anual)."""
    _positive_periods_per_year(periods_per_year)
    sd = sample_stddev(values)
    if sd is None:
        return None
    result = sd * math.sqrt(periods_per_year)
    if not math.isfinite(result):
        raise NonFiniteRiskResult("volatilidade anualizada não finita")
    return result


def rolling_volatility(
    observations: Sequence[ReturnObservation],
    *,
    window: int,
    periods_per_year: int,
) -> list[RollingMetricObservation]:
    """Volatilidade anualizada em janela móvel, datada no fim de cada janela.

    ``window`` é número de observações de retorno. Não há padding/interpolação.
    """
    if window < 2:
        raise ValueError("window deve ser >= 2 para volatilidade amostral")
    _positive_periods_per_year(periods_per_year)
    obs = _validated_return_observations(observations)
    if len(obs) < window:
        return []
    out: list[RollingMetricObservation] = []
    for end in range(window, len(obs) + 1):
        chunk = obs[end - window:end]
        value = annualized_volatility((item.value for item in chunk), periods_per_year=periods_per_year)
        assert value is not None  # window >= 2
        out.append(RollingMetricObservation(
            data=chunk[-1].data,
            value=value,
            window_observations=window,
        ))
    return out


def downside_deviation(values: Iterable[float], *, target_return: float = 0.0) -> float | None:
    """Semidesvio-alvo por período.

    Fórmula: ``sqrt(mean(min(r_i - target, 0)^2))`` usando TODAS as observações no denominador.
    ``target_return`` deve estar na mesma periodicidade/convenção dos retornos de entrada.
    """
    sample = finite_values(values)
    target = _finite_target(target_return)
    if not sample:
        return None
    sum_squares = 0.0
    for value in sample:
        shortfall = min(value - target, 0.0)
        term = shortfall * shortfall
        if not math.isfinite(term):
            raise NonFiniteRiskResult("downside deviation excede a representação finita")
        sum_squares += term
        if not math.isfinite(sum_squares):
            raise NonFiniteRiskResult("downside deviation excede a representação finita")
    result = math.sqrt(sum_squares / len(sample))
    if not math.isfinite(result):
        raise NonFiniteRiskResult("downside deviation não finita")
    return result


def annualized_downside_deviation(
    values: Iterable[float],
    *,
    target_return: float = 0.0,
    periods_per_year: int,
) -> float | None:
    """Downside deviation anualizada pela raiz da base de períodos."""
    _positive_periods_per_year(periods_per_year)
    periodic = downside_deviation(values, target_return=target_return)
    if periodic is None:
        return None
    result = periodic * math.sqrt(periods_per_year)
    if not math.isfinite(result):
        raise NonFiniteRiskResult("downside deviation anualizada não finita")
    return result


def drawdown_series(points: Sequence[MarketPoint]) -> list[DrawdownObservation]:
    """Série de drawdown em relação ao pico corrente do caminho de preços."""
    path = validate_price_path(points)
    if not path:
        return []
    running_peak = path[0].valor
    out: list[DrawdownObservation] = []
    for point in path:
        running_peak = max(running_peak, point.valor)
        value = point.valor / running_peak - 1.0
        # Por construção deveria ser <= 0; clamp microscópico protege contra drift de ponto flutuante.
        if value > 0.0:
            if value <= 1e-15:
                value = 0.0
            else:
                raise NonFiniteRiskResult("drawdown positivo viola a definição de pico corrente")
        if not math.isfinite(value):
            raise NonFiniteRiskResult("drawdown não finito")
        out.append(DrawdownObservation(data=point.data, value=value, running_peak=running_peak))
    return out


def maximum_drawdown(points: Sequence[MarketPoint]) -> float | None:
    """Menor drawdown do caminho. Compatível com o helper legacy atual."""
    series = drawdown_series(points)
    if not series:
        return None
    return min(item.value for item in series)


def maximum_drawdown_episode(points: Sequence[MarketPoint]) -> DrawdownEpisode | None:
    """Episódio correspondente ao drawdown mais profundo.

    Em empate exato de profundidade, mantém o episódio cronologicamente mais antigo. Uma recuperação
    ocorre quando o preço volta a ser >= ao pico que originou o episódio.
    """
    path = validate_price_path(points)
    if len(path) < 2:
        return None

    peak_index = 0
    peak_value = path[0].valor
    active_peak_index: int | None = None
    trough_index: int | None = None
    active_depth = 0.0
    best: DrawdownEpisode | None = None

    def finalize(recovery_index: int | None) -> DrawdownEpisode:
        assert active_peak_index is not None and trough_index is not None
        end_index = recovery_index if recovery_index is not None else len(path) - 1
        return DrawdownEpisode(
            peak_date=path[active_peak_index].data,
            peak_value=path[active_peak_index].valor,
            trough_date=path[trough_index].data,
            trough_value=path[trough_index].valor,
            recovery_date=path[recovery_index].data if recovery_index is not None else None,
            recovery_value=path[recovery_index].valor if recovery_index is not None else None,
            depth=active_depth,
            time_to_trough_intervals=trough_index - active_peak_index,
            recovery_intervals=(recovery_index - trough_index if recovery_index is not None else None),
            duration_intervals=end_index - active_peak_index,
            recovered=recovery_index is not None,
        )

    for index in range(1, len(path)):
        point = path[index]
        if active_peak_index is None:
            if point.valor >= peak_value:
                peak_index = index
                peak_value = point.valor
                continue
            active_peak_index = peak_index
            trough_index = index
            active_depth = point.valor / peak_value - 1.0
            continue

        # Episódio ativo usa o pico fixo que o originou.
        depth = point.valor / path[active_peak_index].valor - 1.0
        if depth < active_depth:
            active_depth = depth
            trough_index = index

        if point.valor >= path[active_peak_index].valor:
            episode = finalize(index)
            if best is None or episode.depth < best.depth:
                best = episode
            active_peak_index = None
            trough_index = None
            active_depth = 0.0
            peak_index = index
            peak_value = point.valor

    if active_peak_index is not None:
        episode = finalize(None)
        if best is None or episode.depth < best.depth:
            best = episode

    return best


def drawdown_duration(points: Sequence[MarketPoint]) -> int | None:
    """Duração, em intervalos observados, do episódio de maximum drawdown."""
    episode = maximum_drawdown_episode(points)
    return None if episode is None else episode.duration_intervals


def recovery_time(points: Sequence[MarketPoint]) -> int | None:
    """Intervalos observados fundo→recuperação do episódio máximo; ``None`` se não recuperado/inexistente."""
    episode = maximum_drawdown_episode(points)
    return None if episode is None else episode.recovery_intervals
