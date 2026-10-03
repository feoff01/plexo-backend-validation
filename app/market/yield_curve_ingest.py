"""Ingestão semântica append-only da ETTJ ANBIMA em market.yield_curve.

Este módulo NÃO faz HTTP/OAuth. Recebe vértices já validados por um adapter físico e expande
as três séries oficiais para o schema canônico existente.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import math
import re
from typing import Iterable

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import ingest

SOURCE_ANBIMA = "anbima"
DATASET_ANBIMA_ETTJ = "anbima.yield_curve.ettj@1"
CURVE_PRE = "ettj_pre"
CURVE_IPCA = "ettj_ipca"
CURVE_IMPLIED = "inflacao_implicita"
CANONICAL_CURVES = (CURVE_PRE, CURVE_IPCA, CURVE_IMPLIED)
DAY_COUNT = "du_252"
_HASH_HEX = re.compile(r"^[0-9a-f]{64}$")


class YieldCurveIngestConflict(RuntimeError):
    """Snapshot semanticamente válido conflita com chave append-only já persistida."""


class AnbimaYieldCurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_date: date
    business_days: int = Field(gt=0)
    pre_rate_pct: float | None = Field(default=None, allow_inf_nan=False)
    ipca_rate_pct: float | None = Field(default=None, allow_inf_nan=False)
    implied_inflation_pct: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def _at_least_one_rate(self):
        values = (self.pre_rate_pct, self.ipca_rate_pct, self.implied_inflation_pct)
        if not any(value is not None for value in values):
            raise ValueError("vertice_ettj_sem_taxa")
        for value in values:
            if value is not None and not math.isfinite(float(value)):
                raise ValueError("taxa_ettj_nao_finita")
        return self


class YieldCurveIngestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: str | None = None
    reused_existing_batch: bool = False
    reference_date: date
    vertices_received: int
    rows_expected: int
    rows_inserted: int
    rows_already_equal: int
    curves_written: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _normalize_points(
    points: Iterable[AnbimaYieldCurvePoint],
) -> tuple[date, list[AnbimaYieldCurvePoint]]:
    materialized = list(points)
    if not materialized:
        raise ValueError("snapshot_ettj_vazio")
    reference_dates = {point.reference_date for point in materialized}
    if len(reference_dates) != 1:
        raise ValueError("snapshot_ettj_multiplas_datas")
    reference_date = next(iter(reference_dates))
    if reference_date > date.today():
        raise ValueError("reference_date_ettj_no_futuro")

    by_vertex: dict[int, AnbimaYieldCurvePoint] = {}
    for point in materialized:
        if point.business_days in by_vertex:
            raise ValueError(f"vertice_ettj_duplicado:{point.business_days}")
        by_vertex[point.business_days] = point
    return reference_date, [by_vertex[key] for key in sorted(by_vertex)]


def _rate_db(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _expanded_rows(
    points: list[AnbimaYieldCurvePoint],
) -> list[tuple[str, date, int, Decimal]]:
    out: list[tuple[str, date, int, Decimal]] = []
    mapping = (
        (CURVE_PRE, "pre_rate_pct"),
        (CURVE_IPCA, "ipca_rate_pct"),
        (CURVE_IMPLIED, "implied_inflation_pct"),
    )
    for point in points:
        for curve_name, attr in mapping:
            value = getattr(point, attr)
            if value is not None:
                out.append((curve_name, point.reference_date, point.business_days, _rate_db(float(value))))
    return out


async def _existing_rows(
    conn: AsyncConnection,
    *,
    reference_date: date,
    curves: list[str],
    vertices: list[int],
) -> dict[tuple[str, int], Decimal]:
    if not curves or not vertices:
        return {}
    cur = await conn.execute(
        """select curve_name::text, business_days, rate_pct::float
             from market.yield_curve
            where source_code = %s
              and reference_date = %s
              and curve_name = any(%s::text[])
              and business_days = any(%s::int[])
            order by curve_name, business_days""",
        (SOURCE_ANBIMA, reference_date, curves, vertices),
    )
    return {
        (curve_name, int(business_days)): Decimal(rate).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        for curve_name, business_days, rate in await cur.fetchall()
    }


async def ingest_anbima_yield_curve(
    conn: AsyncConnection,
    points: Iterable[AnbimaYieldCurvePoint],
    *,
    file_hash: str,
    dataset: str = DATASET_ANBIMA_ETTJ,
    storage_key: str | None = None,
) -> YieldCurveIngestReport:
    """Persiste os vértices oficiais ANBIMA sem sobrescrever uma chave histórica."""
    if dataset != DATASET_ANBIMA_ETTJ:
        raise ValueError(f"dataset_ettj_invalido:{dataset}")
    if not _HASH_HEX.fullmatch(file_hash):
        raise ValueError("file_hash_ettj_invalido")

    reference_date, points_n = _normalize_points(points)
    expanded = _expanded_rows(points_n)
    if not expanded:
        raise ValueError("snapshot_ettj_sem_linhas_canonicas")

    batch_id = await ingest.abrir_lote(
        conn,
        source_code=SOURCE_ANBIMA,
        dataset=dataset,
        file_hash=file_hash,
        reference_date=reference_date,
    )
    if batch_id is None:
        existing_batch = await ingest.lote_existente(
            conn,
            source_code=SOURCE_ANBIMA,
            dataset=dataset,
            file_hash=file_hash,
        )
        return YieldCurveIngestReport(
            batch_id=existing_batch,
            reused_existing_batch=True,
            reference_date=reference_date,
            vertices_received=len(points_n),
            rows_expected=len(expanded),
            rows_inserted=0,
            rows_already_equal=len(expanded),
            curves_written=sorted({row[0] for row in expanded}),
            warnings=["arquivo_ettj_ja_ingerido"],
        )

    if storage_key:
        await conn.execute(
            "update market.ingestion_batches set storage_key = %s where id = %s and status = 'running'",
            (storage_key, batch_id),
        )

    curves = sorted({row[0] for row in expanded})
    vertices = sorted({row[2] for row in expanded})
    existing = await _existing_rows(
        conn,
        reference_date=reference_date,
        curves=curves,
        vertices=vertices,
    )

    pending: list[tuple[str, date, int, Decimal]] = []
    already_equal = 0
    conflicts: list[str] = []
    for curve_name, ref, business_days, rate in expanded:
        current = existing.get((curve_name, business_days))
        if current is None:
            pending.append((curve_name, ref, business_days, rate))
        elif current == rate:
            already_equal += 1
        else:
            conflicts.append(f"{curve_name}:{business_days}")

    if conflicts:
        await ingest.fechar_lote(
            conn,
            batch_id,
            status="failed",
            rows=0,
            error="ettj_conflito_append_only",
            reference_date=reference_date,
            details={"conflicts": sorted(conflicts)},
        )
        raise YieldCurveIngestConflict(
            "ettj_conflito_append_only:" + ",".join(sorted(conflicts))
        )

    inserted = 0
    if pending:
        curve_names, ref_dates, business_days, rates = zip(*pending)
        cur = await conn.execute(
            """insert into market.yield_curve
                   (curve_name, reference_date, business_days, calendar_days, rate_pct,
                    day_count, source_code, ingestion_batch_id)
               select c, r, du, null, taxa, %s::market.day_count, %s, %s
                 from unnest(%s::text[], %s::date[], %s::int[], %s::numeric[])
                      as t(c, r, du, taxa)
               on conflict (curve_name, reference_date, business_days, source_code) do nothing""",
            (
                DAY_COUNT,
                SOURCE_ANBIMA,
                batch_id,
                list(curve_names),
                list(ref_dates),
                list(business_days),
                list(rates),
            ),
        )
        inserted = cur.rowcount
        if inserted != len(pending):
            after = await _existing_rows(
                conn,
                reference_date=reference_date,
                curves=curves,
                vertices=vertices,
            )
            race_conflicts = [
                f"{curve_name}:{du}"
                for curve_name, _ref, du, rate in pending
                if after.get((curve_name, du)) != rate
            ]
            if race_conflicts:
                await ingest.fechar_lote(
                    conn,
                    batch_id,
                    status="partial",
                    rows=inserted,
                    error="ettj_corrida_concorrente",
                    reference_date=reference_date,
                    details={"conflicts": sorted(race_conflicts)},
                )
                raise YieldCurveIngestConflict("ettj_corrida_concorrente")
            already_equal += len(pending) - inserted

    await ingest.fechar_lote(
        conn,
        batch_id,
        status="succeeded",
        rows=inserted,
        reference_date=reference_date,
        details={
            "vertices_received": len(points_n),
            "rows_expected": len(expanded),
            "rows_already_equal": already_equal,
            "curves": curves,
        },
    )
    return YieldCurveIngestReport(
        batch_id=batch_id,
        reused_existing_batch=False,
        reference_date=reference_date,
        vertices_received=len(points_n),
        rows_expected=len(expanded),
        rows_inserted=inserted,
        rows_already_equal=already_equal,
        curves_written=curves,
    )
