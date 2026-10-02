"""Ingestão append-only de carteiras de índice e projeção do universo atual.

``market.index_weights`` mantém os snapshots históricos. ``is_in_universe`` é apenas a projeção
operacional atual, atualizada explicitamente a partir de uma carteira IBrA succeeded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from typing import Iterable

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from app.db.repos import audit
from app.market import ingest
from app.market.b3_index_source import B3IndexPortfolioRecord

SOURCE_B3 = "b3"
IBRA_INDEX_CODE = "ibra"
IBRA_DATASET = "b3.index_portfolio.ibra@1"
_HASH_HEX = re.compile(r"^[0-9a-f]{64}$")


class IndexPortfolioConflict(RuntimeError):
    """O snapshot não pode ser persistido/projetado de forma ambígua ou parcial."""


class IndexPortfolioIngestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: str | None = None
    reused_existing_batch: bool = False
    index_code: str
    reference_date: date
    records_received: int
    matched_instruments: int
    rows_inserted: int
    rows_already_equal: int
    warnings: list[str] = Field(default_factory=list)


class UniverseProjectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index_code: str
    reference_date: date
    source_batch_ids: list[str] = Field(default_factory=list)
    members: int
    equities_total: int
    set_true: int
    set_false: int
    already_true: int
    already_false: int


def _normalize_records(records: Iterable[B3IndexPortfolioRecord]) -> list[B3IndexPortfolioRecord]:
    materialized = list(records)
    if not materialized:
        raise ValueError("snapshot_indice_vazio")
    by_ticker: dict[str, B3IndexPortfolioRecord] = {}
    for record in materialized:
        ticker = record.ticker.strip().upper()
        if ticker in by_ticker:
            raise IndexPortfolioConflict(f"ticker_indice_duplicado:{ticker}")
        by_ticker[ticker] = B3IndexPortfolioRecord(
            ticker=ticker,
            name=record.name.strip(),
            security_type=" ".join(record.security_type.split()),
            theoretical_qty=Decimal(record.theoretical_qty),
            weight_pct=Decimal(record.weight_pct),
        )
    return [by_ticker[ticker] for ticker in sorted(by_ticker)]


async def _resolve_exact_equities(
    conn: AsyncConnection,
    tickers: list[str],
) -> dict[str, str]:
    cur = await conn.execute(
        """select upper(ticker), id::text
             from market.instruments
            where kind = 'acao' and ticker is not null and upper(ticker) = any(%s::text[])
            order by upper(ticker), id""",
        (tickers,),
    )
    out: dict[str, str] = {}
    for ticker, iid in await cur.fetchall():
        if ticker in out and out[ticker] != iid:
            raise IndexPortfolioConflict(f"ticker_ambiguo_no_catalogo:{ticker}")
        out[ticker] = iid
    return out


async def _existing_snapshot(
    conn: AsyncConnection,
    *,
    index_code: str,
    reference_date: date,
    instrument_ids: list[str],
) -> dict[str, tuple[Decimal, Decimal | None]]:
    if not instrument_ids:
        return {}
    cur = await conn.execute(
        """select instrument_id::text, weight_pct, theoretical_qty
             from market.index_weights
            where index_code = %s and reference_date = %s
              and instrument_id = any(%s::uuid[])""",
        (index_code, reference_date, instrument_ids),
    )
    return {
        iid: (Decimal(weight), Decimal(qty) if qty is not None else None)
        for iid, weight, qty in await cur.fetchall()
    }


async def ingest_b3_index_portfolio(
    conn: AsyncConnection,
    records: Iterable[B3IndexPortfolioRecord],
    *,
    index_code: str,
    reference_date: date,
    file_hash: str,
    dataset: str,
    storage_key: str | None = None,
) -> IndexPortfolioIngestReport:
    """Persiste carteira B3 somente se todos os tickers resolverem exatamente antes da escrita."""
    records_n = _normalize_records(records)
    index_code = index_code.strip().lower()
    if reference_date > date.today():
        raise ValueError("reference_date_indice_no_futuro")
    if index_code == IBRA_INDEX_CODE and dataset != IBRA_DATASET:
        raise ValueError(f"dataset_ibra_invalido:{dataset}")
    if not _HASH_HEX.fullmatch(file_hash):
        raise ValueError("file_hash_indice_invalido")

    cur = await conn.execute(
        "select source_code from market.index_definitions where code = %s",
        (index_code,),
    )
    index_row = await cur.fetchone()
    if index_row is None:
        raise ValueError(f"indice_desconhecido:{index_code}")
    if index_row[0] != SOURCE_B3:
        raise ValueError(f"indice_nao_b3:{index_code}")

    batch_id = await ingest.abrir_lote(
        conn,
        source_code=SOURCE_B3,
        dataset=dataset,
        file_hash=file_hash,
        reference_date=reference_date,
    )
    if batch_id is None:
        existing_batch = await ingest.lote_existente(
            conn, source_code=SOURCE_B3, dataset=dataset, file_hash=file_hash
        )
        return IndexPortfolioIngestReport(
            batch_id=existing_batch,
            reused_existing_batch=True,
            index_code=index_code,
            reference_date=reference_date,
            records_received=len(records_n),
            matched_instruments=len(records_n),
            rows_inserted=0,
            rows_already_equal=len(records_n),
            warnings=["arquivo_indice_ja_ingerido"],
        )

    if storage_key:
        await conn.execute(
            "update market.ingestion_batches set storage_key = %s where id = %s and status = 'running'",
            (storage_key, batch_id),
        )

    tickers = [record.ticker for record in records_n]
    resolved = await _resolve_exact_equities(conn, tickers)
    missing = sorted(set(tickers) - set(resolved))
    if missing:
        await ingest.fechar_lote(
            conn,
            batch_id,
            status="failed",
            rows=0,
            error="carteira_indice_ticker_sem_instrumento",
            reference_date=reference_date,
            details={"index_code": index_code, "unmatched_tickers": missing},
        )
        raise IndexPortfolioConflict(
            "carteira_indice_ticker_sem_instrumento:" + ",".join(missing)
        )

    desired = [(resolved[record.ticker], record) for record in records_n]
    existing = await _existing_snapshot(
        conn,
        index_code=index_code,
        reference_date=reference_date,
        instrument_ids=[iid for iid, _record in desired],
    )
    pending: list[tuple[str, B3IndexPortfolioRecord]] = []
    already_equal = 0
    conflicts: list[str] = []
    for iid, record in desired:
        current = existing.get(iid)
        desired_value = (Decimal(record.weight_pct), Decimal(record.theoretical_qty))
        if current is None:
            pending.append((iid, record))
        elif current == desired_value:
            already_equal += 1
        else:
            conflicts.append(iid)
    if conflicts:
        await ingest.fechar_lote(
            conn,
            batch_id,
            status="failed",
            rows=0,
            error="carteira_indice_conflitante_mesma_chave",
            reference_date=reference_date,
            details={"index_code": index_code, "instrument_ids": sorted(conflicts)},
        )
        raise IndexPortfolioConflict("carteira_indice_conflitante_mesma_chave")

    inserted = 0
    if pending:
        iids, weights, quantities = zip(
            *[(iid, record.weight_pct, record.theoretical_qty) for iid, record in pending]
        )
        cur = await conn.execute(
            """insert into market.index_weights
                   (index_code, reference_date, instrument_id, weight_pct, theoretical_qty, ingestion_batch_id)
               select %s, %s, i, w, q, %s
                 from unnest(%s::uuid[], %s::numeric[], %s::numeric[]) as t(i, w, q)
               on conflict (index_code, reference_date, instrument_id) do nothing""",
            (
                index_code,
                reference_date,
                batch_id,
                list(iids),
                [Decimal(v) for v in weights],
                [Decimal(v) for v in quantities],
            ),
        )
        inserted = cur.rowcount
        if inserted != len(pending):
            after = await _existing_snapshot(
                conn,
                index_code=index_code,
                reference_date=reference_date,
                instrument_ids=[iid for iid, _record in pending],
            )
            race_conflicts = [
                iid
                for iid, record in pending
                if after.get(iid) != (Decimal(record.weight_pct), Decimal(record.theoretical_qty))
            ]
            if race_conflicts:
                await ingest.fechar_lote(
                    conn,
                    batch_id,
                    status="partial",
                    rows=inserted,
                    error="corrida_concorrente_carteira_indice",
                    reference_date=reference_date,
                    details={"index_code": index_code, "instrument_ids": sorted(race_conflicts)},
                )
                raise IndexPortfolioConflict("corrida_concorrente_carteira_indice")
            already_equal += len(pending) - inserted

    await ingest.fechar_lote(
        conn,
        batch_id,
        status="succeeded",
        rows=inserted,
        reference_date=reference_date,
        details={
            "index_code": index_code,
            "records_received": len(records_n),
            "matched_instruments": len(resolved),
            "rows_already_equal": already_equal,
        },
    )
    return IndexPortfolioIngestReport(
        batch_id=batch_id,
        reused_existing_batch=False,
        index_code=index_code,
        reference_date=reference_date,
        records_received=len(records_n),
        matched_instruments=len(resolved),
        rows_inserted=inserted,
        rows_already_equal=already_equal,
    )


async def project_current_equity_universe(
    conn: AsyncConnection,
    *,
    index_code: str = IBRA_INDEX_CODE,
    reference_date: date | None = None,
) -> UniverseProjectionReport:
    """Projeta ``is_in_universe`` para ações usando uma carteira IBrA succeeded já persistida."""
    index_code = index_code.strip().lower()
    if index_code != IBRA_INDEX_CODE:
        raise ValueError("universe_v1_aceita_somente_ibra")

    if reference_date is None:
        cur = await conn.execute(
            """select max(w.reference_date)
                 from market.index_weights w
                 join market.ingestion_batches b on b.id = w.ingestion_batch_id
                where w.index_code = %s and b.status = 'succeeded' and b.finished_at is not null""",
            (index_code,),
        )
        reference_date = (await cur.fetchone())[0]
    if reference_date is None:
        raise IndexPortfolioConflict("carteira_ibra_succeeded_ausente")

    cur = await conn.execute(
        """select w.instrument_id::text, w.weight_pct, b.id::text
             from market.index_weights w
             join market.ingestion_batches b on b.id = w.ingestion_batch_id
            where w.index_code = %s and w.reference_date = %s
              and b.status = 'succeeded' and b.finished_at is not null
            order by w.instrument_id""",
        (index_code, reference_date),
    )
    rows = await cur.fetchall()
    if not rows:
        raise IndexPortfolioConflict("carteira_ibra_succeeded_vazia")
    member_ids = [iid for iid, _weight, _batch_id in rows]
    weight_sum = sum((Decimal(weight) for _iid, weight, _batch_id in rows), Decimal("0"))
    if not (Decimal("99.90") <= weight_sum <= Decimal("100.10")):
        raise IndexPortfolioConflict(f"carteira_ibra_peso_total_invalido:{weight_sum}")

    cur = await conn.execute(
        """select count(*),
                  count(*) filter (where is_in_universe),
                  count(*) filter (where is_in_universe and id = any(%s::uuid[])),
                  count(*) filter (where not is_in_universe and not (id = any(%s::uuid[])))
             from market.instruments
            where kind = 'acao'""",
        (member_ids, member_ids),
    )
    equities_total, before_true, already_true, already_false = await cur.fetchone()

    cur = await conn.execute(
        """update market.instruments
              set is_in_universe = (id = any(%s::uuid[]))
            where kind = 'acao'
              and is_in_universe is distinct from (id = any(%s::uuid[]))""",
        (member_ids, member_ids),
    )
    changed = cur.rowcount

    set_true = len(member_ids) - int(already_true)
    set_false = int(before_true) - int(already_true)
    if changed != set_true + set_false:
        raise IndexPortfolioConflict("universe_projection_contagem_inconsistente")

    batch_ids = sorted({batch_id for _iid, _weight, batch_id in rows})
    await audit.registrar(
        conn,
        actor_kind="job",
        action="market.universe.projected",
        object_kind="index_portfolio",
        object_id=f"{index_code}:{reference_date.isoformat()}",
        details={
            "index_code": index_code,
            "reference_date": reference_date.isoformat(),
            "members": len(member_ids),
            "equities_total": int(equities_total),
            "set_true": set_true,
            "set_false": set_false,
            "source_batch_ids": batch_ids,
        },
    )
    return UniverseProjectionReport(
        index_code=index_code,
        reference_date=reference_date,
        source_batch_ids=batch_ids,
        members=len(member_ids),
        equities_total=int(equities_total),
        set_true=set_true,
        set_false=set_false,
        already_true=int(already_true),
        already_false=int(already_false),
    )
