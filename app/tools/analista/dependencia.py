"""Tool canônica `quant.dependencia` (FQ3.2/FQ3.3).

Orquestra MarketSeriesLoader + Returns/Dependence Core. O contrato expõe apenas dependência global
(Pearson/Spearman) e lag assinado; rolling/regimes continuam internos para tools especializadas.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class DependenciaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker_a: str = Field(min_length=1, description="Ticker do primeiro ativo.")
    ticker_b: str | None = Field(default=None, description="Segundo ativo; use exatamente um entre ticker_b e indice_b.")
    indice_b: str | None = Field(default=None, description="Índice/taxa como segunda série, por exemplo CDI, Selic ou IPCA.")
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
                     "como saltos mecânicos; raw_close usa o fechamento publicado. Não se aplica ao índice/taxa."),
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

    @model_validator(mode="after")
    def _um_segundo(self) -> "DependenciaParams":
        if (self.ticker_b is None) == (self.indice_b is None):
            raise ValueError("informe exatamente um: ticker_b ou indice_b")
        return self


class DependenciaResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker_a: str
    codigo_b: str
    tipo_b: Literal["ativo", "indice"]
    instrument_a_id: str | None
    instrument_b_id: str | None = None
    a_in_universe: bool
    b_in_universe: bool
    b_found: bool = True
    index_code_b: str | None = None
    cutoff_date: date
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    serie_a: ResolvedMarketSeries | None
    serie_b: ResolvedMarketSeries | None
    unidade_b: str = "pontos"
    metodo: quant_models.DependenceMethod
    defasagem_observacoes: int = 0
    metodo_retorno: quant_models.ReturnMethod
    dias_uteis_ano: int = Field(ge=1)
    min_observacoes: int = Field(ge=1)
    max_dias_defasagem: int = Field(ge=0)

    @model_validator(mode="after")
    def _coerencia(self) -> "DependenciaResolvida":
        esperado = market_series.temporal_semantics_for_price_basis(self.price_basis)
        if self.temporal_semantics != esperado:
            raise ValueError("temporal_semantics incompatível com price_basis")
        for label, serie, iid in (("A", self.serie_a, self.instrument_a_id),
                                  ("B", self.serie_b if self.tipo_b == "ativo" else None, self.instrument_b_id)):
            if serie is None:
                continue
            if serie.provenance.price_basis != self.price_basis:
                raise ValueError(f"price_basis da série {label} diverge do resolvido")
            if serie.provenance.temporal_semantics != self.temporal_semantics:
                raise ValueError(f"temporal_semantics da série {label} diverge do resolvido")
            if iid is not None and serie.instrument_id != iid:
                raise ValueError(f"instrument_id da série {label} diverge do resolvido")
        if self.tipo_b == "indice" and self.serie_b is not None:
            if self.serie_b.provenance.price_basis is not None:
                raise ValueError("índice/taxa não pode carregar price_basis")
            if self.serie_b.provenance.temporal_semantics != TemporalSemantics.OBSERVATION_DATE_CUTOFF:
                raise ValueError("índice/taxa deve usar observation_date_cutoff")
            if self.index_code_b is not None and self.serie_b.index_code != self.index_code_b:
                raise ValueError("index_code da série B diverge do resolvido")
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
    tipo_b: Literal["ativo", "indice"]
    evidencia: Evidencia


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


async def preparar_dependencia(params: DependenciaParams, ctx: ToolContext) -> DependenciaResolvida:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = janela_padrao(
        cutoff, params.de, params.ate,
        janela_dias=int(params.janela_dias or cfg["janela_padrao_dias"]),
    )
    basis = params.price_basis
    semantics = market_series.temporal_semantics_for_price_basis(basis)

    inst_a = await instrumento_por_termo(ctx.conn, params.ticker_a, cutoff=cutoff)
    a_in_universe = bool(inst_a is not None and inst_a["is_in_universe"])
    serie_a = None
    if a_in_universe and inst_a is not None:
        serie_a = await carregar_serie_resolvida(
            ctx.conn, inst_a["instrument_id"], de=de, ate=ate, cutoff=cutoff,
            codigo=inst_a["ticker"] or params.ticker_a, basis=basis,
            temporal_semantics=semantics, include_calendar=True,
        )

    tipo_b: Literal["ativo", "indice"]
    inst_b = None
    index_code_b = None
    b_found = False
    b_in_universe = False
    serie_b = None
    unidade_b = "pontos"
    if params.ticker_b is not None:
        tipo_b = "ativo"
        inst_b = await instrumento_por_termo(ctx.conn, params.ticker_b, cutoff=cutoff)
        b_found = inst_b is not None
        b_in_universe = bool(inst_b is not None and inst_b["is_in_universe"])
        if b_in_universe and inst_b is not None:
            serie_b = await carregar_serie_resolvida(
                ctx.conn, inst_b["instrument_id"], de=de, ate=ate, cutoff=cutoff,
                codigo=inst_b["ticker"] or params.ticker_b, basis=basis,
                temporal_semantics=semantics, include_calendar=True,
            )
        codigo_b = (inst_b["ticker"] if inst_b and inst_b.get("ticker") else params.ticker_b)
    else:
        tipo_b = "indice"
        index_code_b = params.indice_b.lower()
        codigo_b = index_code_b
        try:
            serie_b = await carregar_indice_resolvido(
                ctx.conn, index_code_b, de=de, ate=ate, cutoff=cutoff, include_calendar=True,
            )
            b_found = True
            unidade_b = serie_b.unit or "pontos"
        except market_series.UnknownIndex:
            b_found = False

    ctx.registrar_insumo(
        "market.series",
        ticker_a=params.ticker_a,
        ticker_b=params.ticker_b,
        indice_b=params.indice_b,
        n_a=serie_a.quality.observations if serie_a is not None else 0,
        n_b=serie_b.quality.observations if serie_b is not None else 0,
        cutoff=cutoff.isoformat(),
        price_basis=basis.value,
        temporal_semantics=semantics.value,
        metodo=params.metodo.value,
        defasagem_observacoes=params.defasagem_observacoes,
    )
    return DependenciaResolvida(
        ticker_a=(inst_a["ticker"] if inst_a and inst_a.get("ticker") else params.ticker_a),
        codigo_b=codigo_b,
        tipo_b=tipo_b,
        instrument_a_id=inst_a["instrument_id"] if inst_a else None,
        instrument_b_id=inst_b["instrument_id"] if inst_b else None,
        a_in_universe=a_in_universe,
        b_in_universe=b_in_universe,
        b_found=b_found,
        index_code_b=index_code_b,
        cutoff_date=cutoff,
        price_basis=basis,
        temporal_semantics=semantics,
        serie_a=serie_a,
        serie_b=serie_b,
        unidade_b=unidade_b,
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
    metodo = ("Pearson mede associação linear" if r.metodo == quant_models.DependenceMethod.PEARSON
              else "Spearman mede associação monotônica pelos ranks")
    indice = (f" Série B é índice/taxa em unidade {r.unidade_b}, convertida em retorno periódico quando necessário."
              if r.tipo_b == "indice" else "")
    return (
        f"{base} {metodo} sobre retornos {r.metodo_retorno.value} alinhados pela interseção de datas; "
        f"lag assinado de {r.defasagem_observacoes} observações (positivo=A antecede B; negativo=B antecede A)."
        f"{indice} Dependência não implica causalidade. {NOTA_RCVM}"
    )


@tool(
    code="quant.dependencia",
    family="quant",
    semver="1.0.1",
    display_name="Dependência entre séries",
    description=("Mede associação histórica entre retornos de dois ativos ou entre um ativo e índice/taxa. "
                 "Suporta Pearson, Spearman e defasagem assinada em observações comuns. Ativos usam adjusted_close "
                 "retrospectivo por padrão; dependência não é causalidade nem previsão."),
    preparar=preparar_dependencia,
    source_dependencies=(
        comum_module.__file__, market_series.__file__, quant_models.__file__,
        quant_returns.__file__, quant_dependence.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=True,
)
def calcular_dependencia(r: DependenciaResolvida) -> DependenciaOutput:
    pontos_a = r.serie_a.points if r.serie_a is not None else []
    pontos_b = r.serie_b.points if r.serie_b is not None else []
    retornos_a = quant_returns.calculate_returns(pontos_a, r.metodo_retorno) if pontos_a else []
    if r.tipo_b == "indice":
        retornos_b = (quant_returns.calculate_index_returns(
            pontos_b, r.unidade_b, periods_per_year=r.dias_uteis_ano, method=r.metodo_retorno,
        ) if pontos_b else [])
    else:
        retornos_b = quant_returns.calculate_returns(pontos_b, r.metodo_retorno) if pontos_b else []

    pares = quant_dependence.align_returns(
        retornos_a, retornos_b, lag_observations=r.defasagem_observacoes,
    )
    n = len(pares)
    as_of = pares[-1].as_of_date if pares else None
    suficiente, avisos = avisos_de_qualidade(
        as_of, r.cutoff_date, n,
        min_observacoes=r.min_observacoes, max_dias_defasagem=r.max_dias_defasagem,
    )

    if r.instrument_a_id is None:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
    elif not r.a_in_universe:
        avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != "sem_dados"]
    if r.tipo_b == "ativo":
        if r.instrument_b_id is None:
            avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
        elif not r.b_in_universe:
            avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != "sem_dados"]
    elif not r.b_found:
        avisos = [INDICE_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]

    series = [s for s in (r.serie_a, r.serie_b) if s is not None]
    for serie in series:
        avisos.extend(serie.provenance.warnings)
    avisos = _unique(avisos)

    estimate = (quant_dependence.dependence_estimate(
        pares, method=r.metodo, lag_observations=r.defasagem_observacoes,
    ) if suficiente else None)
    coeficiente = estimate.coefficient if estimate is not None else None
    if suficiente and estimate is not None and coeficiente is None and (estimate.x_constant or estimate.y_constant):
        avisos = _unique(avisos + [SERIE_CONSTANTE])

    instrument_ids = [x for x in (r.instrument_a_id, r.instrument_b_id if r.tipo_b == "ativo" else None) if x]
    tickers = [r.ticker_a] + ([r.codigo_b] if r.tipo_b == "ativo" else [])
    index_codes = [r.index_code_b] if r.tipo_b == "indice" and r.b_found and r.index_code_b else []
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
        n_observacoes=n,
        lacunas=lacunas,
        metodo=f"{r.metodo.value}_retornos_{r.metodo_retorno.value}_lag_{r.defasagem_observacoes}",
        nota_metodo=_nota_metodo(r),
        suficiente=suficiente,
        avisos=avisos,
        metricas={"coeficiente": coeficiente, "n_pares": float(n)},
        ingestion_batch_ids=lotes,
    )
    return DependenciaOutput(
        par=f"{r.ticker_a} × {r.codigo_b}",
        metodo=r.metodo,
        coeficiente=coeficiente,
        n_pares=n,
        defasagem_observacoes=r.defasagem_observacoes,
        price_basis_ativos=r.price_basis,
        temporal_semantics_ativos=r.temporal_semantics,
        tipo_b=r.tipo_b,
        evidencia=ev,
    )
