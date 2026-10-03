from datetime import date

from app.market.yield_curves import (
    ResolvedYieldCurve,
    YieldCurvePoint,
    YieldCurveProvenance,
)
from app.tools import carregar_tools
from app.tools.analista.curva_juros import CurvaJurosResolvida, montar_curva_juros
from app.tools.registry import spec_de


def _resolved():
    ref = date(2026, 10, 2)
    return ResolvedYieldCurve(
        curve_name="ettj_pre",
        reference_date=ref,
        points=[
            YieldCurvePoint(
                business_days=252,
                rate_pct=13.3811,
                day_count="du_252",
                source_code="anbima",
                ingestion_batch_id="batch-1",
                availability_date=date(2026, 10, 3),
            ),
            YieldCurvePoint(
                business_days=504,
                rate_pct=13.7085,
                day_count="du_252",
                source_code="anbima",
                ingestion_batch_id="batch-1",
                availability_date=date(2026, 10, 3),
            ),
        ],
        provenance=YieldCurveProvenance(
            source_codes=["anbima"],
            ingestion_batch_ids=["batch-1"],
            reference_date=ref,
            availability_date=date(2026, 10, 3),
            cutoff_date=date(2026, 10, 3),
            strict_pit=True,
        ),
    )


def test_curva_juros_shadow_registry_contract():
    carregar_tools()
    spec = spec_de("dados.curva_juros")
    assert spec.semver == "1.0.0"
    assert spec.family == "dados"
    assert spec.exposed_to_llm is False
    assert spec.requires_market_data is True


def test_curva_juros_returns_only_exact_requested_vertices_without_interpolation():
    out = montar_curva_juros(
        CurvaJurosResolvida(
            curva="ettj_pre",
            cutoff_date=date(2026, 10, 3),
            vertices_du=[252, 378],
            resolved=_resolved(),
        )
    )
    assert out.unidade == "% a.a./252 d.u."
    assert out.data_curva == date(2026, 10, 2)
    assert [(p.vertice_du, p.taxa_pct_aa_252) for p in out.pontos] == [(252, 13.3811)]
    assert out.n_vertices_total == 2
    assert out.n_vertices_retornados == 1
    assert "vertice_ettj_indisponivel:378" in out.provenance.warnings
