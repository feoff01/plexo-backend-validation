"""Modelos e helpers compartilhados pelas tools do Analista. Parte pura (retornos, alinhamento,
lacunas, agregações) é golden-testável; parte com banco (`carregar_*`, `resolver_candidatos`) lê
market.* sob a sessão do app (referência global, sem RLS) sempre com `price_date <= cutoff`."""
from __future__ import annotations

import math
import statistics
import unicodedata
from datetime import date, timedelta
from typing import Literal, Protocol, TypeVar

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from app.market.series import (MarketSeriesLoader, PostgresSeriesReader, PriceBasis, ResolvedMarketSeries,
                               TemporalSemantics)

MetodoRetorno = Literal["log", "simples"]

# avisos padronizados (viram evidence_findings 'warning' ou 'missing')
SERIE_CURTA = "serie_curta"
SERIE_DEFASADA = "serie_defasada"
SERIE_AMOSTRADA = "serie_amostrada"
SERIE_CONSTANTE = "serie_constante"
SEM_DADOS = "sem_dados"
INSTRUMENTO_DESCONHECIDO = "instrumento_desconhecido"
INSTRUMENTO_AMBIGUO = "instrumento_ambiguo"
INDICE_DESCONHECIDO = "indice_desconhecido"
FORA_DA_COBERTURA = "fora_da_cobertura"
JANELA_POS_TRUNCADA = "janela_pos_truncada"
EVENTO_AJUSTADO = "evento_ajustado"
SEM_EVENTOS_CONDICAO = "sem_eventos_condicao"

NOTA_RCVM = ("Métrica descritiva sobre preços oficiais passados; retorno passado não indica retorno futuro. "
             "Não é tese, previsão nem indicação de compra ou venda.")


class TemData(Protocol):
    """O mínimo que a amostragem precisa saber de um ponto de série: a data.

    Existe para `amostrar_mensal` servir tanto a `Ponto` quanto ao `PontoNormalizado` do histórico
    comparado — são modelos distintos, e herança entre eles só para compartilhar a amostragem seria
    acoplamento sem ganho.
    """
    data: date


_ComData = TypeVar("_ComData", bound=TemData)


class Ponto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: date
    valor: float


class Serie(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str
    pontos: list[Ponto] = Field(default_factory=list)   # ordem cronológica, uma por data


class Janela(BaseModel):
    model_config = ConfigDict(extra="forbid")
    de: date | None
    ate: date | None
    n: int


class Evidencia(BaseModel):
    """Proveniência e qualidade do que a tool leu — vira evidence_findings e cited_refs."""
    model_config = ConfigDict(extra="forbid")
    fonte: str
    instrument_ids: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    index_codes: list[str] = Field(default_factory=list)
    cutoff_date: date
    as_of: date | None
    n_observacoes: int
    lacunas: list[date] = Field(default_factory=list)
    metodo: str
    nota_metodo: str
    suficiente: bool
    avisos: list[str] = Field(default_factory=list)
    metricas: dict[str, float | None] = Field(default_factory=dict)
    ingestion_batch_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- parte pura
def normalizar(s: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.lower().split())


def retornos(pontos: list[Ponto], metodo: MetodoRetorno) -> list[tuple[date, float]]:
    """Retorno entre pontos consecutivos, datado no ponto final."""
    saida = []
    for a, b in zip(pontos, pontos[1:]):
        r = math.log(b.valor / a.valor) if metodo == "log" else b.valor / a.valor - 1
        saida.append((b.data, r))
    return saida


def retornos_de_indice(pontos: list[Ponto], unidade: str, *, dias_uteis_ano: int,
                       metodo: MetodoRetorno) -> list[tuple[date, float]]:
    """Índice em taxa (a.a./a.m.) vira retorno do período de cada ponto; em pontos, retorno de preço."""
    if unidade == "taxa_aa":
        return [(p.data, (1 + p.valor / 100) ** (1 / dias_uteis_ano) - 1) for p in pontos[1:]]
    if unidade in ("taxa_am", "percentual"):
        return [(p.data, p.valor / 100) for p in pontos[1:]]
    return retornos(pontos, metodo)


def alinhar(ra: list[tuple[date, float]], rb: list[tuple[date, float]], *, defasagem: int = 0
            ) -> list[tuple[date, float, float]]:
    """Pares (data, r_a, r_b) nas datas comuns; `defasagem` d > 0 compara r_a[t] com r_b[t+d] (A antecede B)."""
    comuns = sorted(set(d for d, _ in ra) & set(d for d, _ in rb))
    va, vb = dict(ra), dict(rb)
    a = [va[d] for d in comuns]
    b = [vb[d] for d in comuns]
    n = len(comuns)
    return [(comuns[i], a[i], b[i + defasagem]) for i in range(n) if 0 <= i + defasagem < n]


def lacunas(datas: list[date], calendario: list[date]) -> list[date]:
    """Dias do calendário (pregões do universo) entre o 1º e o último ponto em que a série não tem preço."""
    if not datas:
        return []
    presentes = set(datas)
    return [d for d in calendario if datas[0] <= d <= datas[-1] and d not in presentes]


def defasagem_dias(as_of: date | None, cutoff: date) -> int | None:
    return None if as_of is None else (cutoff - as_of).days


def amostrar_mensal(pontos: list[_ComData]) -> list[_ComData]:
    """Último ponto de cada mês — para séries longas caberem no payload.

    Genérica por `_ComData` porque serve tanto a `Ponto` quanto a `PontoNormalizado` do
    histórico comparado: são modelos distintos e o que a amostragem usa é só a data.
    """
    por_mes: dict[tuple[int, int], _ComData] = {}
    for p in pontos:
        por_mes[(p.data.year, p.data.month)] = p
    return [por_mes[k] for k in sorted(por_mes)]


def max_drawdown(pontos: list[Ponto]) -> float | None:
    if not pontos:
        return None
    pico, pior = pontos[0].valor, 0.0
    for p in pontos:
        pico = max(pico, p.valor)
        pior = min(pior, p.valor / pico - 1)
    return pior


def desvio(valores: list[float]) -> float | None:
    return statistics.stdev(valores) if len(valores) >= 2 else None


def correlacao_pearson(x: list[float], y: list[float]) -> float | None:
    """None quando não há pares suficientes ou uma das séries é constante (não há correlação definida)."""
    if len(x) < 2:
        return None
    try:
        return statistics.correlation(x, y)
    except statistics.StatisticsError:
        return None


def janela_padrao(cutoff: date, de: date | None, ate: date | None, *, janela_dias: int) -> tuple[date, date]:
    fim = min(ate or cutoff, cutoff)
    inicio = de or (fim - timedelta(days=janela_dias))
    return inicio, fim


def avisos_de_qualidade(as_of: date | None, cutoff: date, n: int, *, min_observacoes: int,
                        max_dias_defasagem: int) -> tuple[bool, list[str]]:
    """(suficiente, avisos): sem dados/série curta ⇒ insuficiente; defasagem ⇒ só aviso."""
    avisos: list[str] = []
    if n == 0:
        return False, [SEM_DADOS]
    suficiente = n >= min_observacoes
    if not suficiente:
        avisos.append(SERIE_CURTA)
    d = defasagem_dias(as_of, cutoff)
    if d is not None and d > max_dias_defasagem:
        avisos.append(SERIE_DEFASADA)
    return suficiente, avisos


# ---------------------------------------------------------------- parte com banco
async def data_referencia(conn: AsyncConnection) -> date:
    cur = await conn.execute("select current_date")
    return (await cur.fetchone())[0]


def resolver_cutoff(data_referencia_param: date | None, cutoff_ctx: date | None, hoje: date) -> date:
    """Parâmetro explícito > cutoff da análise > hoje."""
    return data_referencia_param or cutoff_ctx or hoje


async def carregar_serie_resolvida(
    conn: AsyncConnection,
    instrument_id: str,
    *,
    de: date,
    ate: date,
    cutoff: date,
    codigo: str,
    basis: PriceBasis = PriceBasis.RAW_CLOSE,
    temporal_semantics: TemporalSemantics = TemporalSemantics.OBSERVATION_DATE_CUTOFF,
    include_calendar: bool = True,
) -> ResolvedMarketSeries:
    """Caminho canônico para preço de instrumento (FQ1).

    Engines novos devem preferir este retorno rico (quality + provenance). As tools legacy usam
    ``carregar_serie`` abaixo, que adapta para o contrato antigo sem mudar output_payload.
    """
    loader = MarketSeriesLoader(PostgresSeriesReader(conn))
    return await loader.load_prices(
        instrument_id, code=codigo, de=de, ate=ate, cutoff=cutoff,
        basis=basis, temporal_semantics=temporal_semantics, include_calendar=include_calendar,
    )


async def carregar_serie(conn: AsyncConnection, instrument_id: str, *, de: date, ate: date, cutoff: date,
                         codigo: str) -> tuple[Serie, list[str]]:
    """Adapter legacy: RAW_CLOSE + OBSERVATION_DATE_CUTOFF pelo MarketSeriesLoader."""
    resolvida = await carregar_serie_resolvida(
        conn, instrument_id, de=de, ate=ate, cutoff=cutoff, codigo=codigo,
        include_calendar=False,
    )
    serie = Serie(codigo=resolvida.code,
                  pontos=[Ponto(data=p.data, valor=p.valor) for p in resolvida.points])
    return serie, resolvida.provenance.ingestion_batch_ids


async def carregar_indice_resolvido(
    conn: AsyncConnection,
    code: str,
    *,
    de: date,
    ate: date,
    cutoff: date,
    include_calendar: bool = True,
) -> ResolvedMarketSeries:
    """Caminho canônico para índice/taxa, preservando quality + provenance."""
    loader = MarketSeriesLoader(PostgresSeriesReader(conn))
    return await loader.load_index(
        code, de=de, ate=ate, cutoff=cutoff, include_calendar=include_calendar,
    )


async def carregar_indice(conn: AsyncConnection, code: str, *, de: date, ate: date, cutoff: date
                          ) -> tuple[str, str, Serie, list[str]]:
    """Adapter legacy de índice/taxa pelo MarketSeriesLoader."""
    resolvida = await carregar_indice_resolvido(
        conn, code, de=de, ate=ate, cutoff=cutoff, include_calendar=False,
    )
    serie = Serie(codigo=resolvida.code,
                  pontos=[Ponto(data=p.data, valor=p.valor) for p in resolvida.points])
    fonte = resolvida.provenance.source_codes[0] if resolvida.provenance.source_codes else ""
    return resolvida.unit or "pontos", fonte, serie, resolvida.provenance.ingestion_batch_ids


async def calendario(conn: AsyncConnection, *, de: date, ate: date, cutoff: date) -> list[date]:
    """Calendário B3 oficial quando a janela está completa; fallback de preços fica explícito no loader.

    A assinatura legacy devolve apenas as datas para não alterar outputs atuais. Novas tools/engines
    devem usar ``MarketSeriesLoader.load_calendar`` quando precisarem da provenance do calendário.
    """
    loader = MarketSeriesLoader(PostgresSeriesReader(conn))
    snap = await loader.load_calendar(de=de, ate=ate, cutoff=cutoff)
    return snap.business_days


async def resolver_candidatos(conn: AsyncConnection, termo: str, *, cutoff: date) -> list[dict]:
    """Candidatos por ticker exato, alias (codigo_b3/ticker_antigo) ou nome (contém), com último preço <= cutoff."""
    t = termo.strip()
    cur = await conn.execute(
        """with c as (
             select i.id, 0 as prioridade from market.instruments i where upper(i.ticker) = upper(%s)
             union
             select a.instrument_id, 1 from market.instrument_aliases a
              where a.alias_kind in ('codigo_b3','ticker_antigo') and upper(a.alias_value) = upper(%s)
             union
             select i.id, 2 from market.instruments i where i.name ilike '%%' || %s || '%%'
           )
           select i.id::text, i.ticker, i.name, i.kind::text, i.is_in_universe, min(c.prioridade),
                  (select max(p.price_date) from market.prices p
                    where p.instrument_id = i.id and p.kind = 'close' and p.price_date <= %s)
             from c join market.instruments i on i.id = c.id
            group by i.id, i.ticker, i.name, i.kind, i.is_in_universe
            order by min(c.prioridade), i.ticker""", (t, t, t, cutoff))
    return [{"instrument_id": iid, "ticker": ticker, "name": name, "kind": kind, "is_in_universe": uni,
             "prioridade": pri, "ultimo_preco_em": ultimo}
            for iid, ticker, name, kind, uni, pri, ultimo in await cur.fetchall()]


async def instrumento_por_termo(conn: AsyncConnection, termo: str, *, cutoff: date) -> dict | None:
    """Resolução direta para as tools de série: um único candidato exato (ticker/alias) ou único por nome."""
    cands = await resolver_candidatos(conn, termo, cutoff=cutoff)
    exatos = [c for c in cands if c["prioridade"] < 2]
    if len(exatos) == 1:
        return exatos[0]
    if not exatos and len(cands) == 1:
        return cands[0]
    return None
