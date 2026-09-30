"""Event study univariado do Quant Core.

Opera apenas sobre retornos já calculados. O relógio é a interseção de datas ativo×benchmark;
nenhuma consulta a banco, policy ou LLM ocorre aqui. A inferência clássica é opt-in e explicita
hipóteses fortes; o default é puramente descritivo.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.market.analytics.dependence import align_returns
from app.market.analytics.estimates import ConfidenceInterval, MetricEstimate
from app.market.analytics.models import ReturnMethod, ReturnObservation
from app.market.analytics.returns import calculate_returns, validate_price_path
from app.market.series import MarketPoint
from app.market.analytics.regression import RegressionObservation, fit_univariate_ols_hac


NO_ALIGNED_EVENT = "sem_retorno_alinhado_no_evento"
INSUFFICIENT_ESTIMATION = "amostra_insuficiente_event_study"
CONSTANT_BENCHMARK = "benchmark_constante_event_study"
INFERENCE_UNAVAILABLE = "event_study_inferencia_indisponivel"
CLASSIC_ASSUMPTIONS = "event_study_inferencia_hipoteses_fortes"


class EventStudyMethod(StrEnum):
    MARKET_MODEL = "market_model"
    MARKET_ADJUSTED = "market_adjusted"


class EventInferenceMode(StrEnum):
    NONE = "none"
    CLASSIC_IID_NORMAL = "classic_iid_normal"


class EventStudyWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_date: date | None = None
    end_date: date | None = None
    count: int = Field(ge=0)


class EventAbnormalReturn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    value: float = Field(allow_inf_nan=False)


class EventStudyAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    requested_event_date: date
    effective_event_date: date | None
    method: EventStudyMethod
    inference_mode: EventInferenceMode
    alpha: float | None = Field(default=None, allow_inf_nan=False)
    beta: float | None = Field(default=None, allow_inf_nan=False)
    residual_stddev: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    abnormal_returns: list[EventAbnormalReturn] = Field(default_factory=list)
    car: float | None = Field(default=None, allow_inf_nan=False)
    car_estimate: MetricEstimate | None = None
    estimation_window: EventStudyWindow
    event_window: EventStudyWindow
    pre_truncated: bool
    post_truncated: bool
    n_pairs_total: int = Field(ge=0)
    warnings: tuple[str, ...] = ()


def synchronized_returns_from_prices(
    asset_points: Sequence[MarketPoint],
    benchmark_points: Sequence[MarketPoint],
    *,
    method: ReturnMethod | str,
) -> tuple[list[ReturnObservation], list[ReturnObservation]]:
    """Alinha níveis por datas comuns ANTES de calcular retornos.

    Isso garante que cada retorno de ativo e benchmark usa exatamente os mesmos endpoints. Alinhar
    apenas a data final de retornos calculados separadamente é incorreto quando uma série tem lacuna.
    """
    asset = validate_price_path(asset_points)
    benchmark = validate_price_path(benchmark_points)
    asset_by_date = {p.data: p.valor for p in asset}
    benchmark_by_date = {p.data: p.valor for p in benchmark}
    common_dates = sorted(set(asset_by_date) & set(benchmark_by_date))
    aligned_asset = [MarketPoint(data=d, valor=asset_by_date[d]) for d in common_dates]
    aligned_benchmark = [MarketPoint(data=d, valor=benchmark_by_date[d]) for d in common_dates]
    return calculate_returns(aligned_asset, method), calculate_returns(aligned_benchmark, method)


def _window(pairs, start: int, end: int) -> EventStudyWindow:
    sample = pairs[start:end]
    return EventStudyWindow(
        start_date=sample[0].x_date if sample else None,
        end_date=sample[-1].x_date if sample else None,
        count=len(sample),
    )


def _classic_metric(*, car: float | None, se: float | None, n_event: int,
                    confidence_level: float, method: str) -> MetricEstimate:
    if car is None:
        return MetricEstimate(
            estimate=None, unit="pct_abnormal_return", n=0,
            method=method, warnings=(INFERENCE_UNAVAILABLE,),
        )
    if se is None:
        return MetricEstimate(
            estimate=car * 100.0, unit="pct_abnormal_return", n=n_event,
            method=method, warnings=(INFERENCE_UNAVAILABLE,),
        )
    z = statistics.NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    estimate = car * 100.0
    se_pct = se * 100.0
    return MetricEstimate(
        estimate=estimate,
        unit="pct_abnormal_return",
        n=n_event,
        standard_error=se_pct,
        confidence_interval=ConfidenceInterval(
            lower=estimate - z * se_pct,
            upper=estimate + z * se_pct,
            level=confidence_level,
            method="normal_asymptotic_classic_event_study_iid",
        ),
        method=method,
        warnings=(CLASSIC_ASSUMPTIONS,),
    )


def analyze_event_study(
    asset_returns: Sequence[ReturnObservation],
    benchmark_returns: Sequence[ReturnObservation],
    *,
    event_date: date,
    method: EventStudyMethod | str,
    estimation_observations: int,
    pre_observations: int,
    post_observations: int,
    inference_mode: EventInferenceMode | str = EventInferenceMode.NONE,
    confidence_level: float = 0.95,
) -> EventStudyAnalysis:
    """Calcula AR/CAR com janelas em observações de retorno alinhadas.

    A janela de estimação termina imediatamente antes do início da janela de evento. Portanto não
    existe overlap entre estimação e evento, inclusive quando `pre_observations > 0`.
    """
    if estimation_observations < 1:
        raise ValueError("estimation_observations deve ser >= 1")
    if pre_observations < 0 or post_observations < 0:
        raise ValueError("pre_observations e post_observations devem ser >= 0")
    if not (0.0 < confidence_level < 1.0) or not math.isfinite(confidence_level):
        raise ValueError("confidence_level deve estar entre 0 e 1")

    resolved_method = EventStudyMethod(method)
    resolved_inference = EventInferenceMode(inference_mode)
    pairs = align_returns(asset_returns, benchmark_returns, lag_observations=0)
    warnings: list[str] = []

    idx = next((i for i, pair in enumerate(pairs) if pair.x_date >= event_date), None)
    if idx is None:
        warnings.append(NO_ALIGNED_EVENT)
        empty = EventStudyWindow(count=0)
        car_estimate = (
            _classic_metric(
                car=None, se=None, n_event=0, confidence_level=confidence_level,
                method="classic_event_study_iid_normal_unavailable",
            )
            if resolved_inference is EventInferenceMode.CLASSIC_IID_NORMAL else None
        )
        return EventStudyAnalysis(
            requested_event_date=event_date,
            effective_event_date=None,
            method=resolved_method,
            inference_mode=resolved_inference,
            car_estimate=car_estimate,
            estimation_window=empty,
            event_window=empty,
            pre_truncated=False,
            post_truncated=False,
            n_pairs_total=len(pairs),
            warnings=tuple(warnings),
        )

    effective = pairs[idx].x_date
    raw_event_start = idx - pre_observations
    raw_event_end = idx + post_observations + 1
    pre_truncated = raw_event_start < 0
    post_truncated = raw_event_end > len(pairs)
    event_start = max(0, raw_event_start)
    event_end = min(len(pairs), raw_event_end)
    event_pairs = pairs[event_start:event_end]

    estimation_end = event_start
    estimation_start = max(0, estimation_end - estimation_observations)
    estimation_pairs = pairs[estimation_start:estimation_end]

    estimation_window = _window(pairs, estimation_start, estimation_end)
    event_window = _window(pairs, event_start, event_end)

    alpha: float | None
    beta: float | None
    residuals: list[float] = []

    if resolved_method is EventStudyMethod.MARKET_ADJUSTED:
        alpha, beta = 0.0, 1.0
        residuals = [p.x_value - p.y_value for p in estimation_pairs]
    else:
        if len(estimation_pairs) < 2:
            alpha = beta = None
            warnings.append(INSUFFICIENT_ESTIMATION)
        else:
            reg = fit_univariate_ols_hac([
                RegressionObservation(x=p.y_value, y=p.x_value) for p in estimation_pairs
            ])
            alpha = reg.intercept.estimate
            beta = reg.slope.estimate
            if alpha is None or beta is None:
                warnings.append(CONSTANT_BENCHMARK)
            else:
                residuals = [p.x_value - (alpha + beta * p.y_value) for p in estimation_pairs]

    abnormal: list[EventAbnormalReturn] = []
    car: float | None = None
    if alpha is not None and beta is not None and event_pairs:
        abnormal = [
            EventAbnormalReturn(data=p.x_date, value=p.x_value - (alpha + beta * p.y_value))
            for p in event_pairs
        ]
        car = math.fsum(obs.value for obs in abnormal)

    residual_stddev: float | None = None
    if resolved_method is EventStudyMethod.MARKET_MODEL:
        if alpha is not None and beta is not None and len(estimation_pairs) >= 3:
            sse = math.fsum(e * e for e in residuals)
            residual_stddev = math.sqrt(max(0.0, sse / (len(estimation_pairs) - 2)))
    elif len(residuals) >= 2:
        residual_stddev = statistics.stdev(residuals)

    car_estimate: MetricEstimate | None = None
    if resolved_inference is EventInferenceMode.CLASSIC_IID_NORMAL:
        se_car: float | None = None
        inference_method: str
        if resolved_method is EventStudyMethod.MARKET_ADJUSTED:
            inference_method = "classic_market_adjusted_iid_normal"
            if residual_stddev is not None and abnormal:
                se_car = residual_stddev * math.sqrt(len(abnormal))
        else:
            inference_method = "classic_market_model_iid_normal"
            n_est = len(estimation_pairs)
            if residual_stddev is not None and n_est >= 3 and abnormal:
                xs = [p.y_value for p in estimation_pairs]
                xbar = statistics.fmean(xs)
                sxx = math.fsum((x - xbar) ** 2 for x in xs)
                if sxx > 0.0:
                    l_event = len(event_pairs)
                    sum_x_event = math.fsum(p.y_value for p in event_pairs)
                    sigma2 = residual_stddev ** 2
                    variance = sigma2 * (
                        l_event
                        + (l_event * l_event) / n_est
                        + ((sum_x_event - l_event * xbar) ** 2) / sxx
                    )
                    if variance < 0.0 and variance >= -1e-15:
                        variance = 0.0
                    if variance >= 0.0:
                        se_car = math.sqrt(variance)
        car_estimate = _classic_metric(
            car=car,
            se=se_car,
            n_event=len(abnormal),
            confidence_level=confidence_level,
            method=inference_method,
        )

    return EventStudyAnalysis(
        requested_event_date=event_date,
        effective_event_date=effective,
        method=resolved_method,
        inference_mode=resolved_inference,
        alpha=alpha,
        beta=beta,
        residual_stddev=residual_stddev,
        abnormal_returns=abnormal,
        car=car,
        car_estimate=car_estimate,
        estimation_window=estimation_window,
        event_window=event_window,
        pre_truncated=pre_truncated,
        post_truncated=post_truncated,
        n_pairs_total=len(pairs),
        warnings=tuple(dict.fromkeys(warnings)),
    )
