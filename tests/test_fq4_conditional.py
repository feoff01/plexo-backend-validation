from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.market.analytics import conditional
from app.market.analytics.models import ConditionDirection, ConditionMeasure
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
from app.tools.analista import analise_condicional
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


def test_condition_changes_return_preserva_intervalos():
    obs = conditional.condition_changes(
        _points([100, 110, 99]), measure=ConditionMeasure.RETURN
    )
    assert [(o.start_date, o.end_date) for o in obs] == [(D[0], D[1]), (D[1], D[2])]
    assert obs[0].value == pytest.approx(0.10)
    assert obs[1].value == pytest.approx(-0.10)


def test_condition_changes_level_change_aceita_taxa_negativa_e_neutra():
    obs = conditional.condition_changes(
        _points([1.0, 0.5, 0.5, -0.25]), measure=ConditionMeasure.LEVEL_CHANGE
    )
    assert [o.value for o in obs] == pytest.approx([-0.5, 0.0, -0.75])


def test_align_response_intervals_usa_ultimo_preco_em_ou_antes_sem_lookahead():
    response = _points(
        [100, 110, 121],
        dates=[date(2024, 1, 2), date(2024, 1, 4), date(2024, 1, 8)],
    )
    changes = conditional.condition_changes(
        _points(
            [10, 9],
            dates=[date(2024, 1, 3), date(2024, 1, 7)],
        ),
        measure=ConditionMeasure.LEVEL_CHANGE,
    )
    pairs = conditional.align_response_intervals(response, changes)
    assert len(pairs) == 1
    p = pairs[0]
    assert p.condition_start_date == date(2024, 1, 3)
    assert p.condition_end_date == date(2024, 1, 7)
    assert p.response_start_date == date(2024, 1, 2)
    assert p.response_end_date == date(2024, 1, 4)
    assert p.response_return == pytest.approx(0.10)


def test_align_response_intervals_nao_inventa_retorno_se_endpoints_caem_no_mesmo_preco():
    response = _points([100, 101], dates=[date(2024, 1, 5), date(2024, 1, 8)])
    changes = conditional.condition_changes(
        _points([10, 9], dates=[date(2024, 1, 6), date(2024, 1, 7)]),
        measure=ConditionMeasure.LEVEL_CHANGE,
    )
    assert conditional.align_response_intervals(response, changes) == []


def test_conditional_analysis_separa_alta_queda_neutro_e_baseline():
    pairs = [
        conditional.ConditionalResponsePair(
            condition_start_date=date(2024, 1, 2), condition_end_date=date(2024, 1, 3),
            response_start_date=date(2024, 1, 2), response_end_date=date(2024, 1, 3),
            condition_change=-1.0, response_return=0.10,
        ),
        conditional.ConditionalResponsePair(
            condition_start_date=date(2024, 1, 3), condition_end_date=date(2024, 1, 4),
            response_start_date=date(2024, 1, 3), response_end_date=date(2024, 1, 4),
            condition_change=0.0, response_return=-0.05,
        ),
        conditional.ConditionalResponsePair(
            condition_start_date=date(2024, 1, 4), condition_end_date=date(2024, 1, 5),
            response_start_date=date(2024, 1, 4), response_end_date=date(2024, 1, 5),
            condition_change=2.0, response_return=0.02,
        ),
    ]
    down = conditional.analyze_conditional_returns(pairs, direction=ConditionDirection.DOWN)
    assert down.n_total == 3
    assert down.n_selected == 1
    assert down.n_neutral == 1
    assert down.selected.mean == pytest.approx(0.10)
    assert down.selected.positive_fraction == pytest.approx(1.0)
    assert down.baseline.mean == pytest.approx((0.10 - 0.05 + 0.02) / 3)
    assert down.mean_difference == pytest.approx(0.10 - down.baseline.mean)


def test_conditional_analysis_sem_evento_nao_inventa_zero():
    pair = conditional.ConditionalResponsePair(
        condition_start_date=D[0], condition_end_date=D[1],
        response_start_date=D[0], response_end_date=D[1],
        condition_change=1.0, response_return=0.03,
    )
    out = conditional.analyze_conditional_returns([pair], direction=ConditionDirection.DOWN)
    assert out.n_selected == 0
    assert out.selected.mean is None
    assert out.selected.positive_fraction is None
    assert out.mean_difference is None


def test_params_exigem_uma_condicionante_e_defaults_sao_conservadores():
    p = analise_condicional.AnaliseCondicionalParams(ticker="PETR4", indice_condicao="selic_meta", direcao="queda")
    assert p.price_basis == PriceBasis.ADJUSTED_CLOSE
    with pytest.raises(ValidationError):
        analise_condicional.AnaliseCondicionalParams(ticker="PETR4", direcao="queda")
    with pytest.raises(ValidationError):
        analise_condicional.AnaliseCondicionalParams(
            ticker="PETR4", ticker_condicao="VALE3", indice_condicao="selic_meta", direcao="queda"
        )


def _resolved(response: ResolvedMarketSeries | None, condition: ResolvedMarketSeries | None, **overrides):
    data = dict(
        ticker="AAA3",
        condicionante="selic_meta",
        tipo_condicionante="indice",
        instrument_id="iid-a",
        condition_instrument_id=None,
        response_in_universe=True,
        condition_in_universe=False,
        condition_found=True,
        condition_index_code="selic_meta",
        cutoff_date=D[-1],
        price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        serie_resposta=response,
        serie_condicao=condition,
        unidade_condicao="taxa_aa",
        medida_condicao=ConditionMeasure.LEVEL_CHANGE,
        direcao=ConditionDirection.DOWN,
        min_observacoes=2,
        max_dias_defasagem=5,
    )
    data.update(overrides)
    return analise_condicional.AnaliseCondicionalResolvida(**data)


def test_tool_taxa_usa_variacao_de_nivel_e_retorno_do_mesmo_intervalo():
    response = _asset("AAA3", "iid-a", [100, 110, 99, 108.9, 119.79])
    rate = _index("selic_meta", [14.0, 13.5, 13.5, 13.0, 13.5], unit="taxa_aa")
    out = analise_condicional.calcular_analise_condicional(_resolved(response, rate))

    # Quedas da taxa em 03/01 e 05/01. Retornos do ativo nos mesmos intervalos: +10% e +10%.
    assert out.medida_condicao == ConditionMeasure.LEVEL_CHANGE
    assert out.unidade_variacao_condicao == "pontos_percentuais"
    assert out.n_total == 4
    assert out.n_condicional == 2
    assert out.condicional.media_pct == pytest.approx(10.0)
    assert out.condicional.mediana_pct == pytest.approx(10.0)
    assert out.condicional.taxa_positiva_pct == pytest.approx(100.0)
    assert out.variacao_condicao_media == pytest.approx(-0.5)
    assert out.evidencia.index_codes == ["selic_meta"]
    assert ADJUSTED_CLOSE_RETROSPECTIVE in out.evidencia.avisos
    dumped = out.model_dump(mode="json")
    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield str(key).lower()
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)
    assert {"pairs", "pontos", "points"}.isdisjoint(set(keys(dumped)))


def test_tool_indice_em_pontos_condiciona_por_retorno():
    response = _asset("AAA3", "iid-a", [100, 102, 104, 106, 108])
    idx = _index("ibov", [1000, 1100, 990, 1089, 980.1], unit="pontos")
    out = analise_condicional.calcular_analise_condicional(_resolved(
        response, idx,
        condicionante="ibov", condition_index_code="ibov", unidade_condicao="pontos",
        medida_condicao=ConditionMeasure.RETURN,
    ))
    assert out.medida_condicao == ConditionMeasure.RETURN
    assert out.unidade_variacao_condicao == "retorno_pct"
    assert out.n_condicional == 2
    assert out.variacao_condicao_media == pytest.approx(-10.0)


def test_amostra_curta_mantem_metricas_mas_marca_insuficiente():
    response = _asset("AAA3", "iid-a", [100, 110, 99, 108.9, 119.79])
    rate = _index("selic_meta", [14.0, 13.5, 13.5, 13.0, 13.5], unit="taxa_aa")
    out = analise_condicional.calcular_analise_condicional(_resolved(
        response, rate, min_observacoes=5
    ))
    assert out.n_condicional == 2
    assert out.condicional.media_pct == pytest.approx(10.0)
    assert out.evidencia.suficiente is False
    assert "serie_curta" in out.evidencia.avisos


def test_sem_eventos_condicao_tem_warning_especifico():
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    rate = _index("selic_meta", [10, 11, 12, 13, 14], unit="taxa_aa")
    out = analise_condicional.calcular_analise_condicional(_resolved(response, rate))
    assert out.n_condicional == 0
    assert out.condicional.media_pct is None
    assert "sem_eventos_condicao" in out.evidencia.avisos


def test_tool_promovida_e_fingerprint_cobre_engine():
    carregar_tools()
    spec = spec_de("quant.analise_condicional")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    names = {Path(path).name for path in spec.source_files}
    assert {"analise_condicional.py", "_comum.py", "series.py", "models.py", "returns.py", "statistics.py", "conditional.py"} <= names


class _FakeCtx:
    def __init__(self):
        self.conn = object()
        self.cutoff_date = D[-1]
        self.insumos = []

    async def policy(self, code: str):
        assert code == "ANALISE_PARAMS"
        return {
            "janela_padrao_dias": 365,
            "min_observacoes": 2,
            "max_dias_defasagem": 5,
        }

    def registrar_insumo(self, kind: str, **payload):
        self.insumos.append((kind, payload))


@pytest.mark.asyncio
async def test_preparar_deriva_measure_e_semantica_sem_tool_acoplada(monkeypatch):
    ctx = _FakeCtx()
    response = _asset("AAA3", "iid-a", [100, 101, 102, 103, 104])
    rate = _index("selic_meta", [14, 14, 13.75, 13.75, 13.5], unit="taxa_aa")
    calls = []

    async def fake_data_ref(conn):
        return D[-1]

    async def fake_inst(conn, termo, *, cutoff):
        return {"instrument_id": "iid-a", "ticker": "AAA3", "is_in_universe": True}

    async def fake_load_asset(conn, instrument_id, **kwargs):
        calls.append(("asset", kwargs))
        return response

    async def fake_load_index(conn, code, **kwargs):
        calls.append(("index", {"code": code, **kwargs}))
        return rate

    monkeypatch.setattr(analise_condicional, "data_referencia", fake_data_ref)
    monkeypatch.setattr(analise_condicional, "instrumento_por_termo", fake_inst)
    monkeypatch.setattr(analise_condicional, "carregar_serie_resolvida", fake_load_asset)
    monkeypatch.setattr(analise_condicional, "carregar_indice_resolvido", fake_load_index)

    r = await analise_condicional.preparar_analise_condicional(
        analise_condicional.AnaliseCondicionalParams(
            ticker="AAA3", indice_condicao="selic_meta", direcao="queda"
        ),
        ctx,
    )
    assert r.medida_condicao == ConditionMeasure.LEVEL_CHANGE
    assert r.temporal_semantics == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    asset_call = next(payload for kind, payload in calls if kind == "asset")
    assert asset_call["basis"] == PriceBasis.ADJUSTED_CLOSE
    assert asset_call["temporal_semantics"] == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW


def test_property_up_down_neutro_particionam_amostra_e_alinhamento_nunca_usa_futuro():
    import random

    rng = random.Random(20260921)
    for _ in range(400):
        n = rng.randint(3, 25)
        dates = [date(2024, 1, 1).fromordinal(date(2024, 1, 1).toordinal() + i) for i in range(n)]
        response_values = [100.0]
        condition_values = [10.0]
        for _i in range(1, n):
            response_values.append(response_values[-1] * (1 + rng.uniform(-0.08, 0.08)))
            condition_values.append(condition_values[-1] + rng.choice([-1.0, 0.0, 1.0]) * rng.random())
        response = _points(response_values, dates=dates)
        changes = conditional.condition_changes(
            _points(condition_values, dates=dates), measure=ConditionMeasure.LEVEL_CHANGE
        )
        pairs = conditional.align_response_intervals(response, changes)
        up = conditional.analyze_conditional_returns(pairs, direction=ConditionDirection.UP)
        down = conditional.analyze_conditional_returns(pairs, direction=ConditionDirection.DOWN)
        assert up.n_total == down.n_total == len(pairs)
        assert up.n_selected + down.n_selected + up.n_neutral == len(pairs)
        assert up.n_neutral == down.n_neutral
        for pair in pairs:
            assert pair.response_start_date <= pair.condition_start_date
            assert pair.response_end_date <= pair.condition_end_date
            assert pair.response_end_date > pair.response_start_date


def test_property_retorno_condicional_e_invariante_a_escala_do_preco_resposta():
    response = _points([100, 110, 99, 120, 108])
    scaled = _points([1000, 1100, 990, 1200, 1080])
    changes = conditional.condition_changes(
        _points([5, 4, 4.5, 4, 3.5]), measure=ConditionMeasure.LEVEL_CHANGE
    )
    a = conditional.analyze_conditional_returns(
        conditional.align_response_intervals(response, changes), direction=ConditionDirection.DOWN
    )
    b = conditional.analyze_conditional_returns(
        conditional.align_response_intervals(scaled, changes), direction=ConditionDirection.DOWN
    )
    assert a == b


def test_bloco_condicional_mostra_amostra_curta_com_warning_em_vez_de_apagar_metricas():
    from app.agents.blocos import blocos_de

    response = _asset("AAA3", "iid-a", [100, 110, 99, 108.9, 119.79])
    rate = _index("selic_meta", [14.0, 13.5, 13.5, 13.0, 13.5], unit="taxa_aa")
    out = analise_condicional.calcular_analise_condicional(_resolved(response, rate, min_observacoes=5))
    blocks = blocos_de("quant.analise_condicional", out.model_dump(mode="json"), execution_id="e1")
    assert len(blocks) == 1
    assert blocks[0]["tipo"] == "indicadores"
    assert "2 de 4" in blocks[0]["subtitulo"]
    assert any("poucos pontos" in warning for warning in blocks[0]["proveniencia"]["avisos"])


def test_promovida_entra_no_catalogo_do_analista():
    from app.agents.turn import filtrar_tools
    from app.tools.registry import specs_registradas

    carregar_tools()
    codes = {s.code for s in filtrar_tools(specs_registradas(), familias=("dados", "quant"), plano="wealth")}
    assert "quant.analise_condicional" in codes
    assert "quant.risco_retorno" in codes and "quant.dependencia" in codes


def test_endpoint_asof_defasado_demais_e_descartado():
    response = _points([100, 110], dates=[date(2024, 1, 2), date(2024, 1, 10)])
    changes = conditional.condition_changes(
        _points([10, 9], dates=[date(2024, 1, 7), date(2024, 1, 10)]),
        measure=ConditionMeasure.LEVEL_CHANGE,
    )
    assert conditional.align_response_intervals(
        response, changes, max_endpoint_gap_days=2
    ) == []
    assert len(conditional.align_response_intervals(
        response, changes, max_endpoint_gap_days=5
    )) == 1


def test_engine_recusa_intervalos_condicionantes_sobrepostos():
    response = _points([100, 101, 102, 103, 104])
    overlapping = [
        conditional.ConditionChangeObservation(start_date=D[0], end_date=D[2], value=1.0),
        conditional.ConditionChangeObservation(start_date=D[1], end_date=D[3], value=-1.0),
    ]
    with pytest.raises(ValueError, match="sobreposição"):
        conditional.align_response_intervals(response, overlapping)
