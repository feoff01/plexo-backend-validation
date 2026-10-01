"""Coverage read-only do snapshot Economatica contra o catálogo Plexo.

Este módulo NÃO ingere dados. Ele mede, por ticker exato, quais registros do export
Economatica conseguem ser resolvidos em ``market.instruments``/``market.issuers`` e
qual fração dos emissores com ação ``is_in_universe`` é coberta pelo snapshot.

A unidade de decisão para peers é emissor, não ticker: PETR3/PETR4 não contam como
duas companhias. Resultados de banco descartável/dev não devem ser apresentados como
coverage de produção.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from app.market.economatica_sector_source import EconomaticaSectorRecord


class EconomaticaCoverageConflict(RuntimeError):
    """O catálogo ou a entrada não permitem identidade exata e inequívoca."""


class EconomaticaCatalogCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records_received: int
    economic_sector_filled: int
    subsector_filled: int

    matched_tickers: int
    unmatched_tickers: list[str] = Field(default_factory=list)
    tickers_without_issuer: list[str] = Field(default_factory=list)

    matched_issuers: int
    matched_issuers_in_universe: int
    issuers_outside_universe: int

    eligible_universe_issuers: int
    covered_universe_issuers: int
    uncovered_universe_issuers: int
    universe_coverage_pct: Decimal | None = None

    unmatched_ticker_examples: list[str] = Field(default_factory=list)
    ticker_without_issuer_examples: list[str] = Field(default_factory=list)
    issuer_outside_universe_examples: list[str] = Field(default_factory=list)
    uncovered_universe_examples: list[str] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)


def _normalize_records(
    records: Iterable[EconomaticaSectorRecord],
) -> dict[str, EconomaticaSectorRecord]:
    by_ticker: dict[str, EconomaticaSectorRecord] = {}
    for record in records:
        ticker = record.ticker.strip().upper()
        if not ticker:
            continue
        previous = by_ticker.get(ticker)
        if previous is not None and previous.key != record.key:
            raise EconomaticaCoverageConflict(f"ticker_setorial_divergente:{ticker}")
        by_ticker[ticker] = EconomaticaSectorRecord(
            ticker=ticker,
            economic_sector=record.economic_sector,
            subsector=record.subsector,
        )
    if not by_ticker:
        raise ValueError("coverage_economatica_sem_tickers")
    return by_ticker


async def measure_economatica_catalog_coverage(
    conn: AsyncConnection,
    records: Iterable[EconomaticaSectorRecord],
    *,
    max_examples: int = 20,
) -> EconomaticaCatalogCoverage:
    """Mede coverage por SELECTs בלבד, sem criar lote ou gravar classificação."""
    by_ticker = _normalize_records(records)
    tickers = sorted(by_ticker)

    cur = await conn.execute(
        """select upper(i.ticker) as ticker,
                  i.id::text,
                  i.issuer_id::text,
                  i.is_in_universe,
                  coalesce(iss.name, i.name) as issuer_or_instrument_name
             from market.instruments i
             left join market.issuers iss on iss.id = i.issuer_id
            where i.kind = 'acao'
              and i.ticker is not null
              and upper(i.ticker) = any(%s::text[])
            order by upper(i.ticker), i.id""",
        (tickers,),
    )
    rows = await cur.fetchall()

    rows_by_ticker: dict[str, list[tuple[str, str | None, bool, str]]] = defaultdict(list)
    for ticker, instrument_id, issuer_id, is_in_universe, name in rows:
        rows_by_ticker[ticker].append(
            (instrument_id, issuer_id, bool(is_in_universe), name)
        )

    ambiguous = sorted(t for t, values in rows_by_ticker.items() if len(values) > 1)
    if ambiguous:
        raise EconomaticaCoverageConflict(
            "ticker_ambiguo_no_catalogo:" + ",".join(ambiguous[:max_examples])
        )

    matched_tickers_set = set(rows_by_ticker)
    unmatched = sorted(set(tickers) - matched_tickers_set)
    without_issuer = sorted(
        ticker
        for ticker, values in rows_by_ticker.items()
        if values[0][1] is None
    )

    matched_issuer_names: dict[str, str] = {}
    for ticker, values in rows_by_ticker.items():
        _instrument_id, issuer_id, _in_universe, name = values[0]
        if issuer_id is not None:
            matched_issuer_names.setdefault(issuer_id, name)

    cur = await conn.execute(
        """select i.issuer_id::text, min(iss.name) as issuer_name
             from market.instruments i
             join market.issuers iss on iss.id = i.issuer_id
            where i.kind = 'acao'
              and i.is_in_universe
              and i.issuer_id is not null
            group by i.issuer_id
            order by min(iss.name), i.issuer_id"""
    )
    eligible_rows = await cur.fetchall()
    eligible_names = {issuer_id: name for issuer_id, name in eligible_rows}
    eligible_ids = set(eligible_names)
    matched_ids = set(matched_issuer_names)
    covered_ids = matched_ids & eligible_ids
    outside_ids = matched_ids - eligible_ids
    uncovered_ids = eligible_ids - covered_ids

    eligible_count = len(eligible_ids)
    coverage_pct = (
        None
        if eligible_count == 0
        else (Decimal(len(covered_ids)) * Decimal("100") / Decimal(eligible_count)).quantize(
            Decimal("0.01")
        )
    )

    warnings: list[str] = []
    if unmatched:
        warnings.append("economatica_tickers_nao_encontrados")
    if without_issuer:
        warnings.append("economatica_tickers_sem_issuer")
    if outside_ids:
        warnings.append("economatica_issuers_fora_do_universo")
    if eligible_count == 0:
        warnings.append("universo_acoes_sem_issuer_vazio")
    elif uncovered_ids:
        warnings.append("economatica_cobertura_universo_incompleta")

    return EconomaticaCatalogCoverage(
        records_received=len(tickers),
        economic_sector_filled=sum(
            1 for record in by_ticker.values() if record.economic_sector is not None
        ),
        subsector_filled=sum(1 for record in by_ticker.values() if record.subsector is not None),
        matched_tickers=len(matched_tickers_set),
        unmatched_tickers=unmatched,
        tickers_without_issuer=without_issuer,
        matched_issuers=len(matched_ids),
        matched_issuers_in_universe=len(covered_ids),
        issuers_outside_universe=len(outside_ids),
        eligible_universe_issuers=eligible_count,
        covered_universe_issuers=len(covered_ids),
        uncovered_universe_issuers=len(uncovered_ids),
        universe_coverage_pct=coverage_pct,
        unmatched_ticker_examples=unmatched[:max_examples],
        ticker_without_issuer_examples=without_issuer[:max_examples],
        issuer_outside_universe_examples=[
            matched_issuer_names[issuer_id]
            for issuer_id in sorted(outside_ids, key=lambda x: matched_issuer_names[x])[:max_examples]
        ],
        uncovered_universe_examples=[
            eligible_names[issuer_id]
            for issuer_id in sorted(uncovered_ids, key=lambda x: eligible_names[x])[:max_examples]
        ],
        warnings=warnings,
    )
