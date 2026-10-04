"""audit.activity_log — trilha 'quem fez o quê' (append-only, particionada por mês)."""
from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


async def registrar(conn: AsyncConnection, *, actor_kind: str, action: str,
                    object_kind: str | None = None, object_id: str | None = None,
                    actor_user_id: str | None = None, scope_id: str | None = None,
                    details: dict[str, Any] | None = None, request_id: str | None = None,
                    ip_address: str | None = None, user_agent: str | None = None) -> None:
    await conn.execute(
        "insert into audit.activity_log (actor_kind, actor_user_id, scope_id, action, object_kind, object_id, details, "
        "request_id, ip_address, user_agent) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (actor_kind, actor_user_id, scope_id, action, object_kind, object_id, Jsonb(details or {}), request_id,
         ip_address, user_agent))
