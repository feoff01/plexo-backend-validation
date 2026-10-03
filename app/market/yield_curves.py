"""Loader point-in-time para market.yield_curve.

Não interpola, não extrapola e não transforma day-count. O loader devolve exatamente os
vértices persistidos da curva solicitada, com provenance de source/batch/disponibilidade.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Literal

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from app.market.yield_curve_ingest import (
    CANONICAL_CURVES,
    DAY_COUNT,
    SOURCE_ANBIMA,
)

YieldCurveName = Literal["ettj_pre", "ettj_ipca", "inflacao_implicita"]


class YieldCurveLoadConflict(RuntimeError):
    """Curva persistida viola invariantes canônicos do loader."""


class YieldCurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    business_days: int = Field(gt=0)
    calendar_days: int | None = Field(default=None, gt=0)
    rate_pct: float = Field(allow_inf_nan=False)
    day_count: str
    source_code: str
    ingestion_batch_id: str | None = None
    availability_date: date | None = None


class YieldCurveProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str = "market.yield_curve"
    source_codes: list[str] = Field(default_factory=list)
    ingestion_batch_ids: list[str] = Field(default_factory=list)
    reference_date: date | None = None
    availability_date: date | None = None
    cutoff_date: date
    strict_pit: bool = True
    temporal_semantics: str = "ingestion_finished_at_cutoff"
    warnings: list[str] = Field(default_factory=list)


class ResolvedYieldCurve(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    curve_name: YieldCurveName
    reference_date: date | None = None
    points: list[YieldCurvePoint] = Field(default_factory=list)
    provenance: YieldCurveProvenance


def _validate_curve_name(curve_name: str) -> YieldCurveName:
    normalized = curve_name.strip().lower()
    if normalized not in CANONICAL_CURVES:
        raise ValueError(f"curva_ettj_nao_suportada:{normalized}")
    return normalized  # type: ignore[return-value]


async def _resolve_reference_date(
    conn: AsyncConnection,
    *,
    curve_name: str,
    cutoff: date,
    reference_date: date | None,
    strict_pit: bool,
) -> date | None:
    if reference_date is not None:
        if reference_date > cutoff:
            return None
        return reference_date

    if strict_pit:
        cur = await conn.execute(
            """select max(y.reference_date)
                 from market.yield_curve y
                 join market.ingestion_batches b on b.id = y.ingestion_batch_id
                where y.curve_name = %s
                  and y.source_code = %s
                  and y.reference_date <= %s
                  and b.status = 'succeeded'
                  and b.finished_at is not null
                  and b.finished_at::date <= %s""",
            (curve_name, SOURCE_ANBIMA, cutoff, cutoff),
        )
    else:
        cur = await conn.execute(
            """select max(reference_date)
                 from market.yield_curve
                where curve_name = %s
                  and source_code = %s
                  and reference_date <= %s""",
            (curve_name, SOURCE_ANBIMA, cutoff),
        )
    row = await cur.fetchone()
    return row[0] if row else None


async def load_yield_curve(
    conn: AsyncConnection,
    curve_name: str,
    *,
    cutoff: date,
    reference_date: date | None = None,
    strict_pit: bool = True,
) -> ResolvedYieldCurve:
    """Resolve a curva oficial ANBIMA disponível no cutoff sem inventar vértices."""
    curve = _validate_curve_name(curve_name)
    selected_date = await _resolve_reference_date(
        conn,
        curve_name=curve,
        cutoff=cutoff,
        reference_date=reference_date,
        strict_pit=strict_pit,
    )
    warnings: list[str] = []
    if selected_date is None:
        warnings.append("curva_juros_indisponivel")
        return ResolvedYieldCurve(
            curve_name=curve,
            provenance=YieldCurveProvenance(
                cutoff_date=cutoff,
                strict_pit=strict_pit,
                warnings=warnings,
            ),
        )

    pit = """
      and y.ingestion_batch_id is not null
      and b.status = 'succeeded'
      and b.finished_at is not null
      and b.finished_at::date <= %s
    """ if strict_pit else ""
    args: list[object] = [curve, SOURCE_ANBIMA, selected_date]
    if strict_pit:
        args.append(cutoff)

    cur = await conn.execute(
        f"""select y.business_days,
                   y.calendar_days,
                   y.rate_pct::float,
                   y.day_count::text,
                   y.source_code::text,
                   y.ingestion_batch_id::text,
                   b.finished_at::date
              from market.yield_curve y
              left join market.ingestion_batches b on b.id = y.ingestion_batch_id
             where y.curve_name = %s
               and y.source_code = %s
               and y.reference_date = %s
               {pit}
             order by y.business_days""",
        tuple(args),
    )
    rows = await cur.fetchall()
    if not rows:
        warnings.append("curva_juros_indisponivel")
        return ResolvedYieldCurve(
            curve_name=curve,
            reference_date=selected_date,
            provenance=YieldCurveProvenance(
                reference_date=selected_date,
                cutoff_date=cutoff,
                strict_pit=strict_pit,
                warnings=warnings,
            ),
        )

    seen_vertices: set[int] = set()
    points: list[YieldCurvePoint] = []
    for business_days, calendar_days, rate, day_count, source_code, batch_id, availability in rows:
        business_days = int(business_days)
        if business_days in seen_vertices:
            raise YieldCurveLoadConflict(
                f"vertice_ettj_duplicado_persistido:{curve}:{selected_date}:{business_days}"
            )
        seen_vertices.add(business_days)
        if day_count != DAY_COUNT:
            raise YieldCurveLoadConflict(
                f"day_count_ettj_incompativel:{curve}:{selected_date}:{business_days}:{day_count}"
            )
        if calendar_days is not None:
            raise YieldCurveLoadConflict(
                f"calendar_days_ettj_inesperado:{curve}:{selected_date}:{business_days}"
            )
        if not math.isfinite(float(rate)):
            raise YieldCurveLoadConflict(
                f"taxa_ettj_nao_finita:{curve}:{selected_date}:{business_days}"
            )
        points.append(
            YieldCurvePoint(
                business_days=business_days,
                calendar_days=calendar_days,
                rate_pct=float(rate),
                day_count=day_count,
                source_code=source_code,
                ingestion_batch_id=batch_id,
                availability_date=availability,
            )
        )

    if not strict_pit:
        warnings.append("curva_juros_sem_vintage_pit")

    sources = sorted({point.source_code for point in points if point.source_code})
    batches = sorted({
        point.ingestion_batch_id
        for point in points
        if point.ingestion_batch_id is not None
    })
    availability = max(
        (point.availability_date for point in points if point.availability_date is not None),
        default=None,
    )
    return ResolvedYieldCurve(
        curve_name=curve,
        reference_date=selected_date,
        points=points,
        provenance=YieldCurveProvenance(
            source_codes=sources,
            ingestion_batch_ids=batches,
            reference_date=selected_date,
            availability_date=availability,
            cutoff_date=cutoff,
            strict_pit=strict_pit,
            warnings=warnings,
        ),
    )
