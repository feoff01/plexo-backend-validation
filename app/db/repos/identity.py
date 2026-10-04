"""identity.* — resolução de usuário (CLI), plano do escopo e, desde a F7, cadastro/login (sob serviço)."""
from __future__ import annotations

import uuid

from psycopg import AsyncConnection


async def resolver_user_id(conn: AsyncConnection, ref: str) -> str | None:
    """Aceita uuid ou e-mail. Só faz sentido sob papel de serviço (identity.users tem RLS users_self)."""
    try:
        uuid.UUID(ref)
        cur = await conn.execute("select id::text from identity.users where id = %s and deleted_at is null", (ref,))
    except ValueError:
        cur = await conn.execute("select id::text from identity.users where email = %s and deleted_at is null", (ref,))
    row = await cur.fetchone()
    return row[0] if row else None


async def plano_do_escopo(conn: AsyncConnection, scope_id: str) -> str:
    """Plano vigente do escopo: assinatura ativa (trialing/active/past_due) ou 'free'."""
    cur = await conn.execute(
        "select plan_code::text from billing.subscriptions "
        "where scope_id = %s and status in ('trialing','active','past_due') limit 1", (scope_id,))
    row = await cur.fetchone()
    return row[0] if row else "free"


# ------------------------------------------------------------------ F7: auth (sempre sob serviço)
async def usuario_por_email(conn: AsyncConnection, email: str) -> dict | None:
    cur = await conn.execute(
        "select id::text, password_hash, status::text, full_name from identity.users "
        "where email = %s and deleted_at is null", (email,))
    row = await cur.fetchone()
    return {"id": row[0], "password_hash": row[1], "status": row[2], "full_name": row[3]} if row else None


async def usuario_basico(conn: AsyncConnection, user_id: str) -> dict | None:
    cur = await conn.execute(
        "select id::text, email, full_name from identity.users where id = %s and deleted_at is null", (user_id,))
    row = await cur.fetchone()
    return {"id": row[0], "email": row[1], "full_name": row[2]} if row else None


async def escopos_do_usuario(conn: AsyncConnection, user_id: str) -> list[dict]:
    """Escopos onde é dono ou membro aceito não revogado — a mesma regra de identity.membro_do_escopo."""
    cur = await conn.execute(
        """select s.id::text, s.display_name, s.kind::text,
                  case when s.owner_user_id = %s then 'owner' else m.role::text end as role
             from identity.scopes s
             left join identity.scope_members m
               on m.scope_id = s.id and m.user_id = %s and m.accepted_at is not null and m.revoked_at is null
            where s.archived_at is null and (s.owner_user_id = %s or m.user_id is not null)
            order by (s.owner_user_id = %s) desc, (s.kind = 'personal') desc, s.created_at""",
        (user_id, user_id, user_id, user_id))
    return [{"id": r[0], "display_name": r[1], "kind": r[2], "role": r[3]} for r in await cur.fetchall()]


async def criar_usuario_com_escopo(conn: AsyncConnection, *, email: str, nome: str, password_hash: str,
                                   ip: str | None, user_agent: str | None,
                                   termos_versao: str, privacidade_versao: str) -> tuple[str, str]:
    """Usuário ativo (e-mail não verificado: email_verified_at fica NULL, honestamente), identidade
    'password', escopo pessoal com o usuário como owner e os dois consentimentos obrigatórios."""
    cur = await conn.execute(
        "insert into identity.users (email, full_name, password_hash, status) values (%s, %s, %s, 'active') "
        "returning id::text", (email, nome, password_hash))
    user_id = (await cur.fetchone())[0]
    await conn.execute(
        "insert into identity.auth_identities (user_id, provider, provider_uid) values (%s, 'password', %s)",
        (user_id, user_id))
    cur = await conn.execute(
        "insert into identity.scopes (kind, display_name, owner_user_id) values ('personal', 'Pessoal', %s) "
        "returning id::text", (user_id,))
    scope_id = (await cur.fetchone())[0]
    await conn.execute(
        "insert into identity.scope_members (scope_id, user_id, role, accepted_at) values (%s, %s, 'owner', now())",
        (scope_id, user_id))
    await conn.execute(
        "insert into identity.consents (user_id, kind, document_version, granted, ip_address, user_agent) "
        "values (%s, 'terms', %s, true, %s, %s), (%s, 'privacy', %s, true, %s, %s)",
        (user_id, termos_versao, ip, user_agent, user_id, privacidade_versao, ip, user_agent))
    return user_id, scope_id


async def atualizar_password_hash(conn: AsyncConnection, user_id: str, password_hash: str) -> None:
    await conn.execute("update identity.users set password_hash = %s where id = %s", (password_hash, user_id))


async def marcar_visto(conn: AsyncConnection, user_id: str) -> None:
    await conn.execute("update identity.users set last_seen_at = now() where id = %s", (user_id,))
