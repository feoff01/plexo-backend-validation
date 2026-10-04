from __future__ import annotations

import math
import random
import statistics
from datetime import date, timedelta

import pytest

from app.market.analytics.models import DependenceMethod, ReturnObservation
from app.market.analytics.dependence import (
    align_returns,
    dependence_estimate,
    down_market_dependence,
    pearson_correlation,
    rolling_dependence,
    spearman_correlation,
    up_market_dependence,
)


def _returns(values: list[float], *, start=date(2024, 1, 2), step_days: int = 1) -> list[ReturnObservation]:
    return [
        ReturnObservation(data=start + timedelta(days=i * step_days), value=float(value))
        for i, value in enumerate(values)
    ]


def test_pearson_preserva_statistics_correlation_e_indefinidos():
    x = [0.01, -0.02, 0.03, 0.005, 0.04]
    y = [0.02, -0.01, 0.01, 0.015, 0.05]
    assert pearson_correlation(x, y) == statistics.correlation(x, y)
    assert pearson_correlation([1.0], [2.0]) is None
    assert pearson_correlation([1.0, 1.0], [2.0, 3.0]) is None
    assert pearson_correlation([1.0, 2.0], [3.0, 3.0]) is None


def test_pearson_falha_fechado_em_tamanhos_e_nao_finitos():
    with pytest.raises(ValueError, match="mesmo tamanho"):
        pearson_correlation([1.0, 2.0], [1.0])
    with pytest.raises(ValueError, match="não finito"):
        pearson_correlation([1.0, math.nan], [1.0, 2.0])
    with pytest.raises(ValueError, match="não finito"):
        pearson_correlation([1.0, 2.0], [1.0, math.inf])


def test_spearman_monotonia_empates_e_indefinidos():
    assert spearman_correlation([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman_correlation([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)

    x = [10, 10, 20, 30]
    y = [1, 2, 2, 4]
    # ranks médios: x=[1.5,1.5,3,4], y=[1,2.5,2.5,4]
    esperado = statistics.correlation([1.5, 1.5, 3.0, 4.0], [1.0, 2.5, 2.5, 4.0])
    assert spearman_correlation(x, y) == pytest.approx(esperado)
    assert spearman_correlation([1, 1, 1], [1, 2, 3]) is None


def test_align_returns_intersecao_sem_padding_e_lag_assinado():
    x = [
        ReturnObservation(data=date(2024, 1, 2), value=1),
        ReturnObservation(data=date(2024, 1, 3), value=2),
        ReturnObservation(data=date(2024, 1, 5), value=3),
        ReturnObservation(data=date(2024, 1, 8), value=4),
    ]
    y = [
        ReturnObservation(data=date(2024, 1, 2), value=10),
        ReturnObservation(data=date(2024, 1, 4), value=20),
        ReturnObservation(data=date(2024, 1, 5), value=30),
        ReturnObservation(data=date(2024, 1, 8), value=40),
    ]

    zero = align_returns(x, y, lag_observations=0)
    assert [(p.x_date, p.y_date, p.x_value, p.y_value) for p in zero] == [
        (date(2024, 1, 2), date(2024, 1, 2), 1.0, 10.0),
        (date(2024, 1, 5), date(2024, 1, 5), 3.0, 30.0),
        (date(2024, 1, 8), date(2024, 1, 8), 4.0, 40.0),
    ]

    positivo = align_returns(x, y, lag_observations=1)
    assert [(p.x_date, p.y_date, p.as_of_date, p.x_value, p.y_value) for p in positivo] == [
        (date(2024, 1, 2), date(2024, 1, 5), date(2024, 1, 5), 1.0, 30.0),
        (date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 8), 3.0, 40.0),
    ]

    negativo = align_returns(x, y, lag_observations=-1)
    assert [(p.x_date, p.y_date, p.as_of_date, p.x_value, p.y_value) for p in negativo] == [
        (date(2024, 1, 5), date(2024, 1, 2), date(2024, 1, 5), 3.0, 10.0),
        (date(2024, 1, 8), date(2024, 1, 5), date(2024, 1, 8), 4.0, 30.0),
    ]


def test_align_returns_rejeita_datas_duplicadas_ou_fora_de_ordem():
    dup = [
        ReturnObservation(data=date(2024, 1, 2), value=1),
        ReturnObservation(data=date(2024, 1, 2), value=2),
    ]
    bom = _returns([1, 2])
    with pytest.raises(ValueError, match="estritamente crescentes"):
        align_returns(dup, bom)

    invertido = list(reversed(_returns([1, 2, 3])))
    with pytest.raises(ValueError, match="estritamente crescentes"):
        align_returns(invertido, _returns([1, 2, 3]))


def test_dependence_estimate_carrega_metodo_n_e_lag():
    x = _returns([1, 2, 3, 4])
    y = _returns([2, 4, 6, 8])
    pares = align_returns(x, y, lag_observations=0)
    estimate = dependence_estimate(pares, method=DependenceMethod.PEARSON, lag_observations=0)
    assert estimate.coefficient == pytest.approx(1.0)
    assert estimate.n_pairs == 4
    assert estimate.method == DependenceMethod.PEARSON
    assert estimate.lag_observations == 0
    assert not estimate.x_constant and not estimate.y_constant


def test_rolling_dependence_sem_padding_e_data_no_fim_da_janela():
    x = _returns([1, 2, 4, 3, 5, 8])
    y = _returns([2, 4, 8, 7, 10, 16])
    out = rolling_dependence(x, y, window=3, method=DependenceMethod.PEARSON)
    assert len(out) == 4
    assert out[0].data == x[2].data
    assert out[-1].data == x[-1].data
    assert all(item.n_pairs == 3 for item in out)
    assert out[0].coefficient == pytest.approx(1.0)


def test_rolling_dependence_janela_constante_retorna_none_nao_zero():
    x = _returns([1, 1, 1, 2])
    y = _returns([1, 2, 3, 4])
    out = rolling_dependence(x, y, window=3, method=DependenceMethod.PEARSON)
    assert out[0].coefficient is None
    assert out[1].coefficient is not None


def test_up_down_market_condiciona_apos_alinhamento_e_exclui_neutro():
    asset = _returns([0.01, 0.02, -0.03, -0.01, 0.04, -0.02, 0.05])
    market = _returns([0.01, 0.03, -0.02, -0.04, 0.0, -0.01, 0.02])

    up = up_market_dependence(asset, market, method=DependenceMethod.PEARSON)
    down = down_market_dependence(asset, market, method=DependenceMethod.PEARSON)

    assert up.direction == "up"
    assert up.n_pairs == 3  # market > 0; zero fica de fora
    assert down.direction == "down"
    assert down.n_pairs == 3
    assert up.threshold == 0.0 and down.threshold == 0.0
    assert up.coefficient is not None and down.coefficient is not None


def test_up_down_market_threshold_precisa_ser_finito():
    asset = _returns([0.01, 0.02, -0.03])
    market = _returns([0.01, 0.03, -0.02])
    with pytest.raises(ValueError, match="threshold"):
        up_market_dependence(asset, market, threshold=math.nan)


def test_property_pearson_spearman_simetricos_em_lag_zero():
    rng = random.Random(20260921)
    for _ in range(300):
        n = rng.randint(3, 40)
        x = [rng.uniform(-0.15, 0.15) for _ in range(n)]
        y = [rng.uniform(-0.15, 0.15) for _ in range(n)]
        assert pearson_correlation(x, y) == pytest.approx(pearson_correlation(y, x), abs=1e-15)
        assert spearman_correlation(x, y) == pytest.approx(spearman_correlation(y, x), abs=1e-15)


def test_property_lag_positivo_reduz_n_por_abs_lag():
    x = _returns([float(i) for i in range(20)])
    y = _returns([float(i * 2) for i in range(20)])
    for lag in range(-19, 20):
        pares = align_returns(x, y, lag_observations=lag)
        assert len(pares) == 20 - abs(lag)
        assert all(p.as_of_date == max(p.x_date, p.y_date) for p in pares)


def test_property_lag_e_pearson_equivalem_ao_algoritmo_legacy_em_750_casos():
    rng = random.Random(230921)
    start = date(2024, 1, 2)
    for _ in range(750):
        n = rng.randint(3, 60)
        lag = rng.randint(0, n - 2)
        # Evita séries constantes por construção para comparar números definidos.
        xa = [rng.uniform(-0.2, 0.2) + i * 1e-9 for i in range(n)]
        yb = [rng.uniform(-0.2, 0.2) - i * 1e-9 for i in range(n)]
        x_obs = [ReturnObservation(data=start + timedelta(days=i), value=v) for i, v in enumerate(xa)]
        y_obs = [ReturnObservation(data=start + timedelta(days=i), value=v) for i, v in enumerate(yb)]

        # Algoritmo legacy: interseção ordenada e B deslocado para frente quando lag > 0.
        comuns = [start + timedelta(days=i) for i in range(n)]
        legacy_x = [xa[i] for i in range(n - lag)]
        legacy_y = [yb[i + lag] for i in range(n - lag)]
        esperado = statistics.correlation(legacy_x, legacy_y) if len(comuns) - lag >= 2 else None

        pairs = align_returns(x_obs, y_obs, lag_observations=lag)
        atual = dependence_estimate(pairs, method=DependenceMethod.PEARSON, lag_observations=lag)
        assert atual.n_pairs == n - lag
        assert atual.coefficient == pytest.approx(esperado, abs=1e-15)


def test_property_lag_assinado_e_simetrico_ao_trocar_x_y():
    rng = random.Random(231021)
    for _ in range(250):
        n = rng.randint(5, 30)
        lag = rng.randint(1, n - 2)
        x = _returns([rng.uniform(-0.1, 0.1) for _ in range(n)])
        y = _returns([rng.uniform(-0.1, 0.1) for _ in range(n)])
        xy = dependence_estimate(
            align_returns(x, y, lag_observations=lag),
            method=DependenceMethod.PEARSON,
            lag_observations=lag,
        )
        yx = dependence_estimate(
            align_returns(y, x, lag_observations=-lag),
            method=DependenceMethod.PEARSON,
            lag_observations=-lag,
        )
        assert xy.n_pairs == yx.n_pairs
        assert xy.coefficient == pytest.approx(yx.coefficient, abs=1e-15)
