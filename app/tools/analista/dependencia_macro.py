"""Compatibilidade oculta de `quant.dependencia_macro` após o cutover de dependência v2.

Novos planos devem usar `quant.dependencia` 2.0.0 com `serie_b`. A versão 1.0.0 permanece congelada
em `dependencia_macro_legacy_1_0_0.py` para replay; este código 1.0.1 só preserva executabilidade
para consumidores em transição e delega toda a matemática à interface canônica.
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
from app.market.series import PriceBasis, TemporalSemantics
from app.tools.analista import _comum as comum_module
from app.tools.analista import dependencia as dependencia_module
from app.tools.analista import factor_resolution as factor_resolution_module
from app.tools.analista.dependencia import DependenciaParams, DependenciaResolvida
from app.tools.analista.factor_resolution import FactorRef
from app.tools.analista._comum import Evidencia
from app.tools.executor import ToolContext
from app.tools.registry import tool

FactorType = Literal["indice", "cambio"]


class DependenciaMacroParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="Ativo cuja dependência histórica será medida.")
    indice_fator: str | None = Field(default=None, description="Índice/taxa macro.")
    base_currency: str | None = Field(default=None, min_length=3, max_length=3)
    quote_currency: str | None = Field(default=None, min_length=3, max_length=3)
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
            base = market_factors.normalize_currency(self.base_currency or "")
            quote = market_factors.normalize_currency(self.quote_currency or "")
            if base == quote:
                raise ValueError("base_currency e quote_currency devem ser diferentes")
            object.__setattr__(self, "base_currency", base)
            object.__setattr__(self, "quote_currency", quote)
        return self


class DependenciaMacroResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factor_type: FactorType
    factor_code: str
    dependencia: DependenciaResolvida


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


async def preparar_dependencia_macro(params: DependenciaMacroParams, ctx: ToolContext) -> DependenciaMacroResolvida:
    if params.indice_fator is not None:
        ref = FactorRef(tipo="indice", codigo=params.indice_fator)
    else:
        ref = FactorRef(
            tipo="cambio",
            codigo=market_factors.fx_code(params.base_currency or "", params.quote_currency or ""),
        )
    resolved = await dependencia_module.preparar_dependencia(
        DependenciaParams(
            ticker_a=params.ticker,
            serie_b=ref,
            janela_dias=params.janela_dias,
            de=params.de,
            ate=params.ate,
            data_referencia=params.data_referencia,
            price_basis=params.price_basis,
            metodo=params.metodo,
            defasagem_observacoes=params.defasagem_observacoes,
        ),
        ctx,
    )
    return DependenciaMacroResolvida(
        factor_type=ref.tipo,
        factor_code=resolved.fator_b.codigo,
        dependencia=resolved,
    )


@tool(
    code="quant.dependencia_macro",
    family="quant",
    semver="1.0.1",
    display_name="Dependência com fator macro (compatibilidade)",
    description=("Compatibilidade executável para chamadas antigas de dependência com índice/taxa ou câmbio. "
                 "Novos planos usam quant.dependencia; esta interface não é oferecida ao LLM."),
    preparar=preparar_dependencia_macro,
    source_dependencies=(
        comum_module.__file__,
        dependencia_module.__file__,
        factor_resolution_module.__file__,
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
    out = dependencia_module.calcular_dependencia(r.dependencia)
    return DependenciaMacroOutput(
        par=out.par,
        factor_type=r.factor_type,
        factor_code=r.factor_code,
        metodo=out.metodo,
        coeficiente=out.coeficiente,
        n_pares=out.n_pares,
        defasagem_observacoes=out.defasagem_observacoes,
        price_basis_ativo=out.price_basis_ativos,
        temporal_semantics_ativo=out.temporal_semantics_ativos,
        evidencia=out.evidencia,
    )
