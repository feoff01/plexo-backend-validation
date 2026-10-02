"""Comparação determinística de empresa contra peers B3 por subsetor/setor (FQ5.6B shadow).

A tool NÃO reimplementa valuation nem tendências. Ela resolve o universo setorial e compõe
as tools canônicas existentes, usando apenas estatística descritiva compartilhada para resumir
a distribuição dos pares.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.market import fundamental_history
from app.market import fundamentals as market_fundamentals
from app.market import sectors
from app.market import snapshots as market_snapshots
from app.market.analytics import fundamental_trends
from app.market.analytics import statistics as quant_statistics
from app.market.analytics import valuation as valuation_engine
from app.tools.analista import _comum as comum
from app.tools.analista import tendencias_fundamentais as trends_tool
from app.tools.analista import valor_mercado as valor_tool
from app.tools.executor import ToolContext
from app.tools.registry import tool


MetricName = Literal[
    "market_cap_brl",
    "pe",
    "ev_ebitda",
    "price_to_book",
    "fcf_yield_pct",
    "revenue_yoy_pct",
    "ebitda_yoy_pct",
    "net_income_yoy_pct",
    "ebitda_margin_pct",
    "net_margin_pct",
]

DEFAULT_METRICS: tuple[str, ...] = (
    "market_cap_brl",
    "pe",
    "ev_ebitda",
    "price_to_book",
    "fcf_yield_pct",
    "revenue_yoy_pct",
    "ebitda_yoy_pct",
    "net_income_yoy_pct",
    "ebitda_margin_pct",
    "net_margin_pct",
)

METRIC_UNITS = {
    "market_cap_brl": "BRL",
    "pe": "x",
    "ev_ebitda": "x",
    "price_to_book": "x",
    "fcf_yield_pct": "%",
    "revenue_yoy_pct": "%",
    "ebitda_yoy_pct": "%",
    "net_income_yoy_pct": "%",
    "ebitda_margin_pct": "%",
    "net_margin_pct": "%",
}

PEER_MISSING_TICKER = "peer_sem_ticker"
PEER_DATA_INCOMPLETE = "peer_dados_incompletos"
TARGET_METRIC_UNAVAILABLE = "metrica_target_indisponivel"
PEER_SAMPLE_INSUFFICIENT = "metrica_peer_amostra_insuficiente"


class ComparaveisSetorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=40)
    data_referencia: date | None = None
    nivel: Literal["subsetor", "setor"] = "subsetor"
    metricas: list[MetricName] | None = Field(default=None, max_length=10)
    max_exemplos: int = Field(default=5, ge=1, le=10)

    @field_validator("metricas")
    @classmethod
    def _dedupe_metricas(cls, value: list[MetricName] | None):
        if value is None:
            return value
        return list(dict.fromkeys(value))


class PeerCompanyResolved(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer_id: str
    issuer_name: str
    tickers: list[str] = Field(default_factory=list)
    representative_ticker: str
    valuation: valor_tool.ValorMercadoResolvido
    trends: trends_tool.TendenciasFundamentaisResolvida


class ComparaveisSetorResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    instrument_id: str | None = None
    cutoff_date: date
    nivel: Literal["subsetor", "setor"]
    requested_metrics: tuple[str, ...] = DEFAULT_METRICS
    max_exemplos: int = 5
    universe: sectors.PeerUniverse | None = None
    target_valuation: valor_tool.ValorMercadoResolvido | None = None
    target_trends: trends_tool.TendenciasFundamentaisResolvida | None = None
    peers: list[PeerCompanyResolved] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MetricComparisonOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    unit: str
    target_value: float | None = None
    n_valid: int = 0
    mean: float | None = None
    median: float | None = None
    sample_stddev: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    delta_target_vs_median: float | None = None
    delta_unit: str


class PeerExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer_name: str
    tickers: list[str] = Field(default_factory=list)


class ComparaveisSetorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    nivel: Literal["subsetor", "setor"]
    classificacao: str | None = None
    peer_count_total: int = 0
    comparacoes: list[MetricComparisonOutput] = Field(default_factory=list)
    peer_examples: list[PeerExampleOutput] = Field(default_factory=list)
    peer_examples_criterion: str = "ordem_alfabetica"
    evidencia: comum.Evidencia


async def _prepare_company(
    ticker: str,
    cutoff: date,
    ctx: ToolContext,
) -> tuple[valor_tool.ValorMercadoResolvido, trends_tool.TendenciasFundamentaisResolvida]:
    valuation = await valor_tool.preparar_valor_mercado(
        valor_tool.ValorMercadoParams(ticker=ticker, data_referencia=cutoff),
        ctx,
    )
    trends = await trends_tool.preparar_tendencias_fundamentais(
        trends_tool.TendenciasFundamentaisParams(
            ticker=ticker,
            data_referencia=cutoff,
            scope="consolidated",
            periodos=2,
            metricas=["revenue", "ebitda", "net_income"],
        ),
        ctx,
    )
    return valuation, trends


async def preparar_comparaveis_setor(
    params: ComparaveisSetorParams,
    ctx: ToolContext,
) -> ComparaveisSetorResolvida:
    cutoff = comum.resolver_cutoff(
        params.data_referencia,
        ctx.cutoff_date,
        await comum.data_referencia(ctx.conn),
    )
    metrics = tuple(params.metricas or DEFAULT_METRICS)
    inst = await comum.instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    if inst is None:
        return ComparaveisSetorResolvida(
            ticker=params.ticker,
            cutoff_date=cutoff,
            nivel=params.nivel,
            requested_metrics=metrics,
            max_exemplos=params.max_exemplos,
        )

    instrument_id = inst["instrument_id"]
    nivel = sectors.SectorLevel.SUBSETOR if params.nivel == "subsetor" else sectors.SectorLevel.SETOR
    universe = await sectors.peer_issuers(
        ctx.conn,
        instrument_id,
        cutoff=cutoff,
        level=nivel,
        strict_pit=True,
    )
    target_ticker = inst.get("ticker") or params.ticker
    target_valuation, target_trends = await _prepare_company(target_ticker, cutoff, ctx)

    warnings: list[str] = list(universe.warnings)
    peers: list[PeerCompanyResolved] = []
    for peer in universe.peers:
        tickers = sorted(set(peer.tickers))
        if not tickers:
            warnings.append(PEER_MISSING_TICKER)
            continue
        representative = tickers[0]
        valuation, trends = await _prepare_company(representative, cutoff, ctx)
        peers.append(
            PeerCompanyResolved(
                issuer_id=peer.issuer_id,
                issuer_name=peer.issuer_name,
                tickers=tickers,
                representative_ticker=representative,
                valuation=valuation,
                trends=trends,
            )
        )

    ctx.registrar_insumo(
        "market.sector_peers",
        ticker=target_ticker,
        instrument_id=instrument_id,
        cutoff=cutoff.isoformat(),
        level=params.nivel,
        source="b3",
        classification_value=universe.classification_value,
        peer_count_total=len(universe.peers),
        peer_count_prepared=len(peers),
        metrics=list(metrics),
    )
    return ComparaveisSetorResolvida(
        ticker=target_ticker,
        instrument_id=instrument_id,
        cutoff_date=cutoff,
        nivel=params.nivel,
        requested_metrics=metrics,
        max_exemplos=params.max_exemplos,
        universe=universe,
        target_valuation=target_valuation,
        target_trends=target_trends,
        peers=peers,
        warnings=list(dict.fromkeys(warnings)),
    )


def _trend_growth(out: trends_tool.TendenciasFundamentaisOutput, metric: str) -> float | None:
    item = next((x for x in out.metricas if x.metric == metric), None)
    return item.growth_pct if item is not None else None


def _margin(out: trends_tool.TendenciasFundamentaisOutput, name: str) -> float | None:
    item = next((x for x in out.margens if x.margin == name), None)
    return item.latest_pct if item is not None else None


def _metrics(
    valuation: valor_tool.ValorMercadoOutput,
    trends: trends_tool.TendenciasFundamentaisOutput,
) -> dict[str, float | None]:
    return {
        "market_cap_brl": valuation.market_cap_brl,
        "pe": valuation.multiples.pe,
        "ev_ebitda": valuation.multiples.ev_ebitda,
        "price_to_book": valuation.multiples.price_to_book,
        "fcf_yield_pct": valuation.multiples.fcf_yield_pct,
        "revenue_yoy_pct": _trend_growth(trends, "revenue"),
        "ebitda_yoy_pct": _trend_growth(trends, "ebitda"),
        "net_income_yoy_pct": _trend_growth(trends, "net_income"),
        "ebitda_margin_pct": _margin(trends, "ebitda_margin"),
        "net_margin_pct": _margin(trends, "net_margin"),
    }


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


@tool(
    code="quant.comparaveis_setor",
    family="quant",
    semver="1.0.0",
    display_name="Comparáveis por subsetor/setor",
    description=(
        "Compara valuation, crescimento e margens de uma empresa contra todos os peers B3 do mesmo "
        "subsetor ou setor, reutilizando as análises canônicas existentes. Não ranqueia nem recomenda."
    ),
    preparar=preparar_comparaveis_setor,
    source_dependencies=(
        comum.__file__,
        sectors.__file__,
        quant_statistics.__file__,
        valor_tool.__file__,
        trends_tool.__file__,
        market_fundamentals.__file__,
        market_snapshots.__file__,
        valuation_engine.__file__,
        fundamental_history.__file__,
        fundamental_trends.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=False,
)
def calcular_comparaveis_setor(r: ComparaveisSetorResolvida) -> ComparaveisSetorOutput:
    warnings = list(r.warnings)
    if r.target_valuation is None or r.target_trends is None:
        evidencia = comum.Evidencia(
            fonte="b3",
            instrument_ids=[r.instrument_id] if r.instrument_id else [],
            tickers=[r.ticker],
            cutoff_date=r.cutoff_date,
            as_of=None,
            n_observacoes=0,
            metodo="b3_sector_peers_canonical_company_metrics",
            nota_metodo=(
                "Comparação por issuer no mesmo subsetor/setor B3. Valuation e tendências são calculados "
                "pelas tools canônicas existentes; missing não é imputado."
            ),
            suficiente=False,
            avisos=_unique(warnings + [comum.SEM_DADOS]),
        )
        return ComparaveisSetorOutput(
            ticker=r.ticker,
            nivel=r.nivel,
            evidencia=evidencia,
        )

    target_val = valor_tool.calcular_valor_mercado(r.target_valuation)
    target_trends = trends_tool.calcular_tendencias_fundamentais(r.target_trends)
    target_metrics = _metrics(target_val, target_trends)

    peer_outputs: list[
        tuple[PeerCompanyResolved, valor_tool.ValorMercadoOutput, trends_tool.TendenciasFundamentaisOutput]
    ] = []
    for peer in r.peers:
        valuation = valor_tool.calcular_valor_mercado(peer.valuation)
        trends = trends_tool.calcular_tendencias_fundamentais(peer.trends)
        peer_outputs.append((peer, valuation, trends))
        if not valuation.evidencia.suficiente or not trends.evidencia.suficiente:
            warnings.append(PEER_DATA_INCOMPLETE)

    comparisons: list[MetricComparisonOutput] = []
    for metric in r.requested_metrics:
        values = [
            value
            for _peer, valuation, trends in peer_outputs
            if (value := _metrics(valuation, trends).get(metric)) is not None
        ]
        summary = quant_statistics.describe(values)
        target_value = target_metrics.get(metric)
        if target_value is None:
            warnings.append(TARGET_METRIC_UNAVAILABLE)
        if summary.count < 2:
            warnings.append(PEER_SAMPLE_INSUFFICIENT)
        delta = (
            target_value - summary.median
            if target_value is not None and summary.median is not None
            else None
        )
        unit = METRIC_UNITS[metric]
        comparisons.append(
            MetricComparisonOutput(
                metric=metric,
                unit=unit,
                target_value=target_value,
                n_valid=summary.count,
                mean=summary.mean,
                median=summary.median,
                sample_stddev=summary.sample_stddev,
                minimum=summary.minimum,
                maximum=summary.maximum,
                delta_target_vs_median=delta,
                delta_unit="p.p." if unit == "%" else unit,
            )
        )

    peer_examples = [
        PeerExampleOutput(issuer_name=peer.issuer_name, tickers=peer.tickers)
        for peer in sorted(r.peers, key=lambda x: (x.issuer_name.casefold(), x.issuer_id))[
            : r.max_exemplos
        ]
    ]

    source_parts = {"b3"}
    batches: set[str] = set()
    as_of_dates: list[date] = []
    source_evidence = [target_val.evidencia, target_trends.evidencia]
    for _peer, valuation, trends in peer_outputs:
        source_evidence.extend([valuation.evidencia, trends.evidencia])
    for evidence in source_evidence:
        source_parts.update(x for x in evidence.fonte.split("+") if x)
        batches.update(evidence.ingestion_batch_ids)
        if evidence.as_of is not None:
            as_of_dates.append(evidence.as_of)
    if r.universe is not None and r.universe.target.provenance.availability_date is not None:
        as_of_dates.append(r.universe.target.provenance.availability_date)
        batches.update(r.universe.target.provenance.ingestion_batch_ids)

    sufficient_metrics = sum(
        1
        for comparison in comparisons
        if comparison.target_value is not None and comparison.n_valid >= 2
    )
    peer_count = len(r.universe.peers) if r.universe is not None else 0
    suficiente = peer_count >= 2 and sufficient_metrics > 0
    evidencia = comum.Evidencia(
        fonte="+".join(sorted(source_parts)),
        instrument_ids=[r.instrument_id] if r.instrument_id else [],
        tickers=[r.ticker],
        cutoff_date=r.cutoff_date,
        as_of=max(as_of_dates, default=None),
        n_observacoes=peer_count,
        metodo="b3_sector_peers_plus_canonical_valuation_and_fundamental_trends",
        nota_metodo=(
            "O universo é company-level e deduplicado por issuer usando classificação B3 point-in-time. "
            "Subsetor é o nível padrão; setor só quando solicitado. Valuation, YoY e margens reutilizam "
            "integralmente as tools canônicas quant.valor_mercado e quant.tendencias_fundamentais. A "
            "distribuição usa todos os peers com valor válido para cada métrica; missing não vira zero. "
            "A lista de exemplos é alfabética e não altera a estatística. Não há ranking, recomendação, "
            "fair value ou inferência de qualidade."
        ),
        suficiente=suficiente,
        avisos=_unique(warnings),
        metricas={
            "peer_count_total": float(peer_count),
            "peer_count_prepared": float(len(r.peers)),
            "n_metricas_comparadas": float(len(comparisons)),
            "n_metricas_suficientes": float(sufficient_metrics),
        },
        ingestion_batch_ids=sorted(batches),
    )
    return ComparaveisSetorOutput(
        ticker=r.ticker,
        nivel=r.nivel,
        classificacao=(
            r.universe.classification_value if r.universe is not None else None
        ),
        peer_count_total=peer_count,
        comparacoes=comparisons,
        peer_examples=peer_examples,
        evidencia=evidencia,
    )
