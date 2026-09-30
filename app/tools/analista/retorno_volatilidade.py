"""Tool `quant.retorno_volatilidade` — retorno acumulado, anualizado, volatilidade anualizada e máximo
drawdown de um ativo na janela, sobre fechamentos oficiais até o cutoff. Método declarado
(`metodo_retorno` log|simples; base `dias_uteis_ano`) — tudo da política ANALISE_PARAMS."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.market import series as market_series
from app.market.analytics import models as quant_models
from app.market.analytics import returns as quant_returns
from app.market.analytics import risk as quant_risk
from app.market.analytics import statistics as quant_statistics
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (INSTRUMENTO_DESCONHECIDO, NOTA_RCVM, Evidencia, Janela, MetodoRetorno, Serie,
                                       avisos_de_qualidade, calendario, carregar_serie, data_referencia,
                                       instrumento_por_termo, janela_padrao, lacunas, resolver_cutoff)
from app.tools.executor import ToolContext
from app.tools.registry import tool


class RetornoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="Ticker do ativo (ex.: PETR4).")
    janela_dias: int | None = Field(default=None, ge=1, description="Janela em dias corridos até a referência; padrão da política.")
    de: date | None = Field(default=None, description="Início explícito (substitui a janela).")
    ate: date | None = Field(default=None, description="Fim explícito; nunca passa da referência.")
    data_referencia: date | None = Field(default=None, description="Point-in-time: só preços até esta data.")


class RetornoResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    instrument_id: str | None
    cutoff_date: date
    serie: Serie
    calendario: list[date]
    metodo_retorno: MetodoRetorno
    dias_uteis_ano: int
    min_observacoes: int
    max_dias_defasagem: int
    fonte: str
    ingestion_batch_ids: list[str]


class RetornoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    periodo: Janela
    retorno_acumulado_pct: float | None
    retorno_anualizado_pct: float | None
    vol_anualizada_pct: float | None
    max_drawdown_pct: float | None
    evidencia: Evidencia


async def preparar_retorno(params: RetornoParams, ctx: ToolContext) -> RetornoResolvido:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = janela_padrao(cutoff, params.de, params.ate,
                            janela_dias=int(params.janela_dias or cfg["janela_padrao_dias"]))
    inst = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    serie, lotes, cal = Serie(codigo=params.ticker), [], []
    if inst is not None and inst["is_in_universe"]:
        serie, lotes = await carregar_serie(ctx.conn, inst["instrument_id"], de=de, ate=ate, cutoff=cutoff,
                                            codigo=inst["ticker"] or params.ticker)
        cal = await calendario(ctx.conn, de=de, ate=ate, cutoff=cutoff)
    ctx.registrar_insumo("market.prices", ticker=params.ticker, encontrado=inst is not None,
                         n=len(serie.pontos), cutoff=cutoff.isoformat())
    return RetornoResolvido(ticker=params.ticker, instrument_id=inst["instrument_id"] if inst else None,
                            cutoff_date=cutoff, serie=serie, calendario=cal, metodo_retorno=cfg["metodo_retorno"],
                            dias_uteis_ano=int(cfg["dias_uteis_ano"]), min_observacoes=int(cfg["min_observacoes"]),
                            max_dias_defasagem=int(cfg["max_dias_defasagem"]), fonte="b3", ingestion_batch_ids=lotes)


@tool(code="quant.retorno_volatilidade", family="quant", semver="1.0.4",
      display_name="Retorno e volatilidade",
      description=("Retorno acumulado e anualizado, volatilidade anualizada e máximo drawdown de um ativo em uma "
                   "janela, calculados sobre fechamentos oficiais até a data de referência. Devolve n de "
                   "observações, lacunas e método. Descreve o passado; não projeta nem compara como 'melhor'."),
      preparar=preparar_retorno,
      source_dependencies=(comum_module.__file__, market_series.__file__, quant_models.__file__,
                           quant_returns.__file__, quant_risk.__file__, quant_statistics.__file__),
      requires_market_data=True, exposed_to_llm=False)
def calcular_retorno(r: RetornoResolvido) -> RetornoOutput:
    pontos = r.serie.pontos
    n = len(pontos)
    as_of = pontos[-1].data if pontos else None
    suficiente, avisos = avisos_de_qualidade(as_of, r.cutoff_date, n, min_observacoes=r.min_observacoes,
                                             max_dias_defasagem=r.max_dias_defasagem)
    if r.instrument_id is None:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
    acumulado = anualizado = vol = dd = None
    if suficiente and n >= 2:
        market_points = [market_series.MarketPoint(data=p.data, valor=p.valor) for p in pontos]
        rets = [x.value for x in quant_returns.calculate_returns(market_points, r.metodo_retorno)]
        acumulado_raw = quant_returns.cumulative_price_return(market_points)
        anualizado_raw = quant_returns.annualized_price_return(
            market_points, periods_per_year=r.dias_uteis_ano
        )
        acumulado = acumulado_raw * 100 if acumulado_raw is not None else None
        anualizado = anualizado_raw * 100 if anualizado_raw is not None else None
        vol_raw = quant_risk.annualized_volatility(rets, periods_per_year=r.dias_uteis_ano)
        vol = vol_raw * 100 if vol_raw is not None else None
        dd = quant_risk.maximum_drawdown(market_points)
        dd = dd * 100 if dd is not None else None
    ev = Evidencia(fonte=r.fonte, instrument_ids=[r.instrument_id] if r.instrument_id else [],
                   tickers=[r.serie.codigo] if r.instrument_id else [], cutoff_date=r.cutoff_date, as_of=as_of,
                   n_observacoes=n, lacunas=lacunas([p.data for p in pontos], r.calendario),
                   metodo=f"{r.metodo_retorno}_anualizado_base_{r.dias_uteis_ano}",
                   nota_metodo=(f"Retorno {r.metodo_retorno} entre fechamentos consecutivos; anualização geométrica e "
                                f"volatilidade = desvio-padrão × raiz({r.dias_uteis_ano}); drawdown sobre o pico corrente. "
                                + NOTA_RCVM),
                   suficiente=suficiente, avisos=avisos,
                   metricas={"retorno_acumulado_pct": acumulado, "retorno_anualizado_pct": anualizado,
                             "vol_anualizada_pct": vol, "max_drawdown_pct": dd},
                   ingestion_batch_ids=r.ingestion_batch_ids)
    return RetornoOutput(ticker=r.serie.codigo, periodo=Janela(de=pontos[0].data if pontos else None, ate=as_of, n=n),
                         retorno_acumulado_pct=acumulado, retorno_anualizado_pct=anualizado,
                         vol_anualizada_pct=vol, max_drawdown_pct=dd, evidencia=ev)
