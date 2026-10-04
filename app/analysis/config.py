"""Configuração operacional do modo research — lida da policy ANALISE_RESEARCH (config-first, sem literal)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigResearch:
    max_tasks: int
    max_paralelo: int                 # reservado: v1 executa em ordem topológica, um nó por vez
    timeout_task_s: float
    max_tentativas: int
    dsl_version: str
    analise_travada_minutos: int

    @classmethod
    def from_policy(cls, payload: dict[str, Any]) -> "ConfigResearch":
        return cls(max_tasks=int(payload["max_tasks"]), max_paralelo=int(payload["max_paralelo"]),
                   timeout_task_s=float(payload["timeout_task_s"]), max_tentativas=int(payload["max_tentativas"]),
                   dsl_version=str(payload["dsl_version"]), analise_travada_minutos=int(payload["analise_travada_minutos"]))
