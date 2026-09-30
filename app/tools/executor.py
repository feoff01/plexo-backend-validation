"""Executor de tools: valida (Pydantic) → prepara (insumos + policies) → cache → executa → congela.

Os GATES são do banco (18/29): família por agente, plano mínimo, política aprovada quando
client-facing. O executor não os reimplementa — só recebe o 23514 traduzido. O que o executor
garante por conta própria: parâmetros validados, `resolved_params` com `_policies`/`_inputs`
(auditoria), `input_hash` content-addressed (cache muda quando o contexto muda) e a linha
`tool_executions` fechada (`succeeded`/`failed`) — imutável dali em diante.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

from app.db.errors import PolicyNotFound
from app.db.repos import policies as policies_repo
from app.tools.hashing import canonical_json, sha256_hex
from app.tools.registry import ToolSpec, spec_de


class ToolParamsInvalid(ValueError):
    """Parâmetros não passam no schema — o LLM recebe os erros para corrigir UMA vez (F2)."""

    def __init__(self, code: str, erros: list[dict[str, Any]]):
        super().__init__(f"{code}: parâmetros inválidos: {erros}")
        self.code = code
        self.erros = erros


class ToolInsumoFaltante(RuntimeError):
    """A tool declara o que falta (dado do cliente ou política) — vira pergunta, nunca chute."""


class ToolConteudoIndisponivel(RuntimeError):
    """Não há conteúdo APROVADO por compliance para o que foi pedido — o Educador diz isso, não improvisa (F4)."""


class ToolExecutionFailed(RuntimeError):
    def __init__(self, code: str, execution_id: str, causa: BaseException):
        super().__init__(f"{code}: execução {execution_id} falhou: {causa}")
        self.execution_id = execution_id


@dataclass
class ToolContext:
    """O que `preparar` recebe: acesso ao escopo (RLS) e às premissas versionadas."""
    conn: AsyncConnection
    scope_id: str
    conversation_id: str | None
    cutoff_date: date | None = None      # point-in-time da análise (Analista, F5)
    analysis_id: str | None = None
    politicas: dict[str, dict[str, Any]] = field(default_factory=dict)
    politicas_meta: list[dict[str, Any]] = field(default_factory=list)
    insumos: list[dict[str, Any]] = field(default_factory=list)

    async def policy(self, code: str) -> dict[str, Any]:
        """Payload vigente da policy; o USO fica registrado (id → policy_version_ids + _policies)."""
        if code in self.politicas:
            return self.politicas[code]
        row = await policies_repo.get_current(self.conn, code)
        if row is None:
            raise PolicyNotFound(code)
        self.politicas[code] = row.payload
        self.politicas_meta.append({"code": row.code, "version": row.version, "id": row.id,
                                    "content_hash": row.content_hash})
        return row.payload

    def registrar_insumo(self, kind: str, **info: Any) -> None:
        self.insumos.append({"kind": kind, **info})


@dataclass(frozen=True)
class ToolResult:
    execution_id: str
    output: BaseModel
    cache_hit: bool
    politicas_meta: tuple[dict[str, Any], ...] = ()   # {code, version, id, content_hash} usadas


async def _versao_corrente(conn: AsyncConnection, code: str) -> str:
    cur = await conn.execute(
        "select id::text from tools.tool_versions where tool_code = %s and deprecated_at is null", (code,))
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError(f"tool '{code}' sem versão corrente no banco — rode `plexo tools sync`")
    return row[0]


async def executar_tool(conn: AsyncConnection, code: str, requested_params: dict[str, Any] | None,
                        *, scope_id: str, conversation_id: str | None,
                        cutoff_date: date | None = None, analysis_id: str | None = None) -> ToolResult:
    spec: ToolSpec = spec_de(code)
    try:
        params = spec.params_model.model_validate(requested_params or {})
    except ValidationError as e:
        raise ToolParamsInvalid(code, e.errors(include_url=False)) from e

    ctx = ToolContext(conn=conn, scope_id=scope_id, conversation_id=conversation_id,
                      cutoff_date=cutoff_date, analysis_id=analysis_id)
    resolvido: BaseModel = await spec.preparar(params, ctx)
    resolvido_json = resolvido.model_dump(mode="json")
    resolved_params = {
        "params": params.model_dump(mode="json"),
        "resolvido": resolvido_json,
        "_policies": ctx.politicas_meta,
        "_inputs": ctx.insumos,
        "_analysis": {"analysis_id": analysis_id, "cutoff_date": cutoff_date.isoformat() if cutoff_date else None},
    }
    policy_ids = [m["id"] for m in ctx.politicas_meta]
    input_hash = sha256_hex(canonical_json({"tool": code, "semver": spec.semver, "resolvido": resolvido_json}))
    version_id = await _versao_corrente(conn, code)

    # cache content-addressed: mesma versão + mesmo resolvido ⇒ mesmo número (a origem nunca é outra linha de cache)
    cur = await conn.execute(
        "select id::text, output_payload, output_hash from tools.tool_executions "
        "where tool_version_id = %s and input_hash = %s and status = 'succeeded' and not cache_hit "
        "order by started_at limit 1", (version_id, input_hash))
    origem = await cur.fetchone()
    if origem is not None:
        origem_id, payload, output_hash = origem
        cur = await conn.execute(
            """insert into tools.tool_executions
                 (tool_version_id, scope_id, conversation_id, analysis_id, requested_params, resolved_params, input_hash,
                  output_hash, status, cache_hit, cached_from_execution_id, output_payload,
                  policy_version_ids, finished_at, duration_ms)
               values (%s, %s, %s, %s, %s, %s, %s, %s, 'succeeded', true, %s, %s, %s, clock_timestamp(), 0)
               returning id::text""",
            (version_id, scope_id, conversation_id, analysis_id, Jsonb(resolved_params["params"]), Jsonb(resolved_params),
             input_hash, output_hash, origem_id, Jsonb(payload), policy_ids))
        exec_id = (await cur.fetchone())[0]
        return ToolResult(execution_id=exec_id, output=spec.output_model.model_validate(payload),
                          cache_hit=True, politicas_meta=tuple(ctx.politicas_meta))

    cur = await conn.execute(
        """insert into tools.tool_executions
             (tool_version_id, scope_id, conversation_id, analysis_id, requested_params, resolved_params, input_hash,
              status, policy_version_ids)
           values (%s, %s, %s, %s, %s, %s, %s, 'running', %s)
           returning id::text""",
        (version_id, scope_id, conversation_id, analysis_id, Jsonb(resolved_params["params"]), Jsonb(resolved_params),
         input_hash, policy_ids))
    exec_id = (await cur.fetchone())[0]

    t0 = time.perf_counter()
    try:
        saida: BaseModel = spec.calcular(resolvido)   # parte PURA — golden-testável
    except Exception as exc:
        await conn.execute(
            "update tools.tool_executions set status = 'failed', error_code = %s, error_detail = %s, "
            "finished_at = clock_timestamp(), duration_ms = %s where id = %s",
            (type(exc).__name__, str(exc), int((time.perf_counter() - t0) * 1000), exec_id))
        raise ToolExecutionFailed(code, exec_id, exc) from exc

    payload = saida.model_dump(mode="json")
    await conn.execute(
        "update tools.tool_executions set status = 'succeeded', output_payload = %s, output_hash = %s, "
        "finished_at = clock_timestamp(), duration_ms = %s where id = %s",
        (Jsonb(payload), sha256_hex(canonical_json(payload)), int((time.perf_counter() - t0) * 1000), exec_id))
    return ToolResult(execution_id=exec_id, output=saida, cache_hit=False,
                      politicas_meta=tuple(ctx.politicas_meta))
