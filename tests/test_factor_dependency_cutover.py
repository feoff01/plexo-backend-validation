"""Cutover de dependência: resolver compartilhado, equivalência e replay legacy."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.market import series as market_series
from app.market.analytics.models import DependenceMethod, ReturnMethod
from app.market.series import (
    MarketPoint,
    PriceBasis,
    ResolvedMarketSeries,
    SeriesProvenance,
    SeriesQuality,
    TemporalSemantics,
)
from app.tools import carregar_tools
from app.tools.analista import dependencia
from app.tools.analista import dependencia_legacy_1_0_1 as legacy_dep
from app.tools.analista import dependencia_macro_legacy_1_0_0 as legacy_macro
from app.tools.analista import factor_resolution
from app.tools.analista.factor_resolution import FactorRef, ResolvedFactor
from app.tools.registry import spec_de

CUTOFF = date(2024, 1, 8)
DATES = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), CUTOFF]


def _quality(points):
    return SeriesQuality(
        observations=len(points), first_date=points[0].data if points else None,
        last_date=points[-1].data if points else None, stale_days=0 if points else None,
        missing_dates=[], unexpected_dates=[], coverage_ratio=1.0 if points else None,
        calendar_source="market.trading_calendar", calendar_fallback_used=False,
    )


def _asset(code, iid, values):
    points = [MarketPoint(data=d, valor=v) for d, v in zip(DATES, values)]
    return ResolvedMarketSeries(
        code=code, instrument_id=iid, currency="BRL", points=points, quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.v_precos_ajustados", source_codes=["b3"],
            ingestion_batch_ids=[f"batch-{code.lower()}"], calendar_ingestion_batch_ids=["cal"],
            price_basis=PriceBasis.ADJUSTED_CLOSE,
            temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
            cutoff_date=CUTOFF, warnings=["adjusted_close_retrospective"],
        ),
    )


def _index(code, values, unit="taxa_aa"):
    points = [MarketPoint(data=d, valor=v) for d, v in zip(DATES, values)]
    return ResolvedMarketSeries(
        code=code, index_code=code, unit=unit, points=points, quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.index_values", source_codes=["bacen_sgs"], ingestion_batch_ids=["idx-batch"],
            calendar_ingestion_batch_ids=["cal"], price_basis=None,
            temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
            cutoff_date=CUTOFF, warnings=[],
        ),
    )


def _fx(values):
    points = [MarketPoint(data=d, valor=v) for d, v in zip(DATES, values)]
    return ResolvedMarketSeries(
        code="USD/BRL", unit="pontos", points=points, quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.fx_rates", source_codes=["bacen_sgs"], ingestion_batch_ids=[],
            calendar_ingestion_batch_ids=["cal"], price_basis=None,
            temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
            cutoff_date=CUTOFF, warnings=["fx_observation_date_cutoff_sem_vintage"],
        ),
    )


def _fa(series):
    return ResolvedFactor(
        ref=FactorRef(tipo="ativo", codigo=series.code), tipo="ativo", codigo=series.code,
        found=True, in_universe=True, instrument_id=series.instrument_id, series=series,
    )


def _fb_asset(series):
    return ResolvedFactor(
        ref=FactorRef(tipo="ativo", codigo=series.code), tipo="ativo", codigo=series.code,
        found=True, in_universe=True, instrument_id=series.instrument_id, series=series,
    )


def _fb_index(series):
    return ResolvedFactor(
        ref=FactorRef(tipo="indice", codigo=series.code), tipo="indice", codigo=series.code,
        found=True, index_code=series.code, unit=series.unit, series=series,
    )


def _fb_fx(series):
    return ResolvedFactor(
        ref=FactorRef(tipo="cambio", codigo="USD/BRL"), tipo="cambio", codigo="USD/BRL",
        found=True, base_currency="USD", quote_currency="BRL", unit="pontos", series=series,
    )


def _new_resolved(a, b, *, method=DependenceMethod.PEARSON, lag=0):
    return dependencia.DependenciaResolvida(
        fator_a=_fa(a), fator_b=b, cutoff_date=CUTOFF,
        price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        metodo=method, defasagem_observacoes=lag, metodo_retorno=ReturnMethod.LOG,
        dias_uteis_ano=252, min_observacoes=2, max_dias_defasagem=5,
    )


def _legacy_resolved(a, b, *, index=False, method=DependenceMethod.PEARSON, lag=0):
    return legacy_dep.DependenciaResolvida(
        ticker_a=a.code, codigo_b=b.code, tipo_b="indice" if index else "ativo",
        instrument_a_id=a.instrument_id, instrument_b_id=None if index else b.instrument_id,
        a_in_universe=True, b_in_universe=not index, b_found=True,
        index_code_b=b.code if index else None, cutoff_date=CUTOFF,
        price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        serie_a=a, serie_b=b, unidade_b=b.unit or "pontos", metodo=method,
        defasagem_observacoes=lag, metodo_retorno=ReturnMethod.LOG,
        dias_uteis_ano=252, min_observacoes=2, max_dias_defasagem=5,
    )


def test_factor_ref_normaliza_sem_inverter_fx():
    assert FactorRef(tipo="indice", codigo="CDI").codigo == "cdi"
    assert FactorRef(tipo="cambio", codigo="usd/brl").codigo == "USD/BRL"
    assert FactorRef(tipo="ativo", codigo=" PETR4 ").codigo == "PETR4"
    with pytest.raises(ValidationError):
        FactorRef(tipo="cambio", codigo="USD")
    with pytest.raises(ValidationError):
        FactorRef(tipo="cambio", codigo="USD/USD")


@pytest.mark.asyncio
async def test_resolve_factor_ativo_indice_fx_e_fail_closed(monkeypatch):
    asset = _asset("PETR4", "iid-petr", [100, 102, 101, 104, 106])
    idx = _index("cdi", [10, 10.1, 10.2, 10.3, 10.4])
    fx = _fx([4.9, 4.95, 4.92, 5.02, 5.08])

    async def fake_inst(conn, termo, *, cutoff):
        if termo == "PETR4":
            return {"instrument_id": "iid-petr", "ticker": "PETR4", "is_in_universe": True}
        if termo == "FORA3":
            return {"instrument_id": "iid-fora", "ticker": "FORA3", "is_in_universe": False}
        return None

    async def fake_asset(conn, iid, **kwargs): return asset
    async def fake_index(conn, code, **kwargs):
        if code == "desconhecido":
            raise market_series.UnknownIndex(code)
        return idx
    async def fake_exists(conn, base, quote, *, cutoff): return base == "USD" and quote == "BRL"
    async def fake_fx(conn, base, quote, **kwargs): return fx

    monkeypatch.setattr(factor_resolution, "instrumento_por_termo", fake_inst)
    monkeypatch.setattr(factor_resolution, "carregar_serie_resolvida", fake_asset)
    monkeypatch.setattr(factor_resolution, "carregar_indice_resolvido", fake_index)
    monkeypatch.setattr(factor_resolution.market_factors, "fx_pair_exists", fake_exists)
    monkeypatch.setattr(factor_resolution.market_factors, "load_fx_series", fake_fx)

    common = dict(
        conn=object(), de=date(2024, 1, 1), ate=CUTOFF, cutoff=CUTOFF,
        asset_price_basis=PriceBasis.ADJUSTED_CLOSE,
        asset_temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
    )
    ra = await factor_resolution.resolve_factor(ref=FactorRef(tipo="ativo", codigo="PETR4"), **common)
    assert ra.found and ra.in_universe and ra.series is asset
    fora = await factor_resolution.resolve_factor(ref=FactorRef(tipo="ativo", codigo="FORA3"), **common)
    assert fora.found and fora.in_universe is False and fora.series is None
    unknown = await factor_resolution.resolve_factor(ref=FactorRef(tipo="ativo", codigo="ZZZ3"), **common)
    assert not unknown.found and unknown.series is None
    ri = await factor_resolution.resolve_factor(ref=FactorRef(tipo="indice", codigo="CDI"), **common)
    assert ri.found and ri.codigo == "cdi" and ri.series is idx
    iu = await factor_resolution.resolve_factor(ref=FactorRef(tipo="indice", codigo="desconhecido"), **common)
    assert not iu.found and iu.series is None
    rf = await factor_resolution.resolve_factor(ref=FactorRef(tipo="cambio", codigo="usd/brl"), **common)
    assert rf.found and rf.codigo == "USD/BRL" and rf.series is fx
    fu = await factor_resolution.resolve_factor(ref=FactorRef(tipo="cambio", codigo="EUR/BRL"), **common)
    assert not fu.found and fu.series is None


@pytest.mark.parametrize("method", [DependenceMethod.PEARSON, DependenceMethod.SPEARMAN])
@pytest.mark.parametrize("lag", [-1, 0, 1])
def test_v2_ativo_ativo_equivale_v1_0_1(method, lag):
    a = _asset("AAA3", "iid-a", [100, 103, 101, 106, 104])
    b = _asset("BBB3", "iid-b", [200, 198, 205, 203, 210])
    new = dependencia.calcular_dependencia(_new_resolved(a, _fb_asset(b), method=method, lag=lag))
    old = legacy_dep.calcular_dependencia_1_0_1(_legacy_resolved(a, b, method=method, lag=lag))
    assert new.coeficiente == pytest.approx(old.coeficiente) if old.coeficiente is not None else new.coeficiente is None
    assert new.n_pares == old.n_pares
    assert new.evidencia.as_of == old.evidencia.as_of
    assert new.evidencia.suficiente == old.evidencia.suficiente
    assert new.evidencia.metricas == old.evidencia.metricas


@pytest.mark.parametrize("method", [DependenceMethod.PEARSON, DependenceMethod.SPEARMAN])
def test_v2_ativo_indice_equivale_v1_0_1(method):
    a = _asset("AAA3", "iid-a", [100, 103, 101, 106, 104])
    idx = _index("cdi", [10.0, 10.2, 10.1, 10.4, 10.3], unit="taxa_aa")
    new = dependencia.calcular_dependencia(_new_resolved(a, _fb_index(idx), method=method))
    old = legacy_dep.calcular_dependencia_1_0_1(_legacy_resolved(a, idx, index=True, method=method))
    assert new.coeficiente == pytest.approx(old.coeficiente) if old.coeficiente is not None else new.coeficiente is None
    assert new.n_pares == old.n_pares
    assert new.evidencia.as_of == old.evidencia.as_of
    assert new.evidencia.index_codes == old.evidencia.index_codes == ["cdi"]


def test_v2_ativo_fx_equivale_macro_v1_0_0():
    a = _asset("AAA3", "iid-a", [100, 103, 101, 106, 104])
    fx = _fx([4.90, 4.95, 4.92, 5.02, 5.08])
    new = dependencia.calcular_dependencia(_new_resolved(a, _fb_fx(fx)))
    old_r = legacy_macro.DependenciaMacroResolvida(
        ticker="AAA3", factor_code="USD/BRL", factor_type="cambio", instrument_id="iid-a",
        response_in_universe=True, factor_found=True, factor_index_code=None,
        cutoff_date=CUTOFF, price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        serie_resposta=a, serie_fator=fx, unidade_fator="pontos", metodo=DependenceMethod.PEARSON,
        defasagem_observacoes=0, metodo_retorno=ReturnMethod.LOG, dias_uteis_ano=252,
        min_observacoes=2, max_dias_defasagem=5,
    )
    old = legacy_macro.calcular_dependencia_macro_1_0_0(old_r)
    assert new.coeficiente == pytest.approx(old.coeficiente)
    assert new.n_pares == old.n_pares
    assert new.evidencia.as_of == old.evidencia.as_of
    assert "fx_observation_date_cutoff_sem_vintage" in new.evidencia.avisos


def test_registry_cutover_semver_exposicao_e_fingerprints():
    carregar_tools()
    dep = spec_de("quant.dependencia")
    macro = spec_de("quant.dependencia_macro")
    assert dep.semver == "2.0.0" and dep.exposed_to_llm is True
    assert macro.semver == "1.0.1" and macro.exposed_to_llm is False
    assert legacy_dep.LEGACY_SEMVER == "1.0.1"
    assert legacy_macro.LEGACY_SEMVER == "1.0.0"
    names = {Path(p).name for p in dep.source_files}
    assert "factor_resolution.py" in names and "dependence.py" in names and "factors.py" in names


def test_legacy_goldens_replay_exato():
    root = Path(__file__).resolve().parent / "golden"
    dep_data = json.loads((root / "quant_dependencia_1_0_1.json").read_text(encoding="utf-8"))
    dep_out = legacy_dep.calcular_dependencia_1_0_1(
        legacy_dep.DependenciaResolvida.model_validate(dep_data["resolvido"])
    )
    assert dep_out.model_dump(mode="json") == dep_data["esperado"]

    macro_data = json.loads((root / "quant_dependencia_macro_1_0_0.json").read_text(encoding="utf-8"))
    macro_out = legacy_macro.calcular_dependencia_macro_1_0_0(
        legacy_macro.DependenciaMacroResolvida.model_validate(macro_data["resolvido"])
    )
    assert macro_out.model_dump(mode="json") == macro_data["esperado"]
