from __future__ import annotations

import math
import random
import statistics

import pytest

from app.market.analytics import regression


def _manual_ols(xs: list[float], ys: list[float]):
    xb = statistics.fmean(xs)
    yb = statistics.fmean(ys)
    sxx = math.fsum((x - xb) ** 2 for x in xs)
    slope = math.fsum((x - xb) * (y - yb) for x, y in zip(xs, ys)) / sxx
    intercept = yb - slope * xb
    residuals = [y - intercept - slope * x for x, y in zip(xs, ys)]
    sse = math.fsum(e * e for e in residuals)
    sst = math.fsum((y - yb) ** 2 for y in ys)
    r2 = None if sst == 0 else 1 - sse / sst
    return intercept, slope, r2


def _fit(xs, ys, **kwargs):
    return regression.fit_univariate_ols_hac(
        [regression.RegressionObservation(x=x, y=y) for x, y in zip(xs, ys)], **kwargs
    )


def test_500_amostras_ols_batem_com_formula_independente():
    rng = random.Random(20260921)
    for _ in range(500):
        n = rng.randint(3, 80)
        xs = [rng.uniform(-5, 5) + i * 0.01 for i in range(n)]
        beta = rng.uniform(-3, 3)
        alpha = rng.uniform(-2, 2)
        ys = [alpha + beta * x + rng.uniform(-1, 1) for x in xs]
        expected_a, expected_b, expected_r2 = _manual_ols(xs, ys)
        out = _fit(xs, ys)
        assert out.intercept.estimate == pytest.approx(expected_a, rel=1e-12, abs=1e-12)
        assert out.slope.estimate == pytest.approx(expected_b, rel=1e-12, abs=1e-12)
        assert out.r_squared == pytest.approx(expected_r2, rel=1e-12, abs=1e-12)
        assert out.slope.standard_error is not None and math.isfinite(out.slope.standard_error)
        assert out.slope.standard_error >= 0
        assert 0 <= out.hac_lags <= n - 2


def test_transladar_x_nao_muda_slope_nem_se_do_slope():
    xs = [float(i) for i in range(1, 40)]
    ys = [1.5 + 0.7*x + math.sin(x/3) for x in xs]
    a = _fit(xs, ys, hac_lags=4)
    b = _fit([x + 1000 for x in xs], ys, hac_lags=4)
    assert a.slope.estimate == pytest.approx(b.slope.estimate, rel=1e-12)
    assert a.slope.standard_error == pytest.approx(b.slope.standard_error, rel=1e-10)
    assert a.r_squared == pytest.approx(b.r_squared, rel=1e-12)


def test_escalar_y_escala_slope_intercepto_e_se_linearmente():
    xs = [float(i) for i in range(1, 50)]
    ys = [2 + 0.3*x + math.cos(x/5) for x in xs]
    a = _fit(xs, ys, hac_lags=3)
    b = _fit(xs, [10*y for y in ys], hac_lags=3)
    assert b.slope.estimate == pytest.approx(10*a.slope.estimate, rel=1e-12)
    assert b.intercept.estimate == pytest.approx(10*a.intercept.estimate, rel=1e-12)
    assert b.slope.standard_error == pytest.approx(10*a.slope.standard_error, rel=1e-10)
    assert b.r_squared == pytest.approx(a.r_squared, rel=1e-12)


def test_hac_slope_e_intercepto_batem_com_formula_de_influencia_independente():
    xs = [1., 2., 3., 5., 8., 13., 21., 34.]
    ys = [2.1, 2.9, 4.4, 5.2, 7.7, 9.1, 14.8, 20.2]
    lags = 3
    out = _fit(xs, ys, hac_lags=lags)
    alpha, beta, _ = _manual_ols(xs, ys)
    residuals = [y - alpha - beta*x for x, y in zip(xs, ys)]
    n = len(xs)
    xb = statistics.fmean(xs)
    sxx = math.fsum((x-xb)**2 for x in xs)

    influence_slope = [((x-xb)/sxx) * e for x, e in zip(xs, residuals)]
    influence_intercept = [(1/n - xb*(x-xb)/sxx) * e for x, e in zip(xs, residuals)]

    def nw_var(u):
        total = math.fsum(v*v for v in u)
        for lag in range(1, lags+1):
            weight = 1 - lag/(lags+1)
            total += 2 * weight * math.fsum(u[t]*u[t-lag] for t in range(lag, n))
        return (n/(n-2)) * total

    assert out.slope.standard_error == pytest.approx(math.sqrt(max(0.0, nw_var(influence_slope))), rel=1e-11, abs=1e-12)
    assert out.intercept.standard_error == pytest.approx(math.sqrt(max(0.0, nw_var(influence_intercept))), rel=1e-11, abs=1e-12)


def test_hac_lag_zero_equivale_hc1_para_slope_em_regressao_simples():
    xs = [1., 2., 4., 7., 11., 16.]
    ys = [1.2, 2.5, 3.0, 5.8, 7.2, 10.5]
    out = _fit(xs, ys, hac_lags=0)
    alpha, beta, _ = _manual_ols(xs, ys)
    residuals = [y-alpha-beta*x for x, y in zip(xs, ys)]
    xb = statistics.fmean(xs)
    sxx = math.fsum((x-xb)**2 for x in xs)
    n = len(xs)
    var_hc1 = (n/(n-2)) * math.fsum(((x-xb)**2)*(e**2) for x,e in zip(xs,residuals)) / (sxx**2)
    assert out.slope.standard_error == pytest.approx(math.sqrt(var_hc1), rel=1e-12, abs=1e-12)


def test_offset_extremo_em_x_nao_torna_covariance_singular():
    base_x = [float(i) for i in range(1, 60)]
    ys = [2.0 + 0.8*x + math.sin(x/4) for x in base_x]
    a = _fit(base_x, ys, hac_lags=4)
    b = _fit([1e12 + x for x in base_x], ys, hac_lags=4)
    assert b.slope.estimate == pytest.approx(a.slope.estimate, rel=1e-12, abs=1e-12)
    assert b.slope.standard_error == pytest.approx(a.slope.standard_error, rel=1e-9, abs=1e-12)
    assert b.r_squared == pytest.approx(a.r_squared, rel=1e-12, abs=1e-12)
