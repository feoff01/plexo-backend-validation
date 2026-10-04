"""Pontuação do questionário de suitability — função PURA sobre o payload da policy
SUITABILITY_QUESTIONARIO (config-first: nenhum ponto/limiar mora no código).

`pontuar()` não abre conexão nenhuma: recebe as respostas e o payload já lido pelo
chamador (via PolicyStore) e devolve o resultado. Isso a deixa travável por teste sem
Postgres — o mesmo desenho de app/engine/simulacao.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.onboarding.erros import DadoInvalido


class RespostaSuitabilityInvalida(DadoInvalido):
    """Pergunta ou opção fora do questionário vigente, ou questionário mal configurado."""


@dataclass(frozen=True)
class ResultadoSuitability:
    pontuacao: int
    resultado: str


def pontuar(respostas: dict[str, str], payload: dict[str, Any]) -> ResultadoSuitability:
    """Soma os pontos das opções escolhidas e classifica pelos limiares da política.

    `<= conservador_max` → 'conservador'; `<= moderado_max` → 'moderado'; senão 'arrojado'
    — os dois valores vêm de `payload["limiares"]`, nunca de literal aqui.
    """
    perguntas = payload.get("perguntas") or []
    if not perguntas:
        raise RespostaSuitabilityInvalida("questionário sem perguntas configuradas")

    ids_esperados = {p["id"] for p in perguntas}
    faltando = ids_esperados - set(respostas)
    if faltando:
        raise RespostaSuitabilityInvalida(f"faltam respostas: {sorted(faltando)}")
    sobrando = set(respostas) - ids_esperados
    if sobrando:
        raise RespostaSuitabilityInvalida(f"pergunta(s) desconhecida(s): {sorted(sobrando)}")

    total = 0
    for pergunta in perguntas:
        opcoes = pergunta.get("opcoes") or {}
        escolhida = respostas[pergunta["id"]]
        if escolhida not in opcoes:
            raise RespostaSuitabilityInvalida(
                f"opção '{escolhida}' não existe para a pergunta '{pergunta['id']}'")
        total += int(opcoes[escolhida])

    limiares = payload.get("limiares") or {}
    conservador_max = limiares.get("conservador_max")
    moderado_max = limiares.get("moderado_max")
    if conservador_max is None or moderado_max is None:
        raise RespostaSuitabilityInvalida("questionário sem limiares configurados")

    if total <= conservador_max:
        resultado = "conservador"
    elif total <= moderado_max:
        resultado = "moderado"
    else:
        resultado = "arrojado"

    return ResultadoSuitability(pontuacao=total, resultado=resultado)
