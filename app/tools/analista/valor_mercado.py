"""Market valuation de empresa com fundamentos PIT e preço bruto (FQ5.2)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.market import fundamentals as market_fundamentals
from app.market import snapshots as market_snapshots
from app.market.analytics import valuation as valuation_engine
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
FUNDAMENTAL_UNIT_INCOMPATIBLE = "fundamental_unit_incompativel"
SHARES_UNAVAILABLE = "shares_outstanding_indisponivel"
PRICE_UNAVAILABLE = "preco_bruto_indisponivel"

VALUATION_METRICS = (
    "shares_outstanding",
    "net_debt",
    "gross_debt",
    "cash_and_equivalents",
    "net_income",
    "ebitda",
    "ebitda_derived",
    "total_equity",
    "free_cash_flow",
)


class ValorMercadoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, max_length=40)
    data_referencia: date | None = None


class EquityClassResolved(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_id: str
    ticker: str | None = None
    name: str
    price: market_snapshots.MarketPriceSnapshot | None = None


class ValorMercadoResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    name: str | None = None
    instrument_id: str | None = None
    company_cnpj: str | None = None
    in_universe: bool = False
    cutoff_date: date
    classes: list[EquityClassResolved] = Field(default_factory=list)
    fundamentals: market_fundamentals.ResolvedFundamentals | None = None


class EquityClassOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str | None = None
    instrument_id: str
    price_brl: float | None = None
    price_date: date | None = None
    shares_outstanding: float | None = None
    market_value_brl: float | None = None
    complete: bool


class ValuationMultipleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pe: float | None = None
    ev_ebitda: float | None = None
    price_to_book: float | None = None
    fcf_yield_pct: float | None = None


class FundamentalInputUsed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    value: float
    reference_date: date
    availability_date: date
    source_code: str
    is_derived: bool


class ValorMercadoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    requested_price_brl: float | None = None
    requested_price_date: date | None = None
    classes: list[EquityClassOutput] = Field(default_factory=list)
    market_cap_brl: float | None = None
    net_debt_brl: float | None = None
    net_debt_source: str | None = None
    enterprise_value_brl: float | None = None
    multiples: ValuationMultipleOutput
    fundamentals_used: list[FundamentalInputUsed] = Field(default_factory=list)
    intrinsic_value_produced: bool = False
    evidencia: Evidencia


async def preparar_valor_mercado(params: ValorMercadoParams, ctx: ToolContext) -> ValorMercadoResolvido:
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    inst = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    if inst is None:
        ctx.registrar_insumo("market.valuation", ticker=params.ticker, cutoff=cutoff.isoformat(), n_classes=0)
        return ValorMercadoResolvido(ticker=params.ticker, cutoff_date=cutoff)

    identity = await market_fundamentals.company_identity_for_instrument(
        ctx.conn, inst["instrument_id"], cutoff=cutoff
    )
    if identity is None:
        return ValorMercadoResolvido(
            ticker=inst.get("ticker") or params.ticker,
            instrument_id=inst["instrument_id"],
            in_universe=bool(inst["is_in_universe"]),
            cutoff_date=cutoff,
        )

    fundamentals = None
    classes: list[EquityClassResolved] = []
    if identity.is_in_universe and identity.company_cnpj:
        fundamentals = await market_fundamentals.FundamentalsLoader(
            market_fundamentals.PostgresFundamentalsReader(ctx.conn)
        ).load_latest_annual(
            identity.company_cnpj,
            cutoff=cutoff,
            scope=market_fundamentals.FundamentalScope.CONSOLIDATED,
            metrics=VALUATION_METRICS,
        )
        for instrument in await market_fundamentals.equity_instruments_for_company(ctx.conn, identity):
            price = await market_snapshots.read_latest_raw_price(
                ctx.conn, instrument.instrument_id, cutoff=cutoff
            )
            classes.append(
                EquityClassResolved(
                    instrument_id=instrument.instrument_id,
                    ticker=instrument.ticker,
                    name=instrument.name,
                    price=price,
                )
            )

    ctx.registrar_insumo(
        "market.valuation",
        ticker=identity.ticker or params.ticker,
        company_cnpj=identity.company_cnpj,
        cutoff=cutoff.isoformat(),
        price_basis="raw_close",
        fundamental_temporal_semantics=(
            market_fundamentals.FundamentalTemporalSemantics.AVAILABILITY_DATE_CUTOFF.value
        ),
        fundamental_period="latest_dfp_annual",
        n_classes=len(classes),
        n_fundamentals=len(fundamentals.records) if fundamentals is not None else 0,
    )
    return ValorMercadoResolvido(
        ticker=identity.ticker or params.ticker,
        name=identity.name,
        instrument_id=identity.instrument_id,
        company_cnpj=identity.company_cnpj,
        in_universe=identity.is_in_universe,
        cutoff_date=cutoff,
        classes=classes,
        fundamentals=fundamentals,
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _company_metric(
    fundamentals: market_fundamentals.ResolvedFundamentals | None,
    metric: str,
    *,
    requested_instrument_id: str | None,
) -> market_fundamentals.FundamentalRecord | None:
    if fundamentals is None:
        return None
    rows = market_fundamentals.records_for_metric(fundamentals, metric)
    if not rows:
        return None
    company_level = [x for x in rows if x.instrument_id is None]
    if len(company_level) == 1:
        return company_level[0]
    requested = [x for x in rows if x.instrument_id == requested_instrument_id]
    if len(requested) == 1:
        return requested[0]
    return rows[0] if len(rows) == 1 else None


def _brl_value(
    row: market_fundamentals.FundamentalRecord | None,
    warnings: list[str],
) -> float | None:
    if row is None:
        return None
    if row.value_unit != market_fundamentals.FundamentalUnit.BRL or row.currency != "BRL":
        warnings.append(FUNDAMENTAL_UNIT_INCOMPATIBLE)
        return None
    return row.value


def _shares_by_class(
    fundamentals: market_fundamentals.ResolvedFundamentals | None,
    class_ids: list[str],
    warnings: list[str],
) -> dict[str, float | None]:
    out = {iid: None for iid in class_ids}
    if fundamentals is None:
        warnings.append(SHARES_UNAVAILABLE)
        return out
    rows = market_fundamentals.records_for_metric(fundamentals, "shares_outstanding")
    valid = [x for x in rows if x.value_unit == market_fundamentals.FundamentalUnit.SHARES and x.value > 0]
    by_id = {x.instrument_id: x.value for x in valid if x.instrument_id is not None}
    for iid in class_ids:
        if iid in by_id:
            out[iid] = by_id[iid]
    if len(class_ids) == 1 and out[class_ids[0]] is None:
        company = [x for x in valid if x.instrument_id is None]
        if len(company) == 1:
            out[class_ids[0]] = company[0].value
    if any(v is None for v in out.values()):
        warnings.append(SHARES_UNAVAILABLE)
    if any(x.value_unit != market_fundamentals.FundamentalUnit.SHARES for x in rows):
        warnings.append(FUNDAMENTAL_UNIT_INCOMPATIBLE)
    return out


def _used(rows: list[market_fundamentals.FundamentalRecord | None]) -> list[FundamentalInputUsed]:
    seen: set[tuple[str, date, date, str]] = set()
    out: list[FundamentalInputUsed] = []
    for row in rows:
        if row is None:
            continue
        key = (row.metric, row.reference_date, row.availability_date, row.source_code)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            FundamentalInputUsed(
                metric=row.metric,
                value=row.value,
                reference_date=row.reference_date,
                availability_date=row.availability_date,
                source_code=row.source_code,
                is_derived=row.is_derived,
            )
        )
    return sorted(out, key=lambda x: (x.metric, x.reference_date, x.availability_date))


@tool(
    code="quant.valor_mercado",
    family="quant",
    semver="1.0.0",
    display_name="Valor de mercado e múltiplos",
    description=(
        "Calcula preço bruto observado, valor de mercado, enterprise value e múltiplos a partir de "
        "fundamentos anuais point-in-time com unidade explícita. Não produz valor intrínseco/fair value."
    ),
    preparar=preparar_valor_mercado,
    source_dependencies=(
        market_fundamentals.__file__,
        market_snapshots.__file__,
        valuation_engine.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=True,
)
def calcular_valor_mercado(r: ValorMercadoResolvido) -> ValorMercadoOutput:
    warnings: list[str] = []
    if r.instrument_id is None:
        warnings.append(INSTRUMENTO_DESCONHECIDO)
    elif not r.in_universe:
        warnings.append(FORA_DA_COBERTURA)
    elif not r.company_cnpj:
        warnings.append(COMPANY_ID_UNAVAILABLE)

    if r.fundamentals is not None:
        warnings.extend(r.fundamentals.provenance.warnings)

    class_ids = [x.instrument_id for x in r.classes]
    shares = _shares_by_class(r.fundamentals, class_ids, warnings) if class_ids else {}
    engine_inputs: list[valuation_engine.EquityClassInput] = []
    for item in r.classes:
        if item.price is None:
            warnings.append(PRICE_UNAVAILABLE)
            price_brl = None
        else:
            warnings.extend(item.price.warnings)
            price_brl = item.price.value if item.price.currency == "BRL" else None
            if price_brl is None:
                warnings.append(PRICE_UNAVAILABLE)
        engine_inputs.append(
            valuation_engine.EquityClassInput(
                instrument_id=item.instrument_id,
                ticker=item.ticker,
                price_brl=price_brl,
                shares_outstanding=shares.get(item.instrument_id),
            )
        )

    net_debt_row = _company_metric(r.fundamentals, "net_debt", requested_instrument_id=r.instrument_id)
    gross_debt_row = _company_metric(r.fundamentals, "gross_debt", requested_instrument_id=r.instrument_id)
    cash_row = _company_metric(r.fundamentals, "cash_and_equivalents", requested_instrument_id=r.instrument_id)
    net_income_row = _company_metric(r.fundamentals, "net_income", requested_instrument_id=r.instrument_id)
    ebitda_row = _company_metric(r.fundamentals, "ebitda", requested_instrument_id=r.instrument_id)
    if ebitda_row is None:
        ebitda_row = _company_metric(r.fundamentals, "ebitda_derived", requested_instrument_id=r.instrument_id)
    equity_row = _company_metric(r.fundamentals, "total_equity", requested_instrument_id=r.instrument_id)
    fcf_row = _company_metric(r.fundamentals, "free_cash_flow", requested_instrument_id=r.instrument_id)

    if engine_inputs:
        analysis = valuation_engine.analyze_market_valuation(
            engine_inputs,
            net_debt_brl=_brl_value(net_debt_row, warnings),
            gross_debt_brl=_brl_value(gross_debt_row, warnings),
            cash_and_equivalents_brl=_brl_value(cash_row, warnings),
            net_income_brl=_brl_value(net_income_row, warnings),
            ebitda_brl=_brl_value(ebitda_row, warnings),
            total_equity_brl=_brl_value(equity_row, warnings),
            free_cash_flow_brl=_brl_value(fcf_row, warnings),
        )
        warnings.extend(analysis.warnings)
    else:
        analysis = valuation_engine.MarketValuationAnalysis(
            classes=[],
            warnings=[valuation_engine.MARKET_CAP_UNAVAILABLE],
        )
        warnings.append(SEM_DADOS)

    by_id = {x.instrument_id: x for x in analysis.classes}
    classes_out: list[EquityClassOutput] = []
    for item in r.classes:
        calc = by_id.get(item.instrument_id)
        classes_out.append(
            EquityClassOutput(
                ticker=item.ticker,
                instrument_id=item.instrument_id,
                price_brl=calc.price_brl if calc else None,
                price_date=item.price.price_date if item.price else None,
                shares_outstanding=calc.shares_outstanding if calc else None,
                market_value_brl=calc.market_value_brl if calc else None,
                complete=bool(calc and calc.complete),
            )
        )

    requested = next((x for x in classes_out if x.instrument_id == r.instrument_id), None)
    fundamentals_used = _used([
        net_debt_row,
        gross_debt_row,
        cash_row,
        net_income_row,
        ebitda_row,
        equity_row,
        fcf_row,
        *(market_fundamentals.records_for_metric(r.fundamentals, "shares_outstanding")
          if r.fundamentals is not None else []),
    ])
    sources = set(r.fundamentals.provenance.source_codes if r.fundamentals is not None else [])
    batches = set(r.fundamentals.provenance.ingestion_batch_ids if r.fundamentals is not None else [])
    price_dates: list[date] = []
    for item in r.classes:
        if item.price is not None:
            sources.update(item.price.source_codes)
            batches.update(item.price.ingestion_batch_ids)
            price_dates.append(item.price.price_date)
    as_of = max(price_dates, default=max((x.availability_date for x in fundamentals_used), default=None))

    evidencia = Evidencia(
        fonte="+".join(sorted(sources)) or "market",
        instrument_ids=class_ids or ([r.instrument_id] if r.instrument_id else []),
        tickers=[x.ticker for x in r.classes if x.ticker] or [r.ticker],
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=len(fundamentals_used) + sum(1 for x in r.classes if x.price is not None),
        metodo="raw_close_plus_latest_dfp_pit_market_valuation",
        nota_metodo=(
            "Preço é fechamento bruto observado, não preço ajustado. Fundamentos usam o último DFP anual "
            "cujo availability_date já existia no cutoff. Market cap exige preço e shares de todas as classes "
            "de ação identificadas; EV soma dívida líquida. Múltiplos com denominador não positivo ficam "
            "indefinidos. Esta tool não produz valor intrínseco/fair value."
        ),
        suficiente=(analysis.market_cap_brl is not None and r.in_universe and r.company_cnpj is not None),
        avisos=_unique(warnings),
        metricas={
            "market_cap_brl": analysis.market_cap_brl,
            "enterprise_value_brl": analysis.enterprise_value_brl,
            "pe": analysis.pe,
            "ev_ebitda": analysis.ev_ebitda,
            "price_to_book": analysis.price_to_book,
            "fcf_yield_pct": analysis.fcf_yield_pct,
        },
        ingestion_batch_ids=sorted(batches),
    )
    return ValorMercadoOutput(
        ticker=r.ticker,
        requested_price_brl=requested.price_brl if requested else None,
        requested_price_date=requested.price_date if requested else None,
        classes=classes_out,
        market_cap_brl=analysis.market_cap_brl,
        net_debt_brl=analysis.net_debt_brl,
        net_debt_source=analysis.net_debt_source,
        enterprise_value_brl=analysis.enterprise_value_brl,
        multiples=ValuationMultipleOutput(
            pe=analysis.pe,
            ev_ebitda=analysis.ev_ebitda,
            price_to_book=analysis.price_to_book,
            fcf_yield_pct=analysis.fcf_yield_pct,
        ),
        fundamentals_used=fundamentals_used,
        intrinsic_value_produced=False,
        evidencia=evidencia,
    )
