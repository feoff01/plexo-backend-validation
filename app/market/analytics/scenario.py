"""Cenário mecânico a partir de uma sensibilidade histórica já estimada (FQ5.3).

Não estima nova regressão. Apenas transforma slope × choque em impacto incremental e aplica esse
impacto a um preço-base observável. O resultado não é forecast nem fair value.
"""
from __future__ import annotations

import math
from pydantic import BaseModel, ConfigDict, Field

from app.market.analytics.estimates import MetricEstimate

INVALID_NON_POSITIVE_PRICE = "cenario_implica_preco_nao_positivo"
INVALID_INTERVAL_PRICE = "cenario_intervalo_implica_preco_nao_positivo"
SLOPE_UNAVAILABLE = "sensibilidade_indisponivel"

class NumericRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    lower: float = Field(allow_inf_nan=False)
    upper: float = Field(allow_inf_nan=False)

class SensitivityScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    shock_driver: float = Field(allow_inf_nan=False)
    impact_incremental_pct: float | None = Field(default=None, allow_inf_nan=False)
    impact_interval_pct: NumericRange | None = None
    base_price_brl: float = Field(gt=0, allow_inf_nan=False)
    scenario_price_brl: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    scenario_price_interval_brl: NumericRange | None = None
    warnings: list[str] = Field(default_factory=list)
    method: str = "linear_incremental_sensitivity_scenario"

def apply_sensitivity_scenario(*, slope: MetricEstimate, shock_driver: float, base_price_brl: float) -> SensitivityScenario:
    if not math.isfinite(shock_driver):
        raise ValueError("shock_driver não pode ser NaN/inf")
    if not math.isfinite(base_price_brl) or base_price_brl <= 0:
        raise ValueError("base_price_brl deve ser positivo e finito")
    warnings = list(slope.warnings)
    if shock_driver == 0.0:
        return SensitivityScenario(shock_driver=0.0, impact_incremental_pct=0.0, impact_interval_pct=NumericRange(lower=0.0, upper=0.0), base_price_brl=base_price_brl, scenario_price_brl=base_price_brl, scenario_price_interval_brl=NumericRange(lower=base_price_brl, upper=base_price_brl), warnings=list(dict.fromkeys(warnings)))
    if slope.estimate is None:
        warnings.append(SLOPE_UNAVAILABLE)
        return SensitivityScenario(shock_driver=shock_driver, base_price_brl=base_price_brl, warnings=list(dict.fromkeys(warnings)))
    impact = float(slope.estimate) * shock_driver
    price_factor = 1.0 + impact / 100.0
    scenario_price = None
    if price_factor > 0:
        scenario_price = base_price_brl * price_factor
    else:
        warnings.append(INVALID_NON_POSITIVE_PRICE)
    impact_interval = None
    price_interval = None
    ci = slope.confidence_interval
    if ci is not None:
        a = float(ci.lower) * shock_driver
        b = float(ci.upper) * shock_driver
        low_impact, high_impact = min(a, b), max(a, b)
        impact_interval = NumericRange(lower=low_impact, upper=high_impact)
        low_factor = 1.0 + low_impact / 100.0
        high_factor = 1.0 + high_impact / 100.0
        if low_factor > 0 and high_factor > 0:
            price_interval = NumericRange(lower=base_price_brl * low_factor, upper=base_price_brl * high_factor)
        else:
            warnings.append(INVALID_INTERVAL_PRICE)
    return SensitivityScenario(shock_driver=shock_driver, impact_incremental_pct=impact, impact_interval_pct=impact_interval, base_price_brl=base_price_brl, scenario_price_brl=scenario_price, scenario_price_interval_brl=price_interval, warnings=list(dict.fromkeys(warnings)))
