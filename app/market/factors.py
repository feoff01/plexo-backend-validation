"""Adapters canônicos de fatores macro para o Analista (FQ5.4)."""
from __future__ import annotations
import math,re
from datetime import date
from psycopg import AsyncConnection
from pydantic import BaseModel,ConfigDict,Field
from app.market.series import CALENDAR_FALLBACK_FROM_PRICES,MarketPoint,MarketSeriesLoader,PostgresSeriesReader,ResolvedMarketSeries,SeriesProvenance,TemporalSemantics,quality_for_points
FX_OBSERVATION_CUTOFF_ONLY="fx_observation_date_cutoff_sem_vintage"
FX_PAIR_NOT_FOUND="par_cambio_sem_dados"
_CURRENCY_RE=re.compile(r"^[A-Z]{3}$")
class FxRecord(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True)
    data:date
    valor:float=Field(gt=0,allow_inf_nan=False)
    source_code:str|None=None
def normalize_currency(code:str)->str:
    value=code.strip().upper()
    if not _CURRENCY_RE.fullmatch(value): raise ValueError("moeda deve ter exatamente 3 letras ASCII, por exemplo USD ou BRL")
    return value
def fx_code(base_currency:str,quote_currency:str)->str: return f"{normalize_currency(base_currency)}/{normalize_currency(quote_currency)}"
async def fx_pair_exists(conn:AsyncConnection,base_currency:str,quote_currency:str,*,cutoff:date)->bool:
    base=normalize_currency(base_currency); quote=normalize_currency(quote_currency)
    cur=await conn.execute("""select exists(select 1 from market.fx_rates where base_currency = %s::core.currency and quote_currency = %s::core.currency and rate_date <= %s)""",(base,quote,cutoff))
    row=await cur.fetchone(); return bool(row and row[0])
async def read_fx_records(conn:AsyncConnection,base_currency:str,quote_currency:str,*,de:date,ate:date,cutoff:date)->list[FxRecord]:
    base=normalize_currency(base_currency); quote=normalize_currency(quote_currency); end=min(ate,cutoff)
    if de>end:return []
    cur=await conn.execute("""select rate_date, rate::float, source_code::text from market.fx_rates where base_currency = %s::core.currency and quote_currency = %s::core.currency and rate_date between %s and %s and rate_date <= %s order by rate_date""",(base,quote,de,end,cutoff))
    rows=[FxRecord(data=d,valor=v,source_code=source) for d,v,source in await cur.fetchall()]; previous=None
    for row in rows:
        if previous is not None and row.data<=previous: raise ValueError("market.fx_rates retornou datas duplicadas ou fora de ordem")
        if not math.isfinite(row.valor) or row.valor<=0: raise ValueError(f"market.fx_rates retornou taxa inválida em {row.data}")
        previous=row.data
    return rows
async def load_fx_series(conn:AsyncConnection,base_currency:str,quote_currency:str,*,de:date,ate:date,cutoff:date,include_calendar:bool=True)->ResolvedMarketSeries:
    base=normalize_currency(base_currency); quote=normalize_currency(quote_currency); rows=await read_fx_records(conn,base,quote,de=de,ate=ate,cutoff=cutoff)
    loader=MarketSeriesLoader(PostgresSeriesReader(conn)); calendar=await loader.load_calendar(de=de,ate=min(ate,cutoff),cutoff=cutoff) if include_calendar else None
    points=[MarketPoint(data=row.data,valor=row.valor) for row in rows]; quality=quality_for_points(points,calendar,cutoff=cutoff); warnings=[FX_OBSERVATION_CUTOFF_ONLY]
    if calendar is not None and calendar.fallback_used:warnings.append(CALENDAR_FALLBACK_FROM_PRICES)
    return ResolvedMarketSeries(code=f"{base}/{quote}",unit="pontos",points=points,quality=quality,provenance=SeriesProvenance(dataset="market.fx_rates",source_codes=sorted({row.source_code for row in rows if row.source_code}),ingestion_batch_ids=[],calendar_ingestion_batch_ids=(calendar.ingestion_batch_ids if calendar is not None else []),price_basis=None,temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,cutoff_date=cutoff,warnings=warnings))
