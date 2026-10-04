"""Normalização e agregação por família — a metade PURA do score.

Aqui mora a única coisa que transforma um indicador em juízo: a curva. E ela NÃO está
neste arquivo — está em `engine.policy_versions` (CLIENT_SCORES), porque é ela que
compliance revisa. O que está aqui é a interpolação, que é matemática e não opinião.

    "a reserva cobre 4,2 meses"   ← indicador (objetivo, tem unidade)
    "4,2 meses = 0,62"            ← score (juízo, depende da política vigente)

REGRA DO PESO AUSENTE
    Indicador indisponível não entra na conta com zero: o peso dele é REDISTRIBUÍDO entre
    os presentes e a COBERTURA cai. Imputar zero diria ao cliente que ele vai mal onde,
    na verdade, ninguém mediu — é a diferença entre não saber e saber que está ruim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def interpolar(pontos: list[list[float]], x: float, *, clamp: bool = True) -> float:
    """Curva linear por partes. `pontos` é [[x, y], ...] com x crescente.

    Fora do intervalo, satura no extremo quando clamp — que é o que faz "20 meses de
    reserva" não valer mais que "12": acima do suficiente, mais reserva não é mais saúde.
    """
    if not pontos:
        raise ValueError("curva de normalização sem pontos")
    ordenados = sorted(([float(p[0]), float(p[1])] for p in pontos), key=lambda p: p[0])
    if x <= ordenados[0][0]:
        return ordenados[0][1] if clamp else _extrapolar(ordenados[0], ordenados[min(1, len(ordenados) - 1)], x)
    if x >= ordenados[-1][0]:
        return ordenados[-1][1] if clamp else _extrapolar(ordenados[max(-2, -len(ordenados))], ordenados[-1], x)
    for (x0, y0), (x1, y1) in zip(ordenados, ordenados[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ordenados[-1][1]


def _extrapolar(a: list[float], b: list[float], x: float) -> float:
    if b[0] == a[0]:
        return a[1]
    return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])


@dataclass(frozen=True)
class ScoreCalculado:
    valor: float | None
    cobertura: float
    confianca: float
    componentes: dict[str, Any]
    indisponivel: bool
    motivo: str | None


def compor(
    *,
    indicator_codes: list[str],
    valores: dict[str, float],                 # só os DISPONÍVEIS
    confiancas: dict[str, float],
    normalizacao: dict[str, dict[str, Any]],
    pesos: dict[str, float],
    min_coverage: float,
    fundacao_critica: bool,
) -> ScoreCalculado:
    """Compõe o score de uma família a partir dos indicadores dela.

    A ordem das recusas importa e espelha a do banco (C40a antes de C40b): Fundação
    crítica DESATIVA antes de qualquer conta — não é score baixo, é ausência de score.
    """
    peso_total = sum(pesos.get(c, 0.0) for c in indicator_codes)
    presentes = [c for c in indicator_codes if c in valores]
    peso_presente = sum(pesos.get(c, 0.0) for c in presentes)
    cobertura = (peso_presente / peso_total) if peso_total > 0 else 0.0

    componentes: dict[str, Any] = {}
    acumulado = 0.0
    for code in presentes:
        curva = normalizacao.get(code) or {}
        pontos = curva.get("pontos") or []
        if not pontos:
            continue
        bruto = valores[code]
        normalizado = interpolar(pontos, bruto, clamp=bool(curva.get("clamp", True)))
        normalizado = min(1.0, max(0.0, normalizado))
        peso_relativo = (pesos.get(code, 0.0) / peso_presente) if peso_presente > 0 else 0.0
        acumulado += normalizado * peso_relativo
        componentes[code] = {"bruto": bruto, "normalizado": round(normalizado, 4),
                             "peso": round(peso_relativo, 4)}

    # confiança do score = média ponderada da confiança dos indicadores que entraram
    confianca = 0.0
    if peso_presente > 0:
        confianca = sum(confiancas.get(c, 0.0) * pesos.get(c, 0.0) for c in presentes) / peso_presente

    if fundacao_critica:
        return ScoreCalculado(None, round(cobertura, 4), round(confianca, 3), componentes,
                              True, "fundacao_critica")
    if not presentes:
        return ScoreCalculado(None, round(cobertura, 4), round(confianca, 3), componentes,
                              True, "dados_insuficientes")
    if cobertura < min_coverage:
        return ScoreCalculado(None, round(cobertura, 4), round(confianca, 3), componentes,
                              True, "cobertura_insuficiente")

    return ScoreCalculado(round(min(1.0, max(0.0, acumulado)), 4), round(cobertura, 4),
                          round(confianca, 3), componentes, False, None)


def confianca_por_frescor(dias_desde_observacao: int, meia_vida_dias: int) -> float:
    """Fato vencido não invalida o score — ele derruba a CONFIANÇA dele.

    Decaimento linear até a meia-vida, com piso: um fato de seis meses ainda vale
    alguma coisa, só não vale como um de ontem.
    """
    if meia_vida_dias <= 0:
        return 1.0
    fracao = max(0.0, 1.0 - (dias_desde_observacao / meia_vida_dias))
    return round(max(0.25, min(1.0, fracao)), 3)
