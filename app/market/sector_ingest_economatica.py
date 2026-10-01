"""Ingestão auxiliar de classificação corrente Economatica por ticker exato.

Semântica: ``observed_at`` é quando o snapshot passou a ser conhecido pelo Plexo.
O ano do workbook Economatica nunca é tratado como vintage de cadastro/setor.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import re
from typing import Iterable

from psycopg import AsyncConnection

from app.market import ingest
from app.market.economatica_sector_source import EconomaticaSectorRecord

SOURCE = "economatica"
DATASET = "economatica.sector_classification.current@1"
_HASH_HEX = re.compile(r"^[0-9a-f]{64}$")


class EconomaticaSectorIngestConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class EconomaticaSectorIngestReport:
    batch_id: str | None
    reused_existing_batch: bool
    observed_at: date
    records_received: int
    matched_tickers: int
    unmatched_tickers: tuple[str, ...]
    issuers_matched: int
    classes_targeted: int
    rows_inserted: int
    rows_already_equal: int


async def _match_tickers(conn: AsyncConnection, tickers: list[str]) -> dict[str, tuple[str, str]]:
    if not tickers:
        return {}
    cur = await conn.execute(
        """select upper(ticker), id::text, issuer_id::text
             from market.instruments
            where kind = 'acao' and ticker is not null and upper(ticker) = any(%s::text[])
              and issuer_id is not null
            order by upper(ticker), id""",
        (tickers,),
    )
    out: dict[str, tuple[str, str]] = {}
    for ticker, iid, issuer_id in await cur.fetchall():
        if ticker in out and out[ticker] != (iid, issuer_id):
            raise EconomaticaSectorIngestConflict(f"ticker_ambiguo_no_catalogo:{ticker}")
        out[ticker] = (iid, issuer_id)
    return out


async def _equities_by_issuer(conn: AsyncConnection, issuer_ids: list[str]) -> dict[str, list[str]]:
    if not issuer_ids:
        return {}
    cur = await conn.execute(
        """select issuer_id::text, id::text
             from market.instruments
            where kind = 'acao' and issuer_id = any(%s::uuid[])
            order by issuer_id, ticker nulls last, id""",
        (issuer_ids,),
    )
    out: dict[str, list[str]] = defaultdict(list)
    for issuer_id, iid in await cur.fetchall():
        out[issuer_id].append(iid)
    return dict(out)


async def ingest_economatica_sector_records(
    conn: AsyncConnection,
    records: Iterable[EconomaticaSectorRecord],
    *,
    observed_at: date,
    file_hash: str,
    storage_key: str | None = None,
) -> EconomaticaSectorIngestReport:
    materialized = list(records)
    if not materialized:
        raise ValueError("snapshot_economatica_vazio")
    if observed_at > date.today():
        raise ValueError("observed_at_economatica_no_futuro")
    if not _HASH_HEX.fullmatch(file_hash):
        raise ValueError("file_hash_economatica_invalido")

    by_ticker: dict[str, EconomaticaSectorRecord] = {}
    for record in materialized:
        ticker = record.ticker.strip().upper()
        if not ticker or ticker.endswith("-OLD"):
            continue
        previous = by_ticker.get(ticker)
        if previous is not None and previous.key != record.key:
            raise EconomaticaSectorIngestConflict(f"ticker_setorial_divergente:{ticker}")
        by_ticker[ticker] = record
    if not by_ticker:
        raise ValueError("snapshot_economatica_sem_ticker_elegivel")

    batch_id = await ingest.abrir_lote(
        conn, source_code=SOURCE, dataset=DATASET, file_hash=file_hash, reference_date=observed_at
    )
    if batch_id is None:
        existing = await ingest.lote_existente(conn, source_code=SOURCE, dataset=DATASET, file_hash=file_hash)
        return EconomaticaSectorIngestReport(
            batch_id=existing, reused_existing_batch=True, observed_at=observed_at,
            records_received=len(materialized), matched_tickers=0, unmatched_tickers=(),
            issuers_matched=0, classes_targeted=0, rows_inserted=0, rows_already_equal=0,
        )
    if storage_key:
        await conn.execute(
            "update market.ingestion_batches set storage_key = %s where id = %s and status = 'running'",
            (storage_key, batch_id),
        )

    matched = await _match_tickers(conn, sorted(by_ticker))
    unmatched = tuple(sorted(set(by_ticker) - set(matched)))

    by_issuer: dict[str, EconomaticaSectorRecord] = {}
    for ticker, (_iid, issuer_id) in matched.items():
        record = by_ticker[ticker]
        previous = by_issuer.get(issuer_id)
        if previous is not None and previous.key != record.key:
            await ingest.fechar_lote(
                conn, batch_id, status="failed", rows=0,
                error="economatica_classificacao_divergente_mesmo_issuer", reference_date=observed_at,
                details={"issuer_id": issuer_id, "ticker": ticker},
            )
            raise EconomaticaSectorIngestConflict(f"issuer_setorial_divergente:{issuer_id}")
        by_issuer[issuer_id] = record

    equities = await _equities_by_issuer(conn, sorted(by_issuer))
    desired: list[tuple[str, EconomaticaSectorRecord]] = []
    for issuer_id, record in by_issuer.items():
        desired.extend((iid, record) for iid in equities.get(issuer_id, []))

    existing: dict[str, tuple[str | None, str | None]] = {}
    if desired:
        ids = [iid for iid, _ in desired]
        cur = await conn.execute(
            """select instrument_id::text, economic_sector, subsector
                 from market.sector_classification
                where source_code = %s and reference_date = %s
                  and instrument_id = any(%s::uuid[])""",
            (SOURCE, observed_at, ids),
        )
        existing = {iid: (sector, subsector) for iid, sector, subsector in await cur.fetchall()}

    pending: list[tuple[str, EconomaticaSectorRecord]] = []
    already_equal = 0
    conflicts: list[str] = []
    for iid, record in desired:
        current = existing.get(iid)
        if current is None:
            pending.append((iid, record))
        elif current == record.key:
            already_equal += 1
        else:
            conflicts.append(iid)
    if conflicts:
        await ingest.fechar_lote(
            conn, batch_id, status="failed", rows=0,
            error="economatica_classificacao_conflitante_mesma_chave", reference_date=observed_at,
            details={"conflicting_instrument_ids": sorted(conflicts)},
        )
        raise EconomaticaSectorIngestConflict("economatica_classificacao_conflitante_mesma_chave")

    inserted = 0
    if pending:
        iids, sectors, subsectors = zip(*[(iid, r.economic_sector, r.subsector) for iid, r in pending])
        cur = await conn.execute(
            """insert into market.sector_classification
                   (instrument_id, source_code, reference_date, economic_sector, subsector,
                    segment, listing_segment, ingestion_batch_id)
               select i, %s, %s, es, ss, null, null, %s
                 from unnest(%s::uuid[], %s::text[], %s::text[]) as t(i, es, ss)
               on conflict (instrument_id, source_code, reference_date) do nothing""",
            (SOURCE, observed_at, batch_id, list(iids), list(sectors), list(subsectors)),
        )
        inserted = cur.rowcount
        if inserted != len(pending):
            ids_pending = [iid for iid, _ in pending]
            cur = await conn.execute(
                """select instrument_id::text, economic_sector, subsector
                     from market.sector_classification
                    where source_code = %s and reference_date = %s
                      and instrument_id = any(%s::uuid[])""",
                (SOURCE, observed_at, ids_pending),
            )
            after = {iid: (sector, subsector) for iid, sector, subsector in await cur.fetchall()}
            race_conflicts = [iid for iid, record in pending if after.get(iid) != record.key]
            if race_conflicts:
                await ingest.fechar_lote(
                    conn, batch_id, status="partial", rows=inserted,
                    error="economatica_corrida_concorrente_classificacao", reference_date=observed_at,
                    details={"conflicting_instrument_ids": sorted(race_conflicts)},
                )
                raise EconomaticaSectorIngestConflict("economatica_corrida_concorrente_classificacao")
            already_equal += len(pending) - inserted

    await ingest.fechar_lote(
        conn, batch_id, status="succeeded", rows=inserted, reference_date=observed_at,
        details={
            "records_received": len(materialized),
            "matched_tickers": len(matched),
            "unmatched_tickers": list(unmatched),
            "issuers_matched": len(by_issuer),
            "classes_targeted": len(desired),
            "rows_already_equal": already_equal,
            "temporal_semantics": "known_at_ingestion_not_historical_vintage",
        },
    )
    return EconomaticaSectorIngestReport(
        batch_id=batch_id, reused_existing_batch=False, observed_at=observed_at,
        records_received=len(materialized), matched_tickers=len(matched), unmatched_tickers=unmatched,
        issuers_matched=len(by_issuer), classes_targeted=len(desired), rows_inserted=inserted,
        rows_already_equal=already_equal,
    )
