"""Interface única de LLM. Trocar de provedor é trocar a classe, não o orquestrador.

Regra de ouro (19_llm.sql): tokens/custo vêm do `usage` da RESPOSTA DO PROVEDOR; contagem local
serve só para estimativa preflight. `model` é o id faturável e NUNCA entra em regra de domínio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_tokens: int = 0      # subconjunto de input_tokens servido pelo cache de prefixo
    output_tokens: int = 0


@dataclass(frozen=True)
class ToolDef:
    """Definição de função para o LLM — gerada do registro de tools (param_schema), nunca copiada no prompt."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: str                               # system | user | assistant | tool
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None         # role=tool: a chamada que este resultado responde
    name: str | None = None
    reasoning_content: str | None = None    # provedores com "thinking" exigem devolver o raciocínio junto das tool_calls


@dataclass(frozen=True)
class CallMeta:
    """Proveniência gravada em llm.model_calls."""
    purpose: str                            # llm.call_purpose
    agent_code: str | None = None
    scope_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    prompt_version_id: str | None = None
    analysis_id: str | None = None


@dataclass
class ChatRequest:
    messages: list[Message]
    metadata: CallMeta
    tools: list[ToolDef] = field(default_factory=list)
    tool_choice: str | dict[str, Any] = "auto"      # 'auto' | 'none' | 'required' | {"name": ...}
    response_format: dict[str, Any] | None = None  # {"type": "json_object"} | {"type": "json_schema", ...}
    max_output_tokens: int | None = None
    temperature: float | None = None


@dataclass
class ChatResponse:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    finish_reason: str
    model: str
    provider: str
    latency_ms: int
    status: str = "succeeded"              # succeeded | failed | timeout | refused
    error_code: str | None = None
    provider_request_id: str | None = None
    reasoning_content: str | None = None    # raciocínio do provedor (thinking); reenviado na síntese, nunca ao cliente

    @classmethod
    def simples(cls, text: str, *, model: str, provider: str) -> "ChatResponse":
        return cls(text=text, tool_calls=[], usage=Usage(1, 0, 1), finish_reason="stop",
                   model=model, provider=provider, latency_ms=0)


@dataclass(frozen=True)
class Trecho:
    """Um pedaço do stream (F9): `texto` = delta de conteúdo para o cliente; `final` = a resposta completa
    (usage, tool_calls, reasoning) — sempre o último trecho. Reasoning nunca vira `texto`."""
    texto: str | None = None
    final: ChatResponse | None = None


class LLMClient(Protocol):
    provider: str

    async def chat(self, request: ChatRequest) -> ChatResponse: ...


async def streamar(llm: LLMClient, request: ChatRequest) -> AsyncIterator[Trecho]:
    """Stream quando o provedor sabe (`chat_stream`); senão um único trecho final (comportamento antigo)."""
    fn = getattr(llm, "chat_stream", None)
    if fn is None:
        yield Trecho(final=await llm.chat(request))
        return
    async for trecho in fn(request):
        yield trecho


class ProviderUnavailable(RuntimeError):
    """Provedor falhou após retries/timeout — o turno avisa e não grava resposta de agente."""
