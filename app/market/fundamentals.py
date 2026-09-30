"""Fundamentals Data Foundation do Analista (FQ5).

`market.fundamentals` guarda vintages append-only. A semântica temporal aqui é diferente da de
preços: uma linha só pode participar da análise quando `availability_date <= cutoff`. Isso permite
análise point-in-time real para fundamentos, desde que a ingestão tenha preservado a data de
recebimento/publicação e a unidade esteja explícita.

Este módulo não calcula valuation. Ele resolve e normaliza o que estava disponível no cutoff.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from datetime import date
import math

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field, model_validator


RAW_UNIT_UNUSABLE = "fundamental_unit_raw"


class FundamentalUnit(StrEnum):
    RAW = "raw"
    BRL = "brl"
    SHARES = "shares"
    RATIO = "ratio"
    PERCENT = "percent"
    BRL_PER_SHARE = "brl_per_share"


class FundamentalDocumentType(StrEnum):
    DFP = "DFP"
    ITR = "ITR"


class FundamentalScope(StrEnum):
    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"


class FundamentalTemporalSemantics(StrEnum):
    AVAILABILITY_DATE_CUTOFF = "availability_date_cutoff"


class FundamentalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_cnpj: str
    instrument_id: str | None = None
    reference_date: date
    availability_date: date
    document_type: FundamentalDocumentType
    scope: FundamentalScope
    period_label: str
    metric: str
    value: float = Field(allow_inf_nan=False)
    value_unit: FundamentalUnit
    currency: str | None = None
    is_derived: bool = False
    source_code: str
    ingestion_batch_id: str | None = None

    @model_validator(mode="after")
    def _validate_unit_currency(self):
        monetary = self.value_unit in (FundamentalUnit.BRL, FundamentalUnit.BRL_PER_SHARE)
        if monetary and not self.currency:
            raise ValueError("fundamento monetário exige currency")
        if not monetary and self.currency is not None:
            raise ValueError("currency só é válida para brl/brl_per_share")
        if self.availability_date < self.reference_date:
            raise ValueError("availability_date não pode anteceder reference_date")
        if not math.isfinite(self.value):
            raise ValueError("fundamento não pode ser NaN/inf")
        return self


class FundamentalProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str = "market.fundamentals"
    source_codes: list[str] = Field(default_factory=list)
    ingestion_batch_ids: list[str] = Field(default_factory=list)
    cutoff_date: date
    temporal_semantics: FundamentalTemporalSemantics = (
        FundamentalTemporalSemantics.AVAILABILITY_DATE_CUTOFF
    )
    warnings: list[str] = Field(default_factory=list)


class ResolvedFundamentals(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_cnpj: str
    scope: FundamentalScope
    document_type: FundamentalDocumentType
    records: list[FundamentalRecord] = Field(default_factory=list)
    provenance: FundamentalProvenance


class CompanyIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    ticker: str | None = None
    name: str
    issuer_id: str | None = None
    company_cnpj: str | None = None
    is_in_universe: bool


class EquityInstrument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    ticker: str | None = None
    name: str
    is_in_universe: bool


class FundamentalsReader(Protocol):
    async def read_fundamentals(
        self,
        company_cnpj: str,
        *,
        cutoff: date,
        scope: FundamentalScope,
        document_type: FundamentalDocumentType,
        metrics: tuple[str, ...] | None = None,
    ) -> list[FundamentalRecord]: ...


class PostgresFundamentalsReader:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def read_fundamentals(
        self,
        company_cnpj: str,
        *,
        cutoff: date,
        scope: FundamentalScope,
        document_type: FundamentalDocumentType,
        metrics: tuple[str, ...] | None = None,
    ) -> list[FundamentalRecord]:
        metric_clause = ""
        args: list[object] = [company_cnpj, cutoff, cutoff, scope.value, document_type.value]
        if metrics:
            metric_clause = " and metric = any(%s)"
            args.append(list(metrics))
        cur = await self.conn.execute(
            f"""select company_cnpj::text, instrument_id::text, reference_date, availability_date,
                       document_type, scope, period_label, metric::text, value::float,
                       value_unit, currency::text, is_derived, source_code::text,
                       ingestion_batch_id::text
                  from market.fundamentals
                 where company_cnpj = %s
                   and availability_date <= %s
                   and reference_date <= %s
                   and scope = %s
                   and document_type = %s
                   {metric_clause}
                 order by metric, instrument_id nulls first, reference_date, availability_date""",
            tuple(args),
        )
        return [
            FundamentalRecord(
                company_cnpj=cnpj,
                instrument_id=instrument_id,
                reference_date=reference_date,
                availability_date=availability_date,
                document_type=document_type_value,
                scope=scope_value,
                period_label=period_label,
                metric=metric,
                value=value,
                value_unit=value_unit,
                currency=currency,
                is_derived=is_derived,
                source_code=source_code,
                ingestion_batch_id=batch,
            )
            for (
                cnpj,
                instrument_id,
                reference_date,
                availability_date,
                document_type_value,
                scope_value,
                period_label,
                metric,
                value,
                value_unit,
                currency,
                is_derived,
                source_code,
                batch,
            ) in await cur.fetchall()
        ]


class FundamentalsLoader:
    """Seleciona o último vintage que já existia no cutoff, sem fallback silencioso de scope."""

    def __init__(self, reader: FundamentalsReader):
        self.reader = reader

    async def load_latest_annual(
        self,
        company_cnpj: str,
        *,
        cutoff: date,
        scope: FundamentalScope = FundamentalScope.CONSOLIDATED,
        metrics: tuple[str, ...] | None = None,
    ) -> ResolvedFundamentals:
        rows = await self.reader.read_fundamentals(
            company_cnpj,
            cutoff=cutoff,
            scope=scope,
            document_type=FundamentalDocumentType.DFP,
            metrics=metrics,
        )
        valid = [
            r for r in rows
            if r.company_cnpj == company_cnpj
            and r.scope == scope
            and r.document_type == FundamentalDocumentType.DFP
            and r.reference_date <= cutoff
            and r.availability_date <= cutoff
        ]
        latest: dict[tuple[str, str | None], FundamentalRecord] = {}
        for row in valid:
            key = (row.metric, row.instrument_id)
            current = latest.get(key)
            if current is None or (row.reference_date, row.availability_date) > (
                current.reference_date,
                current.availability_date,
            ):
                latest[key] = row

        selected = sorted(
            latest.values(),
            key=lambda r: (r.metric, r.instrument_id or "", r.reference_date, r.availability_date),
        )
        warnings = []
        if any(r.value_unit == FundamentalUnit.RAW for r in selected):
            warnings.append(RAW_UNIT_UNUSABLE)
        return ResolvedFundamentals(
            company_cnpj=company_cnpj,
            scope=scope,
            document_type=FundamentalDocumentType.DFP,
            records=selected,
            provenance=FundamentalProvenance(
                source_codes=sorted({r.source_code for r in selected if r.source_code}),
                ingestion_batch_ids=sorted({r.ingestion_batch_id for r in selected if r.ingestion_batch_id}),
                cutoff_date=cutoff,
                warnings=warnings,
            ),
        )


def record_for(
    resolved: ResolvedFundamentals,
    metric: str,
    *,
    instrument_id: str | None = None,
) -> FundamentalRecord | None:
    for row in resolved.records:
        if row.metric == metric and row.instrument_id == instrument_id:
            return row
    return None


def records_for_metric(resolved: ResolvedFundamentals, metric: str) -> list[FundamentalRecord]:
    return [r for r in resolved.records if r.metric == metric]


async def company_identity_for_instrument(
    conn: AsyncConnection,
    instrument_id: str,
    *,
    cutoff: date,
) -> CompanyIdentity | None:
    cur = await conn.execute(
        """select i.id::text, i.ticker, i.name, i.issuer_id::text, iss.cnpj::text, i.is_in_universe
             from market.instruments i
             left join market.issuers iss on iss.id = i.issuer_id
            where i.id = %s""",
        (instrument_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    iid, ticker, name, issuer_id, issuer_cnpj, in_universe = row
    company_cnpj = issuer_cnpj
    if company_cnpj is None:
        cur = await conn.execute(
            """select company_cnpj::text
                 from market.fundamentals
                where instrument_id = %s and availability_date <= %s
                order by availability_date desc, reference_date desc
                limit 1""",
            (instrument_id, cutoff),
        )
        fallback = await cur.fetchone()
        if fallback is not None:
            company_cnpj = fallback[0]
    return CompanyIdentity(
        instrument_id=iid,
        ticker=ticker,
        name=name,
        issuer_id=issuer_id,
        company_cnpj=company_cnpj,
        is_in_universe=bool(in_universe),
    )


async def equity_instruments_for_company(
    conn: AsyncConnection,
    identity: CompanyIdentity,
) -> list[EquityInstrument]:
    if identity.issuer_id is None:
        return [
            EquityInstrument(
                instrument_id=identity.instrument_id,
                ticker=identity.ticker,
                name=identity.name,
                is_in_universe=identity.is_in_universe,
            )
        ]
    cur = await conn.execute(
        """select id::text, ticker, name, is_in_universe
             from market.instruments
            where issuer_id = %s and kind = 'acao'
            order by ticker nulls last, id""",
        (identity.issuer_id,),
    )
    rows = [
        EquityInstrument(instrument_id=iid, ticker=ticker, name=name, is_in_universe=bool(in_universe))
        for iid, ticker, name, in_universe in await cur.fetchall()
    ]
    return rows or [
        EquityInstrument(
            instrument_id=identity.instrument_id,
            ticker=identity.ticker,
            name=identity.name,
            is_in_universe=identity.is_in_universe,
        )
    ]
