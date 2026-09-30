"""Tool FQ4.3 `quant.regimes` em shadow mode.

Compara o comportamento histórico de um ativo entre dois regimes explícitos do driver. A v1 usa
regras auditáveis de nível ou direção; não faz clustering, otimização de threshold, causalidade ou
previsão.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import series as market_series
from app.market.analytics import conditional as quant_conditional
from app.market.analytics import models as quant_models
from app.market.analytics import regimes as quant_regimes
from app.market.analytics import returns as quant_returns
from app.market.analytics import statistics as quant_statistics
from app.market.series import PriceBasis, ResolvedMarketSeries, TemporalSemantics
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (
    FORA_DA_COBERTURA,
    INDICE_DESCONHECIDO,
    INSTRUMENTO_DESCONHECIDO,
    NOTA_RCVM,
    SEM_DADOS,
    Evidencia,
    Janela,
    avisos_de_qualidade,
    carregar_indice_resolvido,
    carregar_serie_resolvida,
    data_referencia,
    instrumento_por_termo,
    janela_padrao,
    resolver_cutoff,
)
from app.tools.executor import ToolContext
from app.tools.registry import tool


DriverType = Literal["ativo", "indice"]
CriterionParam = Literal["nivel", "direcao"]
RegimeOutputLabel = Literal["alto", "baixo", "alta", "queda"]
ThresholdUnit = Literal["retorno_pct", "pontos_percentuais", "nivel_driver"]

REGIME_SEM_DUAS_AMOSTRAS = "regime_sem_duas_amostras"
REGIME_AMOSTRA_INSUFICIENTE = "regime_amostra_insuficiente"


class RegimesParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, description="Ativo cuja resposta histórica será comparada entre regimes.")
    ticker_driver: str | None = Field(
        default=None,
        description="Ativo que define o regime. Use exatamente um entre ticker_driver e indice_driver.",
    )
    indice_driver: str | None = Field(
        default=None,
        description="Índice/taxa que define o regime, por exemplo Selic, IPCA ou um índice em pontos.",
    )
    criterio: CriterionParam = Field(
        description=("nivel: compara alto vs baixo; direcao: compara alta vs queda. O critério é explícito e "
                     "não usa clustering ou threshold otimizado."),
    )
    limiar: float | None = Field(
        default=None,
        allow_inf_nan=False,
        description=("Corte opcional. Em nivel, usa a unidade original do driver; se omitido, usa a mediana "
                     "histórica da amostra. Em direcao, usa p.p. de retorno para ativos/índices em pontos ou "
                     "p.p. de mudança de nível para taxas; se omitido, usa zero."),
    )
    janela_dias: int | None = Field(default=None, ge=1, description="Janela em dias corridos; quando omitida usa ANALISE_PARAMS.")
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
    def _validar(self) -> "RegimesParams":
        if (self.ticker_driver is None) == (self.indice_driver is None):
            raise ValueError("informe exatamente um: ticker_driver ou indice_driver")
        if self.criterio == "direcao" and self.limiar is not None and self.limiar < 0:
            raise ValueError("limiar de direcao deve ser >= 0")
        return self


class RegimesResolvida(BaseModel):
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
    criterio: quant_regimes.RegimeCriterion
    limiar_interface: float | None = Field(default=None, allow_inf_nan=False)
    min_observacoes: int = Field(ge=1)
    max_dias_defasagem: int = Field(ge=0)

    @model_validator(mode="after")
    def _coerencia(self) -> "RegimesResolvida":
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
        if self.criterio == quant_regimes.RegimeCriterion.DIRECTION:
            if self.limiar_interface is not None and self.limiar_interface < 0:
                raise ValueError("limiar de direção deve ser >= 0")
        return self


class RegimeGroupOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotulo: RegimeOutputLabel
    n: int = Field(ge=0)
    media_pct: float | None = Field(default=None, allow_inf_nan=False)
    mediana_pct: float | None = Field(default=None, allow_inf_nan=False)
    desvio_amostral_pct: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    minimo_pct: float | None = Field(default=None, allow_inf_nan=False)
    maximo_pct: float | None = Field(default=None, allow_inf_nan=False)
    taxa_positiva_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class RegimesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    driver: str
    tipo_driver: DriverType
    criterio: quant_regimes.RegimeCriterion
    medida_driver: quant_models.ConditionMeasure
    unidade_limiar: str
    limiar_usado: float | None = Field(default=None, allow_inf_nan=False)
    origem_limiar: quant_regimes.ThresholdSource
    price_basis_ativos: PriceBasis
    temporal_semantics_ativos: TemporalSemantics
    periodo: Janela
    n_total: int = Field(ge=0)
    n_neutro: int = Field(ge=0)
    grupos: list[RegimeGroupOutput] = Field(min_length=2, max_length=2)
    diferenca_media_pct_pontos: float | None = Field(default=None, allow_inf_nan=False)
    diferenca_desvio_pct_pontos: float | None = Field(default=None, allow_inf_nan=False)
    evidencia: Evidencia


def _driver_measure(tipo: DriverType, unidade: str) -> quant_models.ConditionMeasure:
    if tipo == "ativo" or unidade == quant_models.IndexUnit.POINTS.value:
        return quant_models.ConditionMeasure.RETURN
    return quant_models.ConditionMeasure.LEVEL_CHANGE


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _internal_threshold(
    criterion: quant_regimes.RegimeCriterion,
    measure: quant_models.ConditionMeasure,
    interface_value: float | None,
) -> float | None:
    if interface_value is None:
        return None
    if criterion == quant_regimes.RegimeCriterion.DIRECTION and measure == quant_models.ConditionMeasure.RETURN:
        return interface_value / 100.0
    return interface_value


def _threshold_for_output(
    criterion: quant_regimes.RegimeCriterion,
    measure: quant_models.ConditionMeasure,
    value: float | None,
) -> float | None:
    if value is None:
        return None
    if criterion == quant_regimes.RegimeCriterion.DIRECTION and measure == quant_models.ConditionMeasure.RETURN:
        return value * 100.0
    return value


def _threshold_unit(
    criterion: quant_regimes.RegimeCriterion,
    measure: quant_models.ConditionMeasure,
    driver_unit: str,
) -> str:
    if criterion == quant_regimes.RegimeCriterion.LEVEL:
        return driver_unit or "nivel_driver"
    return "retorno_pct" if measure == quant_models.ConditionMeasure.RETURN else "pontos_percentuais"


def _label(label: quant_regimes.RegimeLabel) -> RegimeOutputLabel:
    mapping: dict[quant_regimes.RegimeLabel, RegimeOutputLabel] = {
        quant_regimes.RegimeLabel.HIGH: "alto",
        quant_regimes.RegimeLabel.LOW: "baixo",
        quant_regimes.RegimeLabel.UP: "alta",
        quant_regimes.RegimeLabel.DOWN: "queda",
    }
    return mapping[label]


def _group_output(group: quant_regimes.RegimeGroup) -> RegimeGroupOutput:
    s = group.summary
    pct = lambda value: None if value is None else value * 100.0
    return RegimeGroupOutput(
        rotulo=_label(group.label),
        n=s.count,
        media_pct=pct(s.mean),
        mediana_pct=pct(s.median),
        desvio_amostral_pct=pct(s.sample_stddev),
        minimo_pct=pct(s.minimum),
        maximo_pct=pct(s.maximum),
        taxa_positiva_pct=pct(s.positive_fraction),
    )


async def preparar_regimes(params: RegimesParams, ctx: ToolContext) -> RegimesResolvida:
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
            unidade_driver = serie_driver.currency or "preco"
        else:
            unidade_driver = "preco"
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

    measure = _driver_measure(tipo, unidade_driver)
    criterion = quant_regimes.RegimeCriterion.LEVEL if params.criterio == "nivel" else quant_regimes.RegimeCriterion.DIRECTION
    ctx.registrar_insumo(
        "market.series",
        ticker=params.ticker,
        ticker_driver=params.ticker_driver,
        indice_driver=params.indice_driver,
        criterio=criterion.value,
        limiar=params.limiar,
        n_resposta=serie_resposta.quality.observations if serie_resposta is not None else 0,
        n_driver=serie_driver.quality.observations if serie_driver is not None else 0,
        cutoff=cutoff.isoformat(),
        price_basis=basis.value,
        temporal_semantics=semantics.value,
        medida_driver=measure.value,
    )
    return RegimesResolvida(
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
        medida_driver=measure,
        criterio=criterion,
        limiar_interface=params.limiar,
        min_observacoes=int(cfg["min_observacoes"]),
        max_dias_defasagem=int(cfg["max_dias_defasagem"]),
    )


def _nota_metodo(r: RegimesResolvida, analysis: quant_regimes.RegimeAnalysis) -> str:
    base = (
        "Ativos usam preços ajustados retrospectivamente com corporate actions conhecidas hoje; não é vintage histórico."
        if r.price_basis == PriceBasis.ADJUSTED_CLOSE
        else "Ativos usam fechamento bruto; o cutoff limita a data da observação, mas não garante vintage histórico."
    )
    if r.criterio == quant_regimes.RegimeCriterion.LEVEL:
        threshold_note = (
            "O corte alto/baixo foi a mediana retrospectiva dos níveis do driver no início dos intervalos."
            if analysis.threshold_source == quant_regimes.ThresholdSource.SAMPLE_MEDIAN
            else "O corte alto/baixo foi informado explicitamente."
        )
        driver_note = "O nível do driver no início de cada intervalo classifica o regime."
    else:
        threshold_note = (
            "O limiar alta/queda foi zero."
            if analysis.threshold_source == quant_regimes.ThresholdSource.ZERO_DEFAULT
            else "O limiar simétrico alta/queda foi informado explicitamente."
        )
        driver_note = (
            "A direção do driver é medida por retorno simples."
            if r.medida_driver == quant_models.ConditionMeasure.RETURN
            else "A direção do driver é medida pela mudança do nível."
        )
    return (
        f"{base} {driver_note} {threshold_note} O retorno simples de {r.ticker} é medido nos mesmos intervalos, "
        "usando somente o último preço disponível em ou antes dos endpoints e respeitando a tolerância de "
        "defasagem. Grupos de regime são amostras históricas possivelmente não contíguas; por isso não se calcula "
        f"drawdown por regime. Comparação descritiva não implica causalidade nem previsão. {NOTA_RCVM}"
    )


@tool(
    code="quant.regimes",
    family="quant",
    semver="1.0.0",
    display_name="Regimes históricos",
    description=("Compara o retorno histórico de um ativo entre dois regimes explícitos de outro ativo, índice ou "
                 "taxa: nível alto/baixo ou direção alta/queda. A classificação é auditável e não usa clustering, "
                 "threshold otimizado, causalidade ou previsão."),
    preparar=preparar_regimes,
    source_dependencies=(
        comum_module.__file__, market_series.__file__, quant_models.__file__, quant_returns.__file__,
        quant_statistics.__file__, quant_conditional.__file__, quant_regimes.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=False,
)
def calcular_regimes(r: RegimesResolvida) -> RegimesOutput:
    response_points = r.serie_resposta.points if r.serie_resposta is not None else []
    driver_points = r.serie_driver.points if r.serie_driver is not None else []
    observations = (
        quant_regimes.driver_observations(
            driver_points, criterion=r.criterio, direction_measure=r.medida_driver,
        )
        if len(driver_points) >= 2 else []
    )
    pairs = (
        quant_regimes.align_response_intervals(
            response_points, observations, max_endpoint_gap_days=r.max_dias_defasagem,
        )
        if response_points else []
    )
    internal_threshold = _internal_threshold(r.criterio, r.medida_driver, r.limiar_interface)
    analysis = quant_regimes.analyze_regimes(
        pairs, criterion=r.criterio, threshold=internal_threshold,
    )

    as_of = pairs[-1].driver_end_date if pairs else None
    suficiente_base, quality_warnings = avisos_de_qualidade(
        as_of, r.cutoff_date, analysis.n_total,
        min_observacoes=r.min_observacoes,
        max_dias_defasagem=r.max_dias_defasagem,
    )
    avisos = list(quality_warnings)
    n1 = analysis.group_1.summary.count
    n2 = analysis.group_2.summary.count
    if analysis.n_total > 0:
        avisos = [a for a in avisos if a != SEM_DADOS]
    if n1 == 0 or n2 == 0:
        avisos.append(REGIME_SEM_DUAS_AMOSTRAS)
    elif n1 < r.min_observacoes or n2 < r.min_observacoes:
        avisos.append(REGIME_AMOSTRA_INSUFICIENTE)
    suficiente = suficiente_base and n1 >= r.min_observacoes and n2 >= r.min_observacoes

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

    groups = [_group_output(analysis.group_1), _group_output(analysis.group_2)]
    period = Janela(
        de=pairs[0].driver_start_date if pairs else None,
        ate=pairs[-1].driver_end_date if pairs else None,
        n=analysis.n_total,
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

    threshold_output = _threshold_for_output(r.criterio, r.medida_driver, analysis.threshold)
    mean_diff = None if analysis.mean_difference is None else analysis.mean_difference * 100.0
    std_diff = None if analysis.sample_stddev_difference is None else analysis.sample_stddev_difference * 100.0
    evidence_metrics = {
        "n_total": float(analysis.n_total),
        "n_neutro": float(analysis.n_neutral),
        "n_regime_1": float(groups[0].n),
        "n_regime_2": float(groups[1].n),
        "retorno_medio_regime_1_pct": groups[0].media_pct,
        "retorno_medio_regime_2_pct": groups[1].media_pct,
        "diferenca_media_pct_pontos": mean_diff,
        "diferenca_desvio_pct_pontos": std_diff,
        "limiar_usado": threshold_output,
    }
    evidencia = Evidencia(
        fonte="+".join(fontes) or "market",
        instrument_ids=instrument_ids,
        tickers=tickers,
        index_codes=index_codes,
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=analysis.n_total,
        lacunas=lacunas,
        metodo=f"regimes_{r.criterio.value}_{r.medida_driver.value}_{analysis.threshold_source.value}",
        nota_metodo=_nota_metodo(r, analysis),
        suficiente=suficiente,
        avisos=avisos,
        metricas=evidence_metrics,
        ingestion_batch_ids=lotes,
    )
    return RegimesOutput(
        ticker=r.ticker,
        driver=r.driver,
        tipo_driver=r.tipo_driver,
        criterio=r.criterio,
        medida_driver=r.medida_driver,
        unidade_limiar=_threshold_unit(r.criterio, r.medida_driver, r.unidade_driver),
        limiar_usado=threshold_output,
        origem_limiar=analysis.threshold_source,
        price_basis_ativos=r.price_basis,
        temporal_semantics_ativos=r.temporal_semantics,
        periodo=period,
        n_total=analysis.n_total,
        n_neutro=analysis.n_neutral,
        grupos=groups,
        diferenca_media_pct_pontos=mean_diff,
        diferenca_desvio_pct_pontos=std_diff,
        evidencia=evidencia,
    )
