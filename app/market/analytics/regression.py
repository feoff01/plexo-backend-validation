"""Regressão linear univariada do Quant Core.

A estimativa pontual é OLS com intercepto. A incerteza usa covariance HAC/Newey–West com kernel
Bartlett e correção finita n/(n-k), apropriada como primeira camada robusta para observações
ordenadas no tempo. Sem banco, LLM, policy, NumPy/SciPy/statsmodels ou decisão de significância.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.market.analytics.estimates import ConfidenceInterval, MetricEstimate


METHOD = "ols_hac_newey_west_bartlett_hc1"
CI_METHOD = "normal_asymptotic_hac_newey_west"
NO_DOF = "sem_graus_liberdade_inferencia"
INSUFFICIENT = "amostra_insuficiente_regressao"
CONSTANT_DRIVER = "driver_constante"


class RegressionObservation(BaseModel):
    """Par numérico já alinhado; transformação/unidade pertencem ao caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class LinearRegressionResult(BaseModel):
    """Resultado auditável de OLS univariada com covariance HAC."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    n: int = Field(ge=0)
    slope: MetricEstimate
    intercept: MetricEstimate
    r_squared: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    hac_lags: int = Field(ge=0)
    confidence_level: float = Field(gt=0, lt=1, allow_inf_nan=False)
    covariance_method: str
    residual_sum_squares: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    total_sum_squares: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def newey_west_auto_lags(n: int) -> int:
    """Bandwidth automático clássico, medido em observações e limitado pela amostra.

    L = floor(4 * (n / 100) ** (2/9)), com `L <= n-2` para preservar ao menos um grau
    de liberdade residual quando covariance é calculável.
    """
    if n <= 2:
        return 0
    raw = math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))
    return max(0, min(raw, n - 2))


def _matmul2(a: tuple[tuple[float, float], tuple[float, float]],
             b: tuple[tuple[float, float], tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    return (
        (a[0][0] * b[0][0] + a[0][1] * b[1][0],
         a[0][0] * b[0][1] + a[0][1] * b[1][1]),
        (a[1][0] * b[0][0] + a[1][1] * b[1][0],
         a[1][0] * b[0][1] + a[1][1] * b[1][1]),
    )


def _nonnegative_variance(value: float) -> float:
    if value >= 0:
        return value
    # Produto de matrizes pode gerar -1e-30 em casos exatos. Só toleramos ruído de máquina.
    if value >= -1e-12:
        return 0.0
    raise ArithmeticError(f"variância robusta negativa: {value}")


def _metric(
    estimate: float | None,
    *,
    unit: str,
    n: int,
    standard_error: float | None,
    confidence_level: float,
    warnings: tuple[str, ...] = (),
    method: str = METHOD,
) -> MetricEstimate:
    ci = None
    if estimate is not None and standard_error is not None:
        z = statistics.NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
        ci = ConfidenceInterval(
            lower=estimate - z * standard_error,
            upper=estimate + z * standard_error,
            level=confidence_level,
            method=CI_METHOD,
        )
    return MetricEstimate(
        estimate=estimate,
        unit=unit,
        n=n,
        standard_error=standard_error,
        confidence_interval=ci,
        method=method,
        warnings=warnings,
    )


def _undefined(*, unit: str, n: int, warning: str) -> MetricEstimate:
    return MetricEstimate(
        estimate=None,
        unit=unit,
        n=n,
        method=METHOD,
        warnings=(warning,),
    )


def fit_univariate_ols_hac(
    observations: Sequence[RegressionObservation],
    *,
    hac_lags: int | None = None,
    confidence_level: float = 0.95,
    slope_unit: str = "y_per_x",
    intercept_unit: str = "y",
) -> LinearRegressionResult:
    """Estima `y = intercept + slope*x + error` com covariance Newey–West.

    A regressão não remove outliers, não imputa dados e não interpreta causalidade. O caller é
    responsável por alinhamento temporal e transformação semântica das unidades.
    """
    sample = list(observations)
    n = len(sample)
    if not (0.0 < confidence_level < 1.0) or not math.isfinite(confidence_level):
        raise ValueError("confidence_level deve estar estritamente entre 0 e 1")
    requested_lags = newey_west_auto_lags(n) if hac_lags is None else hac_lags
    if requested_lags < 0:
        raise ValueError("hac_lags deve ser >= 0")
    if n >= 1 and requested_lags > max(0, n - 2):
        raise ValueError("hac_lags deve ser <= n-2")

    if n < 2:
        return LinearRegressionResult(
            n=n,
            slope=_undefined(unit=slope_unit, n=n, warning=INSUFFICIENT),
            intercept=_undefined(unit=intercept_unit, n=n, warning=INSUFFICIENT),
            hac_lags=0,
            confidence_level=confidence_level,
            covariance_method=METHOD,
        )

    xs = [float(o.x) for o in sample]
    ys = [float(o.y) for o in sample]
    if any(not math.isfinite(v) for v in xs + ys):
        raise ValueError("regressão recebeu valor não finito")

    x_bar = statistics.fmean(xs)
    y_bar = statistics.fmean(ys)
    centered_x = [x - x_bar for x in xs]
    centered_y = [y - y_bar for y in ys]
    sxx = math.fsum(dx * dx for dx in centered_x)
    if sxx == 0.0:
        return LinearRegressionResult(
            n=n,
            slope=_undefined(unit=slope_unit, n=n, warning=CONSTANT_DRIVER),
            intercept=_undefined(unit=intercept_unit, n=n, warning=CONSTANT_DRIVER),
            hac_lags=requested_lags,
            confidence_level=confidence_level,
            covariance_method=METHOD,
        )

    sxy = math.fsum(dx * dy for dx, dy in zip(centered_x, centered_y))
    slope = sxy / sxx
    intercept = y_bar - slope * x_bar
    # Forma centrada evita cancelamento quando intercepto e slope*x são enormes e quase se anulam.
    residuals = [(y - y_bar) - slope * (x - x_bar) for x, y in zip(xs, ys)]
    sse = max(0.0, math.fsum(e * e for e in residuals))
    sst = max(0.0, math.fsum(dy * dy for dy in centered_y))
    r_squared = None
    if sst > 0.0:
        raw_r2 = 1.0 - sse / sst
        if raw_r2 < -1e-12 or raw_r2 > 1.0 + 1e-12:
            raise ArithmeticError(f"R² fora do domínio esperado: {raw_r2}")
        r_squared = min(1.0, max(0.0, raw_r2))

    if n == 2:
        warning = (NO_DOF,)
        return LinearRegressionResult(
            n=n,
            slope=_metric(slope, unit=slope_unit, n=n, standard_error=None,
                          confidence_level=confidence_level, warnings=warning,
                          method="ols_point_estimate_no_covariance"),
            intercept=_metric(intercept, unit=intercept_unit, n=n, standard_error=None,
                              confidence_level=confidence_level, warnings=warning,
                              method="ols_point_estimate_no_covariance"),
            r_squared=r_squared,
            hac_lags=0,
            confidence_level=confidence_level,
            covariance_method="none_no_residual_degrees_of_freedom",
            residual_sum_squares=sse,
            total_sum_squares=sst,
        )

    # Funções de influência centradas evitam cancelamento catastrófico de X'X quando x possui
    # offset muito grande e pequena dispersão. Para regressão simples com intercepto:
    #   beta_hat  = sum h_beta_i * y_i, h_beta_i = (x_i-x_bar)/Sxx
    #   alpha_hat = sum h_alpha_i * y_i, h_alpha_i = 1/n - x_bar*h_beta_i
    # A covariance HAC é aplicada diretamente a h_i * residual_i.
    influence_intercept: list[float] = []
    influence_slope: list[float] = []
    for x, e in zip(xs, residuals):
        h_slope = (x - x_bar) / sxx
        h_intercept = 1.0 / n - x_bar * h_slope
        influence_slope.append(h_slope * e)
        influence_intercept.append(h_intercept * e)

    def hac_cov(a: list[float], b: list[float]) -> float:
        total = math.fsum(x * y for x, y in zip(a, b))
        for lag in range(1, requested_lags + 1):
            weight = 1.0 - lag / (requested_lags + 1.0)
            total += weight * math.fsum(
                a[t] * b[t - lag] + a[t - lag] * b[t]
                for t in range(lag, n)
            )
        return (n / (n - 2.0)) * total

    intercept_var = _nonnegative_variance(hac_cov(influence_intercept, influence_intercept))
    slope_var = _nonnegative_variance(hac_cov(influence_slope, influence_slope))
    intercept_se = math.sqrt(intercept_var)
    slope_se = math.sqrt(slope_var)

    return LinearRegressionResult(
        n=n,
        slope=_metric(slope, unit=slope_unit, n=n, standard_error=slope_se,
                      confidence_level=confidence_level),
        intercept=_metric(intercept, unit=intercept_unit, n=n, standard_error=intercept_se,
                          confidence_level=confidence_level),
        r_squared=r_squared,
        hac_lags=requested_lags,
        confidence_level=confidence_level,
        covariance_method=METHOD,
        residual_sum_squares=sse,
        total_sum_squares=sst,
    )
