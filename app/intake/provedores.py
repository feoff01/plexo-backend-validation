"""Provedores plugáveis do intake — transcrição de áudio e leitura de arquivo.

Decisão da etapa (2026-08-31): a ESTRUTURA nasce agora; o serviço concreto (Whisper,
Deepgram, parser de PDF…) entra na F21d — o usuário escolhe o microserviço e pluga a
API key. Até lá as fábricas devolvem None e a submissão fica HONESTAMENTE em
'aguardando_provedor' (nunca 500, nunca texto inventado) — o mesmo espírito de
"dado insuficiente não é exceção" das tools do Analista.
"""
from __future__ import annotations

from typing import Protocol


class ProvedorIndisponivel(RuntimeError):
    """Nenhum provedor configurado para este tipo de mídia."""


class Transcritor(Protocol):
    async def transcrever(self, media: bytes, mime: str) -> str: ...


class ExtratorDeArquivo(Protocol):
    async def extrair_texto(self, media: bytes, mime: str) -> str: ...


class FakeTranscritor:
    """Transcritor roteirizado para testes — devolve sempre o texto dado."""

    def __init__(self, texto: str):
        self._texto = texto

    async def transcrever(self, media: bytes, mime: str) -> str:  # noqa: ARG002
        return self._texto


class FakeExtratorDeArquivo:
    """Extrator de arquivo roteirizado para testes."""

    def __init__(self, texto: str):
        self._texto = texto

    async def extrair_texto(self, media: bytes, mime: str) -> str:  # noqa: ARG002
        return self._texto


def transcritor_configurado(settings) -> Transcritor | None:  # noqa: ARG001
    """F21d pluga o provedor real aqui (lendo settings). Hoje: nenhum no stack."""
    return None


def extrator_arquivo_configurado(settings) -> ExtratorDeArquivo | None:  # noqa: ARG001
    """F21d pluga o provedor real aqui (lendo settings). Hoje: nenhum no stack."""
    return None
