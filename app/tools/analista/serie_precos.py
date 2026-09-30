"""Tool `dados.serie_precos` — fechamentos oficiais (B3) de um ativo até o cutoff, com lacunas e
proveniência. Série longa é amostrada (último ponto de cada mês) para caber no payload; a evidência
conta a série inteira."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.market import series as market_series
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (INSTRUMENTO_DESCONHECIDO, NOTA_RCVM, SERIE_AMOSTRADA, Evidencia, Ponto, Serie,
                                       amostrar_mensal, avisos_de_qualidade, calendario, carregar_serie,
                                       data_referencia, instrumento_por_termo, janela_padrao, lacunas,
                                       resolver_cutoff)
from app.tools.executor import ToolContext
from app.tools.registry import tool


class SeriePrecosParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="Ticker do ativo (ex.: PETR4, BOVA11).")
    de: date | None = Field(default=None, description="Início do período; padrão: janela padrão da política.")
    ate: date | None = Field(default=None, description="Fim do período; nunca passa da data de referência.")
    data_referencia: date | None = Field(
        default=None,
        description=("Cutoff pela data da observação: não usa preço com data posterior. "
                     "Não garante vintage histórico contra backfills/revisões posteriores."),
    )


class SeriePrecosResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    instrument_id: str | None
    cutoff_date: date
    de: date
    ate: date
    serie: Serie
    calendario: list[date]
    max_pontos: int
    min_observacoes: int
    max_dias_defasagem: int
    fonte: str
    ingestion_batch_ids: list[str]


class SeriePrecosOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    pontos: list[Ponto]
    primeiro: Ponto | None
    ultimo: Ponto | None
    amostrado: bool
    evidencia: Evidencia


async def preparar_serie(params: SeriePrecosParams, ctx: ToolContext) -> SeriePrecosResolvida:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = janela_padrao(cutoff, params.de, params.ate, janela_dias=int(cfg["janela_padrao_dias"]))
    inst = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    serie, lotes, cal = Serie(codigo=params.ticker), [], []
    if inst is not None and inst["is_in_universe"]:
        serie, lotes = await carregar_serie(ctx.conn, inst["instrument_id"], de=de, ate=ate, cutoff=cutoff,
                                            codigo=inst["ticker"] or params.ticker)
        cal = await calendario(ctx.conn, de=de, ate=ate, cutoff=cutoff)
    ctx.registrar_insumo("market.prices", ticker=params.ticker, encontrado=inst is not None,
                         n=len(serie.pontos), cutoff=cutoff.isoformat())
    return SeriePrecosResolvida(ticker=params.ticker, instrument_id=inst["instrument_id"] if inst else None,
                                cutoff_date=cutoff, de=de, ate=ate, serie=serie, calendario=cal,
                                max_pontos=int(cfg["max_pontos"]), min_observacoes=int(cfg["min_observacoes"]),
                                max_dias_defasagem=int(cfg["max_dias_defasagem"]), fonte="b3",
                                ingestion_batch_ids=lotes)


@tool(code="dados.serie_precos", family="dados", semver="1.0.2",
      display_name="Série de preços (fechamento)",
      description=("Fechamentos oficiais da B3 de um ativo em um período, limitados pela data da observação até a "
                   "referência. Esse cutoff não garante vintage histórico contra backfills/revisões posteriores. "
                   "Devolve último preço, pregões sem cotação e fonte. Para métricas (retorno, volatilidade, "
                   "correlação), use as ferramentas quant."),
      preparar=preparar_serie, source_dependencies=(comum_module.__file__, market_series.__file__), requires_market_data=True)
def montar_serie(r: SeriePrecosResolvida) -> SeriePrecosOutput:
    pontos = r.serie.pontos
    n = len(pontos)
    as_of = pontos[-1].data if pontos else None
    suficiente, avisos = avisos_de_qualidade(as_of, r.cutoff_date, n, min_observacoes=r.min_observacoes,
                                             max_dias_defasagem=r.max_dias_defasagem)
    if r.instrument_id is None:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
    amostrado = n > r.max_pontos
    exibidos = amostrar_mensal(pontos) if amostrado else pontos
    if amostrado:
        avisos.append(SERIE_AMOSTRADA)
    ev = Evidencia(fonte=r.fonte, instrument_ids=[r.instrument_id] if r.instrument_id else [],
                   tickers=[r.serie.codigo] if r.instrument_id else [], cutoff_date=r.cutoff_date, as_of=as_of,
                   n_observacoes=n, lacunas=lacunas([p.data for p in pontos], r.calendario),
                   metodo="fechamento_oficial_d1", nota_metodo="Preço de fechamento do pregão (lote padrão), D-1. " + NOTA_RCVM,
                   suficiente=suficiente, avisos=avisos,
                   metricas={"primeiro_fechamento": pontos[0].valor if pontos else None,
                             "ultimo_fechamento": pontos[-1].valor if pontos else None},
                   ingestion_batch_ids=r.ingestion_batch_ids)
    return SeriePrecosOutput(ticker=r.serie.codigo, pontos=exibidos, primeiro=pontos[0] if pontos else None,
                             ultimo=pontos[-1] if pontos else None, amostrado=amostrado, evidencia=ev)
