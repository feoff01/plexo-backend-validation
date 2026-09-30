"""Tool shadow `quant.event_study_v2` (FQ4.4).

A v2 migra o estudo de evento para MarketSeriesLoader + Quant Core sem tocar na implementação
registrada `quant.event_study` 1.0.1. O cutover canônico é uma etapa separada.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import series as market_series
from app.market.analytics import dependence as quant_dependence
from app.market.analytics import estimates as quant_estimates
from app.market.analytics import event_study as quant_event_study
from app.market.analytics import models as quant_models
from app.market.analytics import regression as quant_regression
from app.market.analytics import returns as quant_returns
from app.market.series import PriceBasis, ResolvedMarketSeries, TemporalSemantics
from app.tools.analista import _comum as comum_module
from app.tools.analista import evidencia_estatistica as evidencia_estatistica_module
from app.tools.analista._comum import (
    EVENTO_AJUSTADO,
    FORA_DA_COBERTURA,
    INSTRUMENTO_DESCONHECIDO,
    JANELA_POS_TRUNCADA,
    NOTA_RCVM,
    SERIE_CURTA,
    Janela,
    carregar_serie_resolvida,
    data_referencia,
    instrumento_por_termo,
    resolver_cutoff,
)
from app.tools.analista.evidencia_estatistica import EvidenciaEstatistica
from app.tools.executor import ToolContext
from app.tools.registry import tool


JANELA_PRE_TRUNCADA = "janela_pre_truncada"


class EventStudyV2Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="Ticker do ativo analisado.")
    data_evento: date = Field(
        description="Data civil do evento. A data efetiva será o primeiro retorno comum ativo×benchmark nessa data ou depois."
    )
    benchmark: str | None = Field(default=None, description="Ticker do benchmark; quando omitido usa ANALISE_PARAMS.")
    metodo: quant_event_study.EventStudyMethod | None = Field(
        default=None, description="market_model ou market_adjusted; quando omitido usa ANALISE_PARAMS."
    )
    janela_estimacao_observacoes: int | None = Field(
        default=None, ge=2,
        description="Número de retornos alinhados na janela de estimação; quando omitido usa a policy de event study.",
    )
    pre_observacoes: int | None = Field(
        default=None, ge=0, description="Retornos alinhados antes do evento incluídos na janela de evento."
    )
    pos_observacoes: int | None = Field(
        default=None, ge=0, description="Retornos alinhados depois do evento incluídos na janela de evento."
    )
    inferencia: quant_event_study.EventInferenceMode = Field(
        default=quant_event_study.EventInferenceMode.NONE,
        description=("none mantém o estudo descritivo. classic_iid_normal adiciona erro-padrão/CI do CAR sob "
                     "hipóteses clássicas iid/homoscedásticas explícitas; não produz p-value nem rótulo de significância."),
    )
    price_basis: PriceBasis = Field(
        default=PriceBasis.ADJUSTED_CLOSE,
        description=("Base dos preços do ativo e benchmark. adjusted_close é retrospectivo com corporate actions "
                     "conhecidas hoje; raw_close limita apenas pela data da observação."),
    )
    data_referencia: date | None = Field(
        default=None,
        description=("Cutoff pela data da observação. Nada datado depois entra, mas isso não garante vintage histórico "
                     "contra backfills/revisões posteriores."),
    )


class EventStudyV2Resolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    benchmark: str
    instrument_ids: list[str]
    ticker_found: bool
    benchmark_found: bool
    ticker_in_universe: bool
    benchmark_in_universe: bool
    cutoff_date: date
    data_evento: date
    serie_ativo: ResolvedMarketSeries | None
    serie_benchmark: ResolvedMarketSeries | None
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    metodo: quant_event_study.EventStudyMethod
    metodo_retorno: quant_models.ReturnMethod
    inferencia: quant_event_study.EventInferenceMode
    janela_estimacao_observacoes: int = Field(ge=2)
    pre_observacoes: int = Field(ge=0)
    pos_observacoes: int = Field(ge=0)
    min_observacoes: int = Field(ge=1)

    @model_validator(mode="after")
    def _coerencia(self) -> "EventStudyV2Resolvido":
        esperado = market_series.temporal_semantics_for_price_basis(self.price_basis)
        if self.temporal_semantics != esperado:
            raise ValueError("temporal_semantics incompatível com price_basis")
        for serie in (self.serie_ativo, self.serie_benchmark):
            if serie is None:
                continue
            if serie.provenance.price_basis != self.price_basis:
                raise ValueError("price_basis da série diverge do resolvido")
            if serie.provenance.temporal_semantics != self.temporal_semantics:
                raise ValueError("temporal_semantics da série diverge do resolvido")
        return self


class RetornoAnormalV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    ar_pct: float = Field(allow_inf_nan=False)


class EventStudyV2Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    benchmark: str
    data_evento: date
    data_evento_efetiva: date | None
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    metodo: quant_event_study.EventStudyMethod
    metodo_retorno: quant_models.ReturnMethod
    inferencia: quant_event_study.EventInferenceMode
    alpha: float | None = Field(default=None, allow_inf_nan=False)
    beta: float | None = Field(default=None, allow_inf_nan=False)
    ar: list[RetornoAnormalV2]
    car_pct: float | None = Field(default=None, allow_inf_nan=False)
    car_estimate: quant_estimates.MetricEstimate | None = None
    desvio_residuos_pct: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    janela_estimacao: Janela
    janela_evento: Janela
    truncada_pre: bool
    truncada_pos: bool
    evidencia: EvidenciaEstatistica


async def preparar_event_study_v2(params: EventStudyV2Params, ctx: ToolContext) -> EventStudyV2Resolvido:
    cfg = await ctx.policy("ANALISE_PARAMS")
    es = cfg["event_study"]
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    benchmark = params.benchmark or cfg["benchmark_padrao"]
    basis = params.price_basis
    semantics = market_series.temporal_semantics_for_price_basis(basis)
    janela_est = int(params.janela_estimacao_observacoes or es["janela_estimacao_dias"])
    pre = int(es["pre_dias"] if params.pre_observacoes is None else params.pre_observacoes)
    pos = int(es["pos_dias"] if params.pos_observacoes is None else params.pos_observacoes)
    metodo = params.metodo or quant_event_study.EventStudyMethod(es["metodo"])

    inst_a = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    inst_b = await instrumento_por_termo(ctx.conn, benchmark, cutoff=cutoff)
    in_a = bool(inst_a is not None and inst_a["is_in_universe"])
    in_b = bool(inst_b is not None and inst_b["is_in_universe"])
    serie_a: ResolvedMarketSeries | None = None
    serie_b: ResolvedMarketSeries | None = None

    # Correctness-first: sem API de lookback por contagem ainda, carregamos toda a história disponível
    # do instrumento até o cutoff. `include_calendar=False` evita materializar calendário multi-década.
    if in_a and inst_a is not None:
        serie_a = await carregar_serie_resolvida(
            ctx.conn, inst_a["instrument_id"], de=date.min, ate=cutoff, cutoff=cutoff,
            codigo=inst_a["ticker"] or params.ticker, basis=basis,
            temporal_semantics=semantics, include_calendar=False,
        )
    if in_b and inst_b is not None:
        serie_b = await carregar_serie_resolvida(
            ctx.conn, inst_b["instrument_id"], de=date.min, ate=cutoff, cutoff=cutoff,
            codigo=inst_b["ticker"] or benchmark, basis=basis,
            temporal_semantics=semantics, include_calendar=False,
        )

    instrument_ids = [x["instrument_id"] for x in (inst_a, inst_b) if x is not None]
    ctx.registrar_insumo(
        "market.series",
        ticker=params.ticker,
        benchmark=benchmark,
        data_evento=params.data_evento.isoformat(),
        n_ativo=serie_a.quality.observations if serie_a is not None else 0,
        n_benchmark=serie_b.quality.observations if serie_b is not None else 0,
        cutoff=cutoff.isoformat(),
        price_basis=basis.value,
        temporal_semantics=semantics.value,
        metodo=str(metodo),
        inferencia=params.inferencia.value,
    )
    return EventStudyV2Resolvido(
        ticker=inst_a["ticker"] if inst_a and inst_a.get("ticker") else params.ticker,
        benchmark=inst_b["ticker"] if inst_b and inst_b.get("ticker") else benchmark,
        instrument_ids=instrument_ids,
        ticker_found=inst_a is not None,
        benchmark_found=inst_b is not None,
        ticker_in_universe=in_a,
        benchmark_in_universe=in_b,
        cutoff_date=cutoff,
        data_evento=params.data_evento,
        serie_ativo=serie_a,
        serie_benchmark=serie_b,
        price_basis=basis,
        temporal_semantics=semantics,
        metodo=quant_event_study.EventStudyMethod(metodo),
        metodo_retorno=quant_models.ReturnMethod(cfg["metodo_retorno"]),
        inferencia=params.inferencia,
        janela_estimacao_observacoes=janela_est,
        pre_observacoes=pre,
        pos_observacoes=pos,
        min_observacoes=int(cfg["min_observacoes"]),
    )


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _nota_metodo(r: EventStudyV2Resolvido, analysis: quant_event_study.EventStudyAnalysis) -> str:
    base = (
        "Preços ajustados retrospectivamente com corporate actions conhecidas hoje; não representam vintage histórico."
        if r.price_basis == PriceBasis.ADJUSTED_CLOSE
        else "Fechamentos brutos; o cutoff limita a data da observação, mas não garante vintage histórico."
    )
    infer = (
        "Sem inferência estatística do efeito do evento."
        if r.inferencia == quant_event_study.EventInferenceMode.NONE
        else ("CI do CAR pelo método clássico iid/normal: assume resíduos homoscedásticos e independentes, modelo "
              "corretamente especificado e ausência de mudança de variância induzida pelo evento; não há p-value nem "
              "rótulo automático de significância.")
    )
    return (
        f"{base} Retornos {r.metodo_retorno.value} são alinhados por data comum ativo×benchmark. "
        "A data efetiva é o primeiro retorno comum na data do evento ou depois; a janela de estimação termina antes "
        "da janela de evento, sem overlap. AR = retorno observado − retorno esperado; CAR = soma dos AR da janela. "
        f"{infer} Associação histórica não implica causalidade ou previsão. {NOTA_RCVM}"
    )


@tool(
    code="quant.event_study_v2",
    family="quant",
    semver="1.0.0",
    display_name="Estudo de evento v2",
    description=("Versão shadow do estudo de evento com MarketSeriesLoader/Quant Core. Mede retorno anormal e CAR "
                 "contra benchmark; opcionalmente fornece CI clássico do CAR sob hipóteses iid explícitas. Não gera "
                 "p-value, rótulo de significância, causalidade ou previsão."),
    preparar=preparar_event_study_v2,
    source_dependencies=(
        comum_module.__file__, evidencia_estatistica_module.__file__, market_series.__file__,
        quant_models.__file__, quant_returns.__file__, quant_dependence.__file__, quant_regression.__file__,
        quant_estimates.__file__, quant_event_study.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=False,
)
def calcular_event_study_v2(r: EventStudyV2Resolvido) -> EventStudyV2Output:
    asset_points = r.serie_ativo.points if r.serie_ativo is not None else []
    bench_points = r.serie_benchmark.points if r.serie_benchmark is not None else []
    asset_returns, bench_returns = quant_event_study.synchronized_returns_from_prices(
        asset_points, bench_points, method=r.metodo_retorno,
    ) if len(asset_points) >= 2 and len(bench_points) >= 2 else ([], [])
    analysis = quant_event_study.analyze_event_study(
        asset_returns,
        bench_returns,
        event_date=r.data_evento,
        method=r.metodo,
        estimation_observations=r.janela_estimacao_observacoes,
        pre_observations=r.pre_observacoes,
        post_observations=r.pos_observacoes,
        inference_mode=r.inferencia,
    )

    avisos = list(analysis.warnings)
    if analysis.effective_event_date is not None and analysis.effective_event_date != r.data_evento:
        avisos.append(EVENTO_AJUSTADO)
    if analysis.pre_truncated:
        avisos.append(JANELA_PRE_TRUNCADA)
    if analysis.post_truncated:
        avisos.append(JANELA_POS_TRUNCADA)
    if analysis.estimation_window.count < r.min_observacoes:
        avisos.append(SERIE_CURTA)
    if not r.ticker_found or not r.benchmark_found:
        avisos.append(INSTRUMENTO_DESCONHECIDO)
    if (r.ticker_found and not r.ticker_in_universe) or (r.benchmark_found and not r.benchmark_in_universe):
        avisos.append(FORA_DA_COBERTURA)
    for serie in (r.serie_ativo, r.serie_benchmark):
        if serie is not None:
            avisos.extend(serie.provenance.warnings)
    if analysis.car_estimate is not None:
        avisos.extend(analysis.car_estimate.warnings)
    avisos = _unique(avisos)

    point_available = analysis.car is not None and analysis.alpha is not None and analysis.beta is not None
    suficiente = (
        point_available
        and analysis.estimation_window.count >= r.min_observacoes
        and analysis.event_window.count > 0
        and not analysis.pre_truncated
        and not analysis.post_truncated
        and r.ticker_in_universe
        and r.benchmark_in_universe
    )

    series = [s for s in (r.serie_ativo, r.serie_benchmark) if s is not None]
    fontes = sorted({src for serie in series for src in serie.provenance.source_codes if src})
    lotes = sorted({batch for serie in series for batch in serie.provenance.ingestion_batch_ids if batch})
    lacunas = sorted({d for serie in series for d in serie.quality.missing_dates})
    estimativas = {"car": analysis.car_estimate} if analysis.car_estimate is not None else {}

    evidencia = EvidenciaEstatistica(
        fonte="+".join(fontes) if fontes else "market",
        instrument_ids=r.instrument_ids,
        tickers=[r.ticker, r.benchmark],
        cutoff_date=r.cutoff_date,
        as_of=analysis.event_window.end_date,
        n_observacoes=analysis.estimation_window.count + analysis.event_window.count,
        lacunas=lacunas,
        metodo=f"event_study_v2_{r.metodo.value}_{r.metodo_retorno.value}_{r.inferencia.value}",
        nota_metodo=_nota_metodo(r, analysis),
        suficiente=suficiente,
        avisos=avisos,
        metricas={
            "alpha": analysis.alpha,
            "beta": analysis.beta,
            "car_pct": analysis.car * 100.0 if analysis.car is not None else None,
            "desvio_residuos_pct": analysis.residual_stddev * 100.0 if analysis.residual_stddev is not None else None,
        },
        ingestion_batch_ids=lotes,
        estimativas=estimativas,
    )
    return EventStudyV2Output(
        ticker=r.ticker,
        benchmark=r.benchmark,
        data_evento=r.data_evento,
        data_evento_efetiva=analysis.effective_event_date,
        price_basis=r.price_basis,
        temporal_semantics=r.temporal_semantics,
        metodo=r.metodo,
        metodo_retorno=r.metodo_retorno,
        inferencia=r.inferencia,
        alpha=analysis.alpha,
        beta=analysis.beta,
        ar=[RetornoAnormalV2(data=x.data, ar_pct=x.value * 100.0) for x in analysis.abnormal_returns],
        car_pct=analysis.car * 100.0 if analysis.car is not None else None,
        car_estimate=analysis.car_estimate,
        desvio_residuos_pct=analysis.residual_stddev * 100.0 if analysis.residual_stddev is not None else None,
        janela_estimacao=Janela(
            de=analysis.estimation_window.start_date,
            ate=analysis.estimation_window.end_date,
            n=analysis.estimation_window.count,
        ),
        janela_evento=Janela(
            de=analysis.event_window.start_date,
            ate=analysis.event_window.end_date,
            n=analysis.event_window.count,
        ),
        truncada_pre=analysis.pre_truncated,
        truncada_pos=analysis.post_truncated,
        evidencia=evidencia,
    )
