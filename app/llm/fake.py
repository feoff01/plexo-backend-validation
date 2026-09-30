"""LLM roteirizado para testes: devolve respostas na ordem, guarda as requisições recebidas.

F9: `chat_stream` reparte o texto da resposta roteirizada em `trechos` pedaços (o último trecho traz a
resposta completa) — o turno é exercitado exatamente como com o provedor real em modo stream."""
from __future__ import annotations

from typing import AsyncIterator

from app.llm.client import ChatRequest, ChatResponse, Trecho


class FakeLLM:
    provider = "fake"

    def __init__(self, respostas: list[ChatResponse], trechos: int = 1):
        self._respostas = list(respostas)
        self._trechos = max(1, int(trechos))
        self.requisicoes: list[ChatRequest | None] = []
        self.streams = 0

    def _proxima(self, request: ChatRequest | None) -> ChatResponse:
        self.requisicoes.append(request)
        if not self._respostas:
            raise AssertionError("FakeLLM sem respostas roteirizadas para esta chamada")
        return self._respostas.pop(0)

    async def chat(self, request: ChatRequest | None) -> ChatResponse:
        return self._proxima(request)

    async def chat_stream(self, request: ChatRequest | None) -> AsyncIterator[Trecho]:
        resp = self._proxima(request)
        self.streams += 1
        texto = resp.text or ""
        if texto:
            tamanho = max(1, -(-len(texto) // self._trechos))      # teto da divisão
            for i in range(0, len(texto), tamanho):
                yield Trecho(texto=texto[i:i + tamanho])
        yield Trecho(final=resp)
