"""Adaptador DeepSeek — API compatível com OpenAI (function calling, JSON, cache automático de prefixo).

Decisão de 2026-08-23: provedor primário por custo. O id do modelo vem de LLM_MODEL (config).
Mapeamento de nomes: tools.tools.code usa ponto ('planejamento.projecao_objetivo'); nomes de função
OpenAI-compatible só aceitam [A-Za-z0-9_-] → '.' vira '__' na ida e volta na leitura.
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from openai import APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.config.settings import Settings
from app.llm.client import ChatRequest, ChatResponse, ProviderUnavailable, ToolCall, Trecho, Usage


def nome_para_llm(code: str) -> str:
    return code.replace(".", "__")


def code_de_nome_llm(nome: str) -> str:
    return nome.replace("__", ".")


class DeepSeekClient:
    provider = "deepseek"

    def __init__(self, settings: Settings):
        if settings.llm_api_key is None:
            raise ProviderUnavailable("LLM_API_KEY/DEEPSEEK_API_KEY ausente no ambiente")
        self._model = settings.llm_model
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,   # só 429/5xx/timeout — o SDK já faz backoff
        )

    @property
    def model(self) -> str:
        return self._model

    @staticmethod
    def _mensagens(req: ChatRequest) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in req.messages:
            d: dict[str, Any] = {"role": m.role}
            if m.content is not None:
                d["content"] = m.content
            if m.role == "assistant" and m.tool_calls:
                d["tool_calls"] = [{
                    "id": tc.id, "type": "function",
                    "function": {"name": nome_para_llm(tc.name), "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                } for tc in m.tool_calls]
                d.setdefault("content", None)
                if m.reasoning_content:      # modo thinking: o raciocínio volta junto da mensagem com tool_calls
                    d["reasoning_content"] = m.reasoning_content
            if m.role == "tool":
                d["tool_call_id"] = m.tool_call_id
                if m.name:
                    d["name"] = nome_para_llm(m.name)
            out.append(d)
        return out

    @staticmethod
    def _tools(req: ChatRequest) -> list[dict[str, Any]] | None:
        if not req.tools:
            return None
        return [{"type": "function", "function": {
            "name": nome_para_llm(t.name), "description": t.description, "parameters": t.parameters}}
            for t in req.tools]

    @staticmethod
    def _tool_choice(req: ChatRequest):
        if not req.tools:
            return None
        if isinstance(req.tool_choice, dict):
            return {"type": "function", "function": {"name": nome_para_llm(req.tool_choice["name"])}}
        return req.tool_choice

    def _kwargs(self, req: ChatRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self._model, "messages": self._mensagens(req)}
        if (tools := self._tools(req)):
            kwargs["tools"] = tools
            kwargs["tool_choice"] = self._tool_choice(req)
        if req.response_format:
            kwargs["response_format"] = req.response_format
        if req.max_output_tokens:
            kwargs["max_tokens"] = req.max_output_tokens
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        return kwargs

    @staticmethod
    def _traduzir_erro(e: Exception) -> ProviderUnavailable:
        if isinstance(e, APITimeoutError):
            return ProviderUnavailable(f"timeout no provedor: {type(e).__name__}")
        if isinstance(e, RateLimitError):
            return ProviderUnavailable("limite de taxa do provedor esgotado após retries")
        corpo = ""
        try:
            corpo = str(getattr(e, "body", ""))[:300]
        except Exception:
            pass
        return ProviderUnavailable(f"provedor respondeu HTTP {getattr(e, 'status_code', '?')}: {corpo}")

    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[Trecho]:
        """F9: `stream=True` com usage no último chunk. Texto vira `Trecho(texto)` ao vivo; tool_calls são
        acumuladas por índice e só aparecem no `Trecho(final)`. `reasoning_content` é acumulado e devolvido
        no final (volta ao provedor na próxima chamada), nunca como texto."""
        kwargs = self._kwargs(req)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        t0 = time.perf_counter()
        texto: list[str] = []
        raciocinio: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish = "stop"
        usage_bruto = None
        modelo = self._model
        request_id = None
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                modelo = getattr(chunk, "model", None) or modelo
                request_id = getattr(chunk, "id", None) or request_id
                if getattr(chunk, "usage", None) is not None:
                    usage_bruto = chunk.usage
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if choice.finish_reason:
                    finish = choice.finish_reason
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    raciocinio.append(rc)
                if delta.content:
                    texto.append(delta.content)
                    yield Trecho(texto=delta.content)
                for tc in (delta.tool_calls or []):
                    atual = calls.setdefault(tc.index, {"id": None, "name": "", "arguments": ""})
                    if tc.id:
                        atual["id"] = tc.id
                    if tc.function is not None:
                        if tc.function.name:
                            atual["name"] += tc.function.name
                        if tc.function.arguments:
                            atual["arguments"] += tc.function.arguments
        except (APITimeoutError, RateLimitError, APIStatusError) as e:
            raise self._traduzir_erro(e) from e
        latency = int((time.perf_counter() - t0) * 1000)
        tool_calls: list[ToolCall] = []
        for idx in sorted(calls):
            c = calls[idx]
            try:
                args = json.loads(c["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": c["arguments"]}
            tool_calls.append(ToolCall(id=c["id"] or f"call_{idx}", name=code_de_nome_llm(c["name"]), arguments=args))
        yield Trecho(final=ChatResponse(
            text="".join(texto), tool_calls=tool_calls, usage=self._usage(usage_bruto),
            finish_reason=finish, model=modelo, provider=self.provider, latency_ms=latency,
            provider_request_id=request_id, reasoning_content="".join(raciocinio) or None))

    @staticmethod
    def _usage(u) -> Usage:
        cached = 0
        if u is not None:
            cached = getattr(u, "prompt_cache_hit_tokens", None) or 0
            det = getattr(u, "prompt_tokens_details", None)
            if not cached and det is not None:
                cached = getattr(det, "cached_tokens", 0) or 0
        return Usage(input_tokens=u.prompt_tokens if u else 0, cached_tokens=int(cached),
                     output_tokens=u.completion_tokens if u else 0)

    async def chat(self, req: ChatRequest) -> ChatResponse:
        kwargs: dict[str, Any] = {"model": self._model, "messages": self._mensagens(req)}
        if (tools := self._tools(req)):
            kwargs["tools"] = tools
            kwargs["tool_choice"] = self._tool_choice(req)
        if req.response_format:
            kwargs["response_format"] = req.response_format
        if req.max_output_tokens:
            kwargs["max_tokens"] = req.max_output_tokens
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        t0 = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except APITimeoutError as e:
            raise ProviderUnavailable(f"timeout no provedor: {type(e).__name__}") from e
        except RateLimitError as e:
            raise ProviderUnavailable("limite de taxa do provedor esgotado após retries") from e
        except APIStatusError as e:
            # 4xx de conteúdo não se repete; sobe com o corpo do erro (nunca contém a chave)
            corpo = ""
            try:
                corpo = str(e.body)[:300]
            except Exception:
                pass
            raise ProviderUnavailable(f"provedor respondeu HTTP {e.status_code}: {corpo}") from e
        latency = int((time.perf_counter() - t0) * 1000)
        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=code_de_nome_llm(tc.function.name), arguments=args))
        u = resp.usage
        cached = 0
        if u is not None:
            cached = getattr(u, "prompt_cache_hit_tokens", None) or 0
            det = getattr(u, "prompt_tokens_details", None)
            if not cached and det is not None:
                cached = getattr(det, "cached_tokens", 0) or 0
        usage = Usage(input_tokens=u.prompt_tokens if u else 0, cached_tokens=int(cached),
                      output_tokens=u.completion_tokens if u else 0)
        return ChatResponse(
            text=msg.content or "", tool_calls=tool_calls, usage=usage,
            finish_reason=choice.finish_reason or "stop", model=resp.model or self._model,
            provider=self.provider, latency_ms=latency, provider_request_id=getattr(resp, "id", None),
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )
