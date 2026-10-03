from __future__ import annotations

import importlib
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.market.analytics import returns as quant_returns
from app.market.analytics import risk as quant_risk
from app.market.analytics.models import ReturnMethod
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
from app.tools.analista import _risco_retorno_rolling_shadow as shadow
from app.tools.analista import risco_retorno
from app.tools.registry import spec_de, specs_registradas


def _serie(
    valores: list[float],
    *,
    inicio: date = date(2024, 1, 2),
    basis: PriceBasis = PriceBasis.ADJUSTED_CLOSE,
    semantics: TemporalSemantics = TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
) -> ResolvedMarketSeries:
    datas = [inicio + timedelta(days=i) for i in range(len(valores))]
    pontos = [MarketPoint(data=d, valor=v) for d, v in zip(datas, valores)]
    fim = pontos[-1].data if pontos else inicio
    warnings = [ADJUSTED_CLOSE_RETROSPECTIVE] if basis == PriceBasis.ADJUSTED_CLOSE else []
    return ResolvedMarketSeries(
        code="ROLL3",
        instrument_id="iid-roll",
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
            ingestion_batch_ids=["batch-roll"],
            calendar_ingestion_batch_ids=["cal-roll"],
            price_basis=basis,
            temporal_semantics=semantics,
            cutoff_date=fim,
            warnings=warnings,
        ),
    )


def _resolvido(
    serie: ResolvedMarketSeries,
    *,
    basis: PriceBasis = PriceBasis.ADJUSTED_CLOSE,
) -> risco_retorno.RiscoRetornoResolvido:
    return risco_retorno.RiscoRetornoResolvido(
        ticker="ROLL3",
        instrument_id="iid-roll",
        in_universe=True,
        cutoff_date=serie.points[-1].data,
        price_basis=basis,
        temporal_semantics=risco_retorno.temporal_semantics_for_basis(basis),
        serie=serie,
        metodo_retorno=ReturnMethod.LOG,
        dias_uteis_ano=252,
        min_observacoes=2,
        max_dias_defasagem=5,
    )


def _precos_longos(n: int) -> list[float]:
    return [100.0 + 0.02 * i + 0.15 * (i % 9) for i in range(n)]


def test_shadow_preserva_payload_1_1_integralmente_e_adiciona_somente_campos_candidatos():
    resolvido = _resolvido(_serie([100.0, 102.0, 101.0, 104.0, 103.0]))
    base = risco_retorno.calcular_risco_retorno(resolvido)
    candidato = shadow.calcular_risco_retorno_rolling_shadow(resolvido, janela_observacoes=2)

    payload_candidato = candidato.model_dump()
    extras = {
        "evolucao_volatilidade": payload_candidato.pop("evolucao_volatilidade"),
        "avisos_candidato": payload_candidato.pop("avisos_candidato"),
    }
    assert payload_candidato == base.model_dump()
    assert extras["evolucao_volatilidade"] is not None


def test_shadow_reusa_rolling_volatility_do_quant_core_sem_matematica_paralela():
    resolvido = _resolvido(_serie([100.0, 102.0, 101.0, 104.0, 103.0, 106.0]))
    candidato = shadow.calcular_risco_retorno_rolling_shadow(resolvido, janela_observacoes=3)
    evolucao = candidato.evolucao_volatilidade
    assert evolucao is not None

    retornos = quant_returns.calculate_returns(resolvido.serie.points, resolvido.metodo_retorno)
    esperado = quant_risk.rolling_volatility(
        retornos,
        window=3,
        periods_per_year=resolvido.dias_uteis_ano,
    )
    assert evolucao.n_janelas_total == len(esperado)
    assert evolucao.primeira_data == esperado[0].data
    assert evolucao.ultima_data == esperado[-1].data
    assert evolucao.vol_inicio_pct == pytest.approx(esperado[0].value * 100)
    assert evolucao.vol_fim_pct == pytest.approx(esperado[-1].value * 100)
    assert evolucao.vol_min_pct == pytest.approx(min(x.value for x in esperado) * 100)
    assert evolucao.vol_max_pct == pytest.approx(max(x.value for x in esperado) * 100)


def test_shadow_exige_janela_explicita_valida_e_nao_inventa_quando_insuficiente():
    resolvido = _resolvido(_serie([100.0, 101.0, 102.0, 103.0]))

    with pytest.raises(ValueError, match="janela_observacoes"):
        shadow.calcular_risco_retorno_rolling_shadow(resolvido, janela_observacoes=1)

    candidato = shadow.calcular_risco_retorno_rolling_shadow(resolvido, janela_observacoes=4)
    assert candidato.evolucao_volatilidade is None
    assert candidato.avisos_candidato == [shadow.JANELA_VOLATILIDADE_INSUFICIENTE]


def test_shadow_preserva_semantica_raw_close():
    serie = _serie(
        [100.0, 99.0, 101.0, 100.0, 102.0],
        basis=PriceBasis.RAW_CLOSE,
        semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
    )
    candidato = shadow.calcular_risco_retorno_rolling_shadow(
        _resolvido(serie, basis=PriceBasis.RAW_CLOSE),
        janela_observacoes=2,
    )
    assert candidato.price_basis == PriceBasis.RAW_CLOSE
    assert candidato.temporal_semantics == TemporalSemantics.OBSERVATION_DATE_CUTOFF
    assert ADJUSTED_CLOSE_RETROSPECTIVE not in candidato.evidencia.avisos


def test_compactacao_mensal_e_cap_de_60_preservam_resumo_da_serie_completa():
    resolvido = _resolvido(
        _serie(_precos_longos(2000), inicio=date(2019, 1, 1))
    )
    candidato = shadow.calcular_risco_retorno_rolling_shadow(
        resolvido,
        janela_observacoes=20,
    )
    evolucao = candidato.evolucao_volatilidade
    assert evolucao is not None
    assert evolucao.n_janelas_total == len(resolvido.serie.points) - 20
    assert evolucao.amostrado is True
    assert candidato.avisos_candidato == [shadow.SERIE_RISCO_AMOSTRADA]
    assert len(evolucao.pontos) == shadow.MAX_PONTOS_ROLLING_SHADOW == 60
    assert evolucao.pontos[0].data < evolucao.pontos[-1].data

    retornos = quant_returns.calculate_returns(resolvido.serie.points, resolvido.metodo_retorno)
    completo = quant_risk.rolling_volatility(
        retornos,
        window=20,
        periods_per_year=resolvido.dias_uteis_ano,
    )
    minimo = min(completo, key=lambda x: x.value)
    maximo = max(completo, key=lambda x: x.value)
    assert evolucao.vol_min_pct == pytest.approx(minimo.value * 100)
    assert evolucao.vol_min_data == minimo.data
    assert evolucao.vol_max_pct == pytest.approx(maximo.value * 100)
    assert evolucao.vol_max_data == maximo.data


def test_um_unico_ponto_rolling_nao_e_marcado_como_amostrado():
    resolvido = _resolvido(_serie([100.0, 101.0, 99.0, 102.0]))
    candidato = shadow.calcular_risco_retorno_rolling_shadow(
        resolvido,
        janela_observacoes=3,
    )
    evolucao = candidato.evolucao_volatilidade
    assert evolucao is not None
    assert evolucao.n_janelas_total == 1
    assert len(evolucao.pontos) == 1
    assert evolucao.amostrado is False
    assert candidato.avisos_candidato == []


def test_shadow_nao_registra_tool_nem_altera_semver_exposure_fingerprint_ou_catalogo():
    carregar_tools()
    antes = spec_de("quant.risco_retorno")
    fingerprint = antes.source_sha256
    arquivos = tuple(antes.source_files)
    total = len(specs_registradas())
    expostas = sum(spec.exposed_to_llm for spec in specs_registradas())

    importlib.reload(shadow)

    depois = spec_de("quant.risco_retorno")
    assert depois.semver == "1.1.0"
    assert depois.exposed_to_llm is True
    assert depois.source_sha256 == fingerprint
    assert depois.source_files == arquivos
    assert "_risco_retorno_rolling_shadow.py" not in {Path(p).name for p in depois.source_files}
    assert len(specs_registradas()) == total == 37
    assert sum(spec.exposed_to_llm for spec in specs_registradas()) == expostas == 34
