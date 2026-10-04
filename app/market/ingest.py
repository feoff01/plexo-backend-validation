"""Lotes de ingestão e gravação append-only em market.* — tudo como plexo_service.

Idempotência: `abrir_lote` devolve None quando já existe lote `succeeded` para (source, dataset,
file_hash) — e o banco garante isso por índice único (31). Dentro do lote, `ON CONFLICT DO NOTHING` na
PK: preço já ingerido é o que vale (append-only; correção = outro lote/fonte). Nada aqui faz UPDATE em
série; só o lote `running` muda de estado, uma vez.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from psycopg import AsyncConnection

from app.db.repos import audit
from app.market.cotahist import Cotacao


@dataclass(frozen=True)
class ResumoGravacao:
    inseridos: int
    ignorados_fora_universo: int
    conflitos: int


@dataclass(frozen=True)
class Cobertura:
    inicio: date          # primeiro dia coberto por partição (anual ou mensal)
    fim: date             # último dia coberto por partição
    particoes: int


async def mapa_universo(conn: AsyncConnection, *, somente_universo: bool = True) -> dict[str, str]:
    """codneg (ticker ou alias 'codigo_b3') → instrument_id. Só instrumentos do universo, por padrão."""
    filtro = "and i.is_in_universe" if somente_universo else ""
    cur = await conn.execute(
        f"""select i.ticker, i.id::text from market.instruments i
             where i.ticker is not null {filtro}
            union all
            select a.alias_value, a.instrument_id::text
              from market.instrument_aliases a join market.instruments i on i.id = a.instrument_id
             where a.alias_kind = 'codigo_b3' {filtro}""")
    return {codigo: iid for codigo, iid in await cur.fetchall()}


async def abrir_lote(conn: AsyncConnection, *, source_code: str, dataset: str, file_hash: str,
                     reference_date: date | None) -> str | None:
    """Novo lote `running`, ou None se este arquivo já foi ingerido com sucesso (no-op)."""
    cur = await conn.execute(
        "select id::text from market.ingestion_batches "
        "where source_code = %s and dataset = %s and file_hash = %s and status = 'succeeded'",
        (source_code, dataset, file_hash))
    if await cur.fetchone():
        return None
    cur = await conn.execute(
        "insert into market.ingestion_batches (source_code, dataset, reference_date, file_hash) "
        "values (%s, %s, %s, %s) returning id::text", (source_code, dataset, reference_date, file_hash))
    return (await cur.fetchone())[0]


async def lote_existente(conn: AsyncConnection, *, source_code: str, dataset: str, file_hash: str) -> str | None:
    cur = await conn.execute(
        "select id::text from market.ingestion_batches "
        "where source_code = %s and dataset = %s and file_hash = %s and status = 'succeeded'",
        (source_code, dataset, file_hash))
    row = await cur.fetchone()
    return row[0] if row else None


async def fechar_lote(conn: AsyncConnection, batch_id: str, *, status: str, rows: int | None,
                      error: str | None = None, reference_date: date | None = None,
                      details: dict | None = None) -> None:
    """Única mudança de estado do lote (depois disso o banco o congela)."""
    await conn.execute(
        "update market.ingestion_batches set status = %s, finished_at = clock_timestamp(), rows_ingested = %s, "
        "error_detail = %s, reference_date = coalesce(%s, reference_date) where id = %s",
        (status, rows, error, reference_date, batch_id))
    await audit.registrar(conn, actor_kind="job", action=f"market.ingestion.{status}",
                          object_kind="ingestion_batch", object_id=batch_id,
                          details={"rows_ingested": rows, "error": error, **(details or {})})


async def _inserir_precos(conn: AsyncConnection, linhas: list[tuple], batch_id: str, source_code: str) -> int:
    if not linhas:
        return 0
    datas, ids, valores = zip(*linhas)
    cur = await conn.execute(
        """insert into market.prices (price_date, instrument_id, kind, value, currency, source_code, ingestion_batch_id)
           select d, i, 'close', v, 'BRL', %s, %s
             from unnest(%s::date[], %s::uuid[], %s::numeric[]) as t(d, i, v)
           on conflict (price_date, instrument_id, kind, source_code) do nothing""",
        (source_code, batch_id, list(datas), list(ids), list(valores)))
    return cur.rowcount


async def gravar_precos(conn: AsyncConnection, batch_id: str, cotacoes: Iterable[Cotacao], mapa: dict[str, str],
                        *, source_code: str, lote_linhas: int) -> ResumoGravacao:
    """Fechamentos do universo → market.prices, em lotes de `lote_linhas` (arquivo anual não cabe em memória)."""
    inseridos = ignorados = tentados = 0
    pendentes: list[tuple] = []
    for c in cotacoes:
        iid = mapa.get(c.codneg)
        if iid is None:
            ignorados += 1
            continue
        pendentes.append((c.data, iid, c.fechamento))
        tentados += 1
        if len(pendentes) >= lote_linhas:
            inseridos += await _inserir_precos(conn, pendentes, batch_id, source_code)
            pendentes = []
    inseridos += await _inserir_precos(conn, pendentes, batch_id, source_code)
    return ResumoGravacao(inseridos=inseridos, ignorados_fora_universo=ignorados, conflitos=tentados - inseridos)


async def gravar_indice(conn: AsyncConnection, batch_id: str, index_code: str,
                        valores: Iterable[tuple[date, Decimal]]) -> ResumoGravacao:
    pontos = list(valores)
    if not pontos:
        return ResumoGravacao(0, 0, 0)
    datas, vals = zip(*pontos)
    cur = await conn.execute(
        """insert into market.index_values (index_code, value_date, value, ingestion_batch_id)
           select %s, d, v, %s from unnest(%s::date[], %s::numeric[]) as t(d, v)
           on conflict (index_code, value_date) do nothing""",
        (index_code, batch_id, list(datas), list(vals)))
    return ResumoGravacao(inseridos=cur.rowcount, ignorados_fora_universo=0, conflitos=len(pontos) - cur.rowcount)


_PARTICAO = re.compile(r"^prices_(\d{4})(\d{2})?$")


def _faixa_da_particao(nome: str) -> tuple[date, date] | None:
    """(primeiro dia, último dia) coberto por uma partição de market.prices, pelo nome."""
    m = _PARTICAO.match(nome)
    if not m:
        return None
    ano = int(m.group(1))
    if m.group(2) is None:                      # anual: prices_AAAA
        return date(ano, 1, 1), date(ano, 12, 31)
    mes = int(m.group(2))                       # mensal: prices_AAAAMM
    proximo = date(ano + mes // 12, mes % 12 + 1, 1)
    return date(ano, mes, 1), proximo - timedelta(days=1)


async def cobertura_particoes(conn: AsyncConnection) -> Cobertura:
    """Faixa coberta por partição de market.prices (a DEFAULT não conta — é válvula de escape).

    Desde a migration 61 convivem duas granularidades: anual (`prices_AAAA`) para 1995–2015, que
    não muda mais, e mensal (`prices_AAAAMM`) do período operável. Ler só o nome mensal faria a
    cobertura mentir por vinte anos — diria que a base começa em 2016 com o acervo carregado.
    """
    cur = await conn.execute(
        "select c.relname from pg_inherits i join pg_class c on c.oid = i.inhrelid "
        "where i.inhparent = 'market.prices'::regclass")
    faixas = [f for (nome,) in await cur.fetchall() if (f := _faixa_da_particao(nome))]
    if not faixas:
        return Cobertura(inicio=date.max, fim=date.min, particoes=0)
    return Cobertura(inicio=min(f[0] for f in faixas), fim=max(f[1] for f in faixas),
                     particoes=len(faixas))


async def indices_sgs(conn: AsyncConnection) -> list[tuple[str, int]]:
    """Índices com série no SGS: [(index_code, sgs_series_id)]."""
    cur = await conn.execute(
        "select code, sgs_series_id from market.index_definitions "
        "where sgs_series_id is not null order by code")
    return [(c, int(s)) for c, s in await cur.fetchall()]


async def ultimo_valor_indice(conn: AsyncConnection, index_code: str) -> date | None:
    cur = await conn.execute("select max(value_date) from market.index_values where index_code = %s", (index_code,))
    return (await cur.fetchone())[0]


async def gravar_expectativas(conn: AsyncConnection, batch_id: str, itens) -> int:
    """Focus → market.market_expectations. `ON CONFLICT DO NOTHING` na chave natural: coleta já
    ingerida é a que vale (append-only; revisão do BCB chega como coleta de outra data)."""
    inseridos = 0
    for e in itens:
        cur = await conn.execute(
            "insert into market.market_expectations (indicador, detalhe, data_coleta, referencia, "
            " mediana, media, desvio_padrao, minimo, maximo, respondentes, base_calculo, ingestion_batch_id) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (indicador, coalesce(detalhe, ''), data_coleta, referencia, coalesce(base_calculo, -1)) do nothing "
            "returning id",
            (e.indicador, e.detalhe, e.data_coleta, e.referencia, e.mediana, e.media,
             e.desvio_padrao, e.minimo, e.maximo, e.respondentes, e.base_calculo, batch_id))
        if await cur.fetchone():
            inseridos += 1
    return inseridos
