"""Dependência entre ativo e fator macro (índice/taxa ou câmbio) — FQ5.4.

Reutiliza integralmente Returns/Dependence Core. A tool existe para adaptar fontes macro que não
fazem parte do contrato histórico de ``quant.dependencia`` sem alterar seu semver/fingerprint.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import factors as market_factors
from app.market import series as market_series
from app.market.analytics import dependence as quant_dependence
from app.market.analytics import models as quant_models
from app.market.analytics import returns as quant_returns
from app.market.series import PriceBasis, ResolvedMarketSeries, TemporalSemantics
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (
    FORA_DA_COBERTURA,
    INDICE_DESCONHECIDO,
    INSTRUMENTO_DESCONHECIDO,
    NOTA_RCVM,
    SERIE_CONSTANTE,
    Evidencia,
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


FATOR_CAMBIO_DESCONHECIDO = "par_cambio_desconhecido"
FactorType = Literal["indice", "cambio"]


class DependenciaMacroParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, description="Ativo cuja dependência histórica será medida.")
    indice_fator: str | None = Field(
        default=None,
        description="Índice/taxa macro, por exemplo selic_meta, cdi, ipca ou ibov.",
    )
    base_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Moeda base do par cambial, por exemplo USD em USD/BRL.",
    )
    quote_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Moeda cotada do par cambial, por exemplo BRL em USD/BRL.",
    )
    janela_dias: int | None = Field(default=None, ge=1)
    de: date | None = None
    ate: date | None = None
    data_referencia: date | None = None
    price_basis: PriceBasis = Field(default=PriceBasis.ADJUSTED_CLOSE)
    metodo: quant_models.DependenceMethod = Field(default=quant_models.DependenceMethod.PEARSON)
    defasagem_observacoes: int = 0

    @model_validator(mode="after")
    def _um_fator(self) -> "DependenciaMacroParams":
        has_index = self.indice_fator is not None
        has_base = self.base_currency is not None
        has_quote = self.quote_currency is not None
        if has_base != has_quote:
            raise ValueError("base_currency e quote_currency devem ser informadas juntas")
        if has_index == has_base:
            raise ValueError("informe exatamente um fator: indice_fator ou par base_currency/quote_currency")
        if has_base:
            self.base_currency = market_factors.normalize_currency(self.base_currency or "")
            self.quote_currency = market_factors.normalize_currency(self.quote_currency or "")
            if self.base_currency == self.quote_currency:
                raise ValueError("base_currency e quote_currency devem ser diferentes")
        return self


class DependenciaMacroResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    factor_code: str
    factor_type: FactorType
    instrument_id: str | None
    response_in_universe: bool
    factor_found: bool = True
    factor_index_code: str | None = None
    cutoff_date: date
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    serie_resposta: ResolvedMarketSeries | None
    serie_fator: ResolvedMarketSeries | None
    unidade_fator: str = "pontos"
    metodo: quant_models.DependenceMethod
    defasagem_observacoes: int = 0
    metodo_retorno: quant_models.ReturnMethod
    dias_uteis_ano: int = Field(ge=1)
    min_observacoes: int = Field(ge=1)
    max_dias_defasagem: int = Field(ge=0)

    @model_validator(mode="after")
    def _coerencia(self) -> "DependenciaMacroResolvida":
        expected = market_series.temporal_semantics_for_price_basis(self.price_basis)
        if self.temporal_semantics != expected:
            raise ValueError("temporal_semantics incompatível com price_basis")
        if self.serie_resposta is not None:
            if self.serie_resposta.provenance.price_basis != self.price_basis:
                raise ValueError("price_basis da resposta diverge do resolvido")
            if self.serie_resposta.provenance.temporal_semantics != self.temporal_semantics:
                raise ValueError("temporal_semantics da resposta diverge do resolvido")
        if self.serie_fator is not None:
            if self.serie_fator.provenance.price_basis is not None:
                raise ValueError("fator macro não pode carregar price_basis")
            if self.serie_fator.provenance.temporal_semantics != TemporalSemantics.OBSERVATION_DATE_CUTOFF:
                raise ValueError("fator macro deve usar observation_date_cutoff")
        return self


class DependenciaMacroOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    par: str
    factor_type: FactorType
    factor_code: str
    metodo: quant_models.DependenceMethod
    coeficiente: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    n_pares: int = Field(ge=0)
    defasagem_observacoes: int
    price_basis_ativo: PriceBasis
    temporal_semantics_ativo: TemporalSemantics
    evidencia: Evidencia


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


async def preparar_dependencia_macro(
    params: DependenciaMacroParams,
    ctx: ToolContext,
) -> DependenciaMacroResolvida:
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

    inst = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    response_in_universe = bool(inst is not None and inst["is_in_universe"])
    serie_resposta = None
    if response_in_universe and inst is not None:
        serie_resposta = await carregar_serie_resolvida(
            ctx.conn,
            inst["instrument_id"],
            de=de,
            ate=ate,
            cutoff=cutoff,
            codigo=inst["ticker"] or params.ticker,
            basis=basis,
            temporal_semantics=semantics,
            include_calendar=True,
        )

    serie_fator = None
    factor_found = False
    factor_index_code = None
    unidade = "pontos"
    if params.indice_fator is not None:
        factor_type: FactorType = "indice"
        factor_index_code = params.indice_fator.lower()
        factor_code = factor_index_code
        try:
            serie_fator = await carregar_indice_resolvido(
                ctx.conn,
                factor_index_code,
                de=de,
                ate=ate,
                cutoff=cutoff,
                include_calendar=True,
            )
            factor_found = True
            unidade = serie_fator.unit or "pontos"
        except market_series.UnknownIndex:
            factor_found = False
    else:
        factor_type = "cambio"
        base = market_factors.normalize_currency(params.base_currency or "")
        quote = market_factors.normalize_currency(params.quote_currency or "")
        factor_code = market_factors.fx_code(base, quote)
        factor_found = await market_factors.fx_pair_exists(ctx.conn, base, quote, cutoff=cutoff)
        if factor_found:
            serie_fator = await market_factors.load_fx_series(
                ctx.conn,
                base,
                quote,
                de=de,
                ate=ate,
                cutoff=cutoff,
                include_calendar=True,
            )
            unidade = "pontos"

    ctx.registrar_insumo(
        "market.macro_factor",
        ticker=params.ticker,
        factor_type=factor_type,
        factor_code=factor_code,
        n_resposta=serie_resposta.quality.observations if serie_resposta is not None else 0,
        n_fator=serie_fator.quality.observations if serie_fator is not None else 0,
        cutoff=cutoff.isoformat(),
        price_basis=basis.value,
        temporal_semantics=semantics.value,
        metodo=params.metodo.value,
        defasagem_observacoes=params.defasagem_observacoes,
    )
    return DependenciaMacroResolvida(
        ticker=inst["ticker"] if inst and inst.get("ticker") else params.ticker,
        factor_code=factor_code,
        factor_type=factor_type,
        instrument_id=inst["instrument_id"] if inst else None,
        response_in_universe=response_in_universe,
        factor_found=factor_found,
        factor_index_code=factor_index_code,
        cutoff_date=cutoff,
        price_basis=basis,
        temporal_semantics=semantics,
        serie_resposta=serie_resposta,
        serie_fator=serie_fator,
        unidade_fator=unidade,
        metodo=params.metodo,
        defasagem_observacoes=params.defasagem_observacoes,
        metodo_retorno=quant_models.ReturnMethod(cfg["metodo_retorno"]),
        dias_uteis_ano=int(cfg["dias_uteis_ano"]),
        min_observacoes=int(cfg["min_observacoes"]),
        max_dias_defasagem=int(cfg["max_dias_defasagem"]),
    )


def _nota_metodo(r: DependenciaMacroResolvida) -> str:
    base = (
        "O ativo usa preços ajustados retrospectivamente com corporate actions conhecidas hoje; não é vintage histórico."
        if r.price_basis == PriceBasis.ADJUSTED_CLOSE
        else "O ativo usa fechamento bruto; o cutoff limita a observação, sem garantir vintage contra backfills."
    )
    factor = (
        f"O fator {r.factor_code} é índice/taxa em unidade {r.unidade_fator}."
        if r.factor_type == "indice"
        else (
            f"O fator {r.factor_code} é nível cambial de market.fx_rates; o schema atual não possui "
            "availability_date/ingestion_batch_id para provar vintage histórico."
        )
    )
    method = "Pearson mede associação linear" if r.metodo == quant_models.DependenceMethod.PEARSON else "Spearman mede associação monotônica pelos ranks"
    return (
        f"{base} {factor} {method} sobre retornos alinhados pela interseção de datas; lag assinado de "
        f"{r.defasagem_observacoes} observações (positivo=ativo antecede fator; negativo=fator antecede ativo). "
        f"Dependência não implica causalidade. {NOTA_RCVM}"
    )


@tool(
    code="quant.dependencia_macro",
    family="quant",
    semver="1.0.0",
    display_name="Dependência com fator macro",
    description=(
        "Mede associação histórica Pearson/Spearman entre retornos de um ativo e um índice/taxa ou par cambial "
        "canônico (por exemplo USD/BRL). Reutiliza o Quant Core; não implica causalidade nem previsão."
    ),
    preparar=preparar_dependencia_macro,
    source_dependencies=(
        comum_module.__file__,
        market_series.__file__,
        market_factors.__file__,
        quant_models.__file__,
        quant_returns.__file__,
        quant_dependence.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=False,
)
def calcular_dependencia_macro(r: DependenciaMacroResolvida) -> DependenciaMacroOutput:
    response_points = r.serie_resposta.points if r.serie_resposta is not None else []
    factor_points = r.serie_fator.points if r.serie_fator is not None else []
    returns_a = quant_returns.calculate_returns(response_points, r.metodo_retorno) if response_points else []
    if r.factor_type == "indice":
        returns_b = (
            quant_returns.calculate_index_returns(
                factor_points,
                r.unidade_fator,
                periods_per_year=r.dias_uteis_ano,
                method=r.metodo_retorno,
            )
            if factor_points
            else []
        )
    else:
        returns_b = quant_returns.calculate_returns(factor_points, r.metodo_retorno) if factor_points else []

    pairs = quant_dependence.align_returns(
        returns_a,
        returns_b,
        lag_observations=r.defasagem_observacoes,
    )
    n = len(pairs)
    as_of = pairs[-1].as_of_date if pairs else None
    suficiente, avisos = avisos_de_qualidade(
        as_of,
        r.cutoff_date,
        n,
        min_observacoes=r.min_observacoes,
        max_dias_defasagem=r.max_dias_defasagem,
    )
    if r.instrument_id is None:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [x for x in avisos if x != "sem_dados"]
    elif not r.response_in_universe:
        avisos = [FORA_DA_COBERTURA] + [x for x in avisos if x != "sem_dados"]
    if not r.factor_found:
        avisos = [INDICE_DESCONHECIDO if r.factor_type == "indice" else FATOR_CAMBIO_DESCONHECIDO] + [
            x for x in avisos if x != "sem_dados"
        ]

    series = [s for s in (r.serie_resposta, r.serie_fator) if s is not None]
    for serie in series:
        avisos.extend(serie.provenance.warnings)
    avisos = _unique(avisos)

    estimate = (
        quant_dependence.dependence_estimate(
            pairs,
            method=r.metodo,
            lag_observations=r.defasagem_observacoes,
        )
        if suficiente
        else None
    )
    coefficient = estimate.coefficient if estimate is not None else None
    if suficiente and estimate is not None and coefficient is None and (estimate.x_constant or estimate.y_constant):
        avisos = _unique(avisos + [SERIE_CONSTANTE])

    sources = sorted({src for serie in series for src in serie.provenance.source_codes if src})
    batches = sorted({batch for serie in series for batch in serie.provenance.ingestion_batch_ids if batch})
    missing = sorted({d for serie in series for d in serie.quality.missing_dates})
    evidencia = Evidencia(
        fonte="+".join(sources) or "market",
        instrument_ids=[r.instrument_id] if r.instrument_id else [],
        tickers=[r.ticker],
        index_codes=[r.factor_index_code] if r.factor_type == "indice" and r.factor_index_code and r.factor_found else [],
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=n,
        lacunas=missing,
        metodo=f"{r.metodo.value}_ativo_{r.factor_type}_retornos_{r.metodo_retorno.value}_lag_{r.defasagem_observacoes}",
        nota_metodo=_nota_metodo(r),
        suficiente=suficiente,
        avisos=avisos,
        metricas={"coeficiente": coefficient, "n_pares": float(n)},
        ingestion_batch_ids=batches,
    )
    return DependenciaMacroOutput(
        par=f"{r.ticker} × {r.factor_code}",
        factor_type=r.factor_type,
        factor_code=r.factor_code,
        metodo=r.metodo,
        coeficiente=coefficient,
        n_pares=n,
        defasagem_observacoes=r.defasagem_observacoes,
        price_basis_ativo=r.price_basis,
        temporal_semantics_ativo=r.temporal_semantics,
        evidencia=evidencia,
    )
