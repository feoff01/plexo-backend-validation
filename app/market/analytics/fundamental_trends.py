"""Engine puro de tendências fundamentais anuais (FQ5.5).

Não carrega dados e não produz fair value. Trabalha apenas com DFPs já resolvidos point-in-time.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.market import fundamentals


UNIT_INCOMPATIBLE = "fundamental_unit_incompativel"
INSUFFICIENT_HISTORY = "historico_fundamental_insuficiente"
NON_POSITIVE_GROWTH_BASE = "crescimento_percentual_base_nao_positiva"
NON_POSITIVE_REVENUE = "margem_receita_nao_positiva"
CLASS_SPECIFIC_UNSUPPORTED = "fundamental_metrica_classe_nao_suportada"

CANONICAL_METRICS = (
    "revenue",
    "ebitda",
    "net_income",
    "total_equity",
    "cash_and_equivalents",
    "gross_debt",
    "net_debt",
    "free_cash_flow",
)


class FundamentalTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_date: date
    availability_date: date
    value: float
    value_unit: fundamentals.FundamentalUnit
    currency: str | None = None
    absolute_change: float | None = None
    growth_pct: float | None = None
    source_metric: str
    is_derived: bool = False
    source_code: str


class FundamentalMetricTrend(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str
    points: list[FundamentalTrendPoint] = Field(default_factory=list)
    latest_value: float | None = None
    previous_value: float | None = None
    absolute_change: float | None = None
    growth_pct: float | None = None


class FundamentalMarginPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_date: date
    availability_date: date
    value_pct: float
    numerator_metric: str
    numerator_is_derived: bool = False


class FundamentalMarginTrend(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    margin: str
    points: list[FundamentalMarginPoint] = Field(default_factory=list)
    latest_pct: float | None = None
    previous_pct: float | None = None
    change_pp: float | None = None


class FundamentalTrendAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metrics: list[FundamentalMetricTrend] = Field(default_factory=list)
    margins: list[FundamentalMarginTrend] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _canonical_company_rows(
    records: list[fundamentals.FundamentalRecord],
    requested_metrics: tuple[str, ...],
    warnings: list[str],
) -> dict[str, list[fundamentals.FundamentalRecord]]:
    # v1 é deliberadamente company-level. Não escolhe arbitrariamente uma classe quando há
    # coordenada instrument-specific.
    requested_raw = set(requested_metrics)
    if any(row.instrument_id is not None and row.metric in requested_raw for row in records):
        warnings.append(CLASS_SPECIFIC_UNSUPPORTED)

    company_rows = [row for row in records if row.instrument_id is None]
    by_metric: dict[str, list[fundamentals.FundamentalRecord]] = {}
    for metric in set(requested_metrics) | {"ebitda_derived"}:
        rows = [row for row in company_rows if row.metric == metric]
        rows.sort(key=lambda row: (row.reference_date, row.availability_date))
        by_metric[metric] = rows
    return by_metric


def _valid_brl_rows(
    rows: list[fundamentals.FundamentalRecord], warnings: list[str]
) -> list[fundamentals.FundamentalRecord]:
    out = []
    for row in rows:
        if row.value_unit != fundamentals.FundamentalUnit.BRL or row.currency != "BRL":
            warnings.append(UNIT_INCOMPATIBLE)
            continue
        out.append(row)
    return out


def _ebitda_rows(
    by_metric: dict[str, list[fundamentals.FundamentalRecord]],
    warnings: list[str],
) -> list[fundamentals.FundamentalRecord]:
    reported = {row.reference_date: row for row in _valid_brl_rows(by_metric.get("ebitda", []), warnings)}
    derived = {
        row.reference_date: row
        for row in _valid_brl_rows(by_metric.get("ebitda_derived", []), warnings)
    }
    rows = [reported.get(day) or derived[day] for day in sorted(set(reported) | set(derived))]
    return rows


def _metric_points(
    metric: str,
    rows: list[fundamentals.FundamentalRecord],
    warnings: list[str],
) -> FundamentalMetricTrend:
    points: list[FundamentalTrendPoint] = []
    previous: fundamentals.FundamentalRecord | None = None
    for row in rows:
        absolute_change = None if previous is None else row.value - previous.value
        growth_pct = None
        if previous is not None:
            if previous.value > 0:
                growth_pct = 100.0 * (row.value / previous.value - 1.0)
            else:
                warnings.append(NON_POSITIVE_GROWTH_BASE)
        points.append(
            FundamentalTrendPoint(
                reference_date=row.reference_date,
                availability_date=row.availability_date,
                value=row.value,
                value_unit=row.value_unit,
                currency=row.currency,
                absolute_change=absolute_change,
                growth_pct=growth_pct,
                source_metric=row.metric,
                is_derived=row.is_derived,
                source_code=row.source_code,
            )
        )
        previous = row
    latest = points[-1] if points else None
    prior = points[-2] if len(points) >= 2 else None
    return FundamentalMetricTrend(
        metric=metric,
        points=points,
        latest_value=latest.value if latest else None,
        previous_value=prior.value if prior else None,
        absolute_change=latest.absolute_change if latest else None,
        growth_pct=latest.growth_pct if latest else None,
    )


def _margin(
    name: str,
    numerator_rows: list[fundamentals.FundamentalRecord],
    revenue_rows: list[fundamentals.FundamentalRecord],
    warnings: list[str],
) -> FundamentalMarginTrend:
    numerators = {row.reference_date: row for row in numerator_rows}
    revenues = {row.reference_date: row for row in revenue_rows}
    points: list[FundamentalMarginPoint] = []
    for reference_date in sorted(set(numerators) & set(revenues)):
        numerator = numerators[reference_date]
        revenue = revenues[reference_date]
        if revenue.value <= 0:
            warnings.append(NON_POSITIVE_REVENUE)
            continue
        points.append(
            FundamentalMarginPoint(
                reference_date=reference_date,
                availability_date=max(numerator.availability_date, revenue.availability_date),
                value_pct=100.0 * numerator.value / revenue.value,
                numerator_metric=numerator.metric,
                numerator_is_derived=numerator.is_derived,
            )
        )
    latest = points[-1] if points else None
    prior = points[-2] if len(points) >= 2 else None
    return FundamentalMarginTrend(
        margin=name,
        points=points,
        latest_pct=latest.value_pct if latest else None,
        previous_pct=prior.value_pct if prior else None,
        change_pp=(latest.value_pct - prior.value_pct) if latest and prior else None,
    )


def analyze_fundamental_trends(
    records: list[fundamentals.FundamentalRecord],
    *,
    requested_metrics: tuple[str, ...] = CANONICAL_METRICS,
) -> FundamentalTrendAnalysis:
    unsupported = [metric for metric in requested_metrics if metric not in CANONICAL_METRICS]
    if unsupported:
        raise ValueError(f"métricas não suportadas em FQ5.5: {', '.join(sorted(set(unsupported)))}")

    warnings: list[str] = []
    by_metric = _canonical_company_rows(records, requested_metrics, warnings)
    metric_rows: dict[str, list[fundamentals.FundamentalRecord]] = {}
    for metric in requested_metrics:
        if metric == "ebitda":
            metric_rows[metric] = _ebitda_rows(by_metric, warnings)
        else:
            metric_rows[metric] = _valid_brl_rows(by_metric.get(metric, []), warnings)

    metric_trends = [
        _metric_points(metric, metric_rows[metric], warnings)
        for metric in requested_metrics
        if metric_rows[metric]
    ]

    revenue_rows = metric_rows.get("revenue", [])
    margins: list[FundamentalMarginTrend] = []
    if revenue_rows:
        ebitda_rows = metric_rows.get("ebitda", [])
        if ebitda_rows:
            margins.append(_margin("ebitda_margin", ebitda_rows, revenue_rows, warnings))
        net_income_rows = metric_rows.get("net_income", [])
        if net_income_rows:
            margins.append(_margin("net_margin", net_income_rows, revenue_rows, warnings))
    margins = [margin for margin in margins if margin.points]

    if not any(len(metric.points) >= 2 for metric in metric_trends):
        warnings.append(INSUFFICIENT_HISTORY)

    return FundamentalTrendAnalysis(
        metrics=metric_trends,
        margins=margins,
        warnings=_unique(warnings),
    )
