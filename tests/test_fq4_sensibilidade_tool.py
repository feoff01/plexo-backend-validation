from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.blocos import blocos_de
from app.agents.turn import filtrar_tools
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
from app.tools.analista import sensibilidade
from app.tools.registry import spec_de, specs_registradas

D = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]


def _quality(points: list[MarketPoint]) -> SeriesQuality:
    return SeriesQuality(
        observations=len(points),
        first_date=points[0].data if points else None,
        last_date=points[-1].data if points else None,
        stale_days=0 if points else None,
        missing_dates=[], unexpected_dates=[], coverage_ratio=1.0 if points else None,
        calendar_source="market.trading_calendar", calendar_fallback_used=False,
    )


def _asset(code: str, iid: str, values: list[float]) -> ResolvedMarketSeries:
    points = [MarketPoint(data=d, valor=v) for d, v in zip(D, values)]
    return ResolvedMarketSeries(
        code=code, instrument_id=iid, currency="BRL", points=points, quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.v_precos_ajustados", source_codes=["b3"], ingestion_batch_ids=[f"batch-{code}"],
            calendar_ingestion_batch_ids=["cal-1"], price_basis=PriceBasis.ADJUSTED_CLOSE,
            temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW, cutoff_date=D[-1],
            warnings=[ADJUSTED_CLOSE_RETROSPECTIVE],
        ),
    )


def _index(code: str, values: list[float], unit: str) -> ResolvedMarketSeries:
    points = [MarketPoint(data=d, valor=v) for d, v in zip(D, values)]
    return ResolvedMarketSeries(
        code=code, index_code=code, unit=unit, points=points, quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.index_values", source_codes=["bacen_sgs"], ingestion_batch_ids=[f"batch-{code}"],
            calendar_ingestion_batch_ids=["cal-1"], price_basis=None,
            temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF, cutoff_date=D[-1], warnings=[],
        ),
    )


def _resolved(response, driver_series, **overrides):
    data = dict(
        ticker="AAA3", driver="selic_meta", tipo_driver="indice",
        instrument_id="iid-a", driver_instrument_id=None,
        response_in_universe=True, driver_in_universe=False, driver_found=True,
        driver_index_code="selic_meta", cutoff_date=D[-1],
        price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        serie_resposta=response, serie_driver=driver_series, unidade_driver="taxa_aa",
        medida_driver=ConditionMeasure.LEVEL_CHANGE,
        min_observacoes=3, max_dias_defasagem=5,
    )
    data.update(overrides)
    return sensibilidade.SensibilidadeResolvida(**data)


def test_params_exigem_exatamente_um_driver_e_default_adjusted():
    p = sensibilidade.SensibilidadeParams(ticker="PETR4", indice_driver="selic_meta")
    assert p.price_basis == PriceBasis.ADJUSTED_CLOSE
    with pytest.raises(ValidationError):
        sensibilidade.SensibilidadeParams(ticker="PETR4")
    with pytest.raises(ValidationError):
        sensibilidade.SensibilidadeParams(ticker="PETR4", ticker_driver="VALE3", indice_driver="ibov")


def test_tool_taxa_produz_metric_estimate_hac_e_evidencia_estatistica():
    # Driver: -0.5, +0.5, +1.0, +1.5pp. Resposta: -1%, +1%, +2%, +3% => slope 2.
    response = _asset("AAA3", "iid-a", [100, 99, 99.99, 101.9898, 105.049494])
    rate = _index("selic_meta", [14.0, 13.5, 14.0, 15.0, 16.5], "taxa_aa")
    out = sensibilidade.calcular_sensibilidade(_resolved(response, rate))
    assert out.medida_driver == ConditionMeasure.LEVEL_CHANGE
    assert out.unidade_variacao_driver == "pontos_percentuais"
    assert out.sensibilidade.estimate == pytest.approx(2.0, rel=1e-9)
    assert out.sensibilidade.unit == "pct_return_per_percentage_point"
    assert out.sensibilidade.confidence_interval is not None
    assert out.hac_lags >= 0
    assert out.evidencia.estimativas["sensibilidade"].estimate == pytest.approx(out.sensibilidade.estimate)
    assert out.evidencia.metricas["r_squared"] == pytest.approx(out.r_squared)
    assert ADJUSTED_CLOSE_RETROSPECTIVE in out.evidencia.avisos


def test_indice_em_pontos_usa_retorno_do_driver():
    response = _asset("AAA3", "iid-a", [100, 105, 99.75, 104.7375, 115.21125])
    idx = _index("ibov", [1000, 1100, 990, 1089, 1306.8], "pontos")
    out = sensibilidade.calcular_sensibilidade(_resolved(
        response, idx, driver="ibov", driver_index_code="ibov", unidade_driver="pontos",
        medida_driver=ConditionMeasure.RETURN,
    ))
    assert out.medida_driver == ConditionMeasure.RETURN
    assert out.unidade_variacao_driver == "retorno_pct"
    assert out.sensibilidade.unit == "pct_return_per_pct_driver_return"


def test_duas_observacoes_nao_fingem_inferencia_mesmo_se_min_observacoes_for_2():
    response = _asset("AAA3", "iid-a", [100, 101, 103])
    rate = _index("selic_meta", [10, 11, 13], "taxa_aa")
    out = sensibilidade.calcular_sensibilidade(_resolved(
        response, rate, min_observacoes=2,
    ))
    assert out.n == 2
    assert out.sensibilidade.estimate is not None
    assert out.sensibilidade.standard_error is None
    assert out.evidencia.suficiente is False
    assert "sem_graus_liberdade_inferencia" in out.evidencia.avisos


def test_driver_constante_nao_inventa_sensibilidade():
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    rate = _index("selic_meta", [10, 10, 10, 10, 10], "taxa_aa")
    out = sensibilidade.calcular_sensibilidade(_resolved(response, rate))
    assert out.sensibilidade.estimate is None
    assert out.evidencia.suficiente is False
    assert "driver_constante" in out.evidencia.avisos


def test_output_e_compacto_sem_pares_ou_series_longas():
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    rate = _index("selic_meta", [10, 11, 12, 13, 14], "taxa_aa")
    payload = sensibilidade.calcular_sensibilidade(_resolved(response, rate)).model_dump(mode="json")

    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield str(key).lower()
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)
    assert {"pairs", "pontos", "points", "residuals"}.isdisjoint(set(keys(payload)))


def test_tool_promovida_e_fingerprint_cobre_regressao_estimativas_e_evidencia():
    carregar_tools()
    spec = spec_de("quant.sensibilidade")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    names = {Path(path).name for path in spec.source_files}
    assert {
        "sensibilidade.py", "_comum.py", "evidencia_estatistica.py", "series.py", "models.py",
        "returns.py", "conditional.py", "estimates.py", "regression.py", "sensitivity.py",
    } <= names


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
async def test_preparar_taxa_deriva_level_change_e_basis_sem_tool_acoplada(monkeypatch):
    ctx = _FakeCtx()
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    rate = _index("selic_meta", [14, 13.5, 13, 12.5, 12], "taxa_aa")
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

    monkeypatch.setattr(sensibilidade, "data_referencia", fake_data_ref)
    monkeypatch.setattr(sensibilidade, "instrumento_por_termo", fake_inst)
    monkeypatch.setattr(sensibilidade, "carregar_serie_resolvida", fake_asset)
    monkeypatch.setattr(sensibilidade, "carregar_indice_resolvido", fake_index)

    r = await sensibilidade.preparar_sensibilidade(
        sensibilidade.SensibilidadeParams(ticker="AAA3", indice_driver="selic_meta"), ctx
    )
    assert r.medida_driver == ConditionMeasure.LEVEL_CHANGE
    assert r.temporal_semantics == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    assert calls[0][1]["basis"] == PriceBasis.ADJUSTED_CLOSE
    assert calls[0][1]["temporal_semantics"] == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW


def test_bloco_de_sensibilidade_expoe_beta_ci_e_diagnosticos_sem_causalidade():
    response = _asset("AAA3", "iid-a", [100, 99, 99.99, 101.9898, 105.049494])
    rate = _index("selic_meta", [14.0, 13.5, 14.0, 15.0, 16.5], "taxa_aa")
    out = sensibilidade.calcular_sensibilidade(_resolved(response, rate))
    blocos = blocos_de("quant.sensibilidade", out.model_dump(mode="json"), execution_id="e1")
    assert len(blocos) == 1
    texto = str(blocos[0]).lower()
    assert "sensibilidade estimada" in texto
    assert "limite inferior" in texto
    assert "r²" in texto
    assert "não implica causalidade" in texto


def test_promovida_entra_no_catalogo_do_analista():
    carregar_tools()
    visiveis = {s.code for s in filtrar_tools(specs_registradas(), familias=("quant", "dados"), plano="advanced")}
    assert "quant.sensibilidade" in visiveis
    assert "quant.risco_retorno" in visiveis
    assert "quant.dependencia" in visiveis
