"""Cálculos puros de market valuation (FQ5).

A engine calcula somente valores observáveis/deriváveis de forma determinística. Não produz fair
value, WACC, crescimento terminal, recomendação ou forecast.
"""
from __future__ import annotations
import math
from pydantic import BaseModel, ConfigDict, Field, model_validator
MISSING_CLASS_COVERAGE = "market_cap_cobertura_incompleta"
NET_DEBT_UNAVAILABLE = "divida_liquida_indisponivel"
NON_POSITIVE_NET_INCOME = "lucro_liquido_nao_positivo"
NON_POSITIVE_EBITDA = "ebitda_nao_positivo"
NON_POSITIVE_EQUITY = "patrimonio_liquido_nao_positivo"
MARKET_CAP_UNAVAILABLE = "market_cap_indisponivel"
class EquityClassInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: str
    ticker: str | None = None
    price_brl: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    shares_outstanding: float | None = Field(default=None, gt=0, allow_inf_nan=False)
class EquityClassValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: str
    ticker: str | None = None
    price_brl: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    shares_outstanding: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    market_value_brl: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    complete: bool
class MarketValuationAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    classes: list[EquityClassValue]
    market_cap_brl: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    net_debt_brl: float | None = Field(default=None, allow_inf_nan=False)
    net_debt_source: str | None = None
    enterprise_value_brl: float | None = Field(default=None, allow_inf_nan=False)
    pe: float | None = Field(default=None, allow_inf_nan=False)
    ev_ebitda: float | None = Field(default=None, allow_inf_nan=False)
    price_to_book: float | None = Field(default=None, allow_inf_nan=False)
    fcf_yield_pct: float | None = Field(default=None, allow_inf_nan=False)
    intrinsic_value_produced: bool = False
    warnings: list[str] = Field(default_factory=list)
    @model_validator(mode="after")
    def _no_intrinsic_value(self):
        if self.intrinsic_value_produced:
            raise ValueError("FQ5.2 não produz intrinsic/fair value")
        return self
def _finite_optional(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} não pode ser NaN/inf")
    return v
def analyze_market_valuation(classes: list[EquityClassInput], *, net_debt_brl: float | None = None, gross_debt_brl: float | None = None, cash_and_equivalents_brl: float | None = None, net_income_brl: float | None = None, ebitda_brl: float | None = None, total_equity_brl: float | None = None, free_cash_flow_brl: float | None = None) -> MarketValuationAnalysis:
    if not classes:
        raise ValueError("valuation exige ao menos uma classe de ação")
    class_values=[]
    for item in classes:
        complete=item.price_brl is not None and item.shares_outstanding is not None
        market_value=float(item.price_brl)*float(item.shares_outstanding) if complete else None
        class_values.append(EquityClassValue(instrument_id=item.instrument_id,ticker=item.ticker,price_brl=item.price_brl,shares_outstanding=item.shares_outstanding,market_value_brl=market_value,complete=complete))
    warnings=[]
    market_cap=math.fsum(c.market_value_brl or 0.0 for c in class_values) if all(c.complete for c in class_values) else None
    if market_cap is None:
        warnings += [MISSING_CLASS_COVERAGE, MARKET_CAP_UNAVAILABLE]
    explicit_net_debt=_finite_optional(net_debt_brl,"net_debt_brl")
    gross_debt=_finite_optional(gross_debt_brl,"gross_debt_brl")
    cash=_finite_optional(cash_and_equivalents_brl,"cash_and_equivalents_brl")
    if explicit_net_debt is not None:
        net_debt,net_debt_source=explicit_net_debt,"reported"
    elif gross_debt is not None and cash is not None:
        net_debt,net_debt_source=gross_debt-cash,"derived_gross_debt_minus_cash"
    else:
        net_debt,net_debt_source=None,None; warnings.append(NET_DEBT_UNAVAILABLE)
    ev=market_cap+net_debt if market_cap is not None and net_debt is not None else None
    net_income=_finite_optional(net_income_brl,"net_income_brl"); ebitda=_finite_optional(ebitda_brl,"ebitda_brl"); equity=_finite_optional(total_equity_brl,"total_equity_brl"); fcf=_finite_optional(free_cash_flow_brl,"free_cash_flow_brl")
    pe=None
    if market_cap is not None and net_income is not None:
        if net_income>0: pe=market_cap/net_income
        else: warnings.append(NON_POSITIVE_NET_INCOME)
    ev_ebitda=None
    if ev is not None and ebitda is not None:
        if ebitda>0: ev_ebitda=ev/ebitda
        else: warnings.append(NON_POSITIVE_EBITDA)
    price_to_book=None
    if market_cap is not None and equity is not None:
        if equity>0: price_to_book=market_cap/equity
        else: warnings.append(NON_POSITIVE_EQUITY)
    fcf_yield_pct=100.0*fcf/market_cap if market_cap is not None and market_cap>0 and fcf is not None else None
    return MarketValuationAnalysis(classes=class_values,market_cap_brl=market_cap,net_debt_brl=net_debt,net_debt_source=net_debt_source,enterprise_value_brl=ev,pe=pe,ev_ebitda=ev_ebitda,price_to_book=price_to_book,fcf_yield_pct=fcf_yield_pct,intrinsic_value_produced=False,warnings=list(dict.fromkeys(warnings)))
