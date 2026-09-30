"""Tool FQ4.2 `quant.sensibilidade` em canônica mode.

Estima associação linear histórica entre a mudança de um driver e o retorno de um ativo nos mesmos
intervalos. O ponto é OLS; a incerteza usa HAC/Newey–West. Não implica causalidade ou previsão.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import series as market_series
from app.market.analytics import conditional as quant_conditional
from app.market.analytics import estimates as quant_estimates
from app.market.analytics import models as quant_models
from app.market.analytics import regression as quant_regression
from app.market.analytics import returns as quant_returns
from app.market.analytics import sensitivity as quant_sensitivity
from app.market.series import PriceBasis, ResolvedMarketSeries, TemporalSemantics
from app.tools.analista import _comum as comum_module
from app.tools.analista import evidencia_estatistica as evidencia_estatistica_module
from app.tools.analista._comum import (
    FORA_DA_COBERTURA,
    INDICE_DESCONHECIDO,
    INSTRUMENTO_DESCONHECIDO,
    NOTA_RCVM,
    SEM_DADOS,
    SERIE_CURTA,
    Janela,
    avisos_de_qualidade,
    carregar_indice_resolvido,
    carregar_serie_resolvida,
    data_referencia,
    instrumento_por_termo,
    janela_padrao,
    resolver_cutoff,
)
from app.tools.analista.evidencia_estatistica import EvidenciaEstatistica
from app.tools.executor import ToolContext
from app.tools.registry import tool


DriverType = Literal["ativo", "indice"]
DriverVariationUnit = Literal["retorno_pct", "pontos_percentuais"]


class SensibilidadeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, description="Ativo cuja resposta histórica será medida.")
    ticker_driver: str | None = Field(
        default=None,
        description="Ativo usado como driver. Use exatamente um entre ticker_driver e indice_driver.",
    )
    indice_driver: str | None = Field(
        default=None,
        description="Índice/taxa usado como driver, por exemplo Selic, CDI ou um índice em pontos.",
    )
    janela_dias: int | None = Field(
        default=None, ge=1,
        description="Janela em dias corridos; quando omitida usa ANALISE_PARAMS.",
    )
    de: date | None = Field(default=None, description="Início explícito da janela.")
    ate: date | None = Field(default=None, description="Fim explícito; nunca passa da data de referência.")
    data_referencia: date | None = Field(
        default=None,
        description=("Cutoff pela data da observação. Não usa observações posteriores, mas não garante vintage "
                     "histórico contra backfills/revisões."),
    )
    price_basis: PriceBasis = Field(
        default=PriceBasis.ADJUSTED_CLOSE,
        description=("Base aplicada aos ativos. adjusted_close é retrospectivo e evita corporate actions como "
                     "saltos mecânicos; raw_close usa o fechamento publicado. Não se aplica a índice/taxa."),
    )

    @model_validator(mode="after")
    def _um_driver(self) -> "SensibilidadeParams":
        if (self.ticker_driver is None) == (self.indice_driver is None):
            raise ValueError("informe exatamente um: ticker_driver ou indice_driver")
        return self


class SensibilidadeResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    driver: str
    tipo_driver: DriverType
    instrument_id: str | None
    driver_instrument_id: str | None = None
    response_in_universe: bool
    driver_in_universe: bool
    driver_found: bool = True
    driver_index_code: str | None = None
    cutoff_date: date
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    serie_resposta: ResolvedMarketSeries | None
    serie_driver: ResolvedMarketSeries | None
    unidade_driver: str = "pontos"
    medida_driver: quant_models.ConditionMeasure
    min_observacoes: int = Field(ge=1)
    max_dias_defasagem: int = Field(ge=0)

    @model_validator(mode="after")
    def _coerencia(self) -> "SensibilidadeResolvida":
        esperado = market_series.temporal_semantics_for_price_basis(self.price_basis)
        if self.temporal_semantics != esperado:
            raise ValueError("temporal_semantics incompatível com price_basis")
        for label, serie, iid in (
            ("resposta", self.serie_resposta, self.instrument_id),
            ("driver", self.serie_driver if self.tipo_driver == "ativo" else None, self.driver_instrument_id),
        ):
            if serie is None:
                continue
            if serie.provenance.price_basis != self.price_basis:
                raise ValueError(f"price_basis da série de {label} diverge do resolvido")
            if serie.provenance.temporal_semantics != self.temporal_semantics:
                raise ValueError(f"temporal_semantics da série de {label} diverge do resolvido")
            if iid is not None and serie.instrument_id != iid:
                raise ValueError(f"instrument_id da série de {label} diverge do resolvido")
        if self.tipo_driver == "indice" and self.serie_driver is not None:
            if self.serie_driver.provenance.price_basis is not None:
                raise ValueError("índice/taxa não pode carregar price_basis")
            if self.serie_driver.provenance.temporal_semantics != TemporalSemantics.OBSERVATION_DATE_CUTOFF:
                raise ValueError("índice/taxa deve usar observation_date_cutoff")
            if self.driver_index_code is not None and self.serie_driver.index_code != self.driver_index_code:
                raise ValueError("index_code do driver diverge do resolvido")
        if self.medida_driver != _driver_measure(self.tipo_driver, self.unidade_driver):
            raise ValueError("medida_driver incompatível com o tipo/unidade do driver")
        return self


class SensibilidadeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    driver: str
    tipo_driver: DriverType
    medida_driver: quant_models.ConditionMeasure
    unidade_variacao_driver: DriverVariationUnit
    price_basis_ativos: PriceBasis
    temporal_semantics_ativos: TemporalSemantics
    periodo: Janela
    n: int = Field(ge=0)
    sensibilidade: quant_estimates.MetricEstimate
    r_squared: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    hac_lags: int = Field(ge=0)
    confidence_level: float = Field(gt=0, lt=1, allow_inf_nan=False)
    covariance_method: str
    intervalo_dias_min: int | None = Field(default=None, ge=1)
    intervalo_dias_mediana: float | None = Field(default=None, ge=1, allow_inf_nan=False)
    intervalo_dias_max: int | None = Field(default=None, ge=1)
    outlier_policy: str
    evidencia: EvidenciaEstatistica


def _driver_measure(tipo: DriverType, unidade: str) -> quant_models.ConditionMeasure:
    if tipo == "ativo" or unidade == quant_models.IndexUnit.POINTS.value:
        return quant_models.ConditionMeasure.RETURN
    return quant_models.ConditionMeasure.LEVEL_CHANGE


def _variation_unit(measure: quant_models.ConditionMeasure) -> DriverVariationUnit:
    return "retorno_pct" if measure == quant_models.ConditionMeasure.RETURN else "pontos_percentuais"


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


async def preparar_sensibilidade(params: SensibilidadeParams, ctx: ToolContext) -> SensibilidadeResolvida:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = janela_padrao(
        cutoff, params.de, params.ate,
        janela_dias=int(params.janela_dias or cfg["janela_padrao_dias"]),
    )
    basis = params.price_basis
    semantics = market_series.temporal_semantics_for_price_basis(basis)

    inst = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    response_in_universe = bool(inst is not None and inst["is_in_universe"])
    serie_resposta = None
    if response_in_universe and inst is not None:
        serie_resposta = await carregar_serie_resolvida(
            ctx.conn, inst["instrument_id"], de=de, ate=ate, cutoff=cutoff,
            codigo=inst["ticker"] or params.ticker, basis=basis,
            temporal_semantics=semantics, include_calendar=True,
        )

    tipo: DriverType
    driver_inst = None
    driver_index_code = None
    driver_found = False
    driver_in_universe = False
    serie_driver = None
    unidade_driver = "pontos"
    if params.ticker_driver is not None:
        tipo = "ativo"
        driver_inst = await instrumento_por_termo(ctx.conn, params.ticker_driver, cutoff=cutoff)
        driver_found = driver_inst is not None
        driver_in_universe = bool(driver_inst is not None and driver_inst["is_in_universe"])
        if driver_in_universe and driver_inst is not None:
            serie_driver = await carregar_serie_resolvida(
                ctx.conn, driver_inst["instrument_id"], de=de, ate=ate, cutoff=cutoff,
                codigo=driver_inst["ticker"] or params.ticker_driver, basis=basis,
                temporal_semantics=semantics, include_calendar=True,
            )
        driver = driver_inst["ticker"] if driver_inst and driver_inst.get("ticker") else params.ticker_driver
    else:
        tipo = "indice"
        driver_index_code = params.indice_driver.lower()
        driver = driver_index_code
        try:
            serie_driver = await carregar_indice_resolvido(
                ctx.conn, driver_index_code, de=de, ate=ate, cutoff=cutoff, include_calendar=True,
            )
            driver_found = True
            unidade_driver = serie_driver.unit or "pontos"
        except market_series.UnknownIndex:
            driver_found = False

    medida = _driver_measure(tipo, unidade_driver)
    ctx.registrar_insumo(
        "market.series",
        ticker=params.ticker,
        ticker_driver=params.ticker_driver,
        indice_driver=params.indice_driver,
        n_resposta=serie_resposta.quality.observations if serie_resposta is not None else 0,
        n_driver=serie_driver.quality.observations if serie_driver is not None else 0,
        cutoff=cutoff.isoformat(),
        price_basis=basis.value,
        temporal_semantics=semantics.value,
        medida_driver=medida.value,
        covariance_method=quant_regression.METHOD,
        confidence_level=0.95,
    )
    return SensibilidadeResolvida(
        ticker=inst["ticker"] if inst and inst.get("ticker") else params.ticker,
        driver=driver,
        tipo_driver=tipo,
        instrument_id=inst["instrument_id"] if inst else None,
        driver_instrument_id=driver_inst["instrument_id"] if driver_inst else None,
        response_in_universe=response_in_universe,
        driver_in_universe=driver_in_universe,
        driver_found=driver_found,
        driver_index_code=driver_index_code,
        cutoff_date=cutoff,
        price_basis=basis,
        temporal_semantics=semantics,
        serie_resposta=serie_resposta,
        serie_driver=serie_driver,
        unidade_driver=unidade_driver,
        medida_driver=medida,
        min_observacoes=int(cfg["min_observacoes"]),
        max_dias_defasagem=int(cfg["max_dias_defasagem"]),
    )


def _nota_metodo(r: SensibilidadeResolvida, hac_lags: int) -> str:
    base = (
        "Ativos usam preços ajustados retrospectivamente com corporate actions conhecidas hoje; não é vintage histórico."
        if r.price_basis == PriceBasis.ADJUSTED_CLOSE
        else "Ativos usam fechamento bruto; o cutoff limita a data da observação, mas não garante vintage histórico."
    )
    driver = (
        "O driver é medido por retorno simples em pontos percentuais."
        if r.medida_driver == quant_models.ConditionMeasure.RETURN
        else "O driver é medido pela mudança do nível em pontos percentuais."
    )
    return (
        f"{base} {driver} O retorno simples de {r.ticker} é medido nos mesmos intervalos do driver, usando "
        "somente o último preço disponível em ou antes de cada endpoint e respeitando a tolerância de defasagem. "
        "A sensibilidade é o slope de OLS univariada com intercepto; erro-padrão e intervalo de confiança usam "
        f"HAC/Newey-West Bartlett com {hac_lags} lag(s) em observações e correção n/(n-k), CI bilateral de 95% "
        "por aproximação normal assintótica. Não há imputação, winsorização ou remoção automática de outliers. "
        f"Associação histórica não implica causalidade nem previsão. {NOTA_RCVM}"
    )


@tool(
    code="quant.sensibilidade",
    family="quant",
    semver="1.0.1",
    display_name="Sensibilidade histórica",
    description=("Estima a associação linear histórica entre a mudança de um ativo, índice ou taxa e o retorno de "
                 "outro ativo nos mesmos intervalos. OLS com incerteza HAC/Newey-West; não implica causalidade, "
                 "significância decisória ou previsão."),
    preparar=preparar_sensibilidade,
    source_dependencies=(
        comum_module.__file__, evidencia_estatistica_module.__file__, market_series.__file__,
        quant_models.__file__, quant_returns.__file__, quant_conditional.__file__,
        quant_estimates.__file__, quant_regression.__file__, quant_sensitivity.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=True,
)
def calcular_sensibilidade(r: SensibilidadeResolvida) -> SensibilidadeOutput:
    response_points = r.serie_resposta.points if r.serie_resposta is not None else []
    driver_points = r.serie_driver.points if r.serie_driver is not None else []
    changes = (
        quant_conditional.condition_changes(driver_points, measure=r.medida_driver)
        if len(driver_points) >= 2 else []
    )
    pairs = (
        quant_conditional.align_response_intervals(
            response_points, changes, max_endpoint_gap_days=r.max_dias_defasagem,
        )
        if response_points else []
    )
    analysis = quant_sensitivity.analyze_sensitivity(pairs, driver_measure=r.medida_driver)

    as_of = pairs[-1].condition_end_date if pairs else None
    suficiente_base, quality_warnings = avisos_de_qualidade(
        as_of, r.cutoff_date, analysis.n,
        min_observacoes=r.min_observacoes,
        max_dias_defasagem=r.max_dias_defasagem,
    )
    avisos = list(quality_warnings)
    avisos.extend(analysis.slope.warnings)
    suficiente = (
        suficiente_base
        and analysis.slope.estimate is not None
        and analysis.slope.standard_error is not None
        and analysis.slope.confidence_interval is not None
    )

    if r.instrument_id is None:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != SEM_DADOS]
    elif not r.response_in_universe:
        avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != SEM_DADOS]
    if r.tipo_driver == "ativo":
        if r.driver_instrument_id is None:
            avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != SEM_DADOS]
        elif not r.driver_in_universe:
            avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != SEM_DADOS]
    elif not r.driver_found:
        avisos = [INDICE_DESCONHECIDO] + [a for a in avisos if a != SEM_DADOS]

    series = [s for s in (r.serie_resposta, r.serie_driver) if s is not None]
    for serie in series:
        avisos.extend(serie.provenance.warnings)
    avisos = _unique(avisos)

    period = Janela(
        de=pairs[0].condition_start_date if pairs else None,
        ate=pairs[-1].condition_end_date if pairs else None,
        n=analysis.n,
    )
    instrument_ids = [x for x in (
        r.instrument_id,
        r.driver_instrument_id if r.tipo_driver == "ativo" else None,
    ) if x]
    tickers = [r.ticker] + ([r.driver] if r.tipo_driver == "ativo" else [])
    index_codes = ([r.driver_index_code]
                   if r.tipo_driver == "indice" and r.driver_found and r.driver_index_code else [])
    fontes = sorted({src for serie in series for src in serie.provenance.source_codes if src})
    lotes = sorted({batch for serie in series for batch in serie.provenance.ingestion_batch_ids if batch})
    lacunas = sorted({d for serie in series for d in serie.quality.missing_dates})

    evidencia = EvidenciaEstatistica(
        fonte="+".join(fontes) or "market",
        instrument_ids=instrument_ids,
        tickers=tickers,
        index_codes=index_codes,
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=analysis.n,
        lacunas=lacunas,
        metodo=f"sensibilidade_{analysis.covariance_method}_{r.medida_driver.value}",
        nota_metodo=_nota_metodo(r, analysis.hac_lags),
        suficiente=suficiente,
        avisos=avisos,
        metricas={
            "n_pares": float(analysis.n),
            "r_squared": analysis.r_squared,
            "hac_lags": float(analysis.hac_lags),
            "confidence_level": analysis.confidence_level,
            "interval_days_min": float(analysis.interval_days_min) if analysis.interval_days_min is not None else None,
            "interval_days_median": analysis.interval_days_median,
            "interval_days_max": float(analysis.interval_days_max) if analysis.interval_days_max is not None else None,
        },
        ingestion_batch_ids=lotes,
        estimativas={
            "sensibilidade": analysis.slope,
            "intercepto": analysis.intercept,
        },
    )
    return SensibilidadeOutput(
        ticker=r.ticker,
        driver=r.driver,
        tipo_driver=r.tipo_driver,
        medida_driver=r.medida_driver,
        unidade_variacao_driver=_variation_unit(r.medida_driver),
        price_basis_ativos=r.price_basis,
        temporal_semantics_ativos=r.temporal_semantics,
        periodo=period,
        n=analysis.n,
        sensibilidade=analysis.slope,
        r_squared=analysis.r_squared,
        hac_lags=analysis.hac_lags,
        confidence_level=analysis.confidence_level,
        covariance_method=analysis.covariance_method,
        intervalo_dias_min=analysis.interval_days_min,
        intervalo_dias_mediana=analysis.interval_days_median,
        intervalo_dias_max=analysis.interval_days_max,
        outlier_policy=analysis.outlier_policy,
        evidencia=evidencia,
    )
