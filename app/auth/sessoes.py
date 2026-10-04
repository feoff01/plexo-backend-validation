"""Sessão opaca: token aleatório no cookie, sha256 no banco, expiração deslizante.

Todas as funções abrem `service_session()` — a tabela é fechada para plexo_app (RLS + REVOKE).
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config.settings import Settings
from app.db.repos import sessoes as repo


@dataclass(frozen=True)
class Sessao:
    id: str
    user_id: str
    scope_id: str
    expires_at: datetime
    last_seen_at: datetime

    def precisa_renovar(self, apos_min: int) -> bool:
        return datetime.now(timezone.utc) - self.last_seen_at >= timedelta(minutes=apos_min)


def novo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def hash_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def cookie_params(settings: Settings) -> dict:
    return {"key": settings.cookie_nome, "httponly": True, "secure": settings.cookie_secure,
            "samesite": settings.cookie_samesite, "path": "/", "max_age": settings.sessao_ttl_h * 3600,
            "domain": settings.cookie_domain}


async def criar(db, settings: Settings, *, user_id: str, scope_id: str,
                ip: str | None, user_agent: str | None) -> str:
    """Grava a sessão e devolve o token em claro (vai só para o cookie)."""
    token = novo_token()
    async with db.service_session() as conn:
        await repo.criar(conn, user_id=user_id, scope_id=scope_id, token_hash=hash_token(token),
                         ttl_h=settings.sessao_ttl_h, ip=ip, user_agent=user_agent)
    return token


async def autenticar(db, token: str) -> Sessao | None:
    if not token or len(token) > 128:
        return None
    async with db.service_session() as conn:
        row = await repo.autenticar(conn, hash_token(token))
    return Sessao(*row) if row else None


async def tocar(db, settings: Settings, session_id: str) -> None:
    async with db.service_session() as conn:
        await repo.tocar(conn, session_id, settings.sessao_ttl_h)


async def revogar(db, token: str, motivo: str = "logout") -> None:
    async with db.service_session() as conn:
        await repo.revogar(conn, hash_token(token), motivo)


async def trocar_escopo(db, session_id: str, user_id: str, scope_id: str) -> bool:
    """Só troca se o usuário for membro do escopo (identity.membro_do_escopo)."""
    async with db.service_session() as conn:
        return await repo.trocar_escopo(conn, session_id, user_id, scope_id)
