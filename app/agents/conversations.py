"""agents.conversations / agents.messages — repositório do turno (SQL fino; regras são do banco)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class ConversaRow:
    id: str
    agent_code: str
    plan_code_at_start: str
    status: str
    message_count: int


async def travar(conn: AsyncConnection, conversation_id: str) -> ConversaRow | None:
    """Lock por conversa: serializa turnos concorrentes (advisory + FOR UPDATE)."""
    await conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (conversation_id,))
    cur = await conn.execute(
        "select id::text, agent_code::text, plan_code_at_start::text, status::text, message_count "
        "from agents.conversations where id = %s for update", (conversation_id,))
    row = await cur.fetchone()
    return ConversaRow(*row) if row else None


async def reabrir(conn: AsyncConnection, conversation_id: str) -> bool:
    """Escrever numa conversa encerrada a REABRE, em vez de recusar o turno.

    Antes, trinta minutos de silêncio bastavam para o job de inatividade encerrar a conversa,
    e a partir daí ela era só-leitura para sempre: escrever nela devolvia 422. Não havia
    caminho de volta em lugar nenhum do produto. Quem voltasse no dia seguinte para continuar
    de onde parou tinha que começar do zero — e perdia o contexto que a conversa carregava.

    `processada` também reabre: já foi extraída, e a extração passou a ser incremental
    (registra até que `seq` leu), então retomar não reprocessa o que já foi lido.
    `arquivada` não reabre — arquivar é um ato deliberado de quem arquivou.
    """
    cur = await conn.execute(
        "update agents.conversations set status = 'aberta', ended_at = null "
        "where id = %s and status in ('encerrada', 'processada') returning id",
        (conversation_id,))
    return await cur.fetchone() is not None


async def criar(conn: AsyncConnection, *, scope_id: str, user_id: str, agent_code: str,
                plan_code: str, metadata: dict[str, Any] | None = None) -> str:
    cur = await conn.execute(
        "insert into agents.conversations (scope_id, user_id, agent_code, plan_code_at_start, metadata) "
        "values (%s, %s, %s::agents.agent_code, %s::billing.plan_code, %s) returning id::text",
        (scope_id, user_id, agent_code, plan_code, Jsonb(metadata or {})))
    return (await cur.fetchone())[0]


async def inserir_mensagem(conn: AsyncConnection, *, conversation_id: str, scope_id: str, seq: int,
                           role: str, content: str | None = None, content_json: dict | None = None,
                           tool_execution_id: str | None = None, model_call_id: str | None = None,
                           cited_refs: list[dict] | None = None) -> str:
    cur = await conn.execute(
        """insert into agents.messages
             (conversation_id, scope_id, seq, role, content, content_json,
              tool_execution_id, model_call_id, cited_refs)
           values (%s, %s, %s, %s::agents.message_role, %s, %s, %s, %s, %s)
           returning id::text""",
        (conversation_id, scope_id, seq, role, content,
         Jsonb(content_json) if content_json is not None else None,
         tool_execution_id, model_call_id, Jsonb(cited_refs or [])))
    return (await cur.fetchone())[0]


async def historico(conn: AsyncConnection, conversation_id: str, limite: int | None,
                    max_chars_resultado: int | None = None) -> list[tuple[str, str]]:
    """Histórico para o LLM. F8: a mensagem do agente que veio de uma tool leva os dados medidos
    (`output_payload` da execução, truncado a `max_chars_resultado`) — sem isso o follow-up
    ("e se fossem 20 anos?") perdia os números. Leitura pela sessão (RLS)."""
    sql = ("select m.role::text, coalesce(m.content, m.content_json::text), t.output_payload "
           "from agents.messages m left join tools.tool_executions t on t.id = m.tool_execution_id "
           "where m.conversation_id = %s and m.role in ('user','agent') order by m.seq")
    cur = await conn.execute(sql, (conversation_id,))
    linhas: list[tuple[str, str]] = []
    for role, content, payload in await cur.fetchall():
        if role == "agent" and payload is not None and max_chars_resultado:
            dados = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if len(dados) > int(max_chars_resultado):
                dados = dados[: int(max_chars_resultado)] + "…"
            content = f"{content or ''}\n[dados medidos: {dados}]"
        linhas.append((role, content))
    return linhas[-limite:] if limite else linhas


async def encerrar(conn: AsyncConnection, conversation_id: str) -> bool:
    cur = await conn.execute(
        "update agents.conversations set status = 'encerrada', ended_at = now() "
        "where id = %s and status = 'aberta' returning id", (conversation_id,))
    return await cur.fetchone() is not None


async def listar_mensagens(conn: AsyncConnection, conversation_id: str) -> list[dict[str, Any]]:
    """Mensagens com proveniência (cited_refs) — a tela mostra a fonte também ao reabrir a conversa (F7)."""
    cur = await conn.execute(
        "select id::text, seq, role::text, content, content_json, cited_refs, created_at from agents.messages "
        "where conversation_id = %s order by seq", (conversation_id,))
    return [{"id": r[0], "seq": r[1], "role": r[2], "content": r[3], "content_json": r[4],
             "cited_refs": r[5], "created_at": r[6].isoformat()}
            for r in await cur.fetchall()]


_TITULO_MAX = 80


async def cabecalho(conn: AsyncConnection, conversation_id: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select id::text, agent_code::text, status::text, plan_code_at_start::text, started_at, ended_at, "
        "last_message_at, message_count from agents.conversations where id = %s", (conversation_id,))
    r = await cur.fetchone()
    if r is None:
        return None
    return {"id": r[0], "agent_code": r[1], "status": r[2], "plan_code_at_start": r[3],
            "started_at": r[4].isoformat(), "ended_at": r[5].isoformat() if r[5] else None,
            "last_message_at": r[6].isoformat() if r[6] else None, "message_count": r[7]}


async def listar_conversas(conn: AsyncConnection, *, limite: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    """Conversas visíveis pelo RLS do escopo, mais recentes primeiro. Título = title ou a primeira
    mensagem do usuário, truncada (a tabela não tem created_at: usa started_at)."""
    cur = await conn.execute(
        """select c.id::text, c.agent_code::text, c.status::text,
                  coalesce(c.title, (select m.content from agents.messages m
                                      where m.conversation_id = c.id and m.role = 'user'
                                      order by m.seq limit 1)) as titulo,
                  c.started_at, c.last_message_at, c.message_count
             from agents.conversations c
            where (%s::text is null or c.status::text = %s)
            order by c.last_message_at desc nulls last, c.started_at desc
            limit %s""", (status, status, limite))
    saida = []
    for r in await cur.fetchall():
        titulo = (r[3] or "").strip().replace("\n", " ")
        if len(titulo) > _TITULO_MAX:
            titulo = titulo[:_TITULO_MAX].rstrip() + "…"
        saida.append({"id": r[0], "agent_code": r[1], "status": r[2], "titulo": titulo or None,
                      "started_at": r[4].isoformat(), "last_message_at": r[5].isoformat() if r[5] else None,
                      "message_count": r[6]})
    return saida


async def agentes_visiveis(conn: AsyncConnection) -> list[dict[str, str]]:
    cur = await conn.execute(
        "select code::text, display_name, coalesce(description, '') from agents.agent_definitions "
        "where is_user_facing and is_active order by code")
    return [{"code": r[0], "display_name": r[1], "description": r[2]} for r in await cur.fetchall()]


@dataclass(frozen=True)
class AgentDef:
    code: str
    display_name: str
    is_user_facing: bool
    is_active: bool
    min_plan: str
    allowed_tool_families: tuple[str, ...]


async def agente(conn: AsyncConnection, code: str) -> AgentDef | None:
    cur = await conn.execute(
        "select code::text, display_name, is_user_facing, is_active, min_plan::text, allowed_tool_families "
        "from agents.agent_definitions where code::text = %s", (code,))
    row = await cur.fetchone()
    if row is None:
        return None
    return AgentDef(code=row[0], display_name=row[1], is_user_facing=row[2], is_active=row[3],
                    min_plan=row[4], allowed_tool_families=tuple(row[5] or ()))
