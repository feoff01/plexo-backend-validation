"""Identidade da requisição (F7): cookie de sessão → identity.autenticar_sessao → (user_id, scope_id).

Contrato interno inalterado desde a v1: quem consome recebe `Identidade(user_id, scope_id)` e abre
`db.app_session(...)` — o isolamento real continua sendo o RLS. O que mudou é a porta:
  1. cookie `plx_sessao` (httpOnly) → sessão viva, usuário ativo, membership válida no escopo ativo;
     em método mutador, a origem (`Origin`/`Sec-Fetch-Site`) tem de ser do frontend (CSRF).
  2. headers X-Plexo-User-Id / X-Plexo-Scope-Id — SÓ com `Settings.auth_headers_dev=True`
     (dev e testes das fases anteriores). Em produção o default é desligado.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.auth import sessoes

_MUTADORES = {"POST", "PUT", "PATCH", "DELETE"}
_SITE_OK = {"same-origin", "same-site", "none"}


@dataclass(frozen=True)
class Identidade:
    user_id: str
    scope_id: str
    session_id: str | None = None      # None = headers de dev
    via: str = "cookie"                # cookie | headers


def verificar_origem(request: Request) -> None:
    """CSRF: com cookie, uma mutação só entra se veio do próprio frontend.
    Sem `Origin` nem `Sec-Fetch-Site` (cliente não-browser) passa — o cookie httpOnly não viaja
    em requisição forjada de outro site sem que um desses headers venha junto."""
    settings = request.app.state.settings
    origem = request.headers.get("origin")
    if origem is not None:
        if origem.rstrip("/") not in {o.rstrip("/") for o in settings.cors_origins}:
            raise HTTPException(status_code=403, detail="origem não permitida")
        return
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in _SITE_OK:
        raise HTTPException(status_code=403, detail="origem não permitida")


def _por_headers(request: Request) -> Identidade:
    user = request.headers.get("X-Plexo-User-Id")
    scope = request.headers.get("X-Plexo-Scope-Id")
    if not user or not scope:
        raise HTTPException(status_code=401, detail="não autenticado")
    try:
        uuid.UUID(user), uuid.UUID(scope)
    except ValueError:
        raise HTTPException(status_code=401, detail="identidade inválida")
    return Identidade(user_id=user, scope_id=scope, via="headers")


async def identidade(request: Request) -> Identidade:
    settings = request.app.state.settings
    token = request.cookies.get(settings.cookie_nome)
    if token:
        sessao = await sessoes.autenticar(request.app.state.db, token)
        if sessao is None:
            raise HTTPException(status_code=401, detail="sessão inválida ou expirada")
        if request.method in _MUTADORES:
            verificar_origem(request)
        if sessao.precisa_renovar(settings.sessao_renovar_apos_min):
            await sessoes.tocar(request.app.state.db, settings, sessao.id)
        return Identidade(user_id=sessao.user_id, scope_id=sessao.scope_id, session_id=sessao.id, via="cookie")
    if settings.auth_headers_dev:
        return _por_headers(request)
    raise HTTPException(status_code=401, detail="não autenticado")
