"""Adapter puro entre pares temporais do FQ4.1 e a regressão de sensibilidade.

Converte as duas dimensões para unidades client-facing explícitas e preserva o relógio do driver.
Não remove outliers, não imputa intervalos e não decide causalidade/significância.
"""
from __future__ import annotations

import statistics
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.market.analytics.estimates import MetricEstimate
from app.market.analytics.models import ConditionMeasure, ConditionalResponsePair
from app.market.analytics.regression import RegressionObservation, fit_univariate_ols_hac


class SensitivityAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int = Field(ge=0)
    driver_measure: ConditionMeasure
    driver_unit: str
    response_unit: str
    slope: MetricEstimate
    intercept: MetricEstimate
    r_squared: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    hac_lags: int = Field(ge=0)
    confidence_level: float = Field(gt=0, lt=1, allow_inf_nan=False)
    covariance_method: str
    interval_days_min: int | None = Field(default=None, ge=1)
    interval_days_median: float | None = Field(default=None, ge=1, allow_inf_nan=False)
    interval_days_max: int | None = Field(default=None, ge=1)
    outlier_policy: str = "none"
    missing_policy: str = "no_imputation_drop_unalignable_intervals"


def analyze_sensitivity(
    pairs: Sequence[ConditionalResponsePair],
    *,
    driver_measure: ConditionMeasure | str,
    confidence_level: float = 0.95,
    hac_lags: int | None = None,
) -> SensitivityAnalysis:
    """Estima sensibilidade linear contemporânea nos mesmos intervalos do driver."""
    measure = ConditionMeasure(driver_measure)
    sample = list(pairs)
    previous_end = None
    intervals: list[int] = []
    observations: list[RegressionObservation] = []

    if measure is ConditionMeasure.RETURN:
        driver_unit = "pct_return"
        slope_unit = "pct_return_per_pct_driver_return"
    else:
        driver_unit = "percentage_point"
        slope_unit = "pct_return_per_percentage_point"

    for pair in sample:
        if pair.condition_end_date <= pair.condition_start_date:
            raise ValueError("intervalo do driver deve ter fim posterior ao início")
        if pair.response_end_date <= pair.response_start_date:
            raise ValueError("intervalo da resposta deve ter fim posterior ao início")
        if pair.response_start_date > pair.condition_start_date or pair.response_end_date > pair.condition_end_date:
            raise ValueError("par de sensibilidade contém look-ahead na resposta")
        if previous_end is not None and pair.condition_start_date < previous_end:
            raise ValueError("pares de sensibilidade devem estar em ordem e sem sobreposição")
        previous_end = pair.condition_end_date
        intervals.append((pair.condition_end_date - pair.condition_start_date).days)
        x = pair.condition_change * 100.0 if measure is ConditionMeasure.RETURN else pair.condition_change
        y = pair.response_return * 100.0
        observations.append(RegressionObservation(x=x, y=y))

    fitted = fit_univariate_ols_hac(
        observations,
        hac_lags=hac_lags,
        confidence_level=confidence_level,
        slope_unit=slope_unit,
        intercept_unit="pct_return",
    )
    return SensitivityAnalysis(
        n=fitted.n,
        driver_measure=measure,
        driver_unit=driver_unit,
        response_unit="pct_return",
        slope=fitted.slope,
        intercept=fitted.intercept,
        r_squared=fitted.r_squared,
        hac_lags=fitted.hac_lags,
        confidence_level=fitted.confidence_level,
        covariance_method=fitted.covariance_method,
        interval_days_min=min(intervals) if intervals else None,
        interval_days_median=statistics.median(intervals) if intervals else None,
        interval_days_max=max(intervals) if intervals else None,
    )
