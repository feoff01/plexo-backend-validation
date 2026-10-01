"""Tendências anuais point-in-time de fundamentos de uma empresa (FQ5.5)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.market import fundamental_history
from app.market import fundamentals as market_fundamentals
from app.market.analytics import fundamental_trends
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


class TendenciasFundamentaisParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=40)
    data_referencia: date | None = None
    scope: Literal["consolidated", "standalone"] = "consolidated"
    periodos: int = Field(default=5, ge=2, le=10)
    metricas: list[str] | None = Field(
        default=None,
        max_length=12,
        description=(
            "Métricas company-level anuais para tendência. FQ5.5 não aceita métricas por classe, ITR ou fair value."
        ),
    )

    @field_validator("metricas")
    @classmethod
    def _metricas_suportadas(cls, value: list[str] | None):
        if value is None:
            return value
        unique = list(dict.fromkeys(value))
        unsupported = [m for m in unique if m not in fundamental_trends.CANONICAL_METRICS]
        if unsupported:
            raise ValueError(
                "métricas não suportadas em tendências fundamentais: "
                + ", ".join(sorted(set(unsupported)))
            )
        return unique


class TendenciasFundamentaisResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    name: str | None = None
    instrument_id: str | None = None
    company_cnpj: str | None = None
    in_universe: bool = False
    cutoff_date: date
    scope: market_fundamentals.FundamentalScope
    requested_metrics: tuple[str, ...] = fundamental_trends.CANONICAL_METRICS
    history: fundamental_history.ResolvedFundamentalHistory | None = None


class TendenciasFundamentaisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    company_cnpj: str | None = None
    scope: market_fundamentals.FundamentalScope
    periodo: str = "dfp_anual_point_in_time"
    metricas: list[fundamental_trends.FundamentalMetricTrend] = Field(default_factory=list)
    margens: list[fundamental_trends.FundamentalMarginTrend] = Field(default_factory=list)
    evidencia: Evidencia


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


async def preparar_tendencias_fundamentais(
    params: TendenciasFundamentaisParams,
    ctx: ToolContext,
) -> TendenciasFundamentaisResolvida:
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    inst = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    scope = market_fundamentals.FundamentalScope(params.scope)
    requested = tuple(params.metricas or fundamental_trends.CANONICAL_METRICS)
    if inst is None:
        ctx.registrar_insumo(
            "market.fundamental_history",
            ticker=params.ticker,
            cutoff=cutoff.isoformat(),
            periods=params.periodos,
            n=0,
        )
        return TendenciasFundamentaisResolvida(
            ticker=params.ticker,
            cutoff_date=cutoff,
            scope=scope,
            requested_metrics=requested,
        )

    identity = await market_fundamentals.company_identity_for_instrument(
        ctx.conn,
        inst["instrument_id"],
        cutoff=cutoff,
    )
    if identity is None:
        return TendenciasFundamentaisResolvida(
            ticker=inst.get("ticker") or params.ticker,
            instrument_id=inst["instrument_id"],
            in_universe=bool(inst["is_in_universe"]),
            cutoff_date=cutoff,
            scope=scope,
            requested_metrics=requested,
        )

    history = None
    if identity.is_in_universe and identity.company_cnpj:
        read_metrics = list(requested)
        if "ebitda" in requested and "ebitda_derived" not in read_metrics:
            read_metrics.append("ebitda_derived")
        history = await fundamental_history.FundamentalHistoryLoader(
            market_fundamentals.PostgresFundamentalsReader(ctx.conn)
        ).load_annual_history(
            identity.company_cnpj,
            cutoff=cutoff,
            scope=scope,
            metrics=tuple(read_metrics),
            periods=params.periodos,
        )

    ctx.registrar_insumo(
        "market.fundamental_history",
        ticker=identity.ticker or params.ticker,
        company_cnpj=identity.company_cnpj,
        cutoff=cutoff.isoformat(),
        temporal_semantics=(
            market_fundamentals.FundamentalTemporalSemantics.AVAILABILITY_DATE_CUTOFF.value
        ),
        scope=scope.value,
        document_type=market_fundamentals.FundamentalDocumentType.DFP.value,
        periods=params.periodos,
        metrics=list(requested),
        n=len(history.records) if history is not None else 0,
    )
    return TendenciasFundamentaisResolvida(
        ticker=identity.ticker or params.ticker,
        name=identity.name,
        instrument_id=identity.instrument_id,
        company_cnpj=identity.company_cnpj,
        in_universe=identity.is_in_universe,
        cutoff_date=cutoff,
        scope=scope,
        requested_metrics=requested,
        history=history,
    )


@tool(
    code="quant.tendencias_fundamentais",
    family="quant",
    semver="1.0.0",
    display_name="Tendências fundamentais",
    description=(
        "Analisa a evolução anual point-in-time de fundamentos DFP, incluindo variações YoY e margens "
        "EBITDA/líquida quando disponíveis. Não usa ITR, não faz forecast e não produz fair value."
    ),
    preparar=preparar_tendencias_fundamentais,
    source_dependencies=(
        market_fundamentals.__file__,
        fundamental_history.__file__,
        fundamental_trends.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=False,
)
def calcular_tendencias_fundamentais(
    r: TendenciasFundamentaisResolvida,
) -> TendenciasFundamentaisOutput:
    warnings: list[str] = []
    if r.instrument_id is None:
        warnings.append(INSTRUMENTO_DESCONHECIDO)
    elif not r.in_universe:
        warnings.append(FORA_DA_COBERTURA)
    elif not r.company_cnpj:
        warnings.append(COMPANY_ID_UNAVAILABLE)

    records = r.history.records if r.history is not None else []
    if r.history is not None:
        warnings.extend(r.history.provenance.warnings)
    analysis = fundamental_trends.analyze_fundamental_trends(
        records,
        requested_metrics=r.requested_metrics,
    )
    warnings.extend(analysis.warnings)
    if not analysis.metrics:
        warnings.append(SEM_DADOS)

    all_points = [point for metric in analysis.metrics for point in metric.points]
    sufficient = (
        r.instrument_id is not None
        and r.in_universe
        and r.company_cnpj is not None
        and any(len(metric.points) >= 2 for metric in analysis.metrics)
    )
    sources = r.history.provenance.source_codes if r.history is not None else []
    batches = r.history.provenance.ingestion_batch_ids if r.history is not None else []
    as_of = max((point.availability_date for point in all_points), default=None)
    evidencia = Evidencia(
        fonte="+".join(sources) or "market.fundamentals",
        instrument_ids=[r.instrument_id] if r.instrument_id else [],
        tickers=[r.ticker],
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=len(all_points),
        metodo="annual_dfp_pit_fundamental_trends",
        nota_metodo=(
            "Tendências usam somente DFP anual e, para cada reference_date, o último vintage cujo "
            "availability_date já existia no cutoff. Não há imputação. Crescimento percentual só é "
            "calculado quando a base anterior é positiva. Margens combinam numerador e receita do mesmo "
            "reference_date. EBITDA reportado tem prioridade sobre ebitda_derived. ITR, forecast, CAGR e "
            "fair value não fazem parte desta versão."
        ),
        suficiente=sufficient,
        avisos=_unique(warnings),
        metricas={
            "n_metricas": float(len(analysis.metrics)),
            "n_series_com_tendencia": float(
                sum(1 for metric in analysis.metrics if len(metric.points) >= 2)
            ),
            "n_margens": float(len(analysis.margins)),
        },
        ingestion_batch_ids=batches,
    )
    return TendenciasFundamentaisOutput(
        ticker=r.ticker,
        company_cnpj=r.company_cnpj,
        scope=r.scope,
        metricas=analysis.metrics,
        margens=analysis.margins,
        evidencia=evidencia,
    )
