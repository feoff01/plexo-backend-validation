"""Leitura point-in-time de composição oficial de índices.

Reutiliza market.index_weights e market.ingestion_batches. Não ingere, não projeta
is_in_universe e não infere snapshots ausentes.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import math

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field


class IndexCompositionConflict(RuntimeError):
    """Snapshot persistido viola invariantes de composição."""


class IndexCompositionMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    ticker: str
    name: str
    weight_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    theoretical_qty: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class IndexCompositionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str = "market.index_weights"
    source_codes: list[str] = Field(default_factory=list)
    ingestion_batch_ids: list[str] = Field(default_factory=list)
    reference_date: date | None = None
    availability_date: date | None = None
    cutoff_date: date
    strict_pit: bool = True
    temporal_semantics: str = "ingestion_finished_at_cutoff"
    warnings: list[str] = Field(default_factory=list)


class ResolvedIndexComposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index_code: str
    display_name: str | None = None
    reference_date: date | None = None
    members: list[IndexCompositionMember] = Field(default_factory=list)
    total_weight_pct: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    provenance: IndexCompositionProvenance


def _normalize_index_code(index_code: str) -> str:
    value = index_code.strip().lower()
    if not value:
        raise ValueError("indice_vazio")
    return value


async def _definition(
    conn: AsyncConnection,
    index_code: str,
) -> tuple[str | None, str | None]:
    cur = await conn.execute(
        "select display_name, source_code::text from market.index_definitions where code = %s",
        (index_code,),
    )
    row = await cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


async def _resolve_reference_date(
    conn: AsyncConnection,
    *,
    index_code: str,
    cutoff: date,
    reference_date: date | None,
    strict_pit: bool,
) -> date | None:
    if reference_date is not None:
        return reference_date if reference_date <= cutoff else None

    if strict_pit:
        cur = await conn.execute(
            """select max(w.reference_date)
                 from market.index_weights w
                 join market.ingestion_batches b on b.id = w.ingestion_batch_id
                where w.index_code = %s
                  and w.reference_date <= %s
                  and b.status = 'succeeded'
                  and b.finished_at is not null
                  and b.finished_at::date <= %s""",
            (index_code, cutoff, cutoff),
        )
    else:
        cur = await conn.execute(
            """select max(reference_date)
                 from market.index_weights
                where index_code = %s and reference_date <= %s""",
            (index_code, cutoff),
        )
    row = await cur.fetchone()
    return row[0] if row else None


async def load_index_composition(
    conn: AsyncConnection,
    index_code: str,
    *,
    cutoff: date,
    reference_date: date | None = None,
    strict_pit: bool = True,
) -> ResolvedIndexComposition:
    """Resolve um snapshot exato de composição sem nearest/fallback histórico."""
    code = _normalize_index_code(index_code)
    display_name, definition_source = await _definition(conn, code)
    if display_name is None:
        return ResolvedIndexComposition(
            index_code=code,
            provenance=IndexCompositionProvenance(
                cutoff_date=cutoff,
                strict_pit=strict_pit,
                warnings=["indice_desconhecido"],
            ),
        )

    selected_date = await _resolve_reference_date(
        conn,
        index_code=code,
        cutoff=cutoff,
        reference_date=reference_date,
        strict_pit=strict_pit,
    )
    if selected_date is None:
        return ResolvedIndexComposition(
            index_code=code,
            display_name=display_name,
            provenance=IndexCompositionProvenance(
                cutoff_date=cutoff,
                strict_pit=strict_pit,
                warnings=["composicao_indice_indisponivel"],
            ),
        )

    pit = """
      and w.ingestion_batch_id is not null
      and b.status = 'succeeded'
      and b.finished_at is not null
      and b.finished_at::date <= %s
    """ if strict_pit else ""
    args: list[object] = [code, selected_date]
    if strict_pit:
        args.append(cutoff)

    cur = await conn.execute(
        f"""select i.id::text,
                   i.ticker,
                   i.name,
                   w.weight_pct,
                   w.theoretical_qty,
                   b.id::text,
                   b.source_code::text,
                   b.finished_at::date
              from market.index_weights w
              join market.instruments i on i.id = w.instrument_id
              left join market.ingestion_batches b on b.id = w.ingestion_batch_id
             where w.index_code = %s
               and w.reference_date = %s
               {pit}
             order by w.weight_pct desc, i.ticker nulls last, i.id""",
        tuple(args),
    )
    rows = await cur.fetchall()
    if not rows:
        return ResolvedIndexComposition(
            index_code=code,
            display_name=display_name,
            reference_date=selected_date,
            provenance=IndexCompositionProvenance(
                reference_date=selected_date,
                cutoff_date=cutoff,
                strict_pit=strict_pit,
                warnings=["composicao_indice_indisponivel"],
            ),
        )

    members: list[IndexCompositionMember] = []
    tickers: set[str] = set()
    sources: set[str] = set()
    batches: set[str] = set()
    availability_dates: list[date] = []
    total = Decimal("0")
    for instrument_id, ticker, name, weight, qty, batch_id, source_code, availability in rows:
        normalized_ticker = (ticker or "").strip().upper()
        if not normalized_ticker:
            raise IndexCompositionConflict(
                f"membro_indice_sem_ticker:{code}:{selected_date}:{instrument_id}"
            )
        if normalized_ticker in tickers:
            raise IndexCompositionConflict(
                f"ticker_indice_duplicado_persistido:{code}:{selected_date}:{normalized_ticker}"
            )
        tickers.add(normalized_ticker)

        weight_decimal = Decimal(weight)
        weight_float = float(weight_decimal)
        if not math.isfinite(weight_float) or not 0 <= weight_float <= 100:
            raise IndexCompositionConflict(
                f"peso_indice_invalido:{code}:{selected_date}:{normalized_ticker}"
            )
        total += weight_decimal

        qty_float = float(qty) if qty is not None else None
        if qty_float is not None and (not math.isfinite(qty_float) or qty_float < 0):
            raise IndexCompositionConflict(
                f"quantidade_teorica_invalida:{code}:{selected_date}:{normalized_ticker}"
            )
        if strict_pit and batch_id is None:
            raise IndexCompositionConflict(
                f"membro_indice_sem_lote:{code}:{selected_date}:{normalized_ticker}"
            )
        if source_code:
            sources.add(source_code)
        if batch_id:
            batches.add(batch_id)
        if availability:
            availability_dates.append(availability)

        members.append(
            IndexCompositionMember(
                instrument_id=instrument_id,
                ticker=normalized_ticker,
                name=name,
                weight_pct=weight_float,
                theoretical_qty=qty_float,
            )
        )

    if not (Decimal("99.90") <= total <= Decimal("100.10")):
        raise IndexCompositionConflict(
            f"peso_total_indice_invalido:{code}:{selected_date}:{total}"
        )
    if definition_source and sources and sources != {definition_source}:
        raise IndexCompositionConflict(
            f"fonte_indice_divergente:{code}:{sorted(sources)}:{definition_source}"
        )

    warnings: list[str] = []
    if not strict_pit:
        warnings.append("composicao_indice_sem_vintage_pit")
    return ResolvedIndexComposition(
        index_code=code,
        display_name=display_name,
        reference_date=selected_date,
        members=members,
        total_weight_pct=float(total),
        provenance=IndexCompositionProvenance(
            source_codes=sorted(sources or ({definition_source} if definition_source else set())),
            ingestion_batch_ids=sorted(batches),
            reference_date=selected_date,
            availability_date=max(availability_dates, default=None),
            cutoff_date=cutoff,
            strict_pit=strict_pit,
            warnings=warnings,
        ),
    )
