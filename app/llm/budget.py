"""Orçamento por turno — números vêm de LLM_BUDGETS (policy), nunca do código.

Payload esperado (17/19 seeds + v2): max_model_calls_por_turno, max_output_tokens_por_turno,
max_usd_por_turno (opcional), max_usd_por_analise, max_replans_por_analise.
Estouro → BudgetExceeded → o orquestrador registra guardrail 'limite_orcamento_llm'.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.client import ChatResponse


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class TurnBudget:
    max_model_calls: int
    max_output_tokens: int
    max_usd: float | None = None
    # Piso reservado para a REDAÇÃO final (migration 51). Enquanto o turno encadeia tools, o
    # orçamento oferecido é `restante − reserva`; a chamada que redige recebe o restante
    # inteiro. Sem isso, o turno com mais medições era o que ficava sem tokens para responder.
    reserva_sintese: int = 0
    chamadas: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    historico: list[str] = field(default_factory=list)

    @classmethod
    def from_policy(cls, payload: dict[str, Any]) -> "TurnBudget":
        return cls(max_model_calls=int(payload["max_model_calls_por_turno"]),
                   max_output_tokens=int(payload["max_output_tokens_por_turno"]),
                   reserva_sintese=int(payload.get("reserva_para_sintese_tokens", 0)),
                   max_usd=float(payload["max_usd_por_turno"]) if payload.get("max_usd_por_turno") is not None else None)

    def reservar_chamada(self, purpose: str) -> None:
        if self.chamadas + 1 > self.max_model_calls:
            raise BudgetExceeded(f"max_model_calls_por_turno={self.max_model_calls} atingido ao pedir '{purpose}'")
        self.chamadas += 1
        self.historico.append(purpose)

    def tokens_restantes(self) -> int:
        return max(self.max_output_tokens - self.output_tokens, 0)

    def tokens_para(self, purpose: str) -> int:
        """Quanto oferecer a esta chamada.

        `sintese` recebe tudo o que resta. Qualquer outra finalidade — parametrizar tool,
        reparar marcação — recebe o restante MENOS a reserva, para que sempre sobre com que
        escrever. Se a reserva já não couber, devolve pelo menos 1 token: quem decide
        interromper o turno é `registrar`, levantando `BudgetExceeded`, e não um teto zerado
        que faria o provedor devolver texto vazio sem explicação.
        """
        restante = self.tokens_restantes()
        if purpose == "sintese":
            return restante
        return max(restante - self.reserva_sintese, 1)

    def registrar(self, resp: ChatResponse, custo_usd: float | None = None) -> None:
        self.output_tokens += resp.usage.output_tokens
        if custo_usd:
            self.usd += custo_usd
        if self.output_tokens > self.max_output_tokens:
            raise BudgetExceeded(f"max_output_tokens_por_turno={self.max_output_tokens} excedido ({self.output_tokens})")
        if self.max_usd is not None and self.usd > self.max_usd:
            raise BudgetExceeded(f"max_usd_por_turno={self.max_usd} excedido ({self.usd:.4f})")
