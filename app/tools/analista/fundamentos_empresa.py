"""Fundamentos anuais point-in-time de uma empresa (FQ5.1)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.market import fundamentals as market_fundamentals
from app.tools.analista._comum import (
    Evidencia,
    FORA_DA_COBERTURA,
    INSTRUMENTO_DESCONHECIDO,
    SEM_DADOS,
    data_referencia,
    instrumento_por_termo,
    resolver_cutoff,
)
from app.tools.executor import ToolContext
from app.tools.registry import tool


COMPANY_ID_UNAVAILABLE = "company_cnpj_indisponivel"

DEFAULT_METRICS = (
    "revenue",
    "ebitda",
    "ebitda_derived",
    "net_income",
    "total_equity",
    "cash_and_equivalents",
    "gross_debt",
    "net_debt",
    "free_cash_flow",
    "shares_outstanding",
)


class FundamentosEmpresaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=40)
    data_referencia: date | None = None
    scope: Literal["consolidated", "standalone"] = "consolidated"
    metricas: list[str] | None = Field(
        default=None,
        max_length=20,
        description=(
            "Códigos canônicos de métricas. Quando omitido, usa um conjunto compacto para análise/valuation."
        ),
    )


class FundamentoEmpresaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    value: float
    value_unit: market_fundamentals.FundamentalUnit
    currency: str | None = None
    instrument_id: str | None = None
    reference_date: date
    availability_date: date
    document_type: market_fundamentals.FundamentalDocumentType
    period_label: str
    is_derived: bool
    source_code: str


class FundamentosEmpresaResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    name: str | None = None
    instrument_id: str | None = None
    company_cnpj: str | None = None
    in_universe: bool = False
    cutoff_date: date
    scope: market_fundamentals.FundamentalScope
    resolved: market_fundamentals.ResolvedFundamentals | None = None


class FundamentosEmpresaOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    company_cnpj: str | None = None
    scope: market_fundamentals.FundamentalScope
    periodo: str = "ultimo_dfp_anual_disponivel_no_cutoff"
    fundamentos: list[FundamentoEmpresaItem] = Field(default_factory=list)
    evidencia: Evidencia


async def preparar_fundamentos_empresa(
    params: FundamentosEmpresaParams,
    ctx: ToolContext,
) -> FundamentosEmpresaResolvida:
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    inst = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    scope = market_fundamentals.FundamentalScope(params.scope)
    if inst is None:
        ctx.registrar_insumo("market.fundamentals", ticker=params.ticker, cutoff=cutoff.isoformat(), n=0)
        return FundamentosEmpresaResolvida(
            ticker=params.ticker,
            cutoff_date=cutoff,
            scope=scope,
        )

    identity = await market_fundamentals.company_identity_for_instrument(
        ctx.conn,
        inst["instrument_id"],
        cutoff=cutoff,
    )
    if identity is None:
        ctx.registrar_insumo("market.fundamentals", ticker=params.ticker, cutoff=cutoff.isoformat(), n=0)
        return FundamentosEmpresaResolvida(
            ticker=inst.get("ticker") or params.ticker,
            instrument_id=inst["instrument_id"],
            in_universe=bool(inst["is_in_universe"]),
            cutoff_date=cutoff,
            scope=scope,
        )

    resolved = None
    metrics = tuple(dict.fromkeys(params.metricas or DEFAULT_METRICS))
    if identity.is_in_universe and identity.company_cnpj:
        loader = market_fundamentals.FundamentalsLoader(
            market_fundamentals.PostgresFundamentalsReader(ctx.conn)
        )
        resolved = await loader.load_latest_annual(
            identity.company_cnpj,
            cutoff=cutoff,
            scope=scope,
            metrics=metrics,
        )
    ctx.registrar_insumo(
        "market.fundamentals",
        ticker=identity.ticker or params.ticker,
        company_cnpj=identity.company_cnpj,
        cutoff=cutoff.isoformat(),
        temporal_semantics=market_fundamentals.FundamentalTemporalSemantics.AVAILABILITY_DATE_CUTOFF.value,
        scope=scope.value,
        document_type=market_fundamentals.FundamentalDocumentType.DFP.value,
        metrics=list(metrics),
        n=len(resolved.records) if resolved is not None else 0,
    )
    return FundamentosEmpresaResolvida(
        ticker=identity.ticker or params.ticker,
        name=identity.name,
        instrument_id=identity.instrument_id,
        company_cnpj=identity.company_cnpj,
        in_universe=identity.is_in_universe,
        cutoff_date=cutoff,
        scope=scope,
        resolved=resolved,
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


@tool(
    code="dados.fundamentos_empresa",
    family="dados",
    semver="1.0.0",
    display_name="Fundamentos da empresa",
    description=(
        "Retorna um snapshot compacto dos últimos fundamentos anuais (DFP) que já estavam disponíveis "
        "na data de referência, preservando availability_date, unidade e proveniência. Não calcula fair value."
    ),
    preparar=preparar_fundamentos_empresa,
    source_dependencies=(market_fundamentals.__file__,),
    requires_market_data=True,
    exposed_to_llm=False,
)
def calcular_fundamentos_empresa(r: FundamentosEmpresaResolvida) -> FundamentosEmpresaOutput:
    rows = r.resolved.records if r.resolved is not None else []
    avisos: list[str] = []
    if r.instrument_id is None:
        avisos.append(INSTRUMENTO_DESCONHECIDO)
    elif not r.in_universe:
        avisos.append(FORA_DA_COBERTURA)
    elif not r.company_cnpj:
        avisos.append(COMPANY_ID_UNAVAILABLE)
    elif not rows:
        avisos.append(SEM_DADOS)
    if r.resolved is not None:
        avisos.extend(r.resolved.provenance.warnings)

    items = [
        FundamentoEmpresaItem(
            metric=row.metric,
            value=row.value,
            value_unit=row.value_unit,
            currency=row.currency,
            instrument_id=row.instrument_id,
            reference_date=row.reference_date,
            availability_date=row.availability_date,
            document_type=row.document_type,
            period_label=row.period_label,
            is_derived=row.is_derived,
            source_code=row.source_code,
        )
        for row in rows
    ]
    as_of = max((x.availability_date for x in rows), default=None)
    fontes = r.resolved.provenance.source_codes if r.resolved is not None else []
    batches = r.resolved.provenance.ingestion_batch_ids if r.resolved is not None else []
    canonical = [x for x in rows if x.value_unit != market_fundamentals.FundamentalUnit.RAW]
    evidencia = Evidencia(
        fonte="+".join(fontes) or "market.fundamentals",
        instrument_ids=[r.instrument_id] if r.instrument_id else [],
        tickers=[r.ticker],
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=len(rows),
        metodo="latest_dfp_by_availability_date_cutoff",
        nota_metodo=(
            "Fundamentos usam availability_date <= cutoff e o último vintage anual DFP disponível em cada "
            "métrica/classe. O scope é explícito e não há fallback silencioso. Linhas value_unit=raw são "
            "preservadas, mas não são consideradas unidade canônica para valuation."
        ),
        suficiente=bool(canonical) and not any(
            x in avisos for x in (INSTRUMENTO_DESCONHECIDO, FORA_DA_COBERTURA, COMPANY_ID_UNAVAILABLE)
        ),
        avisos=_unique(avisos),
        metricas={"n_metricas": float(len(rows)), "n_metricas_canonicas": float(len(canonical))},
        ingestion_batch_ids=batches,
    )
    return FundamentosEmpresaOutput(
        ticker=r.ticker,
        company_cnpj=r.company_cnpj,
        scope=r.scope,
        fundamentos=items,
        evidencia=evidencia,
    )
