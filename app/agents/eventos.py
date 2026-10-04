"""Eventos que o turno emite — consumidos pelo SSE (API) e pela CLI. Nome estável = contrato."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Evento:
    @property
    def nome(self) -> str:  # 'ToolDone' -> 'tool_done'
        s = type(self).__name__
        return "".join(("_" + c.lower()) if c.isupper() else c for c in s).lstrip("_")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Routed(Evento):
    agent_code: str
    mode: str                        # forced | chip | auto | continuacao
    confidence: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Clarify(Evento):
    """Roteador sem confiança suficiente: devolve opções, sem abrir conversa nem consumir cota."""
    mensagem: str
    opcoes: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Status(Evento):
    fase: str


@dataclass(frozen=True)
class ToolDone(Evento):
    code: str
    execution_id: str
    cache_hit: bool


@dataclass(frozen=True)
class Bloco(Evento):
    """F11: representação rica (gráfico/tabela/indicadores) derivada do output da tool — chega antes da leitura."""
    execution_id: str
    bloco: dict[str, Any]


@dataclass(frozen=True)
class Delta(Evento):
    texto: str


@dataclass(frozen=True)
class Replace(Evento):
    texto: str


@dataclass(frozen=True)
class HandoffSuggested(Evento):
    para: str
    motivo: str


@dataclass(frozen=True)
class Paywall(Evento):
    gate_code: str
    mensagem: str


@dataclass(frozen=True)
class Erro(Evento):
    tipo: str
    mensagem: str


@dataclass(frozen=True)
class AnalysisQueued(Evento):
    """Modo research (F6): a análise foi registrada e enfileirada; o relatório chega depois, na mesma conversa."""
    analysis_id: str
    conversation_id: str
    message_id: str


@dataclass(frozen=True)
class Proposta(Evento):
    """F14: o Contexto notou uma mudança no meio da conversa e pergunta se pode registrar.

    Chega DEPOIS da resposta do agente, de propósito: o card é um adendo à conversa, não a
    interrompe. `precisa_classificar_natureza` diz à tela para oferecer as três saídas —
    "passou a ser recorrente", "foi pontual", "ainda não sei" — em vez de sim/não.
    """
    proposta: dict[str, Any]


@dataclass(frozen=True)
class Done(Evento):
    conversation_id: str
    message_id: str
    cited_refs: list[dict[str, Any]] = field(default_factory=list)
