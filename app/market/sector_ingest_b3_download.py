"""Adapter do download oficial B3 para a ingestão setorial canônica.

O XLSX oficial observado identifica a companhia por um ``CÓDIGO`` de quatro caracteres,
não por CNPJ. Este adapter resolve o código de forma estrita contra ações já cadastradas,
exige um único issuer e CNPJ válido e então delega toda persistência ao pipeline canônico
``ingest_sector_records``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Iterable

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from app.market.b3_sector_source import B3SectorDownloadRecord
from app.market.sector_ingest import (
    SectorIssuerIngestReport,
    SectorIssuerSourceRecord,
    ingest_sector_issuer_records,
)

_CODE = re.compile(r"^[A-Z0-9]{4}$")


class B3SectorCodeAmbiguity(RuntimeError):
    """Um código oficial B3 não converge para um único issuer."""


class B3SectorCodeResolutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records_received: int
    unique_codes: int
    resolved_codes: int
    unresolved_codes: list[str] = Field(default_factory=list)
    ambiguous_codes: list[str] = Field(default_factory=list)
    codes_without_cnpj: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class B3SectorDownloadIngestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution: B3SectorCodeResolutionReport
    ingest: SectorIssuerIngestReport


@dataclass(frozen=True)
class _ResolvedIssuer:
    issuer_id: str
    cnpj: str | None
    issuer_name: str


def _digits_cnpj(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(char for char in value if char.isdigit())
    return digits if len(digits) == 14 else None


def _coalesce_records(
    records: Iterable[B3SectorDownloadRecord],
) -> tuple[dict[str, B3SectorDownloadRecord], int]:
    materialized = list(records)
    by_code: dict[str, B3SectorDownloadRecord] = {}
    for record in materialized:
        code = record.company_code.strip().upper()
        if not _CODE.fullmatch(code):
            raise ValueError(f"codigo_companhia_b3_invalido:{code}")
        normalized = B3SectorDownloadRecord(
            company_code=code,
            economic_sector=record.economic_sector.strip(),
            subsector=record.subsector.strip(),
        )
        previous = by_code.get(code)
        if previous is not None and previous.key != normalized.key:
            raise B3SectorCodeAmbiguity(f"codigo_setorial_divergente:{code}")
        by_code[code] = normalized
    if not by_code:
        raise ValueError("snapshot_b3_setorial_vazio")
    return by_code, len(materialized)


async def _catalog_matches(
    conn: AsyncConnection,
    company_codes: list[str],
) -> dict[str, list[_ResolvedIssuer]]:
    if not company_codes:
        return {}
    cur = await conn.execute(
        """select upper(left(i.ticker, 4)) as company_code,
                  i.issuer_id::text,
                  iss.cnpj::text,
                  iss.name
             from market.instruments i
             join market.issuers iss on iss.id = i.issuer_id
            where i.kind = 'acao'
              and i.ticker is not null
              and i.issuer_id is not null
              and upper(left(i.ticker, 4)) = any(%s::text[])
            group by upper(left(i.ticker, 4)), i.issuer_id, iss.cnpj, iss.name
            order by upper(left(i.ticker, 4)), i.issuer_id""",
        (company_codes,),
    )
    out: dict[str, list[_ResolvedIssuer]] = {}
    for code, issuer_id, cnpj, issuer_name in await cur.fetchall():
        out.setdefault(code, []).append(
            _ResolvedIssuer(
                issuer_id=issuer_id,
                cnpj=_digits_cnpj(cnpj),
                issuer_name=issuer_name,
            )
        )
    return out


async def resolve_b3_sector_records(
    conn: AsyncConnection,
    records: Iterable[B3SectorDownloadRecord],
) -> tuple[list[SectorIssuerSourceRecord], B3SectorCodeResolutionReport]:
    """Resolve company code oficial -> único issuer, sem escrita."""
    by_code, received = _coalesce_records(records)
    matches = await _catalog_matches(conn, sorted(by_code))

    resolved: list[SectorIssuerSourceRecord] = []
    unresolved: list[str] = []
    ambiguous: list[str] = []
    without_cnpj: list[str] = []

    for code in sorted(by_code):
        issuer_matches = matches.get(code, [])
        if not issuer_matches:
            unresolved.append(code)
            continue
        issuer_ids = {match.issuer_id for match in issuer_matches}
        if len(issuer_ids) != 1:
            ambiguous.append(code)
            continue
        issuer = issuer_matches[0]
        if issuer.cnpj is None:
            without_cnpj.append(code)
        source = by_code[code]
        resolved.append(
            SectorIssuerSourceRecord(
                issuer_id=issuer.issuer_id,
                economic_sector=source.economic_sector,
                subsector=source.subsector,
                segment=None,
                listing_segment=None,
            )
        )

    warnings: list[str] = []
    if unresolved:
        warnings.append("codigo_b3_sem_issuer")
    if ambiguous:
        warnings.append("codigo_b3_ambiguo_entre_issuers")
    if without_cnpj:
        warnings.append("codigo_b3_issuer_sem_cnpj")

    return resolved, B3SectorCodeResolutionReport(
        records_received=received,
        unique_codes=len(by_code),
        resolved_codes=len(resolved),
        unresolved_codes=unresolved,
        ambiguous_codes=ambiguous,
        codes_without_cnpj=without_cnpj,
        warnings=warnings,
    )


async def ingest_b3_sector_download_records(
    conn: AsyncConnection,
    records: Iterable[B3SectorDownloadRecord],
    *,
    reference_date: date,
    file_hash: str,
    storage_key: str | None = None,
) -> B3SectorDownloadIngestReport:
    """Resolve o download B3 e delega persistência à ingestão canônica por issuer."""
    resolved, resolution = await resolve_b3_sector_records(conn, records)
    if resolution.ambiguous_codes:
        raise B3SectorCodeAmbiguity(
            "codigo_b3_ambiguo_entre_issuers:" + ",".join(resolution.ambiguous_codes)
        )
    if not resolved:
        raise ValueError("snapshot_b3_sem_codigo_resolvido")

    ingest_report = await ingest_sector_issuer_records(
        conn,
        resolved,
        reference_date=reference_date,
        file_hash=file_hash,
        storage_key=storage_key,
    )
    return B3SectorDownloadIngestReport(
        resolution=resolution,
        ingest=ingest_report,
    )
