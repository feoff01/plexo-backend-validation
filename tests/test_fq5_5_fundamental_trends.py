from datetime import date

import pytest

from app.market import fundamental_history
from app.market import fundamentals
from app.market.analytics import fundamental_trends
from app.tools import carregar_tools
from app.tools.registry import spec_de


class FakeReader:
    def __init__(self, rows):
        self.rows = rows

    async def read_fundamentals(self, company_cnpj, *, cutoff, scope, document_type, metrics=None):
        allowed = set(metrics or [])
        return [
            row for row in self.rows
            if row.company_cnpj == company_cnpj
            and row.scope == scope
            and row.document_type == document_type
            and (not allowed or row.metric in allowed)
        ]


def row(metric, value, ref, avail, *, derived=False, unit="brl", currency="BRL", instrument_id=None):
    return fundamentals.FundamentalRecord(
        company_cnpj="12345678000199",
        instrument_id=instrument_id,
        reference_date=ref,
        availability_date=avail,
        document_type="DFP",
        scope="consolidated",
        period_label="FY",
        metric=metric,
        value=value,
        value_unit=unit,
        currency=currency,
        is_derived=derived,
        source_code="cvm",
        ingestion_batch_id=None,
    )


@pytest.mark.asyncio
async def test_history_loader_respeita_cutoff_restated_e_limite_de_periodos():
    rows = [
        row("revenue", 100, date(2022,12,31), date(2023,3,1)),
        row("revenue", 110, date(2022,12,31), date(2024,4,1)),  # restatement futuro ao cutoff
        row("revenue", 120, date(2023,12,31), date(2024,3,1)),
        row("revenue", 150, date(2024,12,31), date(2025,3,1)),
        row("revenue", 190, date(2025,12,31), date(2026,3,1)),
    ]
    loader = fundamental_history.FundamentalHistoryLoader(FakeReader(rows))
    resolved = await loader.load_annual_history(
        "12345678000199",
        cutoff=date(2025,6,1),
        metrics=("revenue",),
        periods=3,
    )
    assert [(r.reference_date, r.value) for r in resolved.records] == [
        (date(2022,12,31), 110),  # em 2025 o restatement 2024 já era conhecido
        (date(2023,12,31), 120),
        (date(2024,12,31), 150),
    ]

    before_restated = await loader.load_annual_history(
        "12345678000199",
        cutoff=date(2024,3,15),
        metrics=("revenue",),
        periods=3,
    )
    assert [(r.reference_date, r.value) for r in before_restated.records] == [
        (date(2022,12,31), 100),
        (date(2023,12,31), 120),
    ]


def test_engine_growth_margins_e_preferencia_ebitda_reportado():
    records = [
        row("revenue", 100, date(2022,12,31), date(2023,3,1)),
        row("revenue", 120, date(2023,12,31), date(2024,3,1)),
        row("revenue", 150, date(2024,12,31), date(2025,3,1)),
        row("ebitda_derived", 20, date(2022,12,31), date(2023,3,1), derived=True),
        row("ebitda", 30, date(2023,12,31), date(2024,3,1)),
        row("ebitda_derived", 999, date(2023,12,31), date(2024,3,2), derived=True),
        row("ebitda", 45, date(2024,12,31), date(2025,3,1)),
        row("net_income", 10, date(2022,12,31), date(2023,3,1)),
        row("net_income", 12, date(2023,12,31), date(2024,3,1)),
        row("net_income", 18, date(2024,12,31), date(2025,3,1)),
    ]
    out = fundamental_trends.analyze_fundamental_trends(
        records,
        requested_metrics=("revenue", "ebitda", "net_income"),
    )
    revenue = next(x for x in out.metrics if x.metric == "revenue")
    assert revenue.growth_pct == pytest.approx(25.0)
    ebitda = next(x for x in out.metrics if x.metric == "ebitda")
    assert [p.source_metric for p in ebitda.points] == ["ebitda_derived", "ebitda", "ebitda"]
    assert ebitda.points[1].value == 30
    ebitda_margin = next(x for x in out.margins if x.margin == "ebitda_margin")
    assert [p.value_pct for p in ebitda_margin.points] == pytest.approx([20,25,30])
    assert ebitda_margin.change_pp == pytest.approx(5.0)
    net_margin = next(x for x in out.margins if x.margin == "net_margin")
    assert net_margin.latest_pct == pytest.approx(12.0)


def test_engine_nao_calcula_growth_com_base_nao_positiva_nem_imputa_margem():
    records = [
        row("revenue", 0, date(2022,12,31), date(2023,3,1)),
        row("revenue", 100, date(2023,12,31), date(2024,3,1)),
        row("net_income", -5, date(2022,12,31), date(2023,3,1)),
        row("net_income", 10, date(2023,12,31), date(2024,3,1)),
    ]
    out = fundamental_trends.analyze_fundamental_trends(
        records,
        requested_metrics=("revenue", "net_income"),
    )
    revenue = next(x for x in out.metrics if x.metric == "revenue")
    assert revenue.growth_pct is None
    income = next(x for x in out.metrics if x.metric == "net_income")
    assert income.growth_pct is None
    assert fundamental_trends.NON_POSITIVE_GROWTH_BASE in out.warnings
    assert fundamental_trends.NON_POSITIVE_REVENUE in out.warnings
    net_margin = next(x for x in out.margins if x.margin == "net_margin")
    assert len(net_margin.points) == 1 and net_margin.points[0].reference_date == date(2023,12,31)


def test_engine_exclui_unidade_incompativel_e_avisa_historico_curto():
    records = [
        row("revenue", 100, date(2023,12,31), date(2024,3,1), unit="raw", currency=None),
        row("revenue", 120, date(2024,12,31), date(2025,3,1)),
    ]
    out = fundamental_trends.analyze_fundamental_trends(records, requested_metrics=("revenue",))
    assert len(out.metrics) == 1 and len(out.metrics[0].points) == 1
    assert fundamental_trends.UNIT_INCOMPATIBLE in out.warnings
    assert fundamental_trends.INSUFFICIENT_HISTORY in out.warnings


def test_tool_fq55_publica_sem_afetar_contrato_existente():
    carregar_tools()
    spec = spec_de("quant.tendencias_fundamentais")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    assert spec.requires_market_data is True
    assert spec_de("dados.fundamentos_empresa").semver == "1.0.0"
    assert spec_de("quant.valor_mercado").semver == "1.0.0"
