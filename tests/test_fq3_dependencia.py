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
from app.tools.analista.factor_resolution import FactorRef, ResolvedFactor
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


def _fx(code: str, values: list[float]) -> ResolvedMarketSeries:
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]
    points = [MarketPoint(data=d, valor=v) for d, v in zip(dates, values)]
    return ResolvedMarketSeries(
        code=code,
        unit="pontos",
        points=points,
        quality=_quality(points),
        provenance=SeriesProvenance(
            dataset="market.fx_rates",
            source_codes=["bacen_sgs"],
            ingestion_batch_ids=[],
            calendar_ingestion_batch_ids=["cal-1"],
            price_basis=None,
            temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
            cutoff_date=date(2024, 1, 8),
            warnings=["fx_observation_date_cutoff_sem_vintage"],
        ),
    )


def _fator_ativo(code: str, iid: str | None, series: ResolvedMarketSeries | None, *, found=True, in_universe=True):
    return ResolvedFactor(
        ref=FactorRef(tipo="ativo", codigo=code),
        tipo="ativo",
        codigo=code,
        found=found,
        in_universe=in_universe,
        instrument_id=iid,
        series=series,
    )


def _fator_indice(code: str, series: ResolvedMarketSeries | None, *, found=True):
    return ResolvedFactor(
        ref=FactorRef(tipo="indice", codigo=code),
        tipo="indice",
        codigo=code,
        found=found,
        index_code=code,
        unit=series.unit if series else None,
        series=series,
    )


def _fator_fx(code: str, series: ResolvedMarketSeries | None, *, found=True):
    base, quote = code.split("/")
    return ResolvedFactor(
        ref=FactorRef(tipo="cambio", codigo=code),
        tipo="cambio",
        codigo=code,
        found=found,
        base_currency=base,
        quote_currency=quote,
        unit="pontos",
        series=series,
    )


def _resolved(fator_a: ResolvedFactor, fator_b: ResolvedFactor, **overrides):
    data = dict(
        fator_a=fator_a,
        fator_b=fator_b,
        cutoff_date=date(2024, 1, 8),
        price_basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
        metodo=DependenceMethod.PEARSON,
        defasagem_observacoes=0,
        metodo_retorno=ReturnMethod.LOG,
        dias_uteis_ano=252,
        min_observacoes=2,
        max_dias_defasagem=5,
    )
    data.update(overrides)
    return dependencia.DependenciaResolvida(**data)


def test_params_usam_factor_ref_e_defaults_canonicos():
    p = dependencia.DependenciaParams(
        ticker_a="PETR4",
        serie_b={"tipo": "ativo", "codigo": "VALE3"},
    )
    assert p.serie_b == FactorRef(tipo="ativo", codigo="VALE3")
    assert p.metodo == DependenceMethod.PEARSON
    assert p.defasagem_observacoes == 0
    assert p.price_basis == PriceBasis.ADJUSTED_CLOSE
    with pytest.raises(ValidationError):
        dependencia.DependenciaParams(ticker_a="PETR4")
    with pytest.raises(ValidationError):
        dependencia.DependenciaParams(ticker_a="PETR4", ticker_b="VALE3")


def test_schema_explica_factor_ref_lag_e_basis_sem_expor_temporal_semantics():
    schema = dependencia.DependenciaParams.model_json_schema()
    text = str(schema).lower()
    assert "serie_b" in text and "cambio" in text and "indice" in text and "ativo" in text
    assert "spearman" in text and "pearson" in text
    assert "positivo" in text and "negativo" in text
    assert "adjusted_close" in text and "raw_close" in text
    assert "ticker_b" not in schema.get("properties", {}) and "indice_b" not in schema.get("properties", {})
    assert "temporal_semantics" not in text


def test_resolvido_recusa_provenance_de_ativo_incoerente():
    a = _ativo("AAA3", "iid-a", [100, 105, 102, 108])
    b_raw = _ativo("BBB3", "iid-b", [200, 210, 204, 216], basis=PriceBasis.RAW_CLOSE)
    with pytest.raises(ValueError):
        _resolved(_fator_ativo("AAA3", "iid-a", a), _fator_ativo("BBB3", "iid-b", b_raw))


def test_calculo_ativo_ativo_adjusted_e_compacto():
    a = _ativo("AAA3", "iid-a", [100, 110, 100, 120, 132])
    b = _ativo("BBB3", "iid-b", [200, 220, 200, 240, 264])
    out = dependencia.calcular_dependencia(
        _resolved(_fator_ativo("AAA3", "iid-a", a), _fator_ativo("BBB3", "iid-b", b))
    )
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
    assert "points" not in str(dumped).lower() and "pontos" not in str(dumped).lower()


def test_calculo_ativo_indice_converte_unidade_e_preserva_index_code():
    a = _ativo("AAA3", "iid-a", [100, 101, 102, 103, 104])
    idx = _indice("cdi", [10, 11, 12, 13, 14], unit="taxa_aa")
    out = dependencia.calcular_dependencia(
        _resolved(_fator_ativo("AAA3", "iid-a", a), _fator_indice("cdi", idx))
    )
    assert out.tipo_b == "indice"
    assert out.n_pares == 4
    assert out.evidencia.index_codes == ["cdi"]
    assert out.evidencia.instrument_ids == ["iid-a"]
    assert "bacen_sgs" in out.evidencia.fonte


def test_calculo_ativo_fx_reusa_dependence_core_e_provenance():
    a = _ativo("AAA3", "iid-a", [100, 102, 101, 105, 106])
    fx = _fx("USD/BRL", [4.9, 4.95, 4.92, 5.02, 5.08])
    out = dependencia.calcular_dependencia(
        _resolved(_fator_ativo("AAA3", "iid-a", a), _fator_fx("USD/BRL", fx))
    )
    assert out.tipo_b == "cambio"
    assert out.par == "AAA3 × USD/BRL"
    assert out.n_pares == 4
    assert out.coeficiente is not None
    assert "fx_observation_date_cutoff_sem_vintage" in out.evidencia.avisos
    assert out.evidencia.index_codes == []
    assert out.evidencia.instrument_ids == ["iid-a"]


def test_spearman_e_lag_assinado_sao_expostos_sem_mudar_engine():
    a = _ativo("AAA3", "iid-a", [100, 102, 101, 105, 104])
    b = _ativo("BBB3", "iid-b", [200, 199, 204, 203, 210])
    out = dependencia.calcular_dependencia(_resolved(
        _fator_ativo("AAA3", "iid-a", a),
        _fator_ativo("BBB3", "iid-b", b),
        metodo=DependenceMethod.SPEARMAN,
        defasagem_observacoes=-1,
    ))
    assert out.metodo == DependenceMethod.SPEARMAN
    assert out.defasagem_observacoes == -1
    assert out.n_pares == 3
    assert out.evidencia.metodo.startswith("spearman_retornos_")


def test_serie_constante_nao_vira_correlacao_zero():
    a = _ativo("AAA3", "iid-a", [1, 2, 4, 8, 16])
    b = _ativo("BBB3", "iid-b", [2, 4, 8, 16, 32])
    out = dependencia.calcular_dependencia(
        _resolved(_fator_ativo("AAA3", "iid-a", a), _fator_ativo("BBB3", "iid-b", b))
    )
    assert out.coeficiente is None
    assert "serie_constante" in out.evidencia.avisos


def test_desconhecido_fora_cobertura_indice_e_fx_sao_distintos():
    a = _ativo("AAA3", "iid-a", [100, 101, 102])
    fa = _fator_ativo("AAA3", "iid-a", a)

    unknown_a = dependencia.calcular_dependencia(_resolved(
        _fator_ativo("ZZZ3", None, None, found=False, in_universe=False), fa
    ))
    assert "instrumento_desconhecido" in unknown_a.evidencia.avisos

    fora_b = dependencia.calcular_dependencia(_resolved(
        fa, _fator_ativo("BBB3", "iid-fora", None, found=True, in_universe=False)
    ))
    assert "fora_da_cobertura" in fora_b.evidencia.avisos

    idx_unknown = dependencia.calcular_dependencia(_resolved(fa, _fator_indice("cdi", None, found=False)))
    assert "indice_desconhecido" in idx_unknown.evidencia.avisos

    fx_unknown = dependencia.calcular_dependencia(_resolved(fa, _fator_fx("USD/BRL", None, found=False)))
    assert "par_cambio_desconhecido" in fx_unknown.evidencia.avisos


def test_tool_v2_exposta_e_fingerprint_cobre_resolver_e_core():
    carregar_tools()
    spec = spec_de("quant.dependencia")
    assert spec.semver == "2.0.0"
    assert spec.exposed_to_llm is True
    names = {Path(path).name for path in spec.source_files}
    assert {
        "dependencia.py", "factor_resolution.py", "_comum.py", "series.py", "factors.py",
        "models.py", "returns.py", "dependence.py",
    } <= names


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
async def test_preparar_usa_resolver_compartilhado_para_a_e_b(monkeypatch):
    ctx = _FakeCtx()
    a = _ativo("AAA3", "iid-a", [100, 101, 102])
    b = _ativo("BBB3", "iid-b", [200, 202, 204])
    fa = _fator_ativo("AAA3", "iid-a", a)
    fb = _fator_ativo("BBB3", "iid-b", b)
    calls = []

    async def fake_data_ref(conn): return date(2024, 1, 8)
    async def fake_resolve(conn, ref, **kwargs):
        calls.append((ref, kwargs))
        return fa if len(calls) == 1 else fb

    monkeypatch.setattr(dependencia, "data_referencia", fake_data_ref)
    monkeypatch.setattr(dependencia, "resolve_factor", fake_resolve)

    r = await dependencia.preparar_dependencia(
        dependencia.DependenciaParams(ticker_a="AAA3", serie_b={"tipo": "ativo", "codigo": "BBB3"}),
        ctx,
    )
    assert r.fator_a == fa and r.fator_b == fb
    assert len(calls) == 2
    assert calls[0][0] == FactorRef(tipo="ativo", codigo="AAA3")
    assert calls[1][0] == FactorRef(tipo="ativo", codigo="BBB3")
    for _, kw in calls:
        assert kw["asset_price_basis"] == PriceBasis.ADJUSTED_CLOSE
        assert kw["asset_temporal_semantics"] == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
        assert kw["include_calendar"] is True


@pytest.mark.asyncio
async def test_preparar_preserva_factor_ref_indice_normalizado(monkeypatch):
    ctx = _FakeCtx()
    a = _ativo("AAA3", "iid-a", [100, 101, 102])
    idx = _indice("cdi", [10, 11, 12])
    fa = _fator_ativo("AAA3", "iid-a", a)
    fi = _fator_indice("cdi", idx)
    refs = []

    async def fake_data_ref(conn): return date(2024, 1, 8)
    async def fake_resolve(conn, ref, **kwargs):
        refs.append(ref)
        return fa if len(refs) == 1 else fi

    monkeypatch.setattr(dependencia, "data_referencia", fake_data_ref)
    monkeypatch.setattr(dependencia, "resolve_factor", fake_resolve)
    r = await dependencia.preparar_dependencia(
        dependencia.DependenciaParams(ticker_a="AAA3", serie_b={"tipo": "indice", "codigo": "CDI"}),
        ctx,
    )
    assert r.fator_b.tipo == "indice" and r.fator_b.series is idx
    assert refs[1] == FactorRef(tipo="indice", codigo="cdi")


def test_cutover_expoe_dependencia_e_oculta_correlacao_e_macro():
    from app.agents.turn import filtrar_tools
    from app.tools.registry import specs_registradas

    carregar_tools()
    codes = {s.code for s in filtrar_tools(specs_registradas(), familias=("dados", "quant"), plano="wealth")}
    assert "quant.dependencia" in codes
    assert "quant.correlacao" not in codes
    assert "quant.dependencia_macro" not in codes
