from __future__ import annotations

from datetime import date

import pytest

from app.market.analytics import regression, sensitivity
from app.market.analytics.models import ConditionMeasure, ConditionalResponsePair


def _pair(i: int, x: float, y: float) -> ConditionalResponsePair:
    start = date(2024, 1, i + 1)
    end = date(2024, 1, i + 2)
    return ConditionalResponsePair(
        condition_start_date=start,
        condition_end_date=end,
        response_start_date=start,
        response_end_date=end,
        condition_change=x,
        response_return=y,
    )


def test_auto_newey_west_lags_e_limitado_pela_amostra():
    assert regression.newey_west_auto_lags(0) == 0
    assert regression.newey_west_auto_lags(2) == 0
    assert regression.newey_west_auto_lags(20) == 2
    assert regression.newey_west_auto_lags(100) == 4
    assert regression.newey_west_auto_lags(1000) == 6


def test_ols_linha_exata_recupera_slope_intercepto_e_ci_de_largura_zero():
    obs = [regression.RegressionObservation(x=float(x), y=1.0 + 2.0 * x) for x in range(1, 8)]
    out = regression.fit_univariate_ols_hac(obs)
    assert out.slope.estimate == pytest.approx(2.0)
    assert out.intercept.estimate == pytest.approx(1.0)
    assert out.slope.standard_error == pytest.approx(0.0, abs=1e-14)
    assert out.intercept.standard_error == pytest.approx(0.0, abs=1e-14)
    assert out.slope.confidence_interval is not None
    assert out.slope.confidence_interval.lower == pytest.approx(2.0)
    assert out.slope.confidence_interval.upper == pytest.approx(2.0)
    assert out.r_squared == pytest.approx(1.0)
    assert out.n == 7


def test_hac_usa_lags_em_observacoes_e_difere_de_lag_zero_quando_ha_dependencia_serial():
    # Resíduos com blocos persistentes para que autocovariância não seja zero.
    xs = [float(i) for i in range(1, 41)]
    errors = [1.0] * 10 + [-1.0] * 10 + [1.5] * 10 + [-1.5] * 10
    obs = [regression.RegressionObservation(x=x, y=0.4 * x + e) for x, e in zip(xs, errors)]
    robust = regression.fit_univariate_ols_hac(obs, hac_lags=4)
    lag0 = regression.fit_univariate_ols_hac(obs, hac_lags=0)
    assert robust.hac_lags == 4
    assert lag0.hac_lags == 0
    assert robust.slope.estimate == pytest.approx(lag0.slope.estimate)
    assert robust.slope.standard_error is not None
    assert lag0.slope.standard_error is not None
    assert robust.slope.standard_error != pytest.approx(lag0.slope.standard_error)


def test_duas_observacoes_tem_ponto_estimado_sem_inferencia_ficticia():
    out = regression.fit_univariate_ols_hac([
        regression.RegressionObservation(x=1.0, y=3.0),
        regression.RegressionObservation(x=2.0, y=5.0),
    ])
    assert out.slope.estimate == pytest.approx(2.0)
    assert out.intercept.estimate == pytest.approx(1.0)
    assert out.slope.standard_error is None
    assert out.slope.confidence_interval is None
    assert "sem_graus_liberdade_inferencia" in out.slope.warnings


def test_driver_constante_nao_inventa_beta():
    out = regression.fit_univariate_ols_hac([
        regression.RegressionObservation(x=1.0, y=2.0),
        regression.RegressionObservation(x=1.0, y=3.0),
        regression.RegressionObservation(x=1.0, y=4.0),
    ])
    assert out.slope.estimate is None
    assert out.intercept.estimate is None
    assert out.r_squared is None
    assert "driver_constante" in out.slope.warnings


def test_regressao_rejeita_nao_finito_e_lag_invalido():
    with pytest.raises(ValueError):
        regression.fit_univariate_ols_hac([
            regression.RegressionObservation(x=1.0, y=2.0),
            regression.RegressionObservation(x=float("nan"), y=3.0),
        ])
    with pytest.raises(ValueError):
        regression.fit_univariate_ols_hac([
            regression.RegressionObservation(x=1.0, y=2.0),
            regression.RegressionObservation(x=2.0, y=3.0),
            regression.RegressionObservation(x=3.0, y=4.0),
        ], hac_lags=3)


def test_sensibilidade_de_taxa_usa_pontos_percentuais_e_retorno_pct():
    # driver: -0.5pp, +0.5pp, +1pp; resposta: -1%, +1%, +2% => beta = 2 pp retorno / 1pp driver.
    pairs = [_pair(0, -0.5, -0.01), _pair(1, 0.5, 0.01), _pair(2, 1.0, 0.02)]
    out = sensitivity.analyze_sensitivity(pairs, driver_measure=ConditionMeasure.LEVEL_CHANGE)
    assert out.slope.estimate == pytest.approx(2.0)
    assert out.slope.unit == "pct_return_per_percentage_point"
    assert out.n == 3
    assert out.response_unit == "pct_return"
    assert out.driver_unit == "percentage_point"


def test_sensibilidade_de_indice_escala_x_e_y_para_pct_e_preserva_beta():
    # Mudança do driver está em retorno decimal; ambas as dimensões são *100 antes da regressão.
    pairs = [_pair(0, -0.10, -0.05), _pair(1, 0.05, 0.025), _pair(2, 0.10, 0.05), _pair(3, 0.20, 0.10)]
    out = sensitivity.analyze_sensitivity(pairs, driver_measure=ConditionMeasure.RETURN)
    assert out.slope.estimate == pytest.approx(0.5)
    assert out.slope.unit == "pct_return_per_pct_driver_return"
    assert out.driver_unit == "pct_return"


def test_sensibilidade_nao_remove_outlier_automaticamente():
    pairs = [_pair(i, float(i), 0.01 * float(i)) for i in range(1, 6)]
    pairs.append(_pair(6, 100.0, -0.90))
    out = sensitivity.analyze_sensitivity(pairs, driver_measure=ConditionMeasure.LEVEL_CHANGE)
    assert out.n == len(pairs)
    assert out.outlier_policy == "none"


def test_diagnostico_de_intervalo_e_em_dias_mas_hac_em_observacoes():
    pairs = [
        ConditionalResponsePair(
            condition_start_date=date(2024, 1, 2), condition_end_date=date(2024, 1, 3),
            response_start_date=date(2024, 1, 2), response_end_date=date(2024, 1, 3),
            condition_change=1.0, response_return=0.01,
        ),
        ConditionalResponsePair(
            condition_start_date=date(2024, 1, 3), condition_end_date=date(2024, 1, 8),
            response_start_date=date(2024, 1, 3), response_end_date=date(2024, 1, 8),
            condition_change=2.0, response_return=0.02,
        ),
        ConditionalResponsePair(
            condition_start_date=date(2024, 1, 8), condition_end_date=date(2024, 1, 10),
            response_start_date=date(2024, 1, 8), response_end_date=date(2024, 1, 10),
            condition_change=3.0, response_return=0.03,
        ),
    ]
    out = sensitivity.analyze_sensitivity(pairs, driver_measure=ConditionMeasure.LEVEL_CHANGE)
    assert out.interval_days_min == 1
    assert out.interval_days_median == 2
    assert out.interval_days_max == 5
    assert out.hac_lags >= 0


def test_sensibilidade_recusa_pair_com_lookahead():
    bad = ConditionalResponsePair(
        condition_start_date=date(2024, 1, 2), condition_end_date=date(2024, 1, 5),
        response_start_date=date(2024, 1, 3), response_end_date=date(2024, 1, 5),
        condition_change=1.0, response_return=0.02,
    )
    with pytest.raises(ValueError, match="look-ahead"):
        sensitivity.analyze_sensitivity([bad], driver_measure=ConditionMeasure.LEVEL_CHANGE)
