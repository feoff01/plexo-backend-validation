from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.agents import analysis
from app.market.analytics import estimates
from app.tools.analista import _comum
from app.tools.analista.evidencia_estatistica import EvidenciaEstatistica


def _legacy_evidence() -> _comum.Evidencia:
    return _comum.Evidencia(
        fonte="b3",
        instrument_ids=["iid-1"],
        tickers=["PETR4"],
        cutoff_date=date(2026, 9, 21),
        as_of=date(2026, 9, 18),
        n_observacoes=120,
        lacunas=[],
        metodo="retorno_risco",
        nota_metodo="método descritivo",
        suficiente=True,
        avisos=[],
        metricas={"retorno_pct": 12.3},
        ingestion_batch_ids=["batch-1"],
    )


def _estimate() -> estimates.MetricEstimate:
    return estimates.MetricEstimate(
        estimate=-0.42,
        unit="pct_return_per_percentage_point",
        n=84,
        standard_error=0.12,
        confidence_interval=estimates.ConfidenceInterval(
            lower=-0.66,
            upper=-0.18,
            level=0.95,
            method="normal_approximation",
        ),
        method="ols_hc1",
        warnings=("amostra_moderada",),
    )


def test_metric_estimate_completo_e_json_safe():
    est = _estimate()
    assert est.estimate == -0.42
    assert est.standard_error == 0.12
    assert est.confidence_interval is not None
    assert est.confidence_interval.level == 0.95
    assert est.warnings == ("amostra_moderada",)
    payload = est.model_dump(mode="json")
    assert payload["confidence_interval"]["lower"] == -0.66
    assert payload["unit"] == "pct_return_per_percentage_point"


def test_confidence_interval_rejeita_limites_nivel_e_nao_finitos_invalidos():
    with pytest.raises(ValidationError):
        estimates.ConfidenceInterval(lower=1.0, upper=0.0, level=0.95)
    with pytest.raises(ValidationError):
        estimates.ConfidenceInterval(lower=0.0, upper=1.0, level=1.0)
    with pytest.raises(ValidationError):
        estimates.ConfidenceInterval(lower=float("nan"), upper=1.0, level=0.95)


def test_metric_estimate_rejeita_se_negativo_e_numeros_nao_finitos():
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(estimate=1.0, unit="coef", n=20, standard_error=-0.1, method="ols")
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(estimate=float("inf"), unit="coef", n=20, method="ols")


def test_metric_estimate_indefinido_nao_pode_carregar_incerteza_ficticia():
    sem_estimativa = estimates.MetricEstimate(
        estimate=None,
        unit="coef",
        n=20,
        standard_error=None,
        confidence_interval=None,
        method="ols",
        warnings=("serie_constante",),
    )
    assert sem_estimativa.estimate is None

    with pytest.raises(ValidationError):
        estimates.MetricEstimate(
            estimate=None,
            unit="coef",
            n=20,
            standard_error=0.2,
            method="ols",
        )
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(
            estimate=None,
            unit="coef",
            n=20,
            confidence_interval=estimates.ConfidenceInterval(lower=-1, upper=1, level=0.95),
            method="ols",
        )


def test_metric_estimate_exige_unidade_e_metodo_nao_vazios():
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(estimate=1.0, unit="   ", n=10, method="ols")
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(estimate=1.0, unit="coef", n=10, method="  ")


def test_metric_estimate_nao_antecipa_p_value_no_contrato():
    assert "p_value" not in estimates.MetricEstimate.model_fields
    assert "significant" not in estimates.MetricEstimate.model_fields


def test_evidencia_legacy_nao_ganha_estimativas_no_json():
    payload = _legacy_evidence().model_dump(mode="json")
    assert "estimativas" not in payload
    assert payload["metricas"] == {"retorno_pct": 12.3}


def test_evidencia_estatistica_adiciona_estimativas_sem_alargar_metricas():
    legacy = _legacy_evidence().model_dump()
    ev = EvidenciaEstatistica(**legacy, estimativas={"beta_selic": _estimate()})
    payload = ev.model_dump(mode="json")
    assert payload["metricas"] == {"retorno_pct": 12.3}
    assert payload["estimativas"]["beta_selic"]["method"] == "ols_hc1"
    assert payload["estimativas"]["beta_selic"]["n"] == 84


def test_finding_quantitativo_inclui_estimativas_so_quando_existirem():
    base = {
        "tool": "quant.sensibilidade",
        "as_of": "2026-09-18",
        "n_observacoes": 84,
        "cutoff_date": "2026-09-21",
    }
    legacy = _legacy_evidence()
    finding_legacy = analysis._finding_quantitativo(base, legacy)
    assert finding_legacy["metricas"] == legacy.metricas
    assert "estimativas" not in finding_legacy

    estat = EvidenciaEstatistica(
        **legacy.model_dump(), estimativas={"beta_selic": _estimate()}
    )
    finding_estat = analysis._finding_quantitativo(base, estat)
    assert finding_estat["estimativas"]["beta_selic"]["estimate"] == -0.42
    assert finding_estat["estimativas"]["beta_selic"]["confidence_interval"]["level"] == 0.95


def test_finding_quantitativo_omite_estimativas_vazias():
    legacy = _legacy_evidence()
    estat = EvidenciaEstatistica(**legacy.model_dump(), estimativas={})
    finding = analysis._finding_quantitativo({"tool": "quant.x"}, estat)
    assert "estimativas" not in finding


def test_metric_estimate_definido_exige_amostra_positiva():
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(estimate=0.0, unit="coef", n=0, method="ols")


def test_metric_estimate_indefinido_exige_warning_explicativo():
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(estimate=None, unit="coef", n=20, method="ols")


def test_metric_estimate_rejeita_warnings_vazios_ou_duplicados():
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(estimate=1.0, unit="coef", n=20, method="ols", warnings=(" ",))
    with pytest.raises(ValidationError):
        estimates.MetricEstimate(estimate=1.0, unit="coef", n=20, method="ols", warnings=("x", "x"))
