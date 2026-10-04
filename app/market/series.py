"""Camada canônica de séries de mercado para o Analista (FQ1).

Objetivo: separar a SEMÂNTICA da série (cutoff, base de preço, calendário, qualidade e
proveniência) da fonte física. Engines quantitativos devem depender de ``MarketSeriesLoader`` /
``SeriesReader`` — nunca consultar ``market.prices`` diretamente.

A primeira implementação física é PostgreSQL. Um leitor de Parquet/object storage pode ser
adicionado depois sem mudar os engines.

Atenção à semântica temporal:
- ``observation_date_cutoff`` limita a série pela DATA DA OBSERVAÇÃO. Isso evita olhar observações
  futuras, mas NÃO afirma vintage point-in-time: o schema de preços/índices não guarda quando cada
  observação/revisão se tornou disponível ao mercado. Backfills históricos continuam visíveis.
- ``adjusted_close`` usa ``market.v_precos_ajustados``, que é RETROSPECTIVA: o fator histórico
  incorpora corporate actions que hoje existem no banco. Como ``market.corporate_actions`` ainda
  não possui announcement/availability date, não há como provar quais ajustes eram conhecidos num
  cutoff histórico. Por isso adjusted close exige ``retrospective_as_known_now``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from enum import StrEnum
from typing import Protocol

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field


CALENDAR_FALLBACK_FROM_PRICES = "calendar_fallback_from_prices"
ADJUSTED_CLOSE_RETROSPECTIVE = "adjusted_close_retrospective"


class PriceBasis(StrEnum):
    RAW_CLOSE = "raw_close"
    ADJUSTED_CLOSE = "adjusted_close"


class TemporalSemantics(StrEnum):
    OBSERVATION_DATE_CUTOFF = "observation_date_cutoff"
    RETROSPECTIVE_AS_KNOWN_NOW = "retrospective_as_known_now"


def temporal_semantics_for_price_basis(basis: PriceBasis | str) -> TemporalSemantics:
    """Semântica temporal canônica derivada da base; não é escolha livre da LLM."""
    resolved = PriceBasis(basis)
    if resolved == PriceBasis.ADJUSTED_CLOSE:
        return TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    return TemporalSemantics.OBSERVATION_DATE_CUTOFF


class AdjustedCloseRequiresRetrospective(ValueError):
    """Pedido incompatível com o schema atual de corporate actions.

    Não fazer fallback silencioso para raw_close: isso mudaria a pergunta quantitativa sem o
    chamador perceber. O chamador deve escolher explicitamente outra semântica/base.
    """


class DuplicateSeriesDates(ValueError):
    """Reader violou o contrato de uma observação canônica por data."""


class InvalidSeriesValue(ValueError):
    """Preço inválido para cálculo de retorno (zero/negativo ou não finito)."""


class MarketPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    valor: float


class PriceRecord(BaseModel):
    """Linha física já desambiguada para uma data/fonte."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    valor: float
    currency: str = "BRL"
    source_code: str
    ingestion_batch_id: str | None = None


class IndexDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    unit: str
    source_code: str


class IndexRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    valor: float
    ingestion_batch_id: str | None = None


class UnknownIndex(ValueError):
    """Código ausente de market.index_definitions."""


class CalendarRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    is_business_day: bool
    source_code: str
    ingestion_batch_id: str | None = None


class CalendarSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    calendar_name: str
    business_days: list[date] = Field(default_factory=list)
    source: str
    fallback_used: bool = False
    ingestion_batch_ids: list[str] = Field(default_factory=list)


class SeriesQuality(BaseModel):
    """Qualidade factual; suficiência estatística continua sendo decisão de cada tool/método."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    observations: int
    first_date: date | None = None
    last_date: date | None = None
    stale_days: int | None = None
    missing_dates: list[date] = Field(default_factory=list)
    unexpected_dates: list[date] = Field(default_factory=list)
    coverage_ratio: float | None = None
    calendar_source: str | None = None
    calendar_fallback_used: bool = False


class SeriesProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset: str
    source_codes: list[str] = Field(default_factory=list)
    ingestion_batch_ids: list[str] = Field(default_factory=list)
    calendar_ingestion_batch_ids: list[str] = Field(default_factory=list)
    price_basis: PriceBasis | None = None
    temporal_semantics: TemporalSemantics
    cutoff_date: date
    warnings: list[str] = Field(default_factory=list)


class ResolvedMarketSeries(BaseModel):
    """Série canônica, seja preço de instrumento ou índice/taxa."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    instrument_id: str | None = None
    index_code: str | None = None
    unit: str | None = None
    currency: str | None = None
    points: list[MarketPoint] = Field(default_factory=list)
    quality: SeriesQuality
    provenance: SeriesProvenance


class AlignedValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    left: float
    right: float


class SeriesReader(Protocol):
    async def read_prices(
        self,
        instrument_id: str,
        *,
        de: date,
        ate: date,
        cutoff: date,
        basis: PriceBasis,
    ) -> list[PriceRecord]: ...

    async def read_index_definition(self, code: str) -> IndexDefinition | None: ...

    async def read_index_values(
        self,
        code: str,
        *,
        de: date,
        ate: date,
        cutoff: date,
    ) -> list[IndexRecord]: ...

    async def read_calendar(
        self,
        calendar_name: str,
        *,
        de: date,
        ate: date,
        cutoff: date,
    ) -> list[CalendarRecord]: ...

    async def read_price_calendar_fallback(
        self,
        *,
        de: date,
        ate: date,
        cutoff: date,
    ) -> list[date]: ...


class PostgresSeriesReader:
    """Leitor físico atual. Queries são read-only e respeitam cutoff de observação."""

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def read_prices(
        self,
        instrument_id: str,
        *,
        de: date,
        ate: date,
        cutoff: date,
        basis: PriceBasis,
    ) -> list[PriceRecord]:
        if basis == PriceBasis.RAW_CLOSE:
            cur = await self.conn.execute(
                """select distinct on (price_date)
                          price_date, value::float, currency::text, source_code::text,
                          ingestion_batch_id::text
                     from market.prices
                    where instrument_id = %s and kind = 'close'
                      and price_date between %s and %s and price_date <= %s
                    order by price_date, source_code""",
                (instrument_id, de, ate, cutoff),
            )
        else:
            # A view não expõe ingestion_batch_id; juntamos de volta à linha de preço crua que
            # originou aquela observação. A semântica RETROSPECTIVA é validada pelo loader.
            cur = await self.conn.execute(
                """select distinct on (v.price_date)
                          v.price_date, v.close_adj::float, v.currency::text, v.source_code::text,
                          p.ingestion_batch_id::text
                     from market.v_precos_ajustados v
                     left join market.prices p
                       on p.instrument_id = v.instrument_id
                      and p.price_date = v.price_date
                      and p.kind = 'close'
                      and p.source_code = v.source_code
                    where v.instrument_id = %s
                      and v.price_date between %s and %s and v.price_date <= %s
                    order by v.price_date, v.source_code""",
                (instrument_id, de, ate, cutoff),
            )
        return [
            PriceRecord(data=d, valor=v, currency=currency or "BRL", source_code=source,
                        ingestion_batch_id=batch)
            for d, v, currency, source, batch in await cur.fetchall()
        ]

    async def read_index_definition(self, code: str) -> IndexDefinition | None:
        cur = await self.conn.execute(
            "select code::text, unit, coalesce(source_code::text, '') "
            "from market.index_definitions where code = %s",
            (code,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return IndexDefinition(code=row[0], unit=row[1], source_code=row[2])

    async def read_index_values(
        self,
        code: str,
        *,
        de: date,
        ate: date,
        cutoff: date,
    ) -> list[IndexRecord]:
        cur = await self.conn.execute(
            """select value_date, value::float, ingestion_batch_id::text
                 from market.index_values
                where index_code = %s and value_date between %s and %s and value_date <= %s
                order by value_date""",
            (code, de, ate, cutoff),
        )
        return [IndexRecord(data=d, valor=v, ingestion_batch_id=batch)
                for d, v, batch in await cur.fetchall()]

    async def read_calendar(
        self,
        calendar_name: str,
        *,
        de: date,
        ate: date,
        cutoff: date,
    ) -> list[CalendarRecord]:
        # Lemos dias úteis E não úteis. Se só consultássemos os úteis, uma janela composta apenas
        # por fim de semana/feriado seria indistinguível de "calendário não carregado" e ativaria
        # o fallback errado.
        cur = await self.conn.execute(
            """select calendar_date, is_business_day, source_code::text, ingestion_batch_id::text
                 from market.trading_calendar
                where calendar_name = %s
                  and calendar_date between %s and %s and calendar_date <= %s
                order by calendar_date""",
            (calendar_name, de, ate, cutoff),
        )
        return [
            CalendarRecord(data=d, is_business_day=business, source_code=source,
                           ingestion_batch_id=batch)
            for d, business, source, batch in await cur.fetchall()
        ]

    async def read_price_calendar_fallback(
        self,
        *,
        de: date,
        ate: date,
        cutoff: date,
    ) -> list[date]:
        cur = await self.conn.execute(
            """select distinct p.price_date
                 from market.prices p
                 join market.instruments i
                   on i.id = p.instrument_id and i.is_in_universe
                where p.kind = 'close'
                  and p.price_date between %s and %s and p.price_date <= %s
                order by 1""",
            (de, ate, cutoff),
        )
        return [row[0] for row in await cur.fetchall()]


@dataclass
class MarketSeriesLoader:
    reader: SeriesReader
    calendar_name: str = "b3"

    def __post_init__(self) -> None:
        self._calendar_cache: dict[tuple[str, date, date, date], CalendarSnapshot] = {}

    async def load_calendar(self, *, de: date, ate: date, cutoff: date) -> CalendarSnapshot:
        de, ate = _bounded_window(de, ate, cutoff)
        if de > ate:
            return CalendarSnapshot(
                calendar_name=self.calendar_name, business_days=[], source="empty_window", fallback_used=False
            )
        chave = (self.calendar_name, de, ate, cutoff)
        if chave in self._calendar_cache:
            return self._calendar_cache[chave]

        rows = await self.reader.read_calendar(self.calendar_name, de=de, ate=ate, cutoff=cutoff)
        # A tabela foi desenhada como calendário DIÁRIO (fim de semana também é linha, com
        # is_business_day=false). Uma carga parcial não pode ser confundida com calendário
        # completo: isso esconderia lacunas. Só confiamos nela se toda data civil da janela está
        # representada.
        cobertura_completa = len({r.data for r in rows}) == (ate - de).days + 1
        if rows and cobertura_completa:
            snap = CalendarSnapshot(
                calendar_name=self.calendar_name,
                business_days=[r.data for r in rows if r.is_business_day],
                source="market.trading_calendar",
                fallback_used=False,
                ingestion_batch_ids=sorted({r.ingestion_batch_id for r in rows if r.ingestion_batch_id}),
            )
        else:
            # Fallback temporário/compatível com F5. Ele é EXPLÍCITO na provenance/quality; quando o
            # calendário oficial estiver ingerido para a janela, esta branch deixa de ser usada.
            datas = await self.reader.read_price_calendar_fallback(de=de, ate=ate, cutoff=cutoff)
            snap = CalendarSnapshot(
                calendar_name=self.calendar_name,
                business_days=sorted(set(datas)),
                source="market.prices:universe_fallback",
                fallback_used=True,
            )
        self._calendar_cache[chave] = snap
        return snap

    async def load_index(
        self,
        code: str,
        *,
        de: date,
        ate: date,
        cutoff: date,
        include_calendar: bool = False,
    ) -> ResolvedMarketSeries:
        de, ate = _bounded_window(de, ate, cutoff)
        definicao = await self.reader.read_index_definition(code)
        if definicao is None:
            raise UnknownIndex(code)
        if de > ate:
            rows: list[IndexRecord] = []
        else:
            rows = await self.reader.read_index_values(code, de=de, ate=ate, cutoff=cutoff)
            rows = _validated_index_rows(rows)
        calendario = await self.load_calendar(de=de, ate=ate, cutoff=cutoff) if include_calendar else None
        pontos = [MarketPoint(data=r.data, valor=r.valor) for r in rows]
        quality = quality_for_points(pontos, calendario, cutoff=cutoff)
        warnings = ([CALENDAR_FALLBACK_FROM_PRICES]
                    if calendario is not None and calendario.fallback_used else [])
        return ResolvedMarketSeries(
            code=definicao.code,
            index_code=definicao.code,
            unit=definicao.unit,
            points=pontos,
            quality=quality,
            provenance=SeriesProvenance(
                dataset="market.index_values",
                source_codes=[definicao.source_code] if definicao.source_code else [],
                ingestion_batch_ids=sorted({r.ingestion_batch_id for r in rows if r.ingestion_batch_id}),
                calendar_ingestion_batch_ids=(calendario.ingestion_batch_ids if calendario is not None else []),
                price_basis=None,
                temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
                cutoff_date=cutoff,
                warnings=warnings,
            ),
        )

    async def load_prices(
        self,
        instrument_id: str,
        *,
        code: str,
        de: date,
        ate: date,
        cutoff: date,
        basis: PriceBasis = PriceBasis.RAW_CLOSE,
        temporal_semantics: TemporalSemantics = TemporalSemantics.OBSERVATION_DATE_CUTOFF,
        include_calendar: bool = True,
    ) -> ResolvedMarketSeries:
        de, ate = _bounded_window(de, ate, cutoff)
        if basis == PriceBasis.ADJUSTED_CLOSE and temporal_semantics == TemporalSemantics.OBSERVATION_DATE_CUTOFF:
            raise AdjustedCloseRequiresRetrospective(
                "adjusted_close exige retrospective_as_known_now enquanto corporate_actions não tiver "
                "announcement/availability date"
            )

        if de > ate:
            rows: list[PriceRecord] = []
        else:
            rows = await self.reader.read_prices(
                instrument_id, de=de, ate=ate, cutoff=cutoff, basis=basis,
            )
            rows = _validated_rows(rows)
        calendario = await self.load_calendar(de=de, ate=ate, cutoff=cutoff) if include_calendar else None
        pontos = [MarketPoint(data=r.data, valor=r.valor) for r in rows]
        quality = quality_for_points(pontos, calendario, cutoff=cutoff)

        warnings: list[str] = []
        if calendario is not None and calendario.fallback_used:
            warnings.append(CALENDAR_FALLBACK_FROM_PRICES)
        if basis == PriceBasis.ADJUSTED_CLOSE:
            warnings.append(ADJUSTED_CLOSE_RETROSPECTIVE)

        return ResolvedMarketSeries(
            code=code,
            instrument_id=instrument_id,
            currency=_single_currency(rows),
            points=pontos,
            quality=quality,
            provenance=SeriesProvenance(
                dataset=("market.prices" if basis == PriceBasis.RAW_CLOSE else "market.v_precos_ajustados"),
                source_codes=sorted({r.source_code for r in rows}),
                ingestion_batch_ids=sorted({r.ingestion_batch_id for r in rows if r.ingestion_batch_id}),
                calendar_ingestion_batch_ids=(calendario.ingestion_batch_ids if calendario is not None else []),
                price_basis=basis,
                temporal_semantics=temporal_semantics,
                cutoff_date=cutoff,
                warnings=warnings,
            ),
        )


def quality_for_points(points: list[MarketPoint], calendar: CalendarSnapshot | None, *, cutoff: date) -> SeriesQuality:
    datas = [p.data for p in points]
    first = datas[0] if datas else None
    last = datas[-1] if datas else None
    expected = ([d for d in calendar.business_days if first is not None and last is not None and first <= d <= last]
                if calendar is not None else [])
    presentes = set(datas)
    missing = [d for d in expected if d not in presentes]
    expected_set = set(expected)
    unexpected = ([d for d in datas if d not in expected_set] if calendar is not None and first is not None else [])
    coverage = None if not expected else (len(expected) - len(missing)) / len(expected)
    return SeriesQuality(
        observations=len(points),
        first_date=first,
        last_date=last,
        stale_days=None if last is None else (cutoff - last).days,
        missing_dates=missing,
        unexpected_dates=unexpected,
        coverage_ratio=coverage,
        calendar_source=calendar.source if calendar is not None else None,
        calendar_fallback_used=calendar.fallback_used if calendar is not None else False,
    )


def align_values(left: ResolvedMarketSeries, right: ResolvedMarketSeries) -> list[AlignedValue]:
    """Alinha NÍVEIS pela interseção de datas. Retornos/lag pertencem ao Quant Core (FQ2)."""
    a = {p.data: p.valor for p in left.points}
    b = {p.data: p.valor for p in right.points}
    return [AlignedValue(data=d, left=a[d], right=b[d]) for d in sorted(set(a) & set(b))]


def _bounded_window(de: date, ate: date, cutoff: date) -> tuple[date, date]:
    # NÃO mover `de` para trás quando ele estiver depois do cutoff: isso introduziria uma
    # observação que o chamador não pediu. Janela invertida significa série vazia.
    return de, min(ate, cutoff)


def _validated_rows(rows: list[PriceRecord]) -> list[PriceRecord]:
    ordenadas = sorted(rows, key=lambda r: r.data)
    datas = [r.data for r in ordenadas]
    vistos: set[date] = set()
    duplicadas: set[date] = set()
    for d in datas:
        if d in vistos:
            duplicadas.add(d)
        vistos.add(d)
    if duplicadas:
        primeiras = sorted(duplicadas)[:5]
        raise DuplicateSeriesDates(f"reader retornou datas duplicadas: {primeiras}")
    invalidas = [r for r in ordenadas if not (r.valor > 0 and math.isfinite(r.valor))]
    if invalidas:
        raise InvalidSeriesValue(f"reader retornou preço inválido em {invalidas[0].data}")
    return ordenadas


def _validated_index_rows(rows: list[IndexRecord]) -> list[IndexRecord]:
    ordenadas = sorted(rows, key=lambda r: r.data)
    vistos: set[date] = set()
    for r in ordenadas:
        if r.data in vistos:
            raise DuplicateSeriesDates(f"reader de índice retornou data duplicada: {r.data}")
        vistos.add(r.data)
        if not math.isfinite(r.valor):
            raise InvalidSeriesValue(f"reader de índice retornou valor não finito em {r.data}")
    return ordenadas


def _single_currency(rows: list[PriceRecord]) -> str | None:
    moedas = {r.currency for r in rows if r.currency}
    return next(iter(moedas)) if len(moedas) == 1 else None
