"""identity.sessions / identity.login_attempts — SQL fino, sempre sob papel de serviço."""
from __future__ import annotations

from psycopg import AsyncConnection


async def criar(conn: AsyncConnection, *, user_id: str, scope_id: str, token_hash: str,
                ttl_h: int, ip: str | None, user_agent: str | None) -> str:
    cur = await conn.execute(
        "insert into identity.sessions (user_id, scope_id, token_hash, expires_at, ip_address, user_agent) "
        "values (%s, %s, %s, now() + make_interval(hours => %s), %s, %s) returning id::text",
        (user_id, scope_id, token_hash, ttl_h, ip, user_agent))
    return (await cur.fetchone())[0]


async def autenticar(conn: AsyncConnection, token_hash: str):
    cur = await conn.execute(
        "select session_id::text, user_id::text, scope_id::text, expires_at, last_seen_at "
        "from identity.autenticar_sessao(%s)", (token_hash,))
    return await cur.fetchone()


async def tocar(conn: AsyncConnection, session_id: str, ttl_h: int) -> None:
    await conn.execute(
        "update identity.sessions set last_seen_at = now(), expires_at = now() + make_interval(hours => %s) "
        "where id = %s and revoked_at is null", (ttl_h, session_id))


async def revogar(conn: AsyncConnection, token_hash: str, motivo: str) -> None:
    await conn.execute(
        "update identity.sessions set revoked_at = now(), revoked_reason = %s "
        "where token_hash = %s and revoked_at is null", (motivo, token_hash))


async def revogar_todas_do_usuario(conn: AsyncConnection, user_id: str, motivo: str) -> int:
    cur = await conn.execute(
        "update identity.sessions set revoked_at = now(), revoked_reason = %s "
        "where user_id = %s and revoked_at is null", (motivo, user_id))
    return cur.rowcount


async def trocar_escopo(conn: AsyncConnection, session_id: str, user_id: str, scope_id: str) -> bool:
    cur = await conn.execute(
        "update identity.sessions set scope_id = %s "
        "where id = %s and revoked_at is null and identity.membro_do_escopo(%s, %s)",
        (scope_id, session_id, user_id, scope_id))
    return cur.rowcount == 1


async def registrar_tentativa(conn: AsyncConnection, *, email_hash: str, ip: str | None,
                              ok: bool, reason: str | None) -> None:
    await conn.execute(
        "insert into identity.login_attempts (email_hash, ip_address, ok, reason) values (%s, %s, %s, %s)",
        (email_hash, ip, ok, reason))


async def falhas_recentes(conn: AsyncConnection, *, email_hash: str, ip: str | None, janela_min: int) -> tuple[int, int]:
    """(falhas por e-mail, falhas por ip) na janela."""
    cur = await conn.execute(
        "select count(*) filter (where email_hash = %s), count(*) filter (where ip_address = %s::inet) "
        "from identity.login_attempts where not ok and occurred_at > now() - make_interval(mins => %s)",
        (email_hash, ip, janela_min))
    row = await cur.fetchone()
    return int(row[0]), int(row[1])
