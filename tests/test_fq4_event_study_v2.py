from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.agents.blocos import blocos_de
from app.agents.turn import filtrar_tools
from app.market.analytics import event_study as event_engine
from app.market.analytics.models import ReturnMethod
from app.market.analytics.returns import calculate_returns
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
from app.tools.analista import event_study as event_legacy
from app.tools.analista import event_study_legacy_1_0_1 as event_replay_101
from app.tools.analista import event_study_v2
from app.tools.registry import spec_de, specs_registradas


def _dates(n: int, *, start=date(2024, 1, 2)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def _quality(points: list[MarketPoint]) -> SeriesQuality:
    return SeriesQuality(
        observations=len(points), first_date=points[0].data if points else None,
        last_date=points[-1].data if points else None, stale_days=0 if points else None,
        missing_dates=[], unexpected_dates=[], coverage_ratio=None,
        calendar_source=None, calendar_fallback_used=False,
    )


def _asset(code: str, iid: str, values: list[float], *, dates: list[date] | None = None,
           basis: PriceBasis = PriceBasis.ADJUSTED_CLOSE) -> ResolvedMarketSeries:
    ds = dates or _dates(len(values))
    points = [MarketPoint(data=d, valor=v) for d, v in zip(ds, values)]
    semantics = (TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
                 if basis == PriceBasis.ADJUSTED_CLOSE
                 else TemporalSemantics.OBSERVATION_DATE_CUTOFF)
    return ResolvedMarketSeries(
        code=code, instrument_id=iid, currency="BRL", points=points, quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.v_precos_ajustados" if basis == PriceBasis.ADJUSTED_CLOSE else "market.prices",
            source_codes=["b3"], ingestion_batch_ids=[f"batch-{code}"], calendar_ingestion_batch_ids=[],
            price_basis=basis, temporal_semantics=semantics, cutoff_date=ds[-1] if ds else date(2024, 1, 1),
            warnings=[ADJUSTED_CLOSE_RETROSPECTIVE] if basis == PriceBasis.ADJUSTED_CLOSE else [],
        ),
    )


def _paths_from_returns(benchmark_returns: list[float], *, alpha=0.0, beta=1.0,
                        event_shocks: dict[int, float] | None = None) -> tuple[list[float], list[float]]:
    pb, pa = [100.0], [50.0]
    shocks = event_shocks or {}
    for i, rb in enumerate(benchmark_returns):
        ra = alpha + beta * rb + shocks.get(i, 0.0)
        pb.append(pb[-1] * (1.0 + rb))
        pa.append(pa[-1] * (1.0 + ra))
    return pa, pb


def test_engine_market_model_recovers_exact_alpha_beta_and_zero_car():
    rb = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.0, 0.012, -0.008, 0.004, 0.009, -0.003]
    pa, pb = _paths_from_returns(rb, alpha=0.001, beta=1.5)
    dates = _dates(len(pa))
    ra_obs = calculate_returns(_asset("A", "ia", pa, dates=dates).points, ReturnMethod.SIMPLE)
    rb_obs = calculate_returns(_asset("B", "ib", pb, dates=dates).points, ReturnMethod.SIMPLE)
    requested = dates[9]
    out = event_engine.analyze_event_study(
        ra_obs, rb_obs, event_date=requested,
        method=event_engine.EventStudyMethod.MARKET_MODEL,
        estimation_observations=6, pre_observations=1, post_observations=1,
        inference_mode=event_engine.EventInferenceMode.NONE,
    )
    assert out.effective_event_date == requested
    assert out.alpha == pytest.approx(0.001, abs=1e-12)
    assert out.beta == pytest.approx(1.5, abs=1e-10)
    assert out.car == pytest.approx(0.0, abs=1e-10)
    assert len(out.abnormal_returns) == 3
    assert out.estimation_window.count == 6
    assert out.event_window.count == 3
    assert out.car_estimate is None


def test_effective_event_date_uses_first_aligned_return_not_asset_price_only():
    dates = _dates(7)
    asset = _asset("A", "ia", [100, 101, 102, 103, 104, 105, 106], dates=dates)
    # Benchmark misses dates[3], so the first common return on/after requested dates[3] is later.
    b_dates = [dates[0], dates[1], dates[2], dates[4], dates[5], dates[6]]
    bench = _asset("B", "ib", [100, 101, 102, 103, 104, 105], dates=b_dates)
    out = event_engine.analyze_event_study(
        calculate_returns(asset.points, "simples"), calculate_returns(bench.points, "simples"),
        event_date=dates[3], method="market_adjusted", estimation_observations=2,
        pre_observations=0, post_observations=0, inference_mode="none",
    )
    assert out.effective_event_date == dates[4]


def test_estimation_window_never_overlaps_event_window():
    returns = [0.01, 0.02, -0.01, 0.03, -0.02, 0.01, 0.02, 0.01, -0.01]
    pa, pb = _paths_from_returns(returns, alpha=0.0, beta=1.0)
    ds = _dates(len(pa))
    out = event_engine.analyze_event_study(
        calculate_returns(_asset("A", "ia", pa, dates=ds).points, "simples"),
        calculate_returns(_asset("B", "ib", pb, dates=ds).points, "simples"),
        event_date=ds[7], method="market_model", estimation_observations=3,
        pre_observations=1, post_observations=1, inference_mode="none",
    )
    assert out.estimation_window.end_date < out.event_window.start_date


def test_pre_and_post_truncation_are_separate_and_car_remains_partial():
    pa, pb = _paths_from_returns([0.01, 0.02, -0.01, 0.01])
    ds = _dates(len(pa))
    early = event_engine.analyze_event_study(
        calculate_returns(_asset("A", "ia", pa, dates=ds).points, "simples"),
        calculate_returns(_asset("B", "ib", pb, dates=ds).points, "simples"),
        event_date=ds[1], method="market_adjusted", estimation_observations=2,
        pre_observations=2, post_observations=0, inference_mode="none",
    )
    assert early.pre_truncated is True and early.post_truncated is False
    assert early.car is not None
    late = event_engine.analyze_event_study(
        calculate_returns(_asset("A", "ia", pa, dates=ds).points, "simples"),
        calculate_returns(_asset("B", "ib", pb, dates=ds).points, "simples"),
        event_date=ds[-1], method="market_adjusted", estimation_observations=2,
        pre_observations=0, post_observations=2, inference_mode="none",
    )
    assert late.post_truncated is True and late.car is not None


def test_market_adjusted_abnormal_return_is_asset_minus_benchmark():
    ds = _dates(7)
    pa, pb = _paths_from_returns([0.01, 0.02, -0.01, 0.03, 0.0, 0.01], event_shocks={4: 0.05})
    out = event_engine.analyze_event_study(
        calculate_returns(_asset("A", "ia", pa, dates=ds).points, "simples"),
        calculate_returns(_asset("B", "ib", pb, dates=ds).points, "simples"),
        event_date=ds[5], method="market_adjusted", estimation_observations=3,
        pre_observations=0, post_observations=0, inference_mode="none",
    )
    assert out.alpha == 0.0 and out.beta == 1.0
    assert out.car == pytest.approx(0.05)


def test_market_adjusted_classic_inference_matches_sample_sd_sqrt_L():
    # Estimation residuals = [1%, -1%, 2%, -2%]; event shocks = +3%, +4%.
    rb = [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]
    shocks = {0: 0.01, 1: -0.01, 2: 0.02, 3: -0.02, 4: 0.03, 5: 0.04}
    pa, pb = _paths_from_returns(rb, event_shocks=shocks)
    ds = _dates(len(pa))
    out = event_engine.analyze_event_study(
        calculate_returns(_asset("A", "ia", pa, dates=ds).points, "simples"),
        calculate_returns(_asset("B", "ib", pb, dates=ds).points, "simples"),
        event_date=ds[5], method="market_adjusted", estimation_observations=4,
        pre_observations=0, post_observations=1, inference_mode="classic_iid_normal",
    )
    expected_sd = statistics.stdev([0.01, -0.01, 0.02, -0.02])
    expected_se_pct = expected_sd * math.sqrt(2) * 100
    assert out.car == pytest.approx(0.07)
    assert out.car_estimate is not None
    assert out.car_estimate.estimate == pytest.approx(7.0)
    assert out.car_estimate.standard_error == pytest.approx(expected_se_pct)
    assert "event_study_inferencia_hipoteses_fortes" in out.car_estimate.warnings


def test_market_model_classic_car_variance_matches_independent_formula():
    rb = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.012, -0.008, 0.004, 0.009]
    residuals = [0.003, -0.002, 0.001, -0.004, 0.002, 0.0, 0.02, -0.01, 0.0, 0.0]
    pb, pa = [100.0], [50.0]
    for x, e in zip(rb, residuals):
        pb.append(pb[-1] * (1 + x))
        pa.append(pa[-1] * (1 + 0.001 + 1.2 * x + e))
    ds = _dates(len(pa))
    out = event_engine.analyze_event_study(
        calculate_returns(_asset("A", "ia", pa, dates=ds).points, "simples"),
        calculate_returns(_asset("B", "ib", pb, dates=ds).points, "simples"),
        event_date=ds[8], method="market_model", estimation_observations=6,
        pre_observations=0, post_observations=1, inference_mode="classic_iid_normal",
    )
    # Independent formula from the actual aligned estimation/event benchmark returns.
    est_x = rb[1:7]
    est_y = [0.001 + 1.2*x + e for x, e in zip(rb[1:7], residuals[1:7])]
    xbar = statistics.fmean(est_x)
    ybar = statistics.fmean(est_y)
    sxx = sum((x-xbar)**2 for x in est_x)
    beta = sum((x-xbar)*(y-ybar) for x, y in zip(est_x, est_y)) / sxx
    alpha = ybar - beta*xbar
    errs = [y-(alpha+beta*x) for x, y in zip(est_x, est_y)]
    sigma2 = sum(e*e for e in errs) / (len(est_x)-2)
    evt_x = rb[7:9]
    L = len(evt_x)
    expected_se = math.sqrt(sigma2 * (L + L*L/len(est_x) + (sum(evt_x)-L*xbar)**2/sxx)) * 100
    assert out.car_estimate is not None
    assert out.car_estimate.standard_error == pytest.approx(expected_se, rel=1e-10)


def test_requested_inference_can_be_unavailable_without_erasing_descriptive_car():
    pa, pb = _paths_from_returns([0.01, 0.02, 0.03])
    ds = _dates(len(pa))
    out = event_engine.analyze_event_study(
        calculate_returns(_asset("A", "ia", pa, dates=ds).points, "simples"),
        calculate_returns(_asset("B", "ib", pb, dates=ds).points, "simples"),
        event_date=ds[2], method="market_adjusted", estimation_observations=1,
        pre_observations=0, post_observations=0, inference_mode="classic_iid_normal",
    )
    assert out.car is not None
    assert out.car_estimate is not None
    assert out.car_estimate.estimate == pytest.approx(out.car * 100)
    assert out.car_estimate.standard_error is None
    assert "event_study_inferencia_indisponivel" in out.car_estimate.warnings


def test_constant_benchmark_market_model_does_not_invent_beta_or_car():
    ds = _dates(8)
    # Constant simple return on benchmark => x in estimation is constant.
    pb = [100.0]
    pa = [50.0]
    for i in range(7):
        pb.append(pb[-1] * 1.01)
        pa.append(pa[-1] * (1.01 + (0.001 if i % 2 else -0.001)))
    out = event_engine.analyze_event_study(
        calculate_returns(_asset("A", "ia", pa, dates=ds).points, "simples"),
        calculate_returns(_asset("B", "ib", pb, dates=ds).points, "simples"),
        event_date=ds[6], method="market_model", estimation_observations=4,
        pre_observations=0, post_observations=0, inference_mode="none",
    )
    assert out.beta is None and out.car is None
    assert "benchmark_constante_event_study" in out.warnings


def _resolved(series_a: ResolvedMarketSeries | None, series_b: ResolvedMarketSeries | None, **overrides):
    ds = _dates(12)
    data = dict(
        ticker="AAA3", benchmark="BBB3", instrument_ids=["ia", "ib"],
        ticker_found=True, benchmark_found=True, ticker_in_universe=True, benchmark_in_universe=True, cutoff_date=ds[-1], data_evento=ds[8],
        serie_ativo=series_a, serie_benchmark=series_b, price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        metodo="market_model", metodo_retorno=ReturnMethod.SIMPLE,
        inferencia=event_engine.EventInferenceMode.NONE, janela_estimacao_observacoes=5,
        pre_observacoes=1, pos_observacoes=1, min_observacoes=3,
    )
    data.update(overrides)
    return event_study_v2.EventStudyV2Resolvido(**data)


def test_tool_output_uses_statistical_evidence_and_remains_compact():
    rb = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.0, 0.012, -0.008, 0.004, 0.009]
    pa, pb = _paths_from_returns(rb, alpha=0.001, beta=1.5, event_shocks={7: 0.02})
    ds = _dates(len(pa))
    a = _asset("AAA3", "ia", pa, dates=ds)
    b = _asset("BBB3", "ib", pb, dates=ds)
    out = event_study_v2.calcular_event_study_v2(_resolved(a, b, cutoff_date=ds[-1], data_evento=ds[8], inferencia="classic_iid_normal"))
    payload = out.model_dump(mode="json")
    assert out.car_pct is not None
    assert out.car_estimate is not None
    assert "car" in out.evidencia.estimativas
    assert ADJUSTED_CLOSE_RETROSPECTIVE in out.evidencia.avisos
    serialized = json.dumps(payload)
    for forbidden in ('"prices"', '"pairs"', '"residuals"', '"estimation_returns"'):
        assert forbidden not in serialized


def test_params_default_adjusted_none_inference_and_no_point_in_time_language():
    p = event_study_v2.EventStudyV2Params(ticker="PETR4", data_evento=date(2024, 1, 1))
    assert p.price_basis == PriceBasis.ADJUSTED_CLOSE
    assert p.inferencia == event_engine.EventInferenceMode.NONE
    schema_text = json.dumps(event_study_v2.EventStudyV2Params.model_json_schema(), ensure_ascii=False).lower()
    assert "point-in-time" not in schema_text


def test_v2_is_shadow_and_legacy_101_stays_visible_and_unchanged():
    carregar_tools()
    v2 = spec_de("quant.event_study_v2")
    legacy = spec_de("quant.event_study")
    assert v2.semver == "1.0.0" and v2.exposed_to_llm is False
    assert legacy.semver == "1.0.2" and legacy.exposed_to_llm is True
    visible = {s.code for s in filtrar_tools(specs_registradas(), familias=("quant", "dados"), plano="advanced")}
    assert "quant.event_study_v2" not in visible
    assert "quant.event_study" in visible
    names = {Path(p).name for p in v2.source_files}
    assert {"event_study_v2.py", "event_study.py", "series.py", "returns.py", "dependence.py", "regression.py", "estimates.py", "evidencia_estatistica.py"} <= names


def test_legacy_golden_still_replays_bit_for_bit():
    golden = Path("tests/golden/quant_event_study.json")
    data = json.loads(golden.read_text(encoding="utf-8"))
    output = event_replay_101.calcular_event_study_1_0_1(event_replay_101.EventStudyResolvido.model_validate(data["resolvido"]))
    assert output.model_dump(mode="json") == data["esperado"]


class _FakeCtx:
    def __init__(self, cutoff: date):
        self.conn = object()
        self.cutoff_date = cutoff
        self.insumos = []

    async def policy(self, code: str):
        assert code == "ANALISE_PARAMS"
        return {
            "janela_padrao_dias": 365, "min_observacoes": 3, "max_dias_defasagem": 5,
            "metodo_retorno": "simples", "benchmark_padrao": "BBB3",
            "event_study": {"janela_estimacao_dias": 5, "pre_dias": 1, "pos_dias": 1, "metodo": "market_model"},
        }

    def registrar_insumo(self, kind: str, **payload):
        self.insumos.append((kind, payload))


@pytest.mark.asyncio
async def test_preparar_v2_uses_same_basis_semantics_for_asset_and_benchmark(monkeypatch):
    ds = _dates(12)
    a = _asset("AAA3", "ia", list(range(100, 112)), dates=ds)
    b = _asset("BBB3", "ib", list(range(200, 212)), dates=ds)
    ctx = _FakeCtx(ds[-1])
    calls = []

    async def fake_today(conn): return ds[-1]
    async def fake_inst(conn, termo, *, cutoff):
        return {"instrument_id": "ia" if termo == "AAA3" else "ib", "ticker": termo, "is_in_universe": True}
    async def fake_load(conn, instrument_id, **kwargs):
        calls.append((instrument_id, kwargs))
        return a if instrument_id == "ia" else b

    monkeypatch.setattr(event_study_v2, "data_referencia", fake_today)
    monkeypatch.setattr(event_study_v2, "instrumento_por_termo", fake_inst)
    monkeypatch.setattr(event_study_v2, "carregar_serie_resolvida", fake_load)
    r = await event_study_v2.preparar_event_study_v2(
        event_study_v2.EventStudyV2Params(ticker="AAA3", benchmark="BBB3", data_evento=ds[8]), ctx
    )
    assert r.price_basis == PriceBasis.ADJUSTED_CLOSE
    assert r.temporal_semantics == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    assert len(calls) == 2
    assert all(c[1]["basis"] == PriceBasis.ADJUSTED_CLOSE for c in calls)
    assert all(c[1]["temporal_semantics"] == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW for c in calls)
    assert all(c[1]["include_calendar"] is False for c in calls)


def test_v2_block_exposes_car_ci_without_claiming_significance():
    rb = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.0, 0.012, -0.008, 0.004, 0.009]
    pa, pb = _paths_from_returns(rb, alpha=0.001, beta=1.5, event_shocks={7: 0.02})
    ds = _dates(len(pa))
    out = event_study_v2.calcular_event_study_v2(_resolved(
        _asset("AAA3", "ia", pa, dates=ds), _asset("BBB3", "ib", pb, dates=ds),
        cutoff_date=ds[-1], data_evento=ds[8], inferencia="classic_iid_normal",
    ))
    blocks = blocos_de("quant.event_study_v2", out.model_dump(mode="json"), execution_id="e1")
    assert blocks
    text = str(blocks).lower()
    assert "intervalo de confiança" in text or "limite inferior" in text
    assert "não implica" in text or "não prova" in text
    assert "significativo" not in text


def test_synchronized_returns_align_price_endpoints_before_return_calculation():
    ds = _dates(5)
    asset = [MarketPoint(data=d, valor=v) for d, v in zip(ds, [100, 110, 121, 133.1, 146.41])]
    bench_dates = [ds[0], ds[1], ds[3], ds[4]]  # missing ds[2]
    bench = [MarketPoint(data=d, valor=v) for d, v in zip(bench_dates, [100, 110, 121, 133.1])]
    ra, rb = event_engine.synchronized_returns_from_prices(asset, bench, method="simples")
    assert [x.data for x in ra] == [ds[1], ds[3], ds[4]]
    assert [x.data for x in rb] == [ds[1], ds[3], ds[4]]
    # Both sides now use ds[1] -> ds[3] for the middle return (asset's ds[2] is deliberately ignored).
    assert ra[1].value == pytest.approx(133.1 / 110 - 1)
    assert rb[1].value == pytest.approx(121 / 110 - 1)


def test_unknown_and_out_of_coverage_are_distinct_warnings():
    out_unknown = event_study_v2.calcular_event_study_v2(_resolved(
        None, None, instrument_ids=[], ticker_found=False, benchmark_found=False,
        ticker_in_universe=False, benchmark_in_universe=False,
    ))
    assert "instrumento_desconhecido" in out_unknown.evidencia.avisos
    assert "fora_da_cobertura" not in out_unknown.evidencia.avisos

    out_coverage = event_study_v2.calcular_event_study_v2(_resolved(
        None, None, instrument_ids=["ia", "ib"], ticker_found=True, benchmark_found=True,
        ticker_in_universe=False, benchmark_in_universe=False,
    ))
    assert "fora_da_cobertura" in out_coverage.evidencia.avisos
    assert "instrumento_desconhecido" not in out_coverage.evidencia.avisos


def test_inference_none_does_not_add_empty_estimates_payload():
    rb = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.0, 0.012, -0.008, 0.004, 0.009]
    pa, pb = _paths_from_returns(rb, alpha=0.001, beta=1.5)
    ds = _dates(len(pa))
    out = event_study_v2.calcular_event_study_v2(_resolved(
        _asset("AAA3", "ia", pa, dates=ds), _asset("BBB3", "ib", pb, dates=ds),
        cutoff_date=ds[-1], data_evento=ds[8], inferencia="none",
    ))
    assert out.car_estimate is None
    assert out.evidencia.estimativas == {}


def test_truncated_event_window_is_descriptive_but_not_sufficient():
    rb = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.0]
    pa, pb = _paths_from_returns(rb, alpha=0.001, beta=1.5)
    ds = _dates(len(pa))
    out = event_study_v2.calcular_event_study_v2(_resolved(
        _asset("AAA3", "ia", pa, dates=ds), _asset("BBB3", "ib", pb, dates=ds),
        cutoff_date=ds[-1], data_evento=ds[-1], pre_observacoes=0, pos_observacoes=2,
        janela_estimacao_observacoes=4, min_observacoes=3,
    ))
    assert out.car_pct is not None
    assert out.truncada_pos is True
    assert out.evidencia.suficiente is False
    assert "janela_pos_truncada" in out.evidencia.avisos


def test_legacy_public_schema_no_longer_promises_point_in_time():
    carregar_tools()
    legacy_schema = json.dumps(spec_de("quant.event_study").param_schema, ensure_ascii=False).lower()
    assert "point-in-time" not in legacy_schema
    assert spec_de("quant.event_study").semver == "1.0.2"


def test_property_exact_market_model_recovers_parameters_across_250_paths():
    import random
    rng = random.Random(20260925)
    for _ in range(250):
        n = 18
        benchmark_returns = [rng.uniform(-0.03, 0.03) for _ in range(n)]
        # Guarantee variation in the estimation window.
        if max(benchmark_returns[:10]) - min(benchmark_returns[:10]) < 1e-8:
            benchmark_returns[0] += 0.01
        alpha = rng.uniform(-0.002, 0.002)
        beta = rng.uniform(-1.5, 2.0)
        pa, pb = _paths_from_returns(benchmark_returns, alpha=alpha, beta=beta)
        ds = _dates(len(pa))
        ra, rm = event_engine.synchronized_returns_from_prices(
            _asset("A", "ia", pa, dates=ds).points,
            _asset("B", "ib", pb, dates=ds).points,
            method="simples",
        )
        out = event_engine.analyze_event_study(
            ra, rm, event_date=ds[13], method="market_model", estimation_observations=8,
            pre_observations=1, post_observations=1, inference_mode="none",
        )
        assert out.alpha == pytest.approx(alpha, abs=2e-12)
        assert out.beta == pytest.approx(beta, abs=2e-10)
        assert out.car == pytest.approx(0.0, abs=2e-10)


def test_property_price_scale_does_not_change_event_study_across_250_paths():
    import random
    rng = random.Random(9252026)
    for _ in range(250):
        benchmark_returns = [rng.uniform(-0.025, 0.025) for _ in range(14)]
        shocks = {9: rng.uniform(-0.04, 0.04), 10: rng.uniform(-0.04, 0.04)}
        pa, pb = _paths_from_returns(benchmark_returns, alpha=0.0005, beta=1.1, event_shocks=shocks)
        ds = _dates(len(pa))
        scale_a = rng.uniform(0.1, 1000.0)
        scale_b = rng.uniform(0.1, 1000.0)

        def run(a_values, b_values):
            ra, rm = event_engine.synchronized_returns_from_prices(
                _asset("A", "ia", a_values, dates=ds).points,
                _asset("B", "ib", b_values, dates=ds).points,
                method="simples",
            )
            return event_engine.analyze_event_study(
                ra, rm, event_date=ds[10], method="market_model", estimation_observations=7,
                pre_observations=0, post_observations=1, inference_mode="classic_iid_normal",
            )

        base = run(pa, pb)
        scaled = run([x * scale_a for x in pa], [x * scale_b for x in pb])
        assert scaled.alpha == pytest.approx(base.alpha, abs=2e-12)
        assert scaled.beta == pytest.approx(base.beta, abs=2e-10)
        assert scaled.car == pytest.approx(base.car, abs=2e-10)
        assert scaled.car_estimate is not None and base.car_estimate is not None
        assert scaled.car_estimate.standard_error == pytest.approx(base.car_estimate.standard_error, rel=2e-9, abs=2e-10)
