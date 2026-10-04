"""Classificação setorial point-in-time do Analista (FQ5.6A).

Este módulo é deliberadamente somente leitura. A fonte/ingestão B3 ainda possui um gate próprio;
aqui apenas resolvemos snapshots já presentes em ``market.sector_classification`` respeitando a
proveniência de ``market.ingestion_batches``.

Semântica temporal strict PIT: uma linha só é elegível quando pertence a um lote ``succeeded``
com ``finished_at`` conhecido até o cutoff. Isso reconstrói o que o Plexo conhecia, não uma data
jurídica/econômica de vigência da classificação.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from enum import StrEnum
from typing import Iterable

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field


SOURCE_B3 = "b3"
DATASET = "market.sector_classification"


class SectorLevel(StrEnum):
    SEGMENTO = "segmento"
    SUBSETOR = "subsetor"
    SETOR = "setor"


class SectorClassificationConflict(RuntimeError):
    """Mesmo emissor/snapshot contém classificações incompatíveis entre classes."""


class SectorRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    issuer_id: str
    issuer_name: str
    ticker: str | None = None
    reference_date: date
    economic_sector: str | None = None
    subsector: str | None = None
    segment: str | None = None
    listing_segment: str | None = None
    source_code: str
    ingestion_batch_id: str | None = None
    availability_date: date | None = None

    def value_for(self, level: SectorLevel) -> str | None:
        if level == SectorLevel.SEGMENTO:
            return self.segment
        if level == SectorLevel.SUBSETOR:
            return self.subsector
        return self.economic_sector


class SectorProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str = DATASET
    source_codes: list[str] = Field(default_factory=list)
    ingestion_batch_ids: list[str] = Field(default_factory=list)
    reference_date: date | None = None
    availability_date: date | None = None
    cutoff_date: date
    strict_pit: bool = True
    temporal_semantics: str = "ingestion_finished_at_cutoff"
    warnings: list[str] = Field(default_factory=list)


class ResolvedSectorClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    issuer_id: str | None = None
    issuer_name: str | None = None
    economic_sector: str | None = None
    subsector: str | None = None
    segment: str | None = None
    listing_segment: str | None = None
    found: bool = False
    provenance: SectorProvenance

    def value_for(self, level: SectorLevel) -> str | None:
        if level == SectorLevel.SEGMENTO:
            return self.segment
        if level == SectorLevel.SUBSETOR:
            return self.subsector
        return self.economic_sector


class PeerIssuer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer_id: str
    issuer_name: str
    tickers: list[str] = Field(default_factory=list)
    instrument_ids: list[str] = Field(default_factory=list)
    reference_date: date
    economic_sector: str | None = None
    subsector: str | None = None
    segment: str | None = None
    listing_segments: list[str] = Field(default_factory=list)


class PeerUniverse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: ResolvedSectorClassification
    level: SectorLevel
    classification_value: str | None = None
    peers: list[PeerIssuer] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


async def _target_identity(conn: AsyncConnection, instrument_id: str) -> tuple[str | None, str | None]:
    cur = await conn.execute(
        "select issuer_id::text, name from market.instruments where id = %s",
        (instrument_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None, None
    issuer_id, _instrument_name = row
    if issuer_id is None:
        return None, None
    cur = await conn.execute("select name from market.issuers where id = %s", (issuer_id,))
    issuer = await cur.fetchone()
    return issuer_id, (issuer[0] if issuer else None)


def _classification_key(row: SectorRow) -> tuple[str | None, str | None, str | None]:
    return (row.economic_sector, row.subsector, row.segment)


def _latest_consistent(rows: Iterable[SectorRow]) -> tuple[SectorRow | None, list[str]]:
    """Escolhe o snapshot mais recente e garante consistência econômica entre classes."""
    rows = list(rows)
    if not rows:
        return None, []
    latest = max(r.reference_date for r in rows)
    same_snapshot = [r for r in rows if r.reference_date == latest]
    keys = {_classification_key(r) for r in same_snapshot}
    if len(keys) > 1:
        issuer_id = same_snapshot[0].issuer_id
        raise SectorClassificationConflict(
            f"classificacao_setorial_divergente_entre_classes:{issuer_id}:{latest.isoformat()}"
        )
    warnings: list[str] = []
    representative = sorted(
        same_snapshot,
        key=lambda r: ((r.ticker or ""), r.instrument_id),
    )[0]
    return representative, warnings


async def _rows_for_issuer(
    conn: AsyncConnection,
    issuer_id: str,
    *,
    cutoff: date,
    strict_pit: bool,
    only_in_universe: bool = False,
) -> list[SectorRow]:
    universe = "and i.is_in_universe" if only_in_universe else ""
    pit = """
      and sc.ingestion_batch_id is not null
      and b.status = 'succeeded'
      and b.finished_at is not null
      and b.finished_at::date <= %s
    """ if strict_pit else ""
    args: list[object] = [issuer_id, SOURCE_B3, cutoff]
    if strict_pit:
        args.append(cutoff)
    cur = await conn.execute(
        f"""
        select sc.instrument_id::text,
               i.issuer_id::text,
               iss.name,
               i.ticker,
               sc.reference_date,
               sc.economic_sector,
               sc.subsector,
               sc.segment,
               sc.listing_segment,
               sc.source_code::text,
               sc.ingestion_batch_id::text,
               b.finished_at::date
          from market.sector_classification sc
          join market.instruments i on i.id = sc.instrument_id
          join market.issuers iss on iss.id = i.issuer_id
          left join market.ingestion_batches b on b.id = sc.ingestion_batch_id
         where i.issuer_id = %s
           and i.kind = 'acao'
           {universe}
           and sc.source_code = %s
           and sc.reference_date <= %s
           {pit}
         order by sc.reference_date desc, i.ticker nulls last, sc.instrument_id
        """,
        tuple(args),
    )
    return [
        SectorRow(
            instrument_id=iid,
            issuer_id=row_issuer,
            issuer_name=issuer_name,
            ticker=ticker,
            reference_date=ref_date,
            economic_sector=economic_sector,
            subsector=subsector,
            segment=segment,
            listing_segment=listing_segment,
            source_code=source_code,
            ingestion_batch_id=batch_id,
            availability_date=availability,
        )
        for (
            iid,
            row_issuer,
            issuer_name,
            ticker,
            ref_date,
            economic_sector,
            subsector,
            segment,
            listing_segment,
            source_code,
            batch_id,
            availability,
        ) in await cur.fetchall()
    ]


async def classification_for_instrument(
    conn: AsyncConnection,
    instrument_id: str,
    *,
    cutoff: date,
    strict_pit: bool = True,
) -> ResolvedSectorClassification:
    issuer_id, issuer_name = await _target_identity(conn, instrument_id)
    if issuer_id is None:
        return ResolvedSectorClassification(
            instrument_id=instrument_id,
            found=False,
            provenance=SectorProvenance(
                cutoff_date=cutoff,
                strict_pit=strict_pit,
                warnings=["classificacao_setorial_indisponivel"],
            ),
        )

    rows = await _rows_for_issuer(conn, issuer_id, cutoff=cutoff, strict_pit=strict_pit)
    representative, warnings = _latest_consistent(rows)
    if representative is None:
        return ResolvedSectorClassification(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            issuer_name=issuer_name,
            found=False,
            provenance=SectorProvenance(
                cutoff_date=cutoff,
                strict_pit=strict_pit,
                warnings=["classificacao_setorial_indisponivel"],
            ),
        )

    same_snapshot = [r for r in rows if r.reference_date == representative.reference_date]
    target_row = next((r for r in same_snapshot if r.instrument_id == instrument_id), representative)
    if not strict_pit:
        warnings.append("classificacao_setorial_sem_vintage_pit")
    return ResolvedSectorClassification(
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        issuer_name=representative.issuer_name,
        economic_sector=representative.economic_sector,
        subsector=representative.subsector,
        segment=representative.segment,
        listing_segment=target_row.listing_segment,
        found=True,
        provenance=SectorProvenance(
            source_codes=sorted({r.source_code for r in same_snapshot}),
            ingestion_batch_ids=sorted({r.ingestion_batch_id for r in same_snapshot if r.ingestion_batch_id}),
            reference_date=representative.reference_date,
            availability_date=max((r.availability_date for r in same_snapshot if r.availability_date), default=None),
            cutoff_date=cutoff,
            strict_pit=strict_pit,
            warnings=warnings,
        ),
    )


async def _candidate_rows(
    conn: AsyncConnection,
    *,
    cutoff: date,
    strict_pit: bool,
) -> list[SectorRow]:
    pit = """
      and sc.ingestion_batch_id is not null
      and b.status = 'succeeded'
      and b.finished_at is not null
      and b.finished_at::date <= %s
    """ if strict_pit else ""
    args: list[object] = [SOURCE_B3, cutoff]
    if strict_pit:
        args.append(cutoff)
    cur = await conn.execute(
        f"""
        select sc.instrument_id::text,
               i.issuer_id::text,
               iss.name,
               i.ticker,
               sc.reference_date,
               sc.economic_sector,
               sc.subsector,
               sc.segment,
               sc.listing_segment,
               sc.source_code::text,
               sc.ingestion_batch_id::text,
               b.finished_at::date
          from market.sector_classification sc
          join market.instruments i on i.id = sc.instrument_id
          join market.issuers iss on iss.id = i.issuer_id
          left join market.ingestion_batches b on b.id = sc.ingestion_batch_id
         where i.kind = 'acao'
           and i.is_in_universe
           and sc.source_code = %s
           and sc.reference_date <= %s
           {pit}
         order by iss.id, sc.reference_date desc, i.ticker nulls last, sc.instrument_id
        """,
        tuple(args),
    )
    return [SectorRow(
        instrument_id=iid,
        issuer_id=issuer_id,
        issuer_name=issuer_name,
        ticker=ticker,
        reference_date=ref_date,
        economic_sector=economic_sector,
        subsector=subsector,
        segment=segment,
        listing_segment=listing_segment,
        source_code=source_code,
        ingestion_batch_id=batch_id,
        availability_date=availability,
    ) for (
        iid, issuer_id, issuer_name, ticker, ref_date, economic_sector, subsector, segment,
        listing_segment, source_code, batch_id, availability
    ) in await cur.fetchall()]


async def _eligible_peer_target(conn: AsyncConnection, instrument_id: str) -> bool:
    cur = await conn.execute(
        "select kind = 'acao' and is_in_universe from market.instruments where id = %s",
        (instrument_id,),
    )
    row = await cur.fetchone()
    return bool(row and row[0])


async def peer_issuers(
    conn: AsyncConnection,
    instrument_id: str,
    *,
    cutoff: date,
    level: SectorLevel = SectorLevel.SEGMENTO,
    strict_pit: bool = True,
) -> PeerUniverse:
    target = await classification_for_instrument(
        conn, instrument_id, cutoff=cutoff, strict_pit=strict_pit
    )
    if not await _eligible_peer_target(conn, instrument_id):
        return PeerUniverse(
            target=target,
            level=level,
            classification_value=target.value_for(level) if target.found else None,
            warnings=["fora_da_cobertura"],
        )
    target_value = target.value_for(level) if target.found else None
    if not target.found or target.issuer_id is None or not target_value:
        return PeerUniverse(
            target=target,
            level=level,
            classification_value=target_value,
            warnings=["classificacao_setorial_indisponivel"],
        )

    grouped: dict[str, list[SectorRow]] = defaultdict(list)
    for row in await _candidate_rows(conn, cutoff=cutoff, strict_pit=strict_pit):
        grouped[row.issuer_id].append(row)

    peers: list[PeerIssuer] = []
    warnings: list[str] = []
    for issuer_id, rows in grouped.items():
        if issuer_id == target.issuer_id:
            continue
        representative, issuer_warnings = _latest_consistent(rows)
        if representative is None or representative.value_for(level) != target_value:
            continue
        latest_rows = [r for r in rows if r.reference_date == representative.reference_date]
        warnings.extend(issuer_warnings)
        peers.append(PeerIssuer(
            issuer_id=issuer_id,
            issuer_name=representative.issuer_name,
            tickers=sorted({r.ticker for r in latest_rows if r.ticker}),
            instrument_ids=sorted({r.instrument_id for r in latest_rows}),
            reference_date=representative.reference_date,
            economic_sector=representative.economic_sector,
            subsector=representative.subsector,
            segment=representative.segment,
            listing_segments=sorted({r.listing_segment for r in latest_rows if r.listing_segment}),
        ))

    peers.sort(key=lambda p: (p.issuer_name.casefold(), p.issuer_id))
    if len(peers) < 2:
        warnings.append("pares_insuficientes")
    return PeerUniverse(
        target=target,
        level=level,
        classification_value=target_value,
        peers=peers,
        warnings=sorted(set(warnings)),
    )
