"""Executor do DAG: roda as tasks de um plano em ordem topológica, uma por vez, com checkpoint no banco.

- claim por CAS (`UPDATE … WHERE status IN ('pending','ready') RETURNING`): dois executores não repetem a
  mesma task; `running` alheia fica para a varredura de travadas;
- cada task roda `executar_tool` (mesmo executor das conversas: cache, gates do banco — que valem pela
  análise, T63) com `timeout_task_s`; `ToolExecutionFailed`/timeout retentam até `max_tentativas`;
  `ToolParamsInvalid`/gate do banco falham sem retentar (determinístico);
- sucesso ⇒ `evidence_findings` da task na MESMA transação em que a task vira `succeeded`;
- dependente de nó `failed`/`skipped` vira `skipped`; `important`/`optional` falho vira finding `warning`;
- retomada = o laço ignora o que já está `succeeded`/`skipped`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

from app.agents import analysis as an
from app.analysis.config import ConfigResearch
from app.db.errors import DbError
from app.tools.executor import ToolExecutionFailed, ToolInsumoFaltante, ToolParamsInvalid, executar_tool  # noqa: F401

_FINAIS = ("succeeded", "failed", "skipped", "cancelled")


@dataclass
class Execucao:
    succeeded: list[str] = field(default_factory=list)
    failed_required: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)      # important/optional que falharam
    skipped: list[str] = field(default_factory=list)
    pendentes: list[str] = field(default_factory=list)     # running de outro executor (claim negado)


async def _tasks_do_plano(conn, plan_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        """select id::text, node_id, tool_code, params, depends_on, criticality::text, status::text, attempt
             from analysis.tasks where plan_id = %s order by id""", (plan_id,))   # uuidv7: ordem de inserção = topológica
    return [dict(zip(("id", "node_id", "tool_code", "params", "depends_on", "criticality", "status", "attempt"), r))
            for r in await cur.fetchall()]


async def _claim(conn, task_id: str) -> bool:
    cur = await conn.execute(
        """update analysis.tasks set status = 'running', attempt = attempt + 1, started_at = clock_timestamp()
            where id = %s and status in ('pending', 'ready') returning id""", (task_id,))
    return (await cur.fetchone()) is not None


async def _fechar(conn, task_id: str, *, status: str, execution_id: str | None = None,
                  error_code: str | None = None, error_detail: str | None = None) -> None:
    await conn.execute(
        """update analysis.tasks set status = %s::analysis.task_status, tool_execution_id = coalesce(%s, tool_execution_id),
                  error_code = %s, error_detail = %s, finished_at = clock_timestamp() where id = %s""",
        (status, execution_id, error_code, error_detail, task_id))


async def _reabrir(conn, task_id: str) -> None:
    """Retentativa: volta a pending sem apagar o attempt (o claim seguinte incrementa)."""
    await conn.execute("update analysis.tasks set status = 'pending' where id = %s", (task_id,))


async def _warning(conn, analise: an.AnaliseRow, t: dict[str, Any], erro: str) -> None:
    await conn.execute(
        "insert into analysis.evidence_findings (analysis_id, kind, finding, provenance) values (%s, 'warning', %s, '[]'::jsonb)",
        (analise.id, Jsonb({"node_id": t["node_id"], "tool": t["tool_code"], "criticality": t["criticality"],
                            "aviso": "task_falhou", "erro": erro})))


async def _rodar_task(db, analise: an.AnaliseRow, t: dict[str, Any], cfg: ConfigResearch) -> tuple[str, str | None, str | None]:
    """Uma tentativa. Devolve (status, error_code, error_detail). Task succeeded já vem com findings gravados."""
    try:
        async with db.app_session(user_id=analise.user_id, scope_id=analise.scope_id) as conn:
            r = await asyncio.wait_for(
                executar_tool(conn, t["tool_code"], t["params"], scope_id=analise.scope_id,
                              conversation_id=analise.conversation_id, cutoff_date=analise.cutoff_date, analysis_id=analise.id),
                timeout=cfg.timeout_task_s)
            await an.registrar_findings(conn, analise.id, [(t["tool_code"], r)], node_id=t["node_id"])
            await _fechar(conn, t["id"], status="succeeded", execution_id=r.execution_id)
        return "succeeded", None, None
    except (ToolParamsInvalid, ToolInsumoFaltante, DbError) as exc:      # determinístico: não retenta
        return "failed", type(exc).__name__, str(exc)
    except ToolExecutionFailed as exc:
        return "retry", type(exc).__name__, str(exc)
    except asyncio.TimeoutError as exc:
        return "retry", "TimeoutError", f"task excedeu {cfg.timeout_task_s}s"


async def executar_plano(db, analise: an.AnaliseRow, plan_id: str, cfg: ConfigResearch) -> Execucao:
    res = Execucao()
    async with db.service_session() as conn:
        tasks = await _tasks_do_plano(conn, plan_id)
    estado = {t["node_id"]: t["status"] for t in tasks}
    for t in tasks:
        if t["status"] in _FINAIS:
            (res.succeeded if t["status"] == "succeeded" else res.skipped if t["status"] == "skipped"
             else res.failed_required if t["criticality"] == "required" else res.warnings).append(t["node_id"])
            continue
        if any(estado.get(d) in ("failed", "skipped", "cancelled") for d in t["depends_on"]):
            async with db.service_session() as conn:
                if await _claim(conn, t["id"]):
                    await _fechar(conn, t["id"], status="skipped", error_code="DependenciaFalhou")
            estado[t["node_id"]] = "skipped"
            res.skipped.append(t["node_id"])
            continue
        if any(estado.get(d) != "succeeded" for d in t["depends_on"]):
            res.pendentes.append(t["node_id"])       # dependência ainda running noutro executor
            continue
        async with db.service_session() as conn:
            pegou = await _claim(conn, t["id"])
        if not pegou:
            res.pendentes.append(t["node_id"])
            continue
        status, codigo, detalhe = await _rodar_task(db, analise, t, cfg)
        tentativa = t["attempt"] + 1
        while status == "retry" and tentativa < cfg.max_tentativas:
            async with db.service_session() as conn:
                await _reabrir(conn, t["id"])
                await _claim(conn, t["id"])
            tentativa += 1
            status, codigo, detalhe = await _rodar_task(db, analise, t, cfg)
        if status == "succeeded":
            estado[t["node_id"]] = "succeeded"
            res.succeeded.append(t["node_id"])
            continue
        async with db.service_session() as conn:
            await _fechar(conn, t["id"], status="failed", error_code=codigo, error_detail=detalhe)
            if t["criticality"] != "required":
                await _warning(conn, analise, t, f"{codigo}: {detalhe}")
        estado[t["node_id"]] = "failed"
        (res.failed_required if t["criticality"] == "required" else res.warnings).append(t["node_id"])
    return res
