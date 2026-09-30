"""Retornos puros sobre ``MarketPoint``.

Sem acesso a banco/policy. Bases de anualização são sempre parâmetros explícitos do chamador; não
há 252, 12 ou qualquer outra premissa de negócio escondida neste módulo.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from app.market.analytics.models import IndexUnit, ReturnMethod, ReturnObservation
from app.market.series import MarketPoint


class InvalidPricePath(ValueError):
    """Série de preço viola pré-condições matemáticas do Quant Core."""


def _validated_dates(points: Sequence[MarketPoint], *, error_type: type[ValueError]) -> list[MarketPoint]:
    out = list(points)
    previous_date = None
    for point in out:
        if previous_date is not None and point.data <= previous_date:
            raise error_type("datas devem ser estritamente crescentes e únicas")
        previous_date = point.data
    return out


def validate_price_path(points: Sequence[MarketPoint]) -> list[MarketPoint]:
    out = _validated_dates(points, error_type=InvalidPricePath)
    for point in out:
        if not math.isfinite(point.valor) or point.valor <= 0:
            raise InvalidPricePath(f"preço deve ser positivo e finito em {point.data}")
    return out


def calculate_returns(points: Sequence[MarketPoint], method: ReturnMethod | str) -> list[ReturnObservation]:
    """Retorno entre pontos consecutivos, datado no ponto final."""
    path = validate_price_path(points)
    return_method = ReturnMethod(method)
    out: list[ReturnObservation] = []
    for start, end in zip(path, path[1:]):
        if return_method == ReturnMethod.LOG:
            # Preserva exatamente a semântica legacy no domínio normal; só usa a forma
            # numericamente estável quando a razão intermediária estoura.
            ratio = end.valor / start.valor
            value = (math.log(ratio) if math.isfinite(ratio)
                     else math.log(end.valor) - math.log(start.valor))
        else:
            value = end.valor / start.valor - 1.0
        if not math.isfinite(value):
            raise NonFiniteReturnResult(f"retorno não finito em {end.data}")
        out.append(ReturnObservation(data=end.data, value=value))
    return out


def cumulative_price_return(points: Sequence[MarketPoint]) -> float | None:
    """Retorno simples entre primeiro e último preço; indefinido com menos de dois pontos."""
    path = validate_price_path(points)
    if len(path) < 2:
        return None
    value = path[-1].valor / path[0].valor - 1.0
    if not math.isfinite(value):
        raise NonFiniteReturnResult("retorno acumulado não finito")
    return value


def annualized_price_return(points: Sequence[MarketPoint], *, periods_per_year: int) -> float | None:
    """CAGR pela contagem de intervalos observados, compatível com a tool legacy atual.

    ``periods_per_year`` é obrigatório e explícito. O método usa ``len(points)-1`` intervalos, não
    dias corridos, para preservar a definição atualmente usada pelo Analista.
    """
    if periods_per_year <= 0:
        raise ValueError("periods_per_year deve ser positivo")
    path = validate_price_path(points)
    intervals = len(path) - 1
    if intervals <= 0:
        return None
    gross = path[-1].valor / path[0].valor
    try:
        if math.isfinite(gross):
            # Caminho legacy para manter goldens bit a bit quando a razão é representável.
            value = gross ** (periods_per_year / intervals) - 1.0
        else:
            # Fallback estável apenas para o domínio extremo em que a razão intermediária estoura.
            log_gross = math.log(path[-1].valor) - math.log(path[0].valor)
            value = math.expm1(log_gross * (periods_per_year / intervals))
    except OverflowError as exc:
        raise NonFiniteReturnResult("retorno anualizado excede a representação finita") from exc
    if not math.isfinite(value):
        raise NonFiniteReturnResult("retorno anualizado não finito")
    return value


def compound_simple_returns(values: Iterable[float]) -> float:
    """Compõe retornos simples. Retorno abaixo de -100% é matematicamente inválido."""
    wealth = 1.0
    for raw in values:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("retorno deve ser finito")
        if value < -1.0:
            raise ValueError("retorno simples não pode ser menor que -100%")
        wealth *= 1.0 + value
        if not math.isfinite(wealth):
            raise NonFiniteReturnResult("composição de retornos excede a representação finita")
    return wealth - 1.0


class NonFiniteReturnResult(ValueError):
    """O resultado excedeu a representação numérica finita suportada."""


class InvalidRateSeries(ValueError):
    """Taxa/percentual não pode ser convertido em retorno periódico válido."""


def _validated_rate_points(points: Sequence[MarketPoint]) -> list[MarketPoint]:
    out = _validated_dates(points, error_type=InvalidRateSeries)
    for point in out:
        raw = float(point.valor)
        if not math.isfinite(raw):
            raise InvalidRateSeries(f"taxa deve ser finita em {point.data}")
        if raw < -100.0:
            raise InvalidRateSeries(f"taxa percentual abaixo de -100% em {point.data}")
    return out


def calculate_index_returns(
    points: Sequence[MarketPoint],
    unit: IndexUnit | str,
    *,
    periods_per_year: int,
    method: ReturnMethod | str,
) -> list[ReturnObservation]:
    """Converte série de índice/taxa em retornos periódicos com semântica explícita.

    - ``pontos``: retorno entre níveis consecutivos;
    - ``taxa_aa``: taxa percentual anual convertida para retorno de um período;
    - ``taxa_am``/``percentual``: o valor percentual da observação é o retorno do período.

    Como no legado, a primeira observação não gera retorno porque não há período anterior no recorte.
    """
    if periods_per_year <= 0:
        raise ValueError("periods_per_year deve ser positivo")
    index_unit = IndexUnit(unit)
    path = (validate_price_path(points) if index_unit == IndexUnit.POINTS
            else _validated_rate_points(points))
    if index_unit == IndexUnit.POINTS:
        return calculate_returns(path, method)

    out: list[ReturnObservation] = []
    for point in path[1:]:
        raw = float(point.valor)
        fraction = raw / 100.0
        if index_unit == IndexUnit.ANNUAL_RATE:
            # Fórmula legacy preservada: mudança de implementação não pode causar drift
            # silencioso em correlação com CDI/Selic quando este core for conectado à tool.
            value = (1.0 + fraction) ** (1.0 / periods_per_year) - 1.0
        else:
            value = fraction
        if not math.isfinite(value):
            raise InvalidRateSeries(f"retorno periódico não finito em {point.data}")
        out.append(ReturnObservation(data=point.data, value=value))
    return out
