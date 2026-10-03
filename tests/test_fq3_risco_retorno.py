from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.market.analytics.models import ReturnMethod
from app.market.series import (
    ADJUSTED_CLOSE_RETROSPECTIVE,
    CALENDAR_FALLBACK_FROM_PRICES,
    MarketPoint,
    PriceBasis,
    ResolvedMarketSeries,
    SeriesProvenance,
    SeriesQuality,
    TemporalSemantics,
)
from app.tools import carregar_tools
from app.tools.analista import risco_retorno, serie_precos
from app.tools.registry import spec_de


def _serie(
    valores: list[float],
    *,
    basis: PriceBasis = PriceBasis.ADJUSTED_CLOSE,
    semantics: TemporalSemantics = TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
    warnings: list[str] | None = None,
) -> ResolvedMarketSeries:
    datas = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)][: len(valores)]
    pontos = [MarketPoint(data=d, valor=v) for d, v in zip(datas, valores)]
    return ResolvedMarketSeries(
        code="TEST3",
        instrument_id="iid-3",
        currency="BRL",
        points=pontos,
        quality=SeriesQuality(
            observations=len(pontos),
            first_date=pontos[0].data if pontos else None,
            last_date=pontos[-1].data if pontos else None,
            stale_days=0 if pontos else None,
            missing_dates=[],
            unexpected_dates=[],
            coverage_ratio=1.0 if pontos else None,
            calendar_source="market.trading_calendar",
            calendar_fallback_used=False,
        ),
        provenance=SeriesProvenance(
            dataset="market.v_precos_ajustados" if basis == PriceBasis.ADJUSTED_CLOSE else "market.prices",
            source_codes=["b3"],
            ingestion_batch_ids=["batch-3"],
            calendar_ingestion_batch_ids=["cal-3"],
            price_basis=basis,
            temporal_semantics=semantics,
            cutoff_date=date(2024, 1, 5),
            warnings=list(warnings or []),
        ),
    )


def _resolvido(
    serie: ResolvedMarketSeries | None,
    *,
    basis: PriceBasis = PriceBasis.ADJUSTED_CLOSE,
    in_universe: bool = True,
    instrument_id: str | None = "iid-3",
    min_observacoes: int = 2,
):
    return risco_retorno.RiscoRetornoResolvido(
        ticker="TEST3",
        instrument_id=instrument_id,
        in_universe=in_universe,
        cutoff_date=date(2024, 1, 5),
        price_basis=basis,
        temporal_semantics=risco_retorno.temporal_semantics_for_basis(basis),
        serie=serie,
        metodo_retorno=ReturnMethod.LOG,
        dias_uteis_ano=252,
        min_observacoes=min_observacoes,
        max_dias_defasagem=5,
    )


def test_serie_precos_nao_promete_point_in_time_no_schema_ou_descricao():
    carregar_tools()
    spec = spec_de("dados.serie_precos")
    texto = (spec.description + " " + str(spec.params_model.model_json_schema())).lower()
    assert "point-in-time" not in texto
    assert "vintage" in texto
    assert spec.semver == "1.0.2"


def test_basis_deriva_semantica_temporal_sem_combinacao_invalida():
    assert risco_retorno.temporal_semantics_for_basis(PriceBasis.ADJUSTED_CLOSE) == (
        TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    )
    assert risco_retorno.temporal_semantics_for_basis(PriceBasis.RAW_CLOSE) == (
        TemporalSemantics.OBSERVATION_DATE_CUTOFF
    )


def test_params_default_para_adjusted_close_e_schema_explica_semantica():
    params = risco_retorno.RiscoRetornoParams(ticker="PETR4")
    assert params.price_basis == PriceBasis.ADJUSTED_CLOSE
    schema = risco_retorno.RiscoRetornoParams.model_json_schema()
    texto = str(schema).lower()
    assert "adjusted_close" in texto
    assert "raw_close" in texto
    assert "retrospect" in texto
    assert "vintage" in texto


def test_resolvido_recusa_basis_ou_semantica_divergente_da_serie():
    ajustada = _serie([100, 90, 95, 101])
    with pytest.raises(ValueError):
        risco_retorno.RiscoRetornoResolvido(
            ticker="TEST3",
            instrument_id="iid-3",
            in_universe=True,
            cutoff_date=date(2024, 1, 5),
            price_basis=PriceBasis.RAW_CLOSE,
            temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
            serie=ajustada,
            metodo_retorno=ReturnMethod.LOG,
            dias_uteis_ano=252,
            min_observacoes=2,
            max_dias_defasagem=5,
        )


def test_calculo_canonico_adjusted_e_compacto_com_drawdown_detalhado():
    serie = _serie(
        [100, 90, 95, 101],
        warnings=[ADJUSTED_CLOSE_RETROSPECTIVE, CALENDAR_FALLBACK_FROM_PRICES],
    )
    out = risco_retorno.calcular_risco_retorno(_resolvido(serie))

    assert out.ticker == "TEST3"
    assert out.price_basis == PriceBasis.ADJUSTED_CLOSE
    assert out.temporal_semantics == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    assert out.periodo.n == 4
    assert out.retorno_acumulado_pct == pytest.approx(1.0)
    assert out.max_drawdown_pct == pytest.approx(-10.0)
    assert out.downside_target_periodic_pct == 0.0
    assert out.downside_deviation_anualizada_pct is not None
    assert out.downside_deviation_anualizada_pct > 0.0
    assert out.evidencia.metricas["downside_deviation_anualizada_pct"] == pytest.approx(
        out.downside_deviation_anualizada_pct
    )
    assert out.drawdown is not None
    assert out.drawdown.peak_date == date(2024, 1, 2)
    assert out.drawdown.trough_date == date(2024, 1, 3)
    assert out.drawdown.recovery_date == date(2024, 1, 5)
    assert out.drawdown.depth_pct == pytest.approx(-10.0)
    assert out.drawdown.time_to_trough_intervals == 1
    assert out.drawdown.recovery_intervals == 2
    assert out.drawdown.duration_intervals == 3
    assert out.drawdown.recovered is True
    assert ADJUSTED_CLOSE_RETROSPECTIVE in out.evidencia.avisos
    assert CALENDAR_FALLBACK_FROM_PRICES in out.evidencia.avisos
    assert "pontos" not in out.model_dump(mode="json")


def test_downside_deviation_zero_em_caminho_sem_retorno_negativo():
    serie = _serie([100, 101, 102, 103])
    out = risco_retorno.calcular_risco_retorno(_resolvido(serie))
    assert out.downside_target_periodic_pct == 0.0
    assert out.downside_deviation_anualizada_pct == pytest.approx(0.0)
    assert out.evidencia.metricas["downside_deviation_anualizada_pct"] == pytest.approx(0.0)


def test_raw_close_fica_rotulado_com_observation_date_cutoff():
    serie = _serie(
        [100, 101, 99, 102],
        basis=PriceBasis.RAW_CLOSE,
        semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
    )
    out = risco_retorno.calcular_risco_retorno(
        _resolvido(serie, basis=PriceBasis.RAW_CLOSE)
    )
    assert out.price_basis == PriceBasis.RAW_CLOSE
    assert out.temporal_semantics == TemporalSemantics.OBSERVATION_DATE_CUTOFF
    assert ADJUSTED_CLOSE_RETROSPECTIVE not in out.evidencia.avisos
    assert "vintage" in out.evidencia.nota_metodo.lower()


def test_serie_insuficiente_nao_inventa_metricas():
    serie = _serie([100], warnings=[ADJUSTED_CLOSE_RETROSPECTIVE])
    out = risco_retorno.calcular_risco_retorno(_resolvido(serie, min_observacoes=2))
    assert out.evidencia.suficiente is False
    assert "serie_curta" in out.evidencia.avisos
    assert out.retorno_acumulado_pct is None
    assert out.retorno_anualizado_pct is None
    assert out.vol_anualizada_pct is None
    assert out.downside_deviation_anualizada_pct is None
    assert out.downside_target_periodic_pct == 0.0
    assert out.max_drawdown_pct is None
    assert out.drawdown is None


def test_instrumento_desconhecido_e_fora_da_cobertura_sao_diferentes():
    desconhecido = risco_retorno.calcular_risco_retorno(
        _resolvido(None, instrument_id=None, in_universe=False)
    )
    assert "instrumento_desconhecido" in desconhecido.evidencia.avisos
    assert "fora_da_cobertura" not in desconhecido.evidencia.avisos

    fora = risco_retorno.calcular_risco_retorno(
        _resolvido(None, instrument_id="iid-fora", in_universe=False)
    )
    assert "fora_da_cobertura" in fora.evidencia.avisos
    assert "instrumento_desconhecido" not in fora.evidencia.avisos


def test_tool_canonica_nasce_shadow_e_fingerprint_cobre_quant_core():
    carregar_tools()
    spec = spec_de("quant.risco_retorno")
    assert spec.semver == "1.1.0"
    assert spec.exposed_to_llm is True
    names = {Path(path).name for path in spec.source_files}
    assert {
        "risco_retorno.py",
        "_comum.py",
        "series.py",
        "models.py",
        "returns.py",
        "risk.py",
        "statistics.py",
    } <= names

class _FakeCtx:
    def __init__(self):
        self.conn = object()
        self.cutoff_date = date(2024, 1, 5)
        self.insumos: list[tuple[str, dict]] = []

    async def policy(self, code: str):
        assert code == "ANALISE_PARAMS"
        return {
            "janela_padrao_dias": 365,
            "metodo_retorno": "log",
            "dias_uteis_ano": 252,
            "min_observacoes": 2,
            "max_dias_defasagem": 5,
        }

    def registrar_insumo(self, kind: str, **payload):
        self.insumos.append((kind, payload))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("basis", "semantics"),
    [
        (PriceBasis.ADJUSTED_CLOSE, TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW),
        (PriceBasis.RAW_CLOSE, TemporalSemantics.OBSERVATION_DATE_CUTOFF),
    ],
)
async def test_preparar_deriva_semantica_e_passa_base_ao_loader(monkeypatch, basis, semantics):
    ctx = _FakeCtx()
    serie = _serie(
        [100, 101, 102, 103],
        basis=basis,
        semantics=semantics,
        warnings=[ADJUSTED_CLOSE_RETROSPECTIVE] if basis == PriceBasis.ADJUSTED_CLOSE else [],
    )
    capturado = {}

    async def fake_data_referencia(conn):
        return date(2024, 1, 5)

    async def fake_instrumento(conn, termo, *, cutoff):
        return {"instrument_id": "iid-3", "ticker": "TEST3", "is_in_universe": True}

    async def fake_carregar(conn, instrument_id, **kwargs):
        capturado.update(kwargs)
        return serie

    monkeypatch.setattr(risco_retorno, "data_referencia", fake_data_referencia)
    monkeypatch.setattr(risco_retorno, "instrumento_por_termo", fake_instrumento)
    monkeypatch.setattr(risco_retorno, "carregar_serie_resolvida", fake_carregar)

    resolvido = await risco_retorno.preparar_risco_retorno(
        risco_retorno.RiscoRetornoParams(ticker="TEST3", price_basis=basis),
        ctx,
    )
    assert resolvido.price_basis == basis
    assert resolvido.temporal_semantics == semantics
    assert capturado["basis"] == basis
    assert capturado["temporal_semantics"] == semantics
    assert capturado["include_calendar"] is True
    assert ctx.insumos[-1][1]["price_basis"] == basis.value
    assert ctx.insumos[-1][1]["temporal_semantics"] == semantics.value


def test_cutover_expoe_canonica_e_oculta_legacy_no_catalogo_do_analista():
    from app.agents.turn import filtrar_tools

    carregar_tools()
    from app.tools.registry import specs_registradas
    codes = {spec.code for spec in filtrar_tools(specs_registradas(), familias=("dados", "quant"), plano="wealth")}
    assert "quant.risco_retorno" in codes
    assert "quant.retorno_volatilidade" not in codes
