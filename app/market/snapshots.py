"""Snapshots pontuais de mercado para tools FQ5.

Separado de `series.py` para não alterar fingerprints das tools FQ1–FQ4 já publicadas.
"""
from __future__ import annotations
from datetime import date
import math
from psycopg import AsyncConnection
from pydantic import BaseModel,ConfigDict,Field
AMBIGUOUS_PRICE_SOURCE="preco_multiplas_fontes_sem_prioridade"
NON_BRL_PRICE="preco_moeda_nao_brl"
class MarketPriceSnapshot(BaseModel):
    model_config=ConfigDict(extra="forbid",frozen=True)
    instrument_id:str
    price_date:date
    value:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    currency:str|None=None
    source_codes:list[str]=Field(default_factory=list)
    ingestion_batch_ids:list[str]=Field(default_factory=list)
    warnings:list[str]=Field(default_factory=list)
async def read_latest_raw_price(conn:AsyncConnection,instrument_id:str,*,cutoff:date)->MarketPriceSnapshot|None:
    cur=await conn.execute("""with latest as (select max(price_date) as d from market.prices where instrument_id = %s and kind = 'close' and price_date <= %s) select p.price_date, p.value::float, p.currency::text, p.source_code::text, p.ingestion_batch_id::text from market.prices p, latest l where p.instrument_id = %s and p.kind = 'close' and p.price_date = l.d order by p.source_code""",(instrument_id,cutoff,instrument_id))
    rows=await cur.fetchall()
    if not rows:return None
    price_date=rows[0][0]; values={(float(value),currency or "BRL") for _,value,currency,_,_ in rows}; warnings=[]
    if len(values)!=1:
        value_out=None; currency_out=None; warnings.append(AMBIGUOUS_PRICE_SOURCE)
    else:
        value_out,currency_out=next(iter(values))
        if not math.isfinite(value_out) or value_out<=0: raise ValueError("preço bruto inválido no snapshot")
        if currency_out!="BRL":warnings.append(NON_BRL_PRICE)
    return MarketPriceSnapshot(instrument_id=instrument_id,price_date=price_date,value=value_out,currency=currency_out,source_codes=sorted({source for _,_,_,source,_ in rows if source}),ingestion_batch_ids=sorted({batch for _,_,_,_,batch in rows if batch}),warnings=warnings)
