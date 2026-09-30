from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.market.analytics.models import DependenceMethod, ReturnMethod
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
from app.tools.analista import dependencia
from app.tools.registry import spec_de


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


def _ativo(code: str, iid: str, values: list[float], *, basis=PriceBasis.ADJUSTED_CLOSE) -> ResolvedMarketSeries:
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]
    points = [MarketPoint(data=d, valor=v) for d, v in zip(dates, values)]
    semantics = (TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
                 if basis == PriceBasis.ADJUSTED_CLOSE else TemporalSemantics.OBSERVATION_DATE_CUTOFF)
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
            cutoff_date=date(2024, 1, 8),
            warnings=[ADJUSTED_CLOSE_RETROSPECTIVE] if basis == PriceBasis.ADJUSTED_CLOSE else [],
        ),
    )


def _indice(code: str, values: list[float], unit: str = "taxa_aa") -> ResolvedMarketSeries:
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]
    points = [MarketPoint(data=d, valor=v) for d, v in zip(dates, values)]
    return ResolvedMarketSeries(
        code=code,
        index_code=code,
        unit=unit,
        points=points,
        quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.index_values",
            source_codes=["bacen_sgs"],
            ingestion_batch_ids=["batch-index"],
            calendar_ingestion_batch_ids=["cal-1"],
            price_basis=None,
            temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
            cutoff_date=date(2024, 1, 8),
            warnings=[],
        ),
    )


def _resolved(a: ResolvedMarketSeries | None, b: ResolvedMarketSeries | None, **overrides):
    data = dict(
        ticker_a="AAA3",
        codigo_b="BBB3",
        tipo_b="ativo",
        instrument_a_id="iid-a",
        instrument_b_id="iid-b",
        a_in_universe=True,
        b_in_universe=True,
        index_code_b=None,
        cutoff_date=date(2024, 1, 8),
        price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        serie_a=a,
        serie_b=b,
        unidade_b="pontos",
        metodo=DependenceMethod.PEARSON,
        defasagem_observacoes=0,
        metodo_retorno=ReturnMethod.LOG,
        dias_uteis_ano=252,
        min_observacoes=2,
        max_dias_defasagem=5,
    )
    data.update(overrides)
    return dependencia.DependenciaResolvida(**data)


def test_params_exigem_exatamente_um_segundo_e_defaults_sao_canonicos():
    p = dependencia.DependenciaParams(ticker_a="PETR4", ticker_b="VALE3")
    assert p.metodo == DependenceMethod.PEARSON
    assert p.defasagem_observacoes == 0
    assert p.price_basis == PriceBasis.ADJUSTED_CLOSE
    with pytest.raises(ValidationError):
        dependencia.DependenciaParams(ticker_a="PETR4")
    with pytest.raises(ValidationError):
        dependencia.DependenciaParams(ticker_a="PETR4", ticker_b="VALE3", indice_b="cdi")


def test_schema_explica_lag_assinado_e_basis_sem_expor_temporal_semantics():
    text = str(dependencia.DependenciaParams.model_json_schema()).lower()
    assert "spearman" in text
    assert "pearson" in text
    assert "positivo" in text and "negativo" in text
    assert "adjusted_close" in text and "raw_close" in text
    assert "temporal_semantics" not in text


def test_resolvido_recusa_provenance_de_ativo_incoerente():
    a = _ativo("AAA3", "iid-a", [100, 105, 102, 108])
    b_raw = _ativo("BBB3", "iid-b", [200, 210, 204, 216], basis=PriceBasis.RAW_CLOSE)
    with pytest.raises(ValueError):
        _resolved(a, b_raw)


def test_calculo_ativo_ativo_adjusted_e_compacto():
    a = _ativo("AAA3", "iid-a", [100, 110, 100, 120, 132])
    b = _ativo("BBB3", "iid-b", [200, 220, 200, 240, 264])
    out = dependencia.calcular_dependencia(_resolved(a, b))
    assert out.par == "AAA3 × BBB3"
    assert out.metodo == DependenceMethod.PEARSON
    assert out.coeficiente == pytest.approx(1.0)
    assert out.n_pares == 4
    assert out.defasagem_observacoes == 0
    assert out.price_basis_ativos == PriceBasis.ADJUSTED_CLOSE
    assert out.temporal_semantics_ativos == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    assert out.tipo_b == "ativo"
    assert ADJUSTED_CLOSE_RETROSPECTIVE in out.evidencia.avisos
    dumped = out.model_dump(mode="json")
    assert "points" not in str(dumped).lower()
    assert "pontos" not in str(dumped).lower()


def test_calculo_ativo_indice_converte_unidade_e_preserva_index_code():
    a = _ativo("AAA3", "iid-a", [100, 101, 102, 103, 104])
    idx = _indice("cdi", [10, 11, 12, 13, 14], unit="taxa_aa")
    r = _resolved(
        a, idx,
        codigo_b="cdi",
        tipo_b="indice",
        instrument_b_id=None,
        b_in_universe=False,
        index_code_b="cdi",
        unidade_b="taxa_aa",
    )
    out = dependencia.calcular_dependencia(r)
    assert out.tipo_b == "indice"
    assert out.n_pares == 4
    assert out.evidencia.index_codes == ["cdi"]
    assert out.evidencia.instrument_ids == ["iid-a"]
    assert "bacen_sgs" in out.evidencia.fonte


def test_spearman_e_lag_assinado_sao_expostos_sem_mudar_engine():
    a = _ativo("AAA3", "iid-a", [100, 102, 101, 105, 104])
    b = _ativo("BBB3", "iid-b", [200, 199, 204, 203, 210])
    out = dependencia.calcular_dependencia(_resolved(
        a, b, metodo=DependenceMethod.SPEARMAN, defasagem_observacoes=-1
    ))
    assert out.metodo == DependenceMethod.SPEARMAN
    assert out.defasagem_observacoes == -1
    assert out.n_pares == 3
    assert out.evidencia.metodo.startswith("spearman_retornos_")


def test_serie_constante_nao_vira_correlacao_zero():
    a = _ativo("AAA3", "iid-a", [1, 2, 4, 8, 16])
    b = _ativo("BBB3", "iid-b", [2, 4, 8, 16, 32])
    # Retornos log constantes em ambas: correlação é indefinida.
    out = dependencia.calcular_dependencia(_resolved(a, b))
    assert out.coeficiente is None
    assert "serie_constante" in out.evidencia.avisos


def test_desconhecido_fora_cobertura_e_indice_desconhecido_sao_distintos():
    a = _ativo("AAA3", "iid-a", [100, 101, 102])
    unknown_a = dependencia.calcular_dependencia(_resolved(
        None, a, instrument_a_id=None, a_in_universe=False,
        instrument_b_id="iid-a", codigo_b="AAA3",
    ))
    assert "instrumento_desconhecido" in unknown_a.evidencia.avisos

    fora_b = dependencia.calcular_dependencia(_resolved(
        a, None, instrument_b_id="iid-fora", b_in_universe=False,
    ))
    assert "fora_da_cobertura" in fora_b.evidencia.avisos

    idx_unknown = dependencia.calcular_dependencia(_resolved(
        a, None, tipo_b="indice", instrument_b_id=None, b_in_universe=False,
        index_code_b="cdi", codigo_b="cdi", b_found=False,
    ))
    assert "indice_desconhecido" in idx_unknown.evidencia.avisos


def test_tool_nasce_shadow_e_fingerprint_cobre_core():
    carregar_tools()
    spec = spec_de("quant.dependencia")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    names = {Path(path).name for path in spec.source_files}
    assert {"dependencia.py", "_comum.py", "series.py", "models.py", "returns.py", "dependence.py"} <= names


class _FakeCtx:
    def __init__(self):
        self.conn = object()
        self.cutoff_date = date(2024, 1, 8)
        self.insumos = []

    async def policy(self, code):
        assert code == "ANALISE_PARAMS"
        return {
            "janela_padrao_dias": 365,
            "min_observacoes": 2,
            "max_dias_defasagem": 5,
            "dias_uteis_ano": 252,
            "metodo_retorno": "log",
        }

    def registrar_insumo(self, kind, **payload):
        self.insumos.append((kind, payload))


@pytest.mark.asyncio
async def test_preparar_ativo_ativo_aplica_mesma_basis_e_semantica(monkeypatch):
    ctx = _FakeCtx()
    a = _ativo("AAA3", "iid-a", [100, 101, 102])
    b = _ativo("BBB3", "iid-b", [200, 202, 204])
    calls = []

    async def fake_data_ref(conn): return date(2024, 1, 8)
    async def fake_inst(conn, termo, *, cutoff):
        return {"instrument_id": f"iid-{termo[0].lower()}", "ticker": termo, "is_in_universe": True}
    async def fake_load(conn, instrument_id, **kwargs):
        calls.append((instrument_id, kwargs))
        return a if kwargs["codigo"] == "AAA3" else b

    monkeypatch.setattr(dependencia, "data_referencia", fake_data_ref)
    monkeypatch.setattr(dependencia, "instrumento_por_termo", fake_inst)
    monkeypatch.setattr(dependencia, "carregar_serie_resolvida", fake_load)

    r = await dependencia.preparar_dependencia(
        dependencia.DependenciaParams(ticker_a="AAA3", ticker_b="BBB3"), ctx
    )
    assert r.serie_a is a and r.serie_b is b
    assert len(calls) == 2
    for _, kw in calls:
        assert kw["basis"] == PriceBasis.ADJUSTED_CLOSE
        assert kw["temporal_semantics"] == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
        assert kw["include_calendar"] is True


@pytest.mark.asyncio
async def test_preparar_ativo_indice_nao_aplica_price_basis_ao_indice(monkeypatch):
    ctx = _FakeCtx()
    a = _ativo("AAA3", "iid-a", [100, 101, 102])
    idx = _indice("cdi", [10, 11, 12])
    asset_calls = []
    index_calls = []

    async def fake_data_ref(conn): return date(2024, 1, 8)
    async def fake_inst(conn, termo, *, cutoff):
        return {"instrument_id": "iid-a", "ticker": "AAA3", "is_in_universe": True}
    async def fake_asset(conn, instrument_id, **kwargs):
        asset_calls.append(kwargs); return a
    async def fake_index(conn, code, **kwargs):
        index_calls.append((code, kwargs)); return idx

    monkeypatch.setattr(dependencia, "data_referencia", fake_data_ref)
    monkeypatch.setattr(dependencia, "instrumento_por_termo", fake_inst)
    monkeypatch.setattr(dependencia, "carregar_serie_resolvida", fake_asset)
    monkeypatch.setattr(dependencia, "carregar_indice_resolvido", fake_index)

    r = await dependencia.preparar_dependencia(
        dependencia.DependenciaParams(ticker_a="AAA3", indice_b="cdi"), ctx
    )
    assert r.tipo_b == "indice" and r.serie_b is idx
    assert asset_calls[0]["basis"] == PriceBasis.ADJUSTED_CLOSE
    assert index_calls[0][1]["include_calendar"] is True
    assert "basis" not in index_calls[0][1]


def test_cutover_expoe_dependencia_e_oculta_correlacao():
    from app.agents.turn import filtrar_tools
    from app.tools.registry import specs_registradas

    carregar_tools()
    codes = {s.code for s in filtrar_tools(specs_registradas(), familias=("dados", "quant"), plano="wealth")}
    assert "quant.dependencia" in codes
    assert "quant.correlacao" not in codes
