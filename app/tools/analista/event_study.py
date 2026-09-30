"""Tool `quant.event_study` — reação de um ativo a um evento datado, contra um benchmark.

Método (declarado no output): `market_model` estima alpha/beta por regressão linear simples
(`statistics.linear_regression`) dos retornos do ativo sobre os do benchmark na janela de estimação, que
termina `pre_dias + 1` pregões antes do evento; retorno anormal AR_t = r_t − (alpha + beta·r_m,t) na janela
[−pre, +pos]; CAR = soma. `market_adjusted` usa alpha=0, beta=1. Sem teste de significância: o CAR é
comparado ao desvio dos resíduos apenas como ordem de grandeza — nada de inferência estatística."""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.market import series as market_series
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (EVENTO_AJUSTADO, INSTRUMENTO_DESCONHECIDO, JANELA_POS_TRUNCADA, NOTA_RCVM,
                                       SEM_DADOS, SERIE_CURTA, Evidencia, Janela, MetodoRetorno, Serie, alinhar,
                                       carregar_serie, data_referencia, desvio, instrumento_por_termo, resolver_cutoff,
                                       retornos)
from app.tools.executor import ToolContext
from app.tools.registry import tool

MetodoES = Literal["market_model", "market_adjusted"]


class EventStudyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="Ticker do ativo analisado.")
    data_evento: date = Field(description="Data do evento (se não for pregão, usa-se o próximo).")
    benchmark: str | None = Field(default=None, description="Ticker do benchmark; padrão da política (ETF do índice).")
    metodo: MetodoES | None = Field(default=None, description="market_model (regressão) ou market_adjusted (diferença simples); padrão da política.")
    janela_estimacao_dias: int | None = Field(default=None, ge=2, description="Pregões da janela de estimação; padrão da política.")
    pre_dias: int | None = Field(default=None, ge=0, description="Pregões antes do evento na janela de evento.")
    pos_dias: int | None = Field(default=None, ge=0, description="Pregões depois do evento na janela de evento.")
    data_referencia: date | None = Field(default=None, description=("Cutoff pela data da observação: nada datado depois entra; não garante vintage histórico contra backfills/revisões."))


class EventStudyResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    benchmark: str
    instrument_ids: list[str]
    cutoff_date: date
    data_evento: date
    data_evento_efetiva: date | None
    serie_ativo: Serie
    serie_benchmark: Serie
    metodo: MetodoES
    metodo_retorno: MetodoRetorno
    janela_estimacao_dias: int
    pre_dias: int
    pos_dias: int
    min_observacoes: int
    max_dias_defasagem: int
    fonte: str
    ingestion_batch_ids: list[str]


class RetornoAnormal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: date
    ar_pct: float


class EventStudyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    benchmark: str
    data_evento: date
    data_evento_efetiva: date | None
    metodo: MetodoES
    alpha: float | None
    beta: float | None
    ar: list[RetornoAnormal]
    car_pct: float | None
    desvio_residuos_pct: float | None
    janela_estimacao: Janela
    janela_evento: Janela
    truncada: bool
    evidencia: Evidencia


async def preparar_event_study(params: EventStudyParams, ctx: ToolContext) -> EventStudyResolvido:
    cfg = await ctx.policy("ANALISE_PARAMS")
    es = cfg["event_study"]
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    janela_est = int(params.janela_estimacao_dias or es["janela_estimacao_dias"])
    pre = int(es["pre_dias"] if params.pre_dias is None else params.pre_dias)
    pos = int(es["pos_dias"] if params.pos_dias is None else params.pos_dias)
    benchmark = params.benchmark or cfg["benchmark_padrao"]
    # margem em dias corridos para cobrir a janela de estimação em pregões (fins de semana/feriados)
    de = params.data_evento - timedelta(days=(janela_est + pre + 1) * 2 + 12)
    ate = cutoff
    ids, lotes = [], []
    serie_a, serie_b = Serie(codigo=params.ticker), Serie(codigo=benchmark)
    inst_a = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    if inst_a is not None and inst_a["is_in_universe"]:
        serie_a, la = await carregar_serie(ctx.conn, inst_a["instrument_id"], de=de, ate=ate, cutoff=cutoff, codigo=inst_a["ticker"])
        ids.append(inst_a["instrument_id"]); lotes += la
    inst_b = await instrumento_por_termo(ctx.conn, benchmark, cutoff=cutoff)
    if inst_b is not None and inst_b["is_in_universe"]:
        serie_b, lb = await carregar_serie(ctx.conn, inst_b["instrument_id"], de=de, ate=ate, cutoff=cutoff, codigo=inst_b["ticker"])
        ids.append(inst_b["instrument_id"]); lotes += lb
    efetiva = next((p.data for p in serie_a.pontos if p.data >= params.data_evento), None)
    ctx.registrar_insumo("market.prices", ticker=params.ticker, benchmark=benchmark, n_ativo=len(serie_a.pontos),
                         n_benchmark=len(serie_b.pontos), cutoff=cutoff.isoformat())
    return EventStudyResolvido(ticker=params.ticker, benchmark=benchmark, instrument_ids=ids, cutoff_date=cutoff,
                               data_evento=params.data_evento, data_evento_efetiva=efetiva, serie_ativo=serie_a,
                               serie_benchmark=serie_b, metodo=params.metodo or es["metodo"],
                               metodo_retorno=cfg["metodo_retorno"], janela_estimacao_dias=janela_est, pre_dias=pre,
                               pos_dias=pos, min_observacoes=int(cfg["min_observacoes"]),
                               max_dias_defasagem=int(cfg["max_dias_defasagem"]), fonte="b3",
                               ingestion_batch_ids=sorted(set(lotes)))


@tool(code="quant.event_study", family="quant", semver="1.0.2",
      display_name="Estudo de evento",
      description=("Mede como um ativo reagiu a um evento datado (balanço, decisão de juros, anúncio) descontando o "
                   "benchmark: alpha/beta estimados antes do evento, retorno anormal por pregão na janela do evento "
                   "e o acumulado (CAR). Descreve o que aconteceu; não infere significância nem projeta reação futura."),
      preparar=preparar_event_study, source_dependencies=(comum_module.__file__, market_series.__file__), requires_market_data=True)
def calcular_event_study(r: EventStudyResolvido) -> EventStudyOutput:
    ra = retornos(r.serie_ativo.pontos, r.metodo_retorno)
    rb = retornos(r.serie_benchmark.pontos, r.metodo_retorno)
    pares = alinhar(ra, rb)
    datas = [d for d, _, _ in pares]
    avisos: list[str] = []
    if len(r.instrument_ids) < 2:
        avisos.append(INSTRUMENTO_DESCONHECIDO)
    if r.data_evento_efetiva is not None and r.data_evento_efetiva != r.data_evento:
        avisos.append(EVENTO_AJUSTADO)
    idx = datas.index(r.data_evento_efetiva) if r.data_evento_efetiva in datas else None
    alpha = beta = car = sd = None
    ars: list[RetornoAnormal] = []
    est = Janela(de=None, ate=None, n=0)
    evt = Janela(de=None, ate=None, n=0)
    truncada = False
    suficiente = False
    if idx is None:
        avisos.append(SEM_DADOS)
    else:
        fim_est = idx - r.pre_dias            # exclusivo
        ini_est = max(0, fim_est - r.janela_estimacao_dias)
        estimacao = pares[ini_est:fim_est]
        ini_evt = max(0, idx - r.pre_dias)
        fim_evt = idx + r.pos_dias + 1
        truncada = fim_evt > len(pares)
        evento = pares[ini_evt:fim_evt]
        if truncada:
            avisos.append(JANELA_POS_TRUNCADA)
        est = Janela(de=estimacao[0][0] if estimacao else None, ate=estimacao[-1][0] if estimacao else None, n=len(estimacao))
        evt = Janela(de=evento[0][0] if evento else None, ate=evento[-1][0] if evento else None, n=len(evento))
        suficiente = len(estimacao) >= max(2, r.min_observacoes) and bool(evento)
        if not suficiente:
            avisos.append(SERIE_CURTA)
        else:
            if r.metodo == "market_model":
                reg = statistics.linear_regression([b for _, _, b in estimacao], [a for _, a, _ in estimacao])
                alpha, beta = reg.intercept, reg.slope
            else:
                alpha, beta = 0.0, 1.0
            residuos = [a - (alpha + beta * b) for _, a, b in estimacao]
            sd = desvio(residuos)
            sd = sd * 100 if sd is not None else None
            ars = [RetornoAnormal(data=d, ar_pct=(a - (alpha + beta * b)) * 100) for d, a, b in evento]
            car = sum(x.ar_pct for x in ars)
    as_of = datas[-1] if datas else None
    ev = Evidencia(fonte=r.fonte, instrument_ids=r.instrument_ids, tickers=[r.serie_ativo.codigo, r.serie_benchmark.codigo],
                   cutoff_date=r.cutoff_date, as_of=as_of, n_observacoes=len(pares),
                   metodo=f"event_study_{r.metodo}_{r.metodo_retorno}",
                   nota_metodo=("Retorno anormal = retorno do ativo − retorno esperado pelo benchmark (alpha/beta da janela de "
                                "estimação); CAR = soma na janela do evento. Sem teste de significância nem inferência "
                                "estatística: o CAR comparado ao desvio dos resíduos é só ordem de grandeza. " + NOTA_RCVM),
                   suficiente=suficiente, avisos=avisos,
                   metricas={"alpha": alpha, "beta": beta, "car_pct": car, "desvio_residuos_pct": sd},
                   ingestion_batch_ids=r.ingestion_batch_ids)
    return EventStudyOutput(ticker=r.serie_ativo.codigo, benchmark=r.serie_benchmark.codigo, data_evento=r.data_evento,
                            data_evento_efetiva=r.data_evento_efetiva, metodo=r.metodo, alpha=alpha, beta=beta, ar=ars,
                            car_pct=car, desvio_residuos_pct=sd, janela_estimacao=est, janela_evento=evt,
                            truncada=truncada, evidencia=ev)
