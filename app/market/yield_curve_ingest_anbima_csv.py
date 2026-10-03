"""Ponte física -> semântica para o CSV público oficial ANBIMA de ETTJ.

O módulo recebe bytes já materializados por um adapter/ambiente autorizado. Não faz HTTP,
não conhece credenciais e não duplica persistência: calcula o fingerprint, valida o layout
físico e delega integralmente a escrita a ``ingest_anbima_yield_curve``.
"""
from __future__ import annotations

import hashlib
import re

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict

from app.market.anbima_yield_curve_source import parse_anbima_yield_curve_csv
from app.market.yield_curve_ingest import (
    AnbimaYieldCurvePoint,
    YieldCurveIngestReport,
    ingest_anbima_yield_curve,
)

_HASH_HEX = re.compile(r"^[0-9a-f]{64}$")


class AnbimaYieldCurveCsvIngestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_hash: str
    bytes_received: int
    reference_date: str
    ipca_vertices: int
    pre_vertices: int
    implied_vertices: int
    ingest: YieldCurveIngestReport


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def ingest_anbima_yield_curve_csv(
    conn: AsyncConnection,
    data: bytes,
    *,
    expected_sha256: str | None = None,
    storage_key: str | None = None,
) -> AnbimaYieldCurveCsvIngestReport:
    """Valida o CSV oficial e delega a persistência ao pipeline semântico canônico."""
    file_hash = _sha256(data)
    if expected_sha256 is not None:
        normalized = expected_sha256.strip().lower()
        if not _HASH_HEX.fullmatch(normalized):
            raise ValueError("expected_sha256_ettj_invalido")
        if normalized != file_hash:
            raise ValueError("sha256_ettj_inesperado")

    snapshot = parse_anbima_yield_curve_csv(data)
    points = [
        AnbimaYieldCurvePoint(
            reference_date=snapshot.reference_date,
            business_days=point.business_days,
            pre_rate_pct=(float(point.pre_rate_pct) if point.pre_rate_pct is not None else None),
            ipca_rate_pct=float(point.ipca_rate_pct),
            implied_inflation_pct=(
                float(point.implied_inflation_pct)
                if point.implied_inflation_pct is not None
                else None
            ),
        )
        for point in snapshot.points
    ]
    ingest_report = await ingest_anbima_yield_curve(
        conn,
        points,
        file_hash=file_hash,
        storage_key=storage_key,
    )
    return AnbimaYieldCurveCsvIngestReport(
        file_hash=file_hash,
        bytes_received=len(data),
        reference_date=snapshot.reference_date.isoformat(),
        ipca_vertices=snapshot.ipca_vertices,
        pre_vertices=snapshot.pre_vertices,
        implied_vertices=snapshot.implied_vertices,
        ingest=ingest_report,
    )
