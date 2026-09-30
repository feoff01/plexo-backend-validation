"""Tool canônica FQ4.1 `quant.analise_condicional`.

Compara o retorno histórico de um ativo nos mesmos intervalos em que outra série subiu ou caiu.
É análise descritiva: não implica causalidade, significância estatística nem previsão.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import series as market_series
from app.market.analytics import conditional as quant_conditional
from app.market.analytics import models as quant_models
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
    SEM_EVENTOS_CONDICAO,
    SERIE_CURTA,
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


DirectionParam = Literal["alta", "queda"]
ConditionType = Literal["ativo", "indice"]
ConditionVariationUnit = Literal["retorno_pct", "pontos_percentuais"]


class AnaliseCondicionalParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="Ativo cuja resposta histórica será medida.")
    ticker_condicao: str | None = Field(
        default=None,
        description="Ativo que define a condição. Use exatamente um entre ticker_condicao e indice_condicao.",
    )
    indice_condicao: str | None = Field(
        default=None,
        description="Índice/taxa que define a condição, por exemplo Selic, CDI ou um índice em pontos.",
    )
    direcao: DirectionParam = Field(
        description="Direção histórica da condicionante: alta ou queda. Valores sem mudança são neutros.",
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
    def _uma_condicionante(self) -> "AnaliseCondicionalParams":
        if (self.ticker_condicao is None) == (self.indice_condicao is None):
            raise ValueError("informe exatamente um: ticker_condicao ou indice_condicao")
        return self


class AnaliseCondicionalResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    condicionante: str
    tipo_condicionante: ConditionType
    instrument_id: str | None
    condition_instrument_id: str | None = None
    response_in_universe: bool
    condition_in_universe: bool
    condition_found: bool = True
    condition_index_code: str | None = None
    cutoff_date: date
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    serie_resposta: ResolvedMarketSeries | None
    serie_condicao: ResolvedMarketSeries | None
    unidade_condicao: str = "pontos"
    medida_condicao: quant_models.ConditionMeasure
    direcao: quant_models.ConditionDirection
    min_observacoes: int = Field(ge=1)
    max_dias_defasagem: int = Field(ge=0)

    @model_validator(mode="after")
    def _coerencia(self) -> "AnaliseCondicionalResolvida":
        esperado = market_series.temporal_semantics_for_price_basis(self.price_basis)
        if self.temporal_semantics != esperado:
            raise ValueError("temporal_semantics incompatível com price_basis")
        for label, serie, iid in (
            ("resposta", self.serie_resposta, self.instrument_id),
            ("condição", self.serie_condicao if self.tipo_condicionante == "ativo" else None,
             self.condition_instrument_id),
        ):
            if serie is None:
                continue
            if serie.provenance.price_basis != self.price_basis:
                raise ValueError(f"price_basis da série de {label} diverge do resolvido")
            if serie.provenance.temporal_semantics != self.temporal_semantics:
                raise ValueError(f"temporal_semantics da série de {label} diverge do resolvido")
            if iid is not None and serie.instrument_id != iid:
                raise ValueError(f"instrument_id da série de {label} diverge do resolvido")
        if self.tipo_condicionante == "indice" and self.serie_condicao is not None:
            if self.serie_condicao.provenance.price_basis is not None:
                raise ValueError("índice/taxa não pode carregar price_basis")
            if self.serie_condicao.provenance.temporal_semantics != TemporalSemantics.OBSERVATION_DATE_CUTOFF:
                raise ValueError("índice/taxa deve usar observation_date_cutoff")
            if self.condition_index_code is not None and self.serie_condicao.index_code != self.condition_index_code:
                raise ValueError("index_code da condicionante diverge do resolvido")
        medida_esperada = _condition_measure(self.tipo_condicionante, self.unidade_condicao)
        if self.medida_condicao != medida_esperada:
            raise ValueError("medida_condicao incompatível com o tipo/unidade da condicionante")
        return self


class ResumoRetornosCondicionais(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = Field(ge=0)
    media_pct: float | None = Field(default=None, allow_inf_nan=False)
    mediana_pct: float | None = Field(default=None, allow_inf_nan=False)
    desvio_amostral_pct: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    minimo_pct: float | None = Field(default=None, allow_inf_nan=False)
    maximo_pct: float | None = Field(default=None, allow_inf_nan=False)
    taxa_positiva_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class AnaliseCondicionalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    condicionante: str
    tipo_condicionante: ConditionType
    direcao: DirectionParam
    medida_condicao: quant_models.ConditionMeasure
    unidade_variacao_condicao: ConditionVariationUnit
    price_basis_ativos: PriceBasis
    temporal_semantics_ativos: TemporalSemantics
    periodo: Janela
    n_total: int = Field(ge=0)
    n_condicional: int = Field(ge=0)
    n_neutros: int = Field(ge=0)
    proporcao_condicao_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    variacao_condicao_media: float | None = Field(default=None, allow_inf_nan=False)
    variacao_condicao_mediana: float | None = Field(default=None, allow_inf_nan=False)
    condicional: ResumoRetornosCondicionais
    base: ResumoRetornosCondicionais
    diferenca_media_pct_pontos: float | None = Field(default=None, allow_inf_nan=False)
    evidencia: Evidencia


def _condition_measure(tipo: ConditionType, unidade: str) -> quant_models.ConditionMeasure:
    if tipo == "ativo" or unidade == quant_models.IndexUnit.POINTS.value:
        return quant_models.ConditionMeasure.RETURN
    return quant_models.ConditionMeasure.LEVEL_CHANGE


def _direction(param: DirectionParam) -> quant_models.ConditionDirection:
    return quant_models.ConditionDirection.UP if param == "alta" else quant_models.ConditionDirection.DOWN


def _direction_output(direction: quant_models.ConditionDirection) -> DirectionParam:
    return "alta" if direction == quant_models.ConditionDirection.UP else "queda"


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _summary_pct(summary: quant_models.ReturnSampleSummary) -> ResumoRetornosCondicionais:
    def pct(value: float | None) -> float | None:
        return None if value is None else value * 100.0
    return ResumoRetornosCondicionais(
        n=summary.count,
        media_pct=pct(summary.mean),
        mediana_pct=pct(summary.median),
        desvio_amostral_pct=pct(summary.sample_stddev),
        minimo_pct=pct(summary.minimum),
        maximo_pct=pct(summary.maximum),
        taxa_positiva_pct=pct(summary.positive_fraction),
    )


def _variation_unit(measure: quant_models.ConditionMeasure) -> ConditionVariationUnit:
    return "retorno_pct" if measure == quant_models.ConditionMeasure.RETURN else "pontos_percentuais"


def _condition_value_for_output(value: float | None, measure: quant_models.ConditionMeasure) -> float | None:
    if value is None:
        return None
    return value * 100.0 if measure == quant_models.ConditionMeasure.RETURN else value


async def preparar_analise_condicional(
    params: AnaliseCondicionalParams,
    ctx: ToolContext,
) -> AnaliseCondicionalResolvida:
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

    tipo: ConditionType
    cond_inst = None
    condition_index_code = None
    condition_found = False
    condition_in_universe = False
    serie_condicao = None
    unidade_condicao = "pontos"
    if params.ticker_condicao is not None:
        tipo = "ativo"
        cond_inst = await instrumento_por_termo(ctx.conn, params.ticker_condicao, cutoff=cutoff)
        condition_found = cond_inst is not None
        condition_in_universe = bool(cond_inst is not None and cond_inst["is_in_universe"])
        if condition_in_universe and cond_inst is not None:
            serie_condicao = await carregar_serie_resolvida(
                ctx.conn, cond_inst["instrument_id"], de=de, ate=ate, cutoff=cutoff,
                codigo=cond_inst["ticker"] or params.ticker_condicao, basis=basis,
                temporal_semantics=semantics, include_calendar=True,
            )
        condicionante = cond_inst["ticker"] if cond_inst and cond_inst.get("ticker") else params.ticker_condicao
    else:
        tipo = "indice"
        condition_index_code = params.indice_condicao.lower()
        condicionante = condition_index_code
        try:
            serie_condicao = await carregar_indice_resolvido(
                ctx.conn, condition_index_code, de=de, ate=ate, cutoff=cutoff, include_calendar=True,
            )
            condition_found = True
            unidade_condicao = serie_condicao.unit or "pontos"
        except market_series.UnknownIndex:
            condition_found = False

    medida = _condition_measure(tipo, unidade_condicao)
    direcao = _direction(params.direcao)
    ctx.registrar_insumo(
        "market.series",
        ticker=params.ticker,
        ticker_condicao=params.ticker_condicao,
        indice_condicao=params.indice_condicao,
        n_resposta=serie_resposta.quality.observations if serie_resposta is not None else 0,
        n_condicao=serie_condicao.quality.observations if serie_condicao is not None else 0,
        cutoff=cutoff.isoformat(),
        price_basis=basis.value,
        temporal_semantics=semantics.value,
        medida_condicao=medida.value,
        direcao=params.direcao,
    )
    return AnaliseCondicionalResolvida(
        ticker=inst["ticker"] if inst and inst.get("ticker") else params.ticker,
        condicionante=condicionante,
        tipo_condicionante=tipo,
        instrument_id=inst["instrument_id"] if inst else None,
        condition_instrument_id=cond_inst["instrument_id"] if cond_inst else None,
        response_in_universe=response_in_universe,
        condition_in_universe=condition_in_universe,
        condition_found=condition_found,
        condition_index_code=condition_index_code,
        cutoff_date=cutoff,
        price_basis=basis,
        temporal_semantics=semantics,
        serie_resposta=serie_resposta,
        serie_condicao=serie_condicao,
        unidade_condicao=unidade_condicao,
        medida_condicao=medida,
        direcao=direcao,
        min_observacoes=int(cfg["min_observacoes"]),
        max_dias_defasagem=int(cfg["max_dias_defasagem"]),
    )


def _nota_metodo(r: AnaliseCondicionalResolvida) -> str:
    base = (
        "Ativos usam preços ajustados retrospectivamente com corporate actions conhecidas hoje; não é vintage histórico."
        if r.price_basis == PriceBasis.ADJUSTED_CLOSE
        else "Ativos usam fechamento bruto; o cutoff limita a data da observação, mas não garante vintage histórico."
    )
    cond = (
        "A condicionante é medida por retorno simples entre níveis consecutivos."
        if r.medida_condicao == quant_models.ConditionMeasure.RETURN
        else "A condicionante é medida pela mudança do nível entre observações consecutivas, em pontos percentuais."
    )
    return (
        f"{base} {cond} Cada observação condicionante define um intervalo; o retorno simples de {r.ticker} "
        "é medido entre o último preço disponível em ou antes de cada endpoint, sem look-ahead. "
        "A amostra condicional é comparada descritivamente com todos os intervalos válidos; não há teste de "
        f"significância, causalidade ou previsão. {NOTA_RCVM}"
    )


@tool(
    code="quant.analise_condicional",
    family="quant",
    semver="1.0.1",
    display_name="Análise condicional",
    description=("Descreve como um ativo se comportou nos mesmos intervalos em que outro ativo, índice ou taxa "
                 "subiu ou caiu. Taxas são condicionadas pela mudança do nível; ativos/índices em pontos pelo "
                 "retorno. Compara a amostra condicional à base histórica sem inferir causalidade ou previsão."),
    preparar=preparar_analise_condicional,
    source_dependencies=(
        comum_module.__file__, market_series.__file__, quant_models.__file__,
        quant_returns.__file__, quant_statistics.__file__, quant_conditional.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=True,
)
def calcular_analise_condicional(r: AnaliseCondicionalResolvida) -> AnaliseCondicionalOutput:
    response_points = r.serie_resposta.points if r.serie_resposta is not None else []
    condition_points = r.serie_condicao.points if r.serie_condicao is not None else []
    changes = (quant_conditional.condition_changes(condition_points, measure=r.medida_condicao)
               if len(condition_points) >= 2 else [])
    pairs = (quant_conditional.align_response_intervals(
        response_points, changes, max_endpoint_gap_days=r.max_dias_defasagem,
    ) if response_points else [])
    analysis = quant_conditional.analyze_conditional_returns(pairs, direction=r.direcao)

    as_of = pairs[-1].condition_end_date if pairs else None
    _, quality_warnings = avisos_de_qualidade(
        as_of, r.cutoff_date, analysis.n_total,
        min_observacoes=1, max_dias_defasagem=r.max_dias_defasagem,
    )
    avisos = list(quality_warnings)
    suficiente = analysis.n_selected >= r.min_observacoes
    if analysis.n_total > 0:
        avisos = [a for a in avisos if a != SEM_DADOS]
        if analysis.n_selected == 0:
            avisos.append(SEM_EVENTOS_CONDICAO)
        elif not suficiente:
            avisos.append(SERIE_CURTA)

    if r.instrument_id is None:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != SEM_DADOS]
    elif not r.response_in_universe:
        avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != SEM_DADOS]
    if r.tipo_condicionante == "ativo":
        if r.condition_instrument_id is None:
            avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != SEM_DADOS]
        elif not r.condition_in_universe:
            avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != SEM_DADOS]
    elif not r.condition_found:
        avisos = [INDICE_DESCONHECIDO] + [a for a in avisos if a != SEM_DADOS]

    series = [s for s in (r.serie_resposta, r.serie_condicao) if s is not None]
    for serie in series:
        avisos.extend(serie.provenance.warnings)
    avisos = _unique(avisos)

    conditional_summary = _summary_pct(analysis.selected)
    baseline_summary = _summary_pct(analysis.baseline)
    condition_mean = _condition_value_for_output(analysis.selected_condition.mean, r.medida_condicao)
    condition_median = _condition_value_for_output(analysis.selected_condition.median, r.medida_condicao)
    mean_difference = None if analysis.mean_difference is None else analysis.mean_difference * 100.0
    proportion = (analysis.n_selected / analysis.n_total * 100.0) if analysis.n_total else None
    period = Janela(
        de=pairs[0].condition_start_date if pairs else None,
        ate=pairs[-1].condition_end_date if pairs else None,
        n=analysis.n_total,
    )

    instrument_ids = [x for x in (
        r.instrument_id,
        r.condition_instrument_id if r.tipo_condicionante == "ativo" else None,
    ) if x]
    tickers = [r.ticker] + ([r.condicionante] if r.tipo_condicionante == "ativo" else [])
    index_codes = ([r.condition_index_code]
                   if r.tipo_condicionante == "indice" and r.condition_found and r.condition_index_code else [])
    fontes = sorted({src for serie in series for src in serie.provenance.source_codes if src})
    lotes = sorted({batch for serie in series for batch in serie.provenance.ingestion_batch_ids if batch})
    lacunas = sorted({d for serie in series for d in serie.quality.missing_dates})

    ev = Evidencia(
        fonte="+".join(fontes) or "market",
        instrument_ids=instrument_ids,
        tickers=tickers,
        index_codes=index_codes,
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=analysis.n_selected,
        lacunas=lacunas,
        metodo=f"analise_condicional_{r.medida_condicao.value}_{r.direcao.value}",
        nota_metodo=_nota_metodo(r),
        suficiente=suficiente,
        avisos=avisos,
        metricas={
            "n_total": float(analysis.n_total),
            "n_condicional": float(analysis.n_selected),
            "retorno_medio_condicional_pct": conditional_summary.media_pct,
            "retorno_mediano_condicional_pct": conditional_summary.mediana_pct,
            "taxa_positiva_condicional_pct": conditional_summary.taxa_positiva_pct,
            "retorno_medio_base_pct": baseline_summary.media_pct,
            "diferenca_media_pct_pontos": mean_difference,
        },
        ingestion_batch_ids=lotes,
    )
    return AnaliseCondicionalOutput(
        ticker=r.ticker,
        condicionante=r.condicionante,
        tipo_condicionante=r.tipo_condicionante,
        direcao=_direction_output(r.direcao),
        medida_condicao=r.medida_condicao,
        unidade_variacao_condicao=_variation_unit(r.medida_condicao),
        price_basis_ativos=r.price_basis,
        temporal_semantics_ativos=r.temporal_semantics,
        periodo=period,
        n_total=analysis.n_total,
        n_condicional=analysis.n_selected,
        n_neutros=analysis.n_neutral,
        proporcao_condicao_pct=proportion,
        variacao_condicao_media=condition_mean,
        variacao_condicao_mediana=condition_median,
        condicional=conditional_summary,
        base=baseline_summary,
        diferenca_media_pct_pontos=mean_difference,
        evidencia=ev,
    )
