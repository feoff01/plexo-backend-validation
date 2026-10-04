"""engine.policy_versions — leitura da vigente e publicação de nova versão (sempre draft).

Aprovação de policy metodológica segue o fluxo de compliance (C6); policies OPERACIONAIS
(LLM_PRICING, AGENT_ROUTING, ...) são lidas independentemente do status, como AGENT_QUOTAS.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class PolicyRow:
    id: str
    code: str
    version: int
    payload: dict[str, Any]
    compliance_status: str
    content_hash: str


_COLS = "id::text, code, version, payload, compliance_status::text, content_hash"


async def get_current(conn: AsyncConnection, code: str) -> PolicyRow | None:
    cur = await conn.execute(
        f"select {_COLS} from engine.policy_versions where code = %s and effective_to is null", (code,))
    row = await cur.fetchone()
    return PolicyRow(*row) if row else None


async def set_policy(conn: AsyncConnection, code: str, payload: dict[str, Any],
                     created_by: str | None = None) -> PolicyRow:
    """Fecha a vigente (effective_to) e insere version+1 em draft. Respeita policy_one_current.

    effective_to usa clock_timestamp(): dentro de uma transação now() é constante e a CHECK
    `effective_to > effective_from` falharia para uma versão criada na mesma transação.
    """
    cur = await conn.execute(
        "update engine.policy_versions set effective_to = greatest(clock_timestamp(), effective_from + interval '1 microsecond') "
        "where code = %s and effective_to is null returning version", (code,))
    anterior = await cur.fetchone()
    versao = (anterior[0] + 1) if anterior else 1
    cur = await conn.execute(
        "insert into engine.policy_versions (code, version, payload, compliance_status, created_by) "
        f"values (%s, %s, %s, 'draft', %s) returning {_COLS}",
        (code, versao, Jsonb(payload), created_by))
    return PolicyRow(*(await cur.fetchone()))


async def approve_current(conn: AsyncConnection, code: str, approved_by: str) -> PolicyRow:
    """Aprova a versão VIGENTE (compliance). Necessário antes de qualquer uso client-facing
    (gates de engine.runs e tools.tool_executions). Auditado em audit.activity_log."""
    from app.db.errors import PolicyNotFound
    from app.db.repos import audit

    atual = await get_current(conn, code)
    if atual is None:
        raise PolicyNotFound(code)
    if atual.compliance_status == "approved":
        return atual
    cur = await conn.execute(
        "update engine.policy_versions set compliance_status = 'approved', "
        f"approved_at = clock_timestamp(), approved_by = %s where id = %s returning {_COLS}",
        (approved_by, atual.id))
    aprovada = PolicyRow(*(await cur.fetchone()))
    await audit.registrar(conn, actor_kind="admin", actor_user_id=approved_by, action="policy.approved",
                          object_kind="policy_version", object_id=aprovada.id,
                          details={"code": code, "version": aprovada.version,
                                   "content_hash": aprovada.content_hash})
    return aprovada


async def listar(conn: AsyncConnection) -> list[PolicyRow]:
    cur = await conn.execute(
        f"select {_COLS} from engine.policy_versions where effective_to is null order by code")
    return [PolicyRow(*r) for r in await cur.fetchall()]


def payload_json(row: PolicyRow) -> str:
    return json.dumps(row.payload, ensure_ascii=False, indent=2, sort_keys=True)
