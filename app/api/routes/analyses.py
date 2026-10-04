"""Análises do Analista research: leitura sob RLS (analysis.analyses e, desde a 32, as filhas)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import Identidade, identidade

router = APIRouter()


async def _existe(conn, analysis_id: str) -> dict | None:
    cur = await conn.execute(
        """select id::text, status::text, mode, question, cutoff_date, replan_count, max_replans, created_at, finished_at,
                  conversation_id::text from analysis.analyses where id = %s""", (analysis_id,))
    row = await cur.fetchone()
    if row is None:
        return None
    return dict(zip(("id", "status", "mode", "question", "cutoff_date", "replan_count", "max_replans", "created_at",
                     "finished_at", "conversation_id"), row))


@router.get("/analyses")
async def listar(request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        cur = await conn.execute(
            "select id::text, status::text, mode, question, created_at from analysis.analyses order by created_at desc limit 50")
        return [dict(zip(("id", "status", "mode", "question", "created_at"), r)) for r in await cur.fetchall()]


@router.get("/analyses/{analysis_id}")
async def detalhe(analysis_id: str, request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        a = await _existe(conn, analysis_id)
        if a is None:                       # RLS: análise de outro escopo não existe para este papel
            raise HTTPException(status_code=404, detail="análise não encontrada")
        cur = await conn.execute(
            "select id::text, version, plan->>'objetivo', validation_report from analysis.plans where analysis_id = %s and is_active",
            (analysis_id,))
        p = await cur.fetchone()
        plano = {"id": p[0], "version": p[1], "objetivo": p[2], "validation_report": p[3]} if p else None
        tasks = []
        if p:
            cur = await conn.execute(
                """select node_id, tool_code, status::text, criticality::text, depends_on, attempt, error_code
                     from analysis.tasks where plan_id = %s order by id""", (p[0],))
            tasks = [dict(zip(("node_id", "tool_code", "status", "criticality", "depends_on", "attempt", "error_code"), r))
                     for r in await cur.fetchall()]
        cur = await conn.execute("select count(*) from analysis.evidence_findings where analysis_id = %s", (analysis_id,))
        n_findings = (await cur.fetchone())[0]
        return {**a, "plano": plano, "tasks": tasks, "findings": n_findings}


@router.get("/analyses/{analysis_id}/report")
async def relatorio(analysis_id: str, request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        a = await _existe(conn, analysis_id)
        if a is None:
            raise HTTPException(status_code=404, detail="análise não encontrada")
        cur = await conn.execute(
            """select id::text, version, content_md, status, evidence_hash, published_at from analysis.reports
                where analysis_id = %s and superseded_by is null order by version desc limit 1""", (analysis_id,))
        r = await cur.fetchone()
        report = dict(zip(("id", "version", "content_md", "status", "evidence_hash", "published_at"), r)) if r else None
        return {"status": a["status"], "report": report}
