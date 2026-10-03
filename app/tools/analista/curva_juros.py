"""Tool pública `dados.curva_juros` — leitura exata da ETTJ oficial ANBIMA.

Composição fina sobre `market.yield_curve`: não interpola, não extrapola, não calcula
slope/curvature, não projeta juros e não aplica choque.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.market import yield_curves
from app.tools.analista._comum import data_referencia, resolver_cutoff
from app.tools.executor import ToolContext
from app.tools.registry import tool

CurveName = Literal["ettj_pre", "ettj_ipca", "inflacao_implicita"]


class CurvaJurosParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curva: CurveName
    em: date | None = Field(
        default=None,
        description="Data econômica exata da curva; se omitida, usa a última disponível até o cutoff.",
    )
    data_referencia: date | None = Field(
        default=None,
        description="Cutoff point-in-time; a ingestão precisa estar disponível até esta data.",
    )
    vertices_du: list[int] | None = Field(
        default=None,
        max_length=20,
        description="Vértices exatos em dias úteis. Ausentes não são aproximados.",
    )

    @field_validator("vertices_du")
    @classmethod
    def _validar_vertices(cls, value: list[int] | None):
        if value is None:
            return value
        if any(v <= 0 for v in value):
            raise ValueError("vertice_du_deve_ser_positivo")
        return sorted(set(value))


class CurvaJurosResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curva: CurveName
    cutoff_date: date
    vertices_du: list[int] | None = None
    resolved: yield_curves.ResolvedYieldCurve


class CurvaJurosPontoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vertice_du: int
    taxa_pct_aa_252: float


class CurvaJurosOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curva: CurveName
    unidade: str = "% a.a./252 d.u."
    data_curva: date | None = None
    pontos: list[CurvaJurosPontoOutput] = Field(default_factory=list)
    n_vertices_total: int = 0
    n_vertices_retornados: int = 0
    provenance: yield_curves.YieldCurveProvenance


async def preparar_curva_juros(params: CurvaJurosParams, ctx: ToolContext) -> CurvaJurosResolvida:
    cutoff = resolver_cutoff(
        params.data_referencia,
        ctx.cutoff_date,
        await data_referencia(ctx.conn),
    )
    resolved = await yield_curves.load_yield_curve(
        ctx.conn,
        params.curva,
        cutoff=cutoff,
        reference_date=params.em,
        strict_pit=True,
    )
    ctx.registrar_insumo(
        "market.yield_curve",
        curva=params.curva,
        reference_date=(resolved.reference_date.isoformat() if resolved.reference_date else None),
        cutoff=cutoff.isoformat(),
        n=len(resolved.points),
    )
    return CurvaJurosResolvida(
        curva=params.curva,
        cutoff_date=cutoff,
        vertices_du=params.vertices_du,
        resolved=resolved,
    )


@tool(
    code="dados.curva_juros",
    family="dados",
    semver="1.0.1",
    display_name="Curva de juros oficial",
    description=(
        "Lê vértices oficiais da ETTJ ANBIMA prefixada, IPCA ou inflação implícita em uma data "
        "disponível. Retorna somente vértices publicados; não interpola, extrapola, projeta juros "
        "nem calcula cenário de choque."
    ),
    preparar=preparar_curva_juros,
    source_dependencies=(yield_curves.__file__,),
    requires_market_data=True,
    exposed_to_llm=True,
)
def montar_curva_juros(r: CurvaJurosResolvida) -> CurvaJurosOutput:
    all_points = r.resolved.points
    selected = all_points
    warnings = list(r.resolved.provenance.warnings)
    if r.vertices_du is not None:
        requested = set(r.vertices_du)
        selected = [p for p in all_points if p.business_days in requested]
        available = {p.business_days for p in selected}
        for missing in sorted(requested - available):
            warnings.append(f"vertice_ettj_indisponivel:{missing}")

    provenance = r.resolved.provenance.model_copy(
        update={"warnings": list(dict.fromkeys(warnings))}
    )
    return CurvaJurosOutput(
        curva=r.curva,
        data_curva=r.resolved.reference_date,
        pontos=[
            CurvaJurosPontoOutput(
                vertice_du=p.business_days,
                taxa_pct_aa_252=p.rate_pct,
            )
            for p in selected
        ],
        n_vertices_total=len(all_points),
        n_vertices_retornados=len(selected),
        provenance=provenance,
    )
