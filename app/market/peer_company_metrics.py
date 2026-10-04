"""Carga batch de insumos canônicos para comparáveis company-level.

O módulo NÃO calcula valuation nem tendências. Ele reduz round-trips ao banco carregando
identidade/classes, fundamentos PIT e preços de várias companhias de uma vez e então reutiliza
os loaders canônicos sobre um reader em memória.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
from typing import Iterable

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from app.market import fundamental_history
from app.market import fundamentals
from app.market import snapshots


class PeerCompanyBatchConflict(RuntimeError):
    """Identidade company-level não pôde ser resolvida de forma inequívoca."""


class PeerCompanyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer_id: str
    representative_ticker: str


class PeerEquityClassBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    ticker: str | None = None
    name: str
    is_in_universe: bool
    price: snapshots.MarketPriceSnapshot | None = None


class PeerCompanyBatchResolved(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer_id: str
    issuer_name: str
    representative_ticker: str
    identity: fundamentals.CompanyIdentity
    classes: list[PeerEquityClassBatch] = Field(default_factory=list)
    latest_fundamentals: fundamentals.ResolvedFundamentals | None = None
    history: fundamental_history.ResolvedFundamentalHistory | None = None


class _MemoryFundamentalsReader:
    def __init__(self, rows: list[fundamentals.FundamentalRecord]):
        self._rows = rows

    async def read_fundamentals(
        self,
        company_cnpj: str,
        *,
        cutoff: date,
        scope: fundamentals.FundamentalScope,
        document_type: fundamentals.FundamentalDocumentType,
        metrics: tuple[str, ...] | None = None,
    ) -> list[fundamentals.FundamentalRecord]:
        wanted = set(metrics or ())
        return [
            row
            for row in self._rows
            if row.company_cnpj == company_cnpj
            and row.reference_date <= cutoff
            and row.availability_date <= cutoff
            and row.scope == scope
            and row.document_type == document_type
            and (not wanted or row.metric in wanted)
        ]


def _normalize_requests(
    requests: Iterable[PeerCompanyRequest],
) -> dict[str, PeerCompanyRequest]:
    by_issuer: dict[str, PeerCompanyRequest] = {}
    for request in requests:
        ticker = request.representative_ticker.strip().upper()
        normalized = PeerCompanyRequest(
            issuer_id=request.issuer_id,
            representative_ticker=ticker,
        )
        previous = by_issuer.get(request.issuer_id)
        if previous is not None and previous.representative_ticker != ticker:
            raise PeerCompanyBatchConflict(
                f"issuer_com_multiplos_representantes:{request.issuer_id}"
            )
        by_issuer[request.issuer_id] = normalized
    if not by_issuer:
        raise ValueError("peer_company_batch_sem_requests")
    return by_issuer


async def _instrument_rows(
    conn: AsyncConnection,
    issuer_ids: list[str],
) -> dict[str, list[tuple[str, str | None, str, bool, str, str | None]]]:
    cur = await conn.execute(
        """select i.issuer_id::text,
                  i.id::text,
                  i.ticker,
                  i.name,
                  i.is_in_universe,
                  iss.name,
                  iss.cnpj::text
             from market.instruments i
             join market.issuers iss on iss.id = i.issuer_id
            where i.kind = 'acao'
              and i.issuer_id = any(%s::uuid[])
            order by i.issuer_id, i.ticker nulls last, i.id""",
        (issuer_ids,),
    )
    grouped: dict[str, list[tuple[str, str | None, str, bool, str, str | None]]] = defaultdict(list)
    for issuer_id, iid, ticker, name, in_universe, issuer_name, issuer_cnpj in await cur.fetchall():
        grouped[issuer_id].append(
            (iid, ticker, name, bool(in_universe), issuer_name, issuer_cnpj)
        )
    return dict(grouped)


async def _fallback_cnpjs(
    conn: AsyncConnection,
    instrument_ids: list[str],
    *,
    cutoff: date,
) -> dict[str, str]:
    if not instrument_ids:
        return {}
    cur = await conn.execute(
        """select distinct on (instrument_id)
                  instrument_id::text, company_cnpj::text
             from market.fundamentals
            where instrument_id = any(%s::uuid[])
              and availability_date <= %s
              and reference_date <= %s
            order by instrument_id, availability_date desc, reference_date desc""",
        (instrument_ids, cutoff, cutoff),
    )
    return {iid: cnpj for iid, cnpj in await cur.fetchall()}


async def _fundamental_rows(
    conn: AsyncConnection,
    company_cnpjs: list[str],
    *,
    cutoff: date,
    metrics: tuple[str, ...],
) -> list[fundamentals.FundamentalRecord]:
    if not company_cnpjs:
        return []
    cur = await conn.execute(
        """select company_cnpj::text,
                  instrument_id::text,
                  reference_date,
                  availability_date,
                  document_type,
                  scope,
                  period_label,
                  metric::text,
                  value::float,
                  value_unit,
                  currency::text,
                  is_derived,
                  source_code::text,
                  ingestion_batch_id::text
             from market.fundamentals
            where company_cnpj = any(%s::text[])
              and availability_date <= %s
              and reference_date <= %s
              and scope = 'consolidated'
              and document_type = 'DFP'
              and metric = any(%s::text[])
            order by company_cnpj, metric, instrument_id nulls first,
                     reference_date, availability_date""",
        (company_cnpjs, cutoff, cutoff, list(metrics)),
    )
    return [
        fundamentals.FundamentalRecord(
            company_cnpj=cnpj,
            instrument_id=instrument_id,
            reference_date=reference_date,
            availability_date=availability_date,
            document_type=document_type,
            scope=scope,
            period_label=period_label,
            metric=metric,
            value=value,
            value_unit=value_unit,
            currency=currency,
            is_derived=is_derived,
            source_code=source_code,
            ingestion_batch_id=batch_id,
        )
        for (
            cnpj,
            instrument_id,
            reference_date,
            availability_date,
            document_type,
            scope,
            period_label,
            metric,
            value,
            value_unit,
            currency,
            is_derived,
            source_code,
            batch_id,
        ) in await cur.fetchall()
    ]


async def _latest_price_rows(
    conn: AsyncConnection,
    instrument_ids: list[str],
    *,
    cutoff: date,
) -> dict[str, snapshots.MarketPriceSnapshot]:
    if not instrument_ids:
        return {}
    cur = await conn.execute(
        """with latest as (
               select instrument_id, max(price_date) as price_date
                 from market.prices
                where instrument_id = any(%s::uuid[])
                  and kind = 'close'
                  and price_date <= %s
                group by instrument_id
           )
           select p.instrument_id::text,
                  p.price_date,
                  p.value::float,
                  p.currency::text,
                  p.source_code::text,
                  p.ingestion_batch_id::text
             from market.prices p
             join latest l
               on l.instrument_id = p.instrument_id
              and l.price_date = p.price_date
            where p.kind = 'close'
            order by p.instrument_id, p.source_code""",
        (instrument_ids, cutoff),
    )
    grouped: dict[str, list[tuple[date, float, str | None, str | None, str | None]]] = defaultdict(list)
    for iid, price_date, value, currency, source_code, batch_id in await cur.fetchall():
        grouped[iid].append((price_date, value, currency, source_code, batch_id))

    out: dict[str, snapshots.MarketPriceSnapshot] = {}
    for iid, rows in grouped.items():
        price_date = rows[0][0]
        values = {(float(value), currency or "BRL") for _day, value, currency, _source, _batch in rows}
        warnings: list[str] = []
        if len(values) != 1:
            value_out = None
            currency_out = None
            warnings.append(snapshots.AMBIGUOUS_PRICE_SOURCE)
        else:
            value_out, currency_out = next(iter(values))
            if not math.isfinite(value_out) or value_out <= 0:
                raise ValueError("preço bruto inválido no snapshot")
            if currency_out != "BRL":
                warnings.append(snapshots.NON_BRL_PRICE)
        out[iid] = snapshots.MarketPriceSnapshot(
            instrument_id=iid,
            price_date=price_date,
            value=value_out,
            currency=currency_out,
            source_codes=sorted(
                {source for _day, _value, _currency, source, _batch in rows if source}
            ),
            ingestion_batch_ids=sorted(
                {batch for _day, _value, _currency, _source, batch in rows if batch}
            ),
            warnings=warnings,
        )
    return out


async def load_peer_company_metrics(
    conn: AsyncConnection,
    requests: Iterable[PeerCompanyRequest],
    *,
    cutoff: date,
    valuation_metrics: tuple[str, ...],
    trend_metrics: tuple[str, ...],
    trend_periods: int = 2,
) -> dict[str, PeerCompanyBatchResolved]:
    """Carrega várias companhias em lote e reutiliza os loaders canônicos em memória."""
    if trend_periods < 2 or trend_periods > 10:
        raise ValueError("trend_periods deve ficar entre 2 e 10")

    by_issuer = _normalize_requests(requests)
    issuer_ids = sorted(by_issuer)
    instruments = await _instrument_rows(conn, issuer_ids)

    representative_rows: dict[
        str, tuple[str, str | None, str, bool, str, str | None]
    ] = {}
    missing_representatives: list[str] = []
    for issuer_id, request in by_issuer.items():
        rows = instruments.get(issuer_id, [])
        matches = [
            row
            for row in rows
            if (row[1] or "").strip().upper() == request.representative_ticker
        ]
        if len(matches) != 1:
            missing_representatives.append(f"{issuer_id}:{request.representative_ticker}")
            continue
        representative_rows[issuer_id] = matches[0]
    if missing_representatives:
        raise PeerCompanyBatchConflict(
            "representante_peer_nao_resolvido:" + ",".join(sorted(missing_representatives))
        )

    fallback_needed = [
        row[0]
        for row in representative_rows.values()
        if row[5] is None
    ]
    cnpj_fallback = await _fallback_cnpjs(conn, fallback_needed, cutoff=cutoff)

    cnpj_by_issuer: dict[str, str | None] = {}
    for issuer_id, row in representative_rows.items():
        representative_iid = row[0]
        cnpj_by_issuer[issuer_id] = row[5] or cnpj_fallback.get(representative_iid)

    all_metrics = list(dict.fromkeys([*valuation_metrics, *trend_metrics]))
    if "ebitda" in trend_metrics and "ebitda_derived" not in all_metrics:
        all_metrics.append("ebitda_derived")
    company_cnpjs = sorted({cnpj for cnpj in cnpj_by_issuer.values() if cnpj})
    raw_fundamentals = await _fundamental_rows(
        conn,
        company_cnpjs,
        cutoff=cutoff,
        metrics=tuple(all_metrics),
    )
    reader = _MemoryFundamentalsReader(raw_fundamentals)

    class_ids = sorted(
        {
            row[0]
            for rows in instruments.values()
            for row in rows
        }
    )
    prices = await _latest_price_rows(conn, class_ids, cutoff=cutoff)

    out: dict[str, PeerCompanyBatchResolved] = {}
    for issuer_id, request in by_issuer.items():
        representative = representative_rows[issuer_id]
        iid, ticker, name, in_universe, issuer_name, _issuer_cnpj = representative
        company_cnpj = cnpj_by_issuer[issuer_id]
        identity = fundamentals.CompanyIdentity(
            instrument_id=iid,
            ticker=ticker,
            name=name,
            issuer_id=issuer_id,
            company_cnpj=company_cnpj,
            is_in_universe=in_universe,
        )
        classes = [
            PeerEquityClassBatch(
                instrument_id=class_iid,
                ticker=class_ticker,
                name=class_name,
                is_in_universe=class_in_universe,
                price=prices.get(class_iid),
            )
            for (
                class_iid,
                class_ticker,
                class_name,
                class_in_universe,
                _row_issuer_name,
                _row_issuer_cnpj,
            ) in instruments.get(issuer_id, [])
        ]

        latest = None
        history = None
        if identity.is_in_universe and company_cnpj:
            latest = await fundamentals.FundamentalsLoader(reader).load_latest_annual(
                company_cnpj,
                cutoff=cutoff,
                scope=fundamentals.FundamentalScope.CONSOLIDATED,
                metrics=valuation_metrics,
            )
            history = await fundamental_history.FundamentalHistoryLoader(reader).load_annual_history(
                company_cnpj,
                cutoff=cutoff,
                scope=fundamentals.FundamentalScope.CONSOLIDATED,
                metrics=tuple(
                    list(trend_metrics)
                    + (["ebitda_derived"] if "ebitda" in trend_metrics else [])
                ),
                periods=trend_periods,
            )

        out[issuer_id] = PeerCompanyBatchResolved(
            issuer_id=issuer_id,
            issuer_name=issuer_name,
            representative_ticker=request.representative_ticker,
            identity=identity,
            classes=classes,
            latest_fundamentals=latest,
            history=history,
        )
    return out
