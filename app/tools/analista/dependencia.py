"""Tool canônica `quant.dependencia` v2.

A resolução de ativo/índice/FX é compartilhada por ``factor_resolution``. A matemática continua
integralmente no Returns/Dependence Core de FQ3/FQ4; este módulo apenas orquestra e produz evidência.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import factors as market_factors
from app.market import series as market_series
from app.market.analytics import dependence as quant_dependence
from app.market.analytics import models as quant_models
from app.market.analytics import returns as quant_returns
from app.market.series import PriceBasis, TemporalSemantics
from app.tools.analista import _comum as comum_module
from app.tools.analista import factor_resolution as factor_resolution_module
from app.tools.analista._comum import (
    FORA_DA_COBERTURA,
    INDICE_DESCONHECIDO,
    INSTRUMENTO_DESCONHECIDO,
    NOTA_RCVM,
    SERIE_CONSTANTE,
    Evidencia,
    avisos_de_qualidade,
    data_referencia,
    janela_padrao,
    resolver_cutoff,
)
from app.tools.analista.factor_resolution import (
    FATOR_CAMBIO_DESCONHECIDO,
    FactorKind,
    FactorRef,
    ResolvedFactor,
    resolve_factor,
)
from app.tools.executor import ToolContext
from app.tools.registry import tool


class DependenciaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker_a: str = Field(min_length=1, description="Ticker do ativo analisado.")
    serie_b: FactorRef = Field(
        description=("Segunda série: {tipo:'ativo',codigo:'VALE3'}, {tipo:'indice',codigo:'ibov'} ou "
                     "{tipo:'cambio',codigo:'USD/BRL'}.")
    )
    janela_dias: int | None = Field(default=None, ge=1, description="Janela em dias corridos; quando omitida usa ANALISE_PARAMS.")
    de: date | None = Field(default=None, description="Início explícito; substitui a janela padrão.")
    ate: date | None = Field(default=None, description="Fim explícito; nunca passa da data de referência.")
    data_referencia: date | None = Field(
        default=None,
        description=("Cutoff pela data da observação. Não usa observações posteriores, mas não garante vintage "
                     "histórico contra backfills/revisões."),
    )
    price_basis: PriceBasis = Field(
        default=PriceBasis.ADJUSTED_CLOSE,
        description=("Base aplicada aos ativos negociados. adjusted_close é retrospectivo e evita corporate actions "
                     "como saltos mecânicos; raw_close usa o fechamento publicado. Não se aplica a índice/taxa/FX."),
    )
    metodo: quant_models.DependenceMethod = Field(
        default=quant_models.DependenceMethod.PEARSON,
        description="Pearson mede associação linear; Spearman mede associação monotônica por ranks.",
    )
    defasagem_observacoes: int = Field(
        default=0,
        description=("Lag assinado sobre observações comuns: positivo = A antecede B; negativo = B antecede A; "
                     "zero = mesma observação. Não representa dias corridos."),
    )


class DependenciaResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fator_a: ResolvedFactor
    fator_b: ResolvedFactor
    cutoff_date: date
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    metodo: quant_models.DependenceMethod
    defasagem_observacoes: int = 0
    metodo_retorno: quant_models.ReturnMethod
    dias_uteis_ano: int = Field(ge=1)
    min_observacoes: int = Field(ge=1)
    max_dias_defasagem: int = Field(ge=0)

    @model_validator(mode="after")
    def _coerencia(self) -> "DependenciaResolvida":
        if self.fator_a.tipo != "ativo":
            raise ValueError("série A deve ser ativo")
        esperado = market_series.temporal_semantics_for_price_basis(self.price_basis)
        if self.temporal_semantics != esperado:
            raise ValueError("temporal_semantics incompatível com price_basis")
        for factor in (self.fator_a, self.fator_b):
            serie = factor.series
            if serie is None:
                continue
            if factor.tipo == "ativo":
                if serie.provenance.price_basis != self.price_basis:
                    raise ValueError("price_basis de ativo diverge do resolvido")
                if serie.provenance.temporal_semantics != self.temporal_semantics:
                    raise ValueError("temporal_semantics de ativo diverge do resolvido")
            else:
                if serie.provenance.price_basis is not None:
                    raise ValueError("índice/FX não pode carregar price_basis")
                if serie.provenance.temporal_semantics != TemporalSemantics.OBSERVATION_DATE_CUTOFF:
                    raise ValueError("índice/FX deve usar observation_date_cutoff")
        return self


class DependenciaOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    par: str
    metodo: quant_models.DependenceMethod
    coeficiente: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    n_pares: int = Field(ge=0)
    defasagem_observacoes: int
    price_basis_ativos: PriceBasis
    temporal_semantics_ativos: TemporalSemantics
    tipo_b: FactorKind
    evidencia: Evidencia


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


async def preparar_dependencia(params: DependenciaParams, ctx: ToolContext) -> DependenciaResolvida:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = janela_padrao(
        cutoff,
        params.de,
        params.ate,
        janela_dias=int(params.janela_dias or cfg["janela_padrao_dias"]),
    )
    basis = params.price_basis
    semantics = market_series.temporal_semantics_for_price_basis(basis)

    fator_a = await resolve_factor(
        ctx.conn,
        FactorRef(tipo="ativo", codigo=params.ticker_a),
        de=de,
        ate=ate,
        cutoff=cutoff,
        asset_price_basis=basis,
        asset_temporal_semantics=semantics,
        include_calendar=True,
    )
    fator_b = await resolve_factor(
        ctx.conn,
        params.serie_b,
        de=de,
        ate=ate,
        cutoff=cutoff,
        asset_price_basis=basis,
        asset_temporal_semantics=semantics,
        include_calendar=True,
    )

    ctx.registrar_insumo(
        "market.factor_series",
        ticker_a=params.ticker_a,
        serie_b=params.serie_b.model_dump(mode="json"),
        codigo_a=fator_a.codigo,
        codigo_b=fator_b.codigo,
        n_a=fator_a.series.quality.observations if fator_a.series is not None else 0,
        n_b=fator_b.series.quality.observations if fator_b.series is not None else 0,
        cutoff=cutoff.isoformat(),
        price_basis=basis.value,
        temporal_semantics=semantics.value,
        metodo=params.metodo.value,
        defasagem_observacoes=params.defasagem_observacoes,
    )
    return DependenciaResolvida(
        fator_a=fator_a,
        fator_b=fator_b,
        cutoff_date=cutoff,
        price_basis=basis,
        temporal_semantics=semantics,
        metodo=params.metodo,
        defasagem_observacoes=params.defasagem_observacoes,
        metodo_retorno=quant_models.ReturnMethod(cfg["metodo_retorno"]),
        dias_uteis_ano=int(cfg["dias_uteis_ano"]),
        min_observacoes=int(cfg["min_observacoes"]),
        max_dias_defasagem=int(cfg["max_dias_defasagem"]),
    )


def _nota_metodo(r: DependenciaResolvida) -> str:
    base = (
        "Ativos usam preços ajustados retrospectivamente com corporate actions conhecidas hoje; não é vintage histórico."
        if r.price_basis == PriceBasis.ADJUSTED_CLOSE
        else "Ativos usam fechamento bruto; o cutoff limita a data da observação, mas não garante vintage histórico."
    )
    metodo = (
        "Pearson mede associação linear"
        if r.metodo == quant_models.DependenceMethod.PEARSON
        else "Spearman mede associação monotônica pelos ranks"
    )
    detalhe_b = ""
    if r.fator_b.tipo == "indice":
        detalhe_b = (
            f" Série B é índice/taxa {r.fator_b.codigo} em unidade {r.fator_b.unit or 'pontos'}, "
            "convertida em retorno periódico quando necessário."
        )
    elif r.fator_b.tipo == "cambio":
        detalhe_b = (
            f" Série B é nível cambial {r.fator_b.codigo} de market.fx_rates; o schema atual não possui "
            "availability_date/ingestion_batch_id para provar vintage histórico."
        )
    return (
        f"{base} {metodo} sobre retornos {r.metodo_retorno.value} alinhados pela interseção de datas; "
        f"lag assinado de {r.defasagem_observacoes} observações (positivo=A antecede B; negativo=B antecede A)."
        f"{detalhe_b} Dependência não implica causalidade. {NOTA_RCVM}"
    )


def _retornos_do_fator(r: DependenciaResolvida, factor: ResolvedFactor):
    pontos = factor.series.points if factor.series is not None else []
    if not pontos:
        return []
    if factor.tipo == "indice":
        return quant_returns.calculate_index_returns(
            pontos,
            factor.unit or "pontos",
            periods_per_year=r.dias_uteis_ano,
            method=r.metodo_retorno,
        )
    return quant_returns.calculate_returns(pontos, r.metodo_retorno)


@tool(
    code="quant.dependencia",
    family="quant",
    semver="2.0.0",
    display_name="Dependência entre séries",
    description=("Mede associação histórica Pearson/Spearman entre retornos de um ativo e outra série: ativo, "
                 "índice/taxa ou câmbio canônico como USD/BRL. Suporta defasagem assinada; dependência não é "
                 "causalidade nem previsão."),
    preparar=preparar_dependencia,
    source_dependencies=(
        comum_module.__file__,
        factor_resolution_module.__file__,
        market_series.__file__,
        market_factors.__file__,
        quant_models.__file__,
        quant_returns.__file__,
        quant_dependence.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=True,
)
def calcular_dependencia(r: DependenciaResolvida) -> DependenciaOutput:
    retornos_a = _retornos_do_fator(r, r.fator_a)
    retornos_b = _retornos_do_fator(r, r.fator_b)
    pares = quant_dependence.align_returns(
        retornos_a,
        retornos_b,
        lag_observations=r.defasagem_observacoes,
    )
    n = len(pares)
    as_of = pares[-1].as_of_date if pares else None
    suficiente, avisos = avisos_de_qualidade(
        as_of,
        r.cutoff_date,
        n,
        min_observacoes=r.min_observacoes,
        max_dias_defasagem=r.max_dias_defasagem,
    )

    if not r.fator_a.found:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
    elif not r.fator_a.in_universe:
        avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != "sem_dados"]

    if r.fator_b.tipo == "ativo":
        if not r.fator_b.found:
            avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
        elif not r.fator_b.in_universe:
            avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != "sem_dados"]
    elif r.fator_b.tipo == "indice" and not r.fator_b.found:
        avisos = [INDICE_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
    elif r.fator_b.tipo == "cambio" and not r.fator_b.found:
        avisos = [FATOR_CAMBIO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]

    series = [factor.series for factor in (r.fator_a, r.fator_b) if factor.series is not None]
    for serie in series:
        avisos.extend(serie.provenance.warnings)
    avisos = _unique(avisos)

    estimate = (
        quant_dependence.dependence_estimate(
            pares,
            method=r.metodo,
            lag_observations=r.defasagem_observacoes,
        )
        if suficiente
        else None
    )
    coeficiente = estimate.coefficient if estimate is not None else None
    if suficiente and estimate is not None and coeficiente is None and (estimate.x_constant or estimate.y_constant):
        avisos = _unique(avisos + [SERIE_CONSTANTE])

    instrument_ids = [
        factor.instrument_id
        for factor in (r.fator_a, r.fator_b)
        if factor.tipo == "ativo" and factor.instrument_id
    ]
    tickers = [factor.codigo for factor in (r.fator_a, r.fator_b) if factor.tipo == "ativo"]
    index_codes = [r.fator_b.index_code] if r.fator_b.tipo == "indice" and r.fator_b.found and r.fator_b.index_code else []
    fontes = sorted({src for serie in series for src in serie.provenance.source_codes if src})
    lotes = sorted({batch for serie in series for batch in serie.provenance.ingestion_batch_ids if batch})
    lacunas = sorted({d for serie in series for d in serie.quality.missing_dates})
    metodo_evidencia = (
        f"{r.metodo.value}_ativo_cambio_retornos_{r.metodo_retorno.value}_lag_{r.defasagem_observacoes}"
        if r.fator_b.tipo == "cambio"
        else f"{r.metodo.value}_retornos_{r.metodo_retorno.value}_lag_{r.defasagem_observacoes}"
    )

    ev = Evidencia(
        fonte="+".join(fontes) or "market",
        instrument_ids=instrument_ids,
        tickers=tickers,
        index_codes=index_codes,
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=n,
        lacunas=lacunas,
        metodo=metodo_evidencia,
        nota_metodo=_nota_metodo(r),
        suficiente=suficiente,
        avisos=avisos,
        metricas={"coeficiente": coeficiente, "n_pares": float(n)},
        ingestion_batch_ids=lotes,
    )
    return DependenciaOutput(
        par=f"{r.fator_a.codigo} × {r.fator_b.codigo}",
        metodo=r.metodo,
        coeficiente=coeficiente,
        n_pares=n,
        defasagem_observacoes=r.defasagem_observacoes,
        price_basis_ativos=r.price_basis,
        temporal_semantics_ativos=r.temporal_semantics,
        tipo_b=r.fator_b.tipo,
        evidencia=ev,
    )
