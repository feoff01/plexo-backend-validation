"""Fundação de ingestão setorial B3 (FQ5.6A), independente do formato de rede.

Este módulo NÃO parseia CSV/JSON/XML nem faz HTTP. Ele recebe registros semânticos já validados
por uma futura camada de fonte, aplica matching determinístico CNPJ -> issuer, expande o snapshot
para todas as classes ``acao`` do emissor e grava ``market.sector_classification`` de forma
append-only, usando a infraestrutura canônica de ``market.ingestion_batches``.

A separação é deliberada: enquanto o layout real do UP2DATA SummaryData não estiver materializado
como fixture oficial, nenhum parser de arquivo deve ser inventado. A ingestão e o coverage gate,
por outro lado, podem ser testados integralmente sobre o schema existente.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
import re
from typing import Iterable

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.market import ingest
from app.market.sectors import SOURCE_B3, SectorLevel


DATASET = "b3.sector_classification@1"
_HASH_HEX = re.compile(r"^[0-9a-f]{64}$")


class SectorIngestConflict(RuntimeError):
    """O mesmo snapshot não pode reescrever classificação já persistida."""


class SectorSourceRecord(BaseModel):
    """Registro semântico normalizado que um parser oficial deverá produzir no futuro."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer_cnpj: str
    economic_sector: str | None = None
    subsector: str | None = None
    segment: str | None = None
    listing_segment: str | None = None

    @field_validator("issuer_cnpj")
    @classmethod
    def _cnpj_14_digits(cls, value: str) -> str:
        value = value.strip()
        if len(value) != 14 or not value.isdigit():
            raise ValueError("issuer_cnpj deve conter exatamente 14 dígitos já normalizados")
        return value

    @field_validator("economic_sector", "subsector", "segment", "listing_segment")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    def classification_key(self) -> tuple[str | None, str | None, str | None, str | None]:
        return (self.economic_sector, self.subsector, self.segment, self.listing_segment)


class SectorIngestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: str | None = None
    reused_existing_batch: bool = False
    reference_date: date
    source_code: str = SOURCE_B3
    dataset: str = DATASET
    records_received: int = 0
    unique_cnpjs: int = 0
    matched_issuers: int = 0
    unmatched_cnpjs: list[str] = Field(default_factory=list)
    issuers_without_equity: list[str] = Field(default_factory=list)
    classes_targeted: int = 0
    rows_inserted: int = 0
    rows_already_equal: int = 0
    warnings: list[str] = Field(default_factory=list)


class SectorCoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cutoff_date: date
    level: SectorLevel
    eligible_issuers: int
    classified_issuers: int
    coverage_pct: Decimal | None = None
    unclassified_issuers: list[str] = Field(default_factory=list)
    unclassified_tickers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _coalesce_records(records: Iterable[SectorSourceRecord]) -> tuple[list[SectorSourceRecord], int]:
    """Deduplica CNPJ idêntico e falha fechado se o mesmo CNPJ vier divergente no snapshot."""
    materialized = list(records)
    by_cnpj: dict[str, SectorSourceRecord] = {}
    for record in materialized:
        previous = by_cnpj.get(record.issuer_cnpj)
        if previous is None:
            by_cnpj[record.issuer_cnpj] = record
            continue
        if previous.classification_key() != record.classification_key():
            raise SectorIngestConflict(
                f"fonte_setorial_divergente_mesmo_cnpj:{record.issuer_cnpj}"
            )
    return [by_cnpj[key] for key in sorted(by_cnpj)], len(materialized)


async def _issuer_map(conn: AsyncConnection, cnpjs: list[str]) -> dict[str, tuple[str, str]]:
    if not cnpjs:
        return {}
    cur = await conn.execute(
        """select btrim(cnpj::text), id::text, name
             from market.issuers
            where cnpj is not null and btrim(cnpj::text) = any(%s::text[])""",
        (cnpjs,),
    )
    return {cnpj: (issuer_id, name) for cnpj, issuer_id, name in await cur.fetchall()}


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
    for issuer_id, instrument_id in await cur.fetchall():
        out[issuer_id].append(instrument_id)
    return dict(out)


async def _existing_snapshot(
    conn: AsyncConnection,
    instrument_ids: list[str],
    *,
    source_code: str,
    reference_date: date,
) -> dict[str, tuple[str | None, str | None, str | None, str | None]]:
    if not instrument_ids:
        return {}
    cur = await conn.execute(
        """select instrument_id::text, economic_sector, subsector, segment, listing_segment
             from market.sector_classification
            where source_code = %s and reference_date = %s
              and instrument_id = any(%s::uuid[])""",
        (source_code, reference_date, instrument_ids),
    )
    return {
        iid: (economic_sector, subsector, segment, listing_segment)
        for iid, economic_sector, subsector, segment, listing_segment in await cur.fetchall()
    }


async def ingest_sector_records(
    conn: AsyncConnection,
    records: Iterable[SectorSourceRecord],
    *,
    reference_date: date,
    file_hash: str,
    storage_key: str | None = None,
    source_code: str = SOURCE_B3,
    dataset: str = DATASET,
) -> SectorIngestReport:
    """Projeta um snapshot setorial validado para ``market.sector_classification``."""
    unique_records, records_received = _coalesce_records(records)
    if not unique_records:
        raise ValueError("snapshot_setorial_vazio")
    if reference_date > date.today():
        raise ValueError("reference_date_setorial_no_futuro")
    if not _HASH_HEX.fullmatch(file_hash):
        raise ValueError("file_hash_setorial_invalido")
    if source_code != SOURCE_B3:
        raise ValueError("FQ5.6 v1 aceita somente source_code=b3")
    if dataset != DATASET:
        raise ValueError(f"dataset setorial v1 deve ser {DATASET}")

    batch_id = await ingest.abrir_lote(
        conn,
        source_code=source_code,
        dataset=dataset,
        file_hash=file_hash,
        reference_date=reference_date,
    )
    if batch_id is None:
        existing_batch = await ingest.lote_existente(
            conn, source_code=source_code, dataset=dataset, file_hash=file_hash
        )
        return SectorIngestReport(
            batch_id=existing_batch,
            reused_existing_batch=True,
            reference_date=reference_date,
            source_code=source_code,
            dataset=dataset,
            records_received=records_received,
            unique_cnpjs=len(unique_records),
            warnings=["arquivo_setorial_ja_ingerido"],
        )

    if storage_key:
        await conn.execute(
            "update market.ingestion_batches set storage_key = %s where id = %s and status = 'running'",
            (storage_key, batch_id),
        )

    cnpjs = [record.issuer_cnpj for record in unique_records]
    issuer_map = await _issuer_map(conn, cnpjs)
    unmatched = sorted(set(cnpjs) - set(issuer_map))
    equities = await _equities_by_issuer(conn, [issuer_id for issuer_id, _ in issuer_map.values()])

    by_cnpj = {record.issuer_cnpj: record for record in unique_records}
    without_equity: list[str] = []
    desired: list[tuple[str, SectorSourceRecord]] = []
    matched_issuers = 0
    for cnpj in sorted(issuer_map):
        issuer_id, _issuer_name = issuer_map[cnpj]
        ids = equities.get(issuer_id, [])
        if not ids:
            without_equity.append(cnpj)
            continue
        matched_issuers += 1
        desired.extend((instrument_id, by_cnpj[cnpj]) for instrument_id in ids)

    instrument_ids = [instrument_id for instrument_id, _ in desired]
    existing = await _existing_snapshot(
        conn,
        instrument_ids,
        source_code=source_code,
        reference_date=reference_date,
    )

    already_equal = 0
    pending: list[tuple[str, SectorSourceRecord]] = []
    conflicts: list[str] = []
    for instrument_id, record in desired:
        current = existing.get(instrument_id)
        if current is None:
            pending.append((instrument_id, record))
        elif current == record.classification_key():
            already_equal += 1
        else:
            conflicts.append(instrument_id)

    if conflicts:
        await ingest.fechar_lote(
            conn,
            batch_id,
            status="failed",
            rows=0,
            error="classificacao_setorial_conflitante_mesma_chave",
            reference_date=reference_date,
            details={
                "conflicting_instrument_ids": sorted(conflicts),
                "records_received": records_received,
                "unique_cnpjs": len(unique_records),
            },
        )
        raise SectorIngestConflict(
            "classificacao_setorial_conflitante_mesma_chave:"
            + ",".join(sorted(conflicts))
        )

    inserted = 0
    if pending:
        instrument_ids_p, economic_sectors, subsectors, segments, listing_segments = zip(
            *[
                (
                    instrument_id,
                    record.economic_sector,
                    record.subsector,
                    record.segment,
                    record.listing_segment,
                )
                for instrument_id, record in pending
            ]
        )
        cur = await conn.execute(
            """insert into market.sector_classification
                   (instrument_id, source_code, reference_date, economic_sector, subsector,
                    segment, listing_segment, ingestion_batch_id)
               select i, %s, %s, es, ss, sg, ls, %s
                 from unnest(%s::uuid[], %s::text[], %s::text[], %s::text[], %s::text[])
                      as t(i, es, ss, sg, ls)
               on conflict (instrument_id, source_code, reference_date) do nothing""",
            (
                source_code,
                reference_date,
                batch_id,
                list(instrument_ids_p),
                list(economic_sectors),
                list(subsectors),
                list(segments),
                list(listing_segments),
            ),
        )
        inserted = cur.rowcount

    if inserted != len(pending):
        after = await _existing_snapshot(
            conn,
            [instrument_id for instrument_id, _ in pending],
            source_code=source_code,
            reference_date=reference_date,
        )
        race_conflicts = [
            instrument_id
            for instrument_id, record in pending
            if after.get(instrument_id) != record.classification_key()
        ]
        if race_conflicts:
            await ingest.fechar_lote(
                conn,
                batch_id,
                status="partial",
                rows=inserted,
                error="corrida_concorrente_classificacao_setorial",
                reference_date=reference_date,
                details={"conflicting_instrument_ids": sorted(race_conflicts)},
            )
            raise SectorIngestConflict(
                "corrida_concorrente_classificacao_setorial:"
                + ",".join(sorted(race_conflicts))
            )
        already_equal += len(pending) - inserted

    warnings: list[str] = []
    if unmatched:
        warnings.append("cnpj_setorial_sem_issuer")
    if without_equity:
        warnings.append("issuer_setorial_sem_acao")

    details = {
        "records_received": records_received,
        "unique_cnpjs": len(unique_records),
        "matched_issuers": matched_issuers,
        "unmatched_cnpjs": unmatched,
        "issuers_without_equity": sorted(without_equity),
        "classes_targeted": len(desired),
        "rows_already_equal": already_equal,
        "warnings": warnings,
    }
    await ingest.fechar_lote(
        conn,
        batch_id,
        status="succeeded",
        rows=inserted,
        reference_date=reference_date,
        details=details,
    )
    return SectorIngestReport(
        batch_id=batch_id,
        reused_existing_batch=False,
        reference_date=reference_date,
        source_code=source_code,
        dataset=dataset,
        records_received=records_received,
        unique_cnpjs=len(unique_records),
        matched_issuers=matched_issuers,
        unmatched_cnpjs=unmatched,
        issuers_without_equity=sorted(without_equity),
        classes_targeted=len(desired),
        rows_inserted=inserted,
        rows_already_equal=already_equal,
        warnings=warnings,
    )


async def measure_sector_coverage(
    conn: AsyncConnection,
    *,
    cutoff: date,
    level: SectorLevel = SectorLevel.SEGMENTO,
    max_examples: int = 20,
) -> SectorCoverageReport:
    """Mede cobertura PIT por nível dos emissores com ação no universo, sem limiar automático."""
    level_column = {
        SectorLevel.SEGMENTO: "sc.segment",
        SectorLevel.SUBSETOR: "sc.subsector",
        SectorLevel.SETOR: "sc.economic_sector",
    }[level]
    cur = await conn.execute(
        f"""with eligible as (
               select i.issuer_id, array_agg(i.ticker order by i.ticker) filter (where i.ticker is not null) as tickers
                 from market.instruments i
                where i.kind = 'acao' and i.is_in_universe and i.issuer_id is not null
                group by i.issuer_id
             ), classified as (
               select distinct i.issuer_id
                 from market.sector_classification sc
                 join market.instruments i on i.id = sc.instrument_id
                 join market.ingestion_batches b on b.id = sc.ingestion_batch_id
                where sc.source_code = %s
                  and sc.reference_date <= %s
                  and b.status = 'succeeded'
                  and b.finished_at is not null
                  and b.finished_at::date <= %s
                  and nullif(btrim({level_column}), '') is not null
             )
             select e.issuer_id::text, iss.name, e.tickers,
                    (c.issuer_id is not null) as classified
               from eligible e
               join market.issuers iss on iss.id = e.issuer_id
               left join classified c on c.issuer_id = e.issuer_id
              order by iss.name, e.issuer_id""",
        (SOURCE_B3, cutoff, cutoff),
    )
    rows = await cur.fetchall()
    eligible = len(rows)
    classified = sum(1 for *_prefix, is_classified in rows if is_classified)
    unclassified = [row for row in rows if not row[3]]
    pct = (
        None
        if eligible == 0
        else (Decimal(classified) * Decimal("100") / Decimal(eligible)).quantize(Decimal("0.01"))
    )
    warnings: list[str] = []
    if eligible == 0:
        warnings.append("universo_acoes_vazio")
    elif classified < eligible:
        warnings.append("cobertura_setorial_incompleta")
    return SectorCoverageReport(
        cutoff_date=cutoff,
        level=level,
        eligible_issuers=eligible,
        classified_issuers=classified,
        coverage_pct=pct,
        unclassified_issuers=[
            name for _issuer_id, name, _tickers, _c in unclassified[:max_examples]
        ],
        unclassified_tickers=[
            ticker
            for _issuer_id, _name, tickers, _c in unclassified[:max_examples]
            for ticker in (tickers or [])
        ][:max_examples],
        warnings=warnings,
    )
