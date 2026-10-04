"""Pipeline do modo research — a máquina de status de `analysis.analyses`, idempotente e retomável:

  received | needs_replan ─planner─▶ planned ─compiler─▶ compiled ─executor─▶ executing
     ▲                                                                        │
     └──────────── required falhou e replan_count < max_replans ◀─────────────┤
                                                                              ▼
                                        evidence_ready ─▶ synthesizing ─▶ final | final_with_warnings | blocked
Plano inválido também é gravado (versão + validation_report): o banco conta o replan (T66) e recusa o
excedente — o teto é do banco, não deste laço. Orçamento estourado ⇒ relatório `blocked` com texto seguro.
Qualquer outra falha ⇒ `failed` + audit `analysis.failed`. Toda passada começa com advisory lock por
análise; segunda chamada em análise terminal é no-op.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg

from app.agents import analysis as an
from app.agents import guardrails
from app.analysis import compiler, executor, planner, report
from app.analysis.budget import AnalysisBudget
from app.analysis.config import ConfigResearch
from app.analysis.dsl import PlanoVazio
from app.db.errors import DbError
from app.db.repos import audit
from app.llm.budget import BudgetExceeded

NAO_TERMINAIS = ("received", "normalized", "planned", "plan_validated", "compiled", "executing", "partial_failure",
                 "needs_replan", "validating", "evidence_ready", "synthesizing")


@dataclass
class ResultadoAnalise:
    analysis_id: str
    status: str
    plan_id: str | None = None
    report_id: str | None = None
    message_id: str | None = None
    replans: int = 0
    erro: str | None = None
    noop: bool = False
    falhas: list[dict[str, Any]] = field(default_factory=list)

    def resumo(self) -> dict[str, Any]:
        return {"analysis_id": self.analysis_id, "status": self.status, "plan_id": self.plan_id, "report_id": self.report_id,
                "message_id": self.message_id, "replans": self.replans, "erro": self.erro, "noop": self.noop}


async def _plano_ativo(conn, analysis_id: str) -> tuple[str | None, str]:
    cur = await conn.execute(
        "select id::text, plan->>'objetivo' from analysis.plans where analysis_id = %s and is_active", (analysis_id,))
    row = await cur.fetchone()
    return (row[0], row[1] or "") if row else (None, "")


async def _relatorio_existente(conn, analysis_id: str) -> tuple[str | None, str | None]:
    cur = await conn.execute(
        """select r.id::text, m.id::text from analysis.reports r
             left join agents.messages m on m.content_json->>'report_id' = r.id::text
            where r.analysis_id = %s and r.superseded_by is null order by r.version desc limit 1""", (analysis_id,))
    row = await cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


async def _avancar(db, analysis_id: str, para: str) -> None:
    async with db.service_session() as conn:
        await an.avancar_status(conn, analysis_id, de=NAO_TERMINAIS, para=para)


async def _falhar(db, analise: an.AnaliseRow, res: ResultadoAnalise, exc: BaseException) -> ResultadoAnalise:
    res.status, res.erro = an.STATUS_FALHOU, f"{type(exc).__name__}: {exc}"
    async with db.service_session() as conn:
        try:
            await an.avancar_status(conn, analise.id, de=NAO_TERMINAIS, para=an.STATUS_FALHOU)
        except an.TransicaoInvalida:
            pass
        await audit.registrar(conn, actor_kind="job", action="analysis.failed", object_kind="analysis", object_id=analise.id,
                              scope_id=analise.scope_id, details={"erro": res.erro, "falhas": res.falhas})
    return res


async def executar_analise(db, llm, policies, analysis_id: str) -> ResultadoAnalise:
    async with db.service_session() as conn:
        await conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (analysis_id,))
        analise = await an.carregar(conn, analysis_id)
        if analise is None:
            raise LookupError(f"análise {analysis_id} não existe")
        if analise.status in an.TERMINAIS:
            rid, mid = await _relatorio_existente(conn, analysis_id)
            return ResultadoAnalise(analysis_id, analise.status, report_id=rid, message_id=mid, replans=analise.replan_count, noop=True)
        if analise.mode != "research" or analise.conversation_id is None:
            raise ValueError(f"análise {analysis_id} não é research com conversa")
    cfg = ConfigResearch.from_policy(await policies.payload("ANALISE_RESEARCH"))
    budget = AnalysisBudget.from_analysis(analise, cfg=cfg)
    res = ResultadoAnalise(analysis_id=analysis_id, status=analise.status)
    objetivo = ""
    avisos_execucao: list[str] = []
    try:
        while True:
            async with db.service_session() as conn:
                analise = await an.carregar(conn, analysis_id)
                plan_id, objetivo = await _plano_ativo(conn, analysis_id)
            res.replans = analise.replan_count
            precisa_plano = plan_id is None or analise.status in ("received", "needs_replan", "planned")
            if precisa_plano:
                if res.falhas and analise.replan_count >= analise.max_replans:
                    break                                    # esgotou: fecha com o que houver
                try:
                    plano, descartados, call_id = await planner.planejar(
                        db, llm, policies, analise, cfg=cfg, falhas_anteriores=res.falhas or None, budget=budget)
                except PlanoVazio as exc:
                    res.falhas.append({"tentativa": len(res.falhas) + 1, "motivo": str(exc)})
                    if analise.replan_count >= analise.max_replans:
                        break
                    await _avancar(db, analysis_id, "needs_replan")
                    continue
                await _avancar(db, analysis_id, "planned")
                async with db.service_session() as conn:
                    familias, plano_conta = await planner.contexto_do_agente(conn, analise)
                    try:
                        comp = await compiler.compilar(conn, analise, plano, familias=familias, plano_conta=plano_conta, cfg=cfg,
                                                       planner_model_call_id=call_id, descartados=descartados)
                    except compiler.PlanoInvalido as exc:
                        motivo = "; ".join(d["motivo"] for d in exc.validation_report.get("descartados", [])) or str(exc)
                        res.falhas.append({"tentativa": len(res.falhas) + 1, "motivo": motivo})
                        comp = None
                    except compiler.CicloNoPlano as exc:
                        res.falhas.append({"tentativa": len(res.falhas) + 1, "motivo": str(exc)})
                        comp = None
                if comp is None:
                    await _avancar(db, analysis_id, "needs_replan")
                    continue
                plan_id, objetivo = comp.plan_id, plano.objetivo
            res.plan_id = plan_id
            await _avancar(db, analysis_id, "executing")
            async with db.service_session() as conn:
                analise = await an.carregar(conn, analysis_id)
            exec_res = await executor.executar_plano(db, analise, plan_id, cfg)
            if exec_res.pendentes:                           # outro executor segura tasks: não é falha
                res.status = "executing"
                return res
            avisos_execucao = [f"nó {n} falhou (criticidade não obrigatória)" for n in exec_res.warnings]
            if exec_res.failed_required:
                motivo = "nós obrigatórios falharam: " + ", ".join(exec_res.failed_required)
                res.falhas.append({"tentativa": len(res.falhas) + 1, "motivo": motivo})
                async with db.service_session() as conn:
                    analise = await an.carregar(conn, analysis_id)
                if analise.replan_count < analise.max_replans:
                    await _avancar(db, analysis_id, "needs_replan")
                    continue
                avisos_execucao.append(motivo)
            break

        async with db.service_session() as conn:
            findings = await an.listar_findings(conn, analysis_id)
            analise = await an.carregar(conn, analysis_id)
        res.replans = analise.replan_count
        if not any(f["kind"] in ("quantitative", "documentary") for f in findings):
            return await _falhar(db, analise, res, RuntimeError("nenhuma evidência material após " + str(len(res.falhas)) + " tentativa(s): "
                                                                 + "; ".join(f["motivo"] for f in res.falhas)))
        await _avancar(db, analysis_id, "evidence_ready")
        await _avancar(db, analysis_id, "synthesizing")
        rel = await report.sintetizar(db, llm, policies, analise, objetivo=objetivo, avisos_execucao=avisos_execucao, budget=budget)
        await _avancar(db, analysis_id, rel.status)
        res.status, res.report_id, res.message_id = rel.status, rel.report_id, rel.message_id
        return res

    except BudgetExceeded as exc:
        rel = await report.publicar_bloqueado(db, analise, texto=guardrails.TEXTO_SEGURO_ORCAMENTO, motivo=str(exc))
        await _avancar(db, analysis_id, an.STATUS_BLOQUEADA)
        res.status, res.report_id, res.message_id, res.erro = an.STATUS_BLOQUEADA, rel.report_id, rel.message_id, str(exc)
        return res
    except (planner.SaidaInvalida, DbError, psycopg.Error, LookupError, ValueError, RuntimeError, an.TransicaoInvalida) as exc:
        return await _falhar(db, analise, res, exc)
    except Exception as exc:          # PromptNotApproved, ProviderUnavailable e afins: falha registrada, nunca improvisa
        return await _falhar(db, analise, res, exc)
