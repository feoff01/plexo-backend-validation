from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.market.analytics import regimes
from app.market.analytics.models import ConditionMeasure
from app.market.series import (
    ADJUSTED_CLOSE_RETROSPECTIVE,
    MarketPoint,
    PriceBasis,
    ResolvedMarketSeries,
    SeriesProvenance,
    SeriesQuality,
    TemporalSemantics,
)
from app.tools import carregar_tools
from app.tools.analista import regimes as regimes_tool
from app.tools.registry import spec_de


D = [
    date(2024, 1, 2),
    date(2024, 1, 3),
    date(2024, 1, 4),
    date(2024, 1, 5),
    date(2024, 1, 8),
]


def _points(values: list[float], dates: list[date] | None = None) -> list[MarketPoint]:
    return [MarketPoint(data=d, valor=v) for d, v in zip(dates or D, values)]


def _quality(points: list[MarketPoint]) -> SeriesQuality:
    return SeriesQuality(
        observations=len(points),
        first_date=points[0].data if points else None,
        last_date=points[-1].data if points else None,
        stale_days=0 if points else None,
        missing_dates=[],
        unexpected_dates=[],
        coverage_ratio=1.0 if points else None,
        calendar_source="market.trading_calendar",
        calendar_fallback_used=False,
    )


def _asset(code: str, iid: str, values: list[float], *, basis=PriceBasis.ADJUSTED_CLOSE) -> ResolvedMarketSeries:
    points = _points(values)
    semantics = (
        TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
        if basis == PriceBasis.ADJUSTED_CLOSE
        else TemporalSemantics.OBSERVATION_DATE_CUTOFF
    )
    return ResolvedMarketSeries(
        code=code,
        instrument_id=iid,
        currency="BRL",
        points=points,
        quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.v_precos_ajustados" if basis == PriceBasis.ADJUSTED_CLOSE else "market.prices",
            source_codes=["b3"],
            ingestion_batch_ids=[f"batch-{code.lower()}"],
            calendar_ingestion_batch_ids=["cal-1"],
            price_basis=basis,
            temporal_semantics=semantics,
            cutoff_date=D[-1],
            warnings=[ADJUSTED_CLOSE_RETROSPECTIVE] if basis == PriceBasis.ADJUSTED_CLOSE else [],
        ),
    )


def _index(code: str, values: list[float], *, unit: str) -> ResolvedMarketSeries:
    points = _points(values)
    return ResolvedMarketSeries(
        code=code,
        index_code=code,
        unit=unit,
        points=points,
        quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.index_values",
            source_codes=["bacen_sgs"],
            ingestion_batch_ids=[f"batch-{code}"],
            calendar_ingestion_batch_ids=["cal-1"],
            price_basis=None,
            temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
            cutoff_date=D[-1],
            warnings=[],
        ),
    )


def test_level_driver_intervals_use_start_level_not_end_level():
    observations = regimes.driver_observations(
        _points([14.0, 13.0, 12.0]),
        criterion=regimes.RegimeCriterion.LEVEL,
        direction_measure=ConditionMeasure.LEVEL_CHANGE,
    )
    assert [o.driver_value for o in observations] == [14.0, 13.0]
    assert [(o.start_date, o.end_date) for o in observations] == [(D[0], D[1]), (D[1], D[2])]


def test_direction_driver_intervals_rate_use_level_change():
    observations = regimes.driver_observations(
        _points([14.0, 13.5, 14.0]),
        criterion=regimes.RegimeCriterion.DIRECTION,
        direction_measure=ConditionMeasure.LEVEL_CHANGE,
    )
    assert [o.driver_value for o in observations] == pytest.approx([-0.5, 0.5])


def test_direction_driver_intervals_points_use_return():
    observations = regimes.driver_observations(
        _points([100.0, 110.0, 99.0]),
        criterion=regimes.RegimeCriterion.DIRECTION,
        direction_measure=ConditionMeasure.RETURN,
    )
    assert [o.driver_value for o in observations] == pytest.approx([0.10, -0.10])


def test_align_regime_response_never_looks_forward_and_respects_freshness():
    response = _points(
        [100.0, 110.0, 121.0],
        dates=[date(2024, 1, 2), date(2024, 1, 4), date(2024, 1, 8)],
    )
    observations = [
        regimes.RegimeDriverObservation(
            start_date=date(2024, 1, 3), end_date=date(2024, 1, 7), driver_value=10.0,
        )
    ]
    pairs = regimes.align_response_intervals(response, observations, max_endpoint_gap_days=3)
    assert len(pairs) == 1
    assert pairs[0].response_start_date == date(2024, 1, 2)
    assert pairs[0].response_end_date == date(2024, 1, 4)
    assert pairs[0].response_return == pytest.approx(0.10)
    assert regimes.align_response_intervals(response, observations, max_endpoint_gap_days=1) == []


def _pair(driver: float, response: float, i: int) -> regimes.RegimeResponsePair:
    return regimes.RegimeResponsePair(
        driver_start_date=date(2024, 1, 2 + i),
        driver_end_date=date(2024, 1, 3 + i),
        response_start_date=date(2024, 1, 2 + i),
        response_end_date=date(2024, 1, 3 + i),
        driver_value=driver,
        response_return=response,
    )


def test_level_regimes_auto_median_split_is_explicit_and_balanced():
    pairs = [_pair(5, 0.01, 0), _pair(10, 0.02, 1), _pair(15, 0.03, 2), _pair(20, 0.04, 3)]
    out = regimes.analyze_regimes(pairs, criterion=regimes.RegimeCriterion.LEVEL)
    assert out.threshold == pytest.approx(12.5)
    assert out.threshold_source == regimes.ThresholdSource.SAMPLE_MEDIAN
    assert out.group_1.label == regimes.RegimeLabel.HIGH
    assert out.group_2.label == regimes.RegimeLabel.LOW
    assert out.group_1.summary.count == 2
    assert out.group_2.summary.count == 2
    assert out.mean_difference == pytest.approx(0.02)
    assert out.n_neutral == 0


def test_level_regimes_equal_to_threshold_are_neutral():
    pairs = [_pair(10, 0.01, 0), _pair(10, 0.02, 1), _pair(20, 0.03, 2)]
    out = regimes.analyze_regimes(
        pairs, criterion=regimes.RegimeCriterion.LEVEL, threshold=10.0,
    )
    assert out.threshold_source == regimes.ThresholdSource.EXPLICIT
    assert out.n_neutral == 2
    assert out.group_1.summary.count == 1
    assert out.group_2.summary.count == 0
    assert out.mean_difference is None


def test_direction_regimes_use_symmetric_threshold():
    pairs = [_pair(-0.03, 0.04, 0), _pair(-0.01, 0.01, 1), _pair(0.00, 0.00, 2), _pair(0.04, -0.02, 3)]
    out = regimes.analyze_regimes(
        pairs, criterion=regimes.RegimeCriterion.DIRECTION, threshold=0.02,
    )
    assert out.group_1.label == regimes.RegimeLabel.UP
    assert out.group_2.label == regimes.RegimeLabel.DOWN
    assert out.group_1.summary.count == 1
    assert out.group_2.summary.count == 1
    assert out.n_neutral == 2
    assert out.mean_difference == pytest.approx(-0.06)


def test_direction_default_threshold_is_zero_and_invalid_threshold_fails_closed():
    pairs = [_pair(-1.0, 0.01, 0), _pair(1.0, 0.02, 1)]
    out = regimes.analyze_regimes(pairs, criterion=regimes.RegimeCriterion.DIRECTION)
    assert out.threshold == 0.0
    assert out.threshold_source == regimes.ThresholdSource.ZERO_DEFAULT
    with pytest.raises(ValueError):
        regimes.analyze_regimes(pairs, criterion=regimes.RegimeCriterion.DIRECTION, threshold=-0.1)


def test_params_one_driver_and_threshold_semantics():
    p = regimes_tool.RegimesParams(ticker="PETR4", indice_driver="selic_meta", criterio="nivel")
    assert p.price_basis == PriceBasis.ADJUSTED_CLOSE
    assert p.limiar is None
    with pytest.raises(ValidationError):
        regimes_tool.RegimesParams(ticker="PETR4", criterio="nivel")
    with pytest.raises(ValidationError):
        regimes_tool.RegimesParams(
            ticker="PETR4", ticker_driver="VALE3", indice_driver="selic_meta", criterio="nivel"
        )
    with pytest.raises(ValidationError):
        regimes_tool.RegimesParams(
            ticker="PETR4", indice_driver="selic_meta", criterio="direcao", limiar=-0.1
        )


def _resolved(response: ResolvedMarketSeries | None, driver_series: ResolvedMarketSeries | None, **overrides):
    data = dict(
        ticker="AAA3",
        driver="selic_meta",
        tipo_driver="indice",
        instrument_id="iid-a",
        driver_instrument_id=None,
        response_in_universe=True,
        driver_in_universe=False,
        driver_found=True,
        driver_index_code="selic_meta",
        cutoff_date=D[-1],
        price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        serie_resposta=response,
        serie_driver=driver_series,
        unidade_driver="taxa_aa",
        medida_driver=ConditionMeasure.LEVEL_CHANGE,
        criterio=regimes.RegimeCriterion.LEVEL,
        limiar_interface=None,
        min_observacoes=1,
        max_dias_defasagem=5,
    )
    data.update(overrides)
    return regimes_tool.RegimesResolvida(**data)


def test_tool_level_rate_uses_start_level_median_and_compact_output():
    response = _asset("AAA3", "iid-a", [100, 110, 99, 108.9, 119.79])
    driver = _index("selic_meta", [10.0, 12.0, 14.0, 16.0, 18.0], unit="taxa_aa")
    out = regimes_tool.calcular_regimes(_resolved(response, driver))
    assert out.criterio == regimes.RegimeCriterion.LEVEL
    assert out.origem_limiar == regimes.ThresholdSource.SAMPLE_MEDIAN
    assert out.limiar_usado == pytest.approx(13.0)
    assert [g.rotulo for g in out.grupos] == ["alto", "baixo"]
    assert out.n_total == 4
    dumped = out.model_dump(mode="json")
    text = str(dumped).lower()
    assert "response_points" not in text
    assert "pairs" not in dumped


def test_tool_direction_rate_converts_interface_threshold_in_percentage_points():
    response = _asset("AAA3", "iid-a", [100, 102, 104.04, 101.9592, 103.998384])
    driver = _index("selic_meta", [10.0, 10.5, 10.6, 10.0, 9.9], unit="taxa_aa")
    out = regimes_tool.calcular_regimes(_resolved(
        response, driver,
        criterio=regimes.RegimeCriterion.DIRECTION,
        limiar_interface=0.25,
    ))
    assert out.limiar_usado == pytest.approx(0.25)
    assert out.unidade_limiar == "pontos_percentuais"
    assert [g.rotulo for g in out.grupos] == ["alta", "queda"]
    assert out.n_neutro == 2


def test_tool_direction_index_return_converts_one_percent_to_decimal_internal():
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    driver = _index("ibov", [100, 102, 101, 103, 100], unit="pontos")
    out = regimes_tool.calcular_regimes(_resolved(
        response, driver,
        driver="ibov", driver_index_code="ibov", unidade_driver="pontos",
        medida_driver=ConditionMeasure.RETURN,
        criterio=regimes.RegimeCriterion.DIRECTION,
        limiar_interface=1.0,
    ))
    assert out.limiar_usado == pytest.approx(1.0)
    assert out.unidade_limiar == "retorno_pct"
    assert [g.rotulo for g in out.grupos] == ["alta", "queda"]


def test_tool_marks_insufficient_when_one_regime_is_too_small_but_keeps_numbers():
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    driver = _index("selic_meta", [10.0, 11.0, 12.0, 13.0, 30.0], unit="taxa_aa")
    out = regimes_tool.calcular_regimes(_resolved(
        response, driver, min_observacoes=2, limiar_interface=12.0,
    ))
    counts = {g.rotulo: g.n for g in out.grupos}
    assert counts["alto"] == 1
    assert counts["baixo"] == 2
    assert out.evidencia.suficiente is False
    assert regimes_tool.REGIME_AMOSTRA_INSUFICIENTE in out.evidencia.avisos
    assert any(g.media_pct is not None for g in out.grupos)


def test_tool_promovida_registry_and_fingerprint():
    carregar_tools()
    spec = spec_de("quant.regimes")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    names = {Path(p).name for p in spec.source_files}
    assert {"regimes.py", "conditional.py", "series.py", "statistics.py"}.issubset(names)


def test_block_regimes_is_deterministic_and_translates_warnings():
    from app.agents.blocos import blocos_de

    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    driver = _index("selic_meta", [10.0, 11.0, 12.0, 13.0, 30.0], unit="taxa_aa")
    out = regimes_tool.calcular_regimes(_resolved(
        response, driver, min_observacoes=2, limiar_interface=12.0,
    ))
    blocks = blocos_de("quant.regimes", out.model_dump(mode="json"), execution_id="e-reg")
    assert len(blocks) == 1
    assert blocks[0]["tipo"] == "indicadores"
    assert "Regimes históricos" in blocks[0]["titulo"]
    warnings = (blocks[0].get("proveniencia") or {}).get("avisos") or []
    assert any("poucas observações" in warning for warning in warnings)


class _FakeCtx:
    def __init__(self):
        self.conn = object()
        self.cutoff_date = D[-1]
        self.insumos = []

    async def policy(self, code: str):
        assert code == "ANALISE_PARAMS"
        return {"janela_padrao_dias": 365, "min_observacoes": 3, "max_dias_defasagem": 5}

    def registrar_insumo(self, kind: str, **payload):
        self.insumos.append((kind, payload))


@pytest.mark.asyncio
async def test_preparar_regime_taxa_deriva_level_change_e_adjusted_sem_tool_acoplada(monkeypatch):
    ctx = _FakeCtx()
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    rate = _index("selic_meta", [14, 13.5, 13, 12.5, 12], unit="taxa_aa")
    calls = []

    async def fake_data_ref(conn):
        return D[-1]

    async def fake_inst(conn, termo, *, cutoff):
        return {"instrument_id": "iid-a", "ticker": "AAA3", "is_in_universe": True}

    async def fake_asset(conn, instrument_id, **kwargs):
        calls.append(("asset", kwargs))
        return response

    async def fake_index(conn, code, **kwargs):
        calls.append(("index", {"code": code, **kwargs}))
        return rate

    monkeypatch.setattr(regimes_tool, "data_referencia", fake_data_ref)
    monkeypatch.setattr(regimes_tool, "instrumento_por_termo", fake_inst)
    monkeypatch.setattr(regimes_tool, "carregar_serie_resolvida", fake_asset)
    monkeypatch.setattr(regimes_tool, "carregar_indice_resolvido", fake_index)

    r = await regimes_tool.preparar_regimes(
        regimes_tool.RegimesParams(ticker="AAA3", indice_driver="selic_meta", criterio="nivel"), ctx
    )
    assert r.medida_driver == ConditionMeasure.LEVEL_CHANGE
    assert r.criterio == regimes.RegimeCriterion.LEVEL
    assert r.temporal_semantics == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    assert calls[0][1]["basis"] == PriceBasis.ADJUSTED_CLOSE
    assert calls[0][1]["temporal_semantics"] == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW


def test_promovida_entra_no_catalogo_do_analista():
    from app.agents.turn import filtrar_tools
    from app.tools.registry import specs_registradas

    carregar_tools()
    visible = {s.code for s in filtrar_tools(specs_registradas(), familias=("quant", "dados"), plano="advanced")}
    assert "quant.regimes" in visible
    assert "quant.risco_retorno" in visible
    assert "quant.dependencia" in visible


def test_level_asset_reports_price_series_unit_instead_of_points():
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    driver = _asset("BBB3", "iid-b", [20, 21, 22, 23, 24])
    resolved = _resolved(
        response, driver,
        driver="BBB3", tipo_driver="ativo", driver_instrument_id="iid-b",
        driver_in_universe=True, driver_index_code=None, unidade_driver="BRL",
        medida_driver=ConditionMeasure.RETURN,
    )
    out = regimes_tool.calcular_regimes(resolved)
    assert out.unidade_limiar == "BRL"
