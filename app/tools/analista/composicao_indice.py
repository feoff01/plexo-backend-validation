"""Tool shadow dados.composicao_indice — composição/pesos de snapshots oficiais."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.market import index_compositions
from app.tools.analista._comum import data_referencia, resolver_cutoff
from app.tools.executor import ToolContext
from app.tools.registry import tool


class ComposicaoIndiceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indice: str = Field(min_length=1, description="Código do índice com carteira ingerida, por exemplo ibra.")
    em: date | None = Field(
        default=None,
        description="Data econômica exata do snapshot; se omitida usa o último snapshot disponível até o cutoff.",
    )
    data_referencia: date | None = Field(
        default=None,
        description="Cutoff point-in-time: o lote precisa estar disponível até esta data.",
    )
    tickers: list[str] | None = Field(
        default=None,
        max_length=20,
        description="Tickers exatos opcionais. Quando presentes, somente eles são procurados no snapshot.",
    )
    limite: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Máximo de componentes retornados quando tickers não é informado.",
    )

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, value: list[str] | None):
        if value is None:
            return None
        normalized = [item.strip().upper() for item in value if item.strip()]
        if not normalized:
            return None
        return list(dict.fromkeys(normalized))


class ComposicaoIndiceResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    composition: index_compositions.ResolvedIndexComposition
    requested_tickers: list[str] | None = None
    limite: int = Field(ge=1, le=25)


class ComposicaoIndiceMembroOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    nome: str
    peso_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    quantidade_teorica: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ComposicaoIndiceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indice: str
    nome_indice: str | None = None
    data_carteira: date | None = None
    n_componentes_total: int = Field(ge=0)
    peso_total_pct: float = Field(ge=0, allow_inf_nan=False)
    componentes: list[ComposicaoIndiceMembroOutput] = Field(default_factory=list)
    truncado: bool = False
    provenance: index_compositions.IndexCompositionProvenance


async def preparar_composicao_indice(
    params: ComposicaoIndiceParams,
    ctx: ToolContext,
) -> ComposicaoIndiceResolvida:
    cutoff = resolver_cutoff(
        params.data_referencia,
        ctx.cutoff_date,
        await data_referencia(ctx.conn),
    )
    composition = await index_compositions.load_index_composition(
        ctx.conn,
        params.indice,
        cutoff=cutoff,
        reference_date=params.em,
        strict_pit=True,
    )
    ctx.registrar_insumo(
        "market.index_weights",
        indice=params.indice.strip().lower(),
        reference_date=(
            composition.reference_date.isoformat()
            if composition.reference_date is not None
            else None
        ),
        cutoff=cutoff.isoformat(),
        n=len(composition.members),
    )
    return ComposicaoIndiceResolvida(
        composition=composition,
        requested_tickers=params.tickers,
        limite=params.limite,
    )


@tool(
    code="dados.composicao_indice",
    family="dados",
    semver="1.0.1",
    display_name="Composição oficial de índice",
    description=(
        "Lê membros e pesos de um snapshot oficial de carteira de índice já ingerido. "
        "Não infere membership histórico, não calcula performance e não é recomendação."
    ),
    preparar=preparar_composicao_indice,
    source_dependencies=(index_compositions.__file__,),
    requires_market_data=True,
    exposed_to_llm=True,
)
def montar_composicao_indice(r: ComposicaoIndiceResolvida) -> ComposicaoIndiceOutput:
    composition = r.composition
    warnings = list(composition.provenance.warnings)
    selected = composition.members
    truncado = False

    if r.requested_tickers is not None:
        by_ticker = {member.ticker: member for member in composition.members}
        selected = [by_ticker[ticker] for ticker in r.requested_tickers if ticker in by_ticker]
        for missing in [ticker for ticker in r.requested_tickers if ticker not in by_ticker]:
            warnings.append(f"ticker_fora_da_carteira:{missing}")
    elif len(selected) > r.limite:
        selected = selected[: r.limite]
        truncado = True
        warnings.append("composicao_indice_truncada")

    provenance = composition.provenance.model_copy(
        update={"warnings": list(dict.fromkeys(warnings))}
    )
    return ComposicaoIndiceOutput(
        indice=composition.index_code,
        nome_indice=composition.display_name,
        data_carteira=composition.reference_date,
        n_componentes_total=len(composition.members),
        peso_total_pct=composition.total_weight_pct,
        componentes=[
            ComposicaoIndiceMembroOutput(
                ticker=member.ticker,
                nome=member.name,
                peso_pct=member.weight_pct,
                quantidade_teorica=member.theoretical_qty,
            )
            for member in selected
        ],
        truncado=truncado,
        provenance=provenance,
    )
