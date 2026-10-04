"""Roteador do Copiloto (padrão C6): chip → sem LLM; dropdown → forçado; senão intenção por LLM.

Confiança abaixo de AGENT_ROUTING.min_confidence vira Clarify — sem conversa, sem cota.
O prompt do roteador é versionado/aprovado como qualquer outro (llm.prompt_versions:
'copiloto.router'); a escolha fica registrada em conversations.metadata.routing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_CHIPS_PATH = Path(__file__).resolve().parent.parent / "config" / "chips.yaml"


@dataclass(frozen=True)
class Chip:
    id: str
    rotulo: str
    agente: str
    texto: str
    modo: str = "standard"        # research = análise aprofundada (F6), só para o analista


@lru_cache
def chips() -> dict[str, Chip]:
    data = yaml.safe_load(_CHIPS_PATH.read_text(encoding="utf-8")) or {}
    return {c["id"]: Chip(**c) for c in data.get("chips", [])}


def chips_lista() -> list[Chip]:
    """Na ordem do YAML (a tela respeita a ordem editorial do arquivo)."""
    return list(chips().values())


@dataclass(frozen=True)
class Rota:
    agent_code: str
    mode: str                    # forced | chip | auto
    confidence: float | None = None
    reason: str | None = None
    texto: str | None = None     # chip pode sugerir o texto da pergunta
    model_call_id: str | None = None
    modo: str = "standard"        # standard | research (vem do chip)


# [F15] `GET /chips` põe as perguntas dinâmicas (`falta:<fact_key>`, de
# `app/agents/perguntas.py`) NA FRENTE dos chips do YAML, e este roteador só conhecia o
# YAML. O primeiro botão da tela inicial de qualquer cliente com fato faltando devolvia
# `chip_desconhecido` e não abria conversa nenhuma — e quem tem fato faltando é justamente
# o cliente NOVO, então o atalho de onboarding inteiro estava morto. Achado no
# /code-review de 2026-08-30; a costura era testada só de um lado
# (`test_f7_endpoints.py` afirmava que os ids do YAML existem).
PREFIXO_PERGUNTA_DINAMICA = "falta:"


def rota_por_chip(chip_id: str) -> Rota | None:
    if chip_id.startswith(PREFIXO_PERGUNTA_DINAMICA):
        # O TEXTO vem do cliente — é o mesmo que ele poderia digitar no campo, então não há
        # superfície nova. O que o chip decide, e o que fica no servidor, é o AGENTE:
        # `Pergunta.para_chip()` sempre manda ao Assessor, e é ele que se fixa aqui.
        return Rota(agent_code="assessor", mode="chip", texto=None, modo="standard")
    chip = chips().get(chip_id)
    if chip is None:
        return None
    return Rota(agent_code=chip.agente, mode="chip", texto=chip.texto, modo=chip.modo)


MENSAGEM_CLARIFY_PADRAO = "Não tenho certeza de qual agente atende melhor — escolha um:"


@dataclass(frozen=True)
class Intencao:
    agent_code: str | None
    confidence: float
    reason: str
    resposta_curta: str | None = None   # F8: saudação/meta/fora de finanças → texto curto sem abrir conversa


def parse_intencao(texto: str) -> Intencao:
    """Extrai {agent_code, confidence, reason, resposta_curta} do output do LLM (tolerante a cerca de código)."""
    bruto = texto.strip()
    m = re.search(r"\{.*\}", bruto, re.S)
    if not m:
        return Intencao(None, 0.0, "sem JSON na resposta do roteador")
    try:
        obj = json.loads(m.group(0))
        curta = obj.get("resposta_curta")
        return Intencao(obj.get("agent_code") or None, float(obj.get("confidence") or 0.0),
                        str(obj.get("reason") or ""), str(curta) if curta else None)
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return Intencao(None, 0.0, "JSON inválido do roteador")
