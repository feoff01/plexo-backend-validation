"""Síntese do relatório: os `evidence_findings` da análise (ordenados, hash canônico = `evidence_hash`) viram
texto por LLM (`purpose='sintese'`, prompt `analista.report`), passam pelos MESMOS guardrails do turno
(vocabulário → 1 reparo → texto seguro; marcação vazada; rodapé ILUSTRATIVO) ANTES do INSERT — o banco
congela o relatório (T21/T67) — e são entregues como mensagem do agente NA conversa, com `cited_refs`
(`analysis_report`, `analysis_finding`, `tool_execution`, `price_asof`/`index_asof`) e custo em
`cost_ledger ref_kind='analysis'`."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

from app.agents.blocos import blocos_de_execucoes
from app.agents import analysis as an
from app.agents import conversations as convs
from app.agents import guardrails
from app.analysis.budget import AnalysisBudget
from app.llm.budget import TurnBudget
from app.llm.client import CallMeta, ChatRequest, Message
from app.llm.custos import upsert_cost_ledger
from app.llm.prompts import PromptLoader
from app.llm.recorder import ModelCallRecorder
from app.tools.registry import spec_de

PROMPT_CODE = "analista.report"
AGENT_CODE = "analista"


@dataclass(frozen=True)
class Relatorio:
    report_id: str
    message_id: str
    status: str
    evidence_hash: str | None
    model_call_id: str | None


async def _chamar(db, llm, turno: TurnBudget, req: ChatRequest) -> tuple[Any, str]:
    turno.reservar_chamada(req.metadata.purpose)
    resp = await llm.chat(req)
    async with db.service_session() as conn:
        call_id = await ModelCallRecorder(conn).gravar(resp, req.metadata)
    turno.registrar(resp)
    return resp, call_id


async def _tasks_concluidas(conn, analysis_id: str) -> list[tuple[str, str]]:
    """(tool_code, tool_execution_id) das tasks succeeded do plano ativo."""
    cur = await conn.execute(
        """select t.tool_code, t.tool_execution_id::text from analysis.tasks t
             join analysis.plans p on p.id = t.plan_id and p.is_active
            where t.analysis_id = %s and t.status = 'succeeded' order by t.id""", (analysis_id,))
    return [(c, e) for c, e in await cur.fetchall()]


def _cited_refs(report_id: str, findings: list[dict[str, Any]], execucoes: list[tuple[str, str]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = [{"kind": "analysis_report", "id": report_id}]
    refs += [{"kind": "tool_execution", "id": e} for _, e in execucoes]
    vistos: set[tuple[str, str]] = set()
    for f in findings:
        refs.append({"kind": "analysis_finding", "id": f["id"]})
        for p in f["provenance"]:
            for pa in p.get("price_asof", []):
                chave = ("price_asof", pa["instrument_id"])
                if chave not in vistos:
                    vistos.add(chave)
                    refs.append({"kind": "price_asof", "instrument_id": pa["instrument_id"], "as_of": pa.get("as_of")})
            for ia in p.get("index_asof", []):
                chave = ("index_asof", ia["index_code"])
                if chave not in vistos:
                    vistos.add(chave)
                    refs.append({"kind": "index_asof", "index_code": ia["index_code"], "as_of": ia.get("as_of")})
    return refs


async def publicar(db, analise: an.AnaliseRow, *, content_md: str, status: str, evidence_hash: str | None,
                   model_call_id: str | None, guardrail_eventos: list[tuple[str, str, str]]) -> Relatorio:
    """INSERT do relatório + mensagem do agente na conversa + guardrail_events + cost_ledger, numa transação de serviço."""
    async with db.service_session() as conn:
        await conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (analise.id,))
        findings = await an.listar_findings(conn, analise.id)
        execucoes = await _tasks_concluidas(conn, analise.id)
        cur = await conn.execute(
            """insert into analysis.reports (analysis_id, content_md, evidence_hash, synthesis_model_call_id, status)
               values (%s, %s, %s, %s, %s) returning id::text""",
            (analise.id, content_md, evidence_hash, model_call_id, status))
        report_id = (await cur.fetchone())[0]
        conversa = await convs.travar(conn, analise.conversation_id)
        msg_id = await convs.inserir_mensagem(
            conn, conversation_id=analise.conversation_id, scope_id=analise.scope_id, seq=conversa.message_count + 1,
            role="agent", content=content_md,
            content_json={"analysis_id": analise.id, "report_id": report_id, "status": status,
                          "blocos": await blocos_de_execucoes(conn, execucoes)},   # F11: gráficos das medições do DAG
            model_call_id=model_call_id, cited_refs=_cited_refs(report_id, findings, execucoes))
        for kind, action, detalhe in guardrail_eventos:
            await conn.execute(
                "insert into agents.guardrail_events (conversation_id, message_id, scope_id, kind, action_taken, details) "
                "values (%s, %s, %s, %s, %s, %s)", (analise.conversation_id, msg_id, analise.scope_id, kind, action, Jsonb({"detalhe": detalhe})))
        cur = await conn.execute(
            "select id::text, input_tokens, cached_tokens, output_tokens from llm.model_calls where analysis_id = %s", (analise.id,))
        calls = await cur.fetchall()
        await upsert_cost_ledger(conn, scope_id=analise.scope_id, ref_kind="analysis", ref_id=analise.id,
                                 call_ids=[c[0] for c in calls], input_tokens=sum(c[1] for c in calls),
                                 cached_tokens=sum(c[2] for c in calls), output_tokens=sum(c[3] for c in calls),
                                 tool_executions=len(execucoes))
    return Relatorio(report_id=report_id, message_id=msg_id, status=status, evidence_hash=evidence_hash, model_call_id=model_call_id)


async def sintetizar(db, llm, policies, analise: an.AnaliseRow, *, objetivo: str, avisos_execucao: list[str],
                     budget: AnalysisBudget | None = None) -> Relatorio:
    async with db.service_session() as conn:
        prompt = await PromptLoader(conn).carregar_por_code(PROMPT_CODE)
        findings = await an.listar_findings(conn, analise.id)
        execucoes = await _tasks_concluidas(conn, analise.id)
        if budget is not None:
            await budget.checar(conn)
    evidence_hash = an.evidence_hash_de(findings)
    com_avisos = any(f["kind"] in ("missing", "warning") for f in findings) or bool(avisos_execucao)
    status = an.STATUS_COM_AVISOS if com_avisos else an.STATUS_FINAL
    sistema = prompt.render(pergunta=analise.question, objetivo=objetivo or "", cutoff_date=str(analise.cutoff_date),
                            findings=json.dumps([{k: f[k] for k in ("kind", "finding", "provenance")} for f in findings],
                                                ensure_ascii=False, indent=1, default=str),
                            avisos="\n".join(f"- {a}" for a in avisos_execucao) or "(nenhum)")
    orcamentos = await policies.payload("LLM_BUDGETS")
    turno = TurnBudget.from_policy(orcamentos)
    # síntese tem teto próprio (o reasoning do provedor conta como saída): sem a chave, vale o teto do turno
    teto_relatorio = int(orcamentos.get("max_output_tokens_por_relatorio") or turno.max_output_tokens)
    turno = dataclasses.replace(turno, max_output_tokens=teto_relatorio)     # o registrar() do orçamento usa o mesmo teto
    meta = CallMeta(purpose="sintese", agent_code=AGENT_CODE, scope_id=analise.scope_id, conversation_id=analise.conversation_id,
                    prompt_version_id=prompt.id, analysis_id=analise.id)
    mensagens = [Message(role="system", content=sistema), Message(role="user", content="Redija o relatório agora.")]
    resp, call_id = await _chamar(db, llm, turno, ChatRequest(messages=mensagens, metadata=meta, max_output_tokens=teto_relatorio))
    texto = (resp.text or "").strip()
    eventos: list[tuple[str, str, str]] = []
    if not texto:      # saída vazia/truncada (teto de tokens engolido pelo reasoning): nunca publicar 'final' vazio
        return await publicar(db, analise, content_md=guardrails.TEXTO_SEGURO_RELATORIO, status=an.STATUS_BLOQUEADA, evidence_hash=evidence_hash,
                              model_call_id=call_id, guardrail_eventos=[("outro", "bloqueado", f"sintese_vazia finish_reason={resp.finish_reason}")])

    achados = guardrails.vocabulario(texto)
    if achados:
        reparo, call_reparo = await _chamar(db, llm, turno, ChatRequest(
            messages=mensagens + [Message(role="assistant", content=texto),
                                  Message(role="user", content=guardrails.instrucao_de_reescrita(achados))],
            metadata=CallMeta(purpose="guardrail", agent_code=AGENT_CODE, scope_id=analise.scope_id,
                              conversation_id=analise.conversation_id, prompt_version_id=prompt.id, analysis_id=analise.id),
            max_output_tokens=turno.tokens_restantes()))
        if reparo.text and not guardrails.vocabulario(reparo.text):
            texto, call_id = reparo.text, call_reparo
            eventos.append(("vocabulario_proibido", "reescrito", ", ".join(achados)))
        else:
            texto, status = guardrails.TEXTO_SEGURO_VOCABULARIO, an.STATUS_BLOQUEADA
            eventos.append(("vocabulario_proibido", "bloqueado", ", ".join(achados)))
    limpo, vazou = guardrails.limpar_marcacao_de_tool(texto)
    if vazou:
        texto = limpo or guardrails.TEXTO_SEGURO_TOOL
        eventos.append(("outro", "bloqueado", "marcacao_de_tool_vazada"))
    houve_calculo = any(spec_de(code).emite_numero for code, _ in execucoes)
    texto = guardrails.garantir_ilustrativo(texto, houve_calculo=houve_calculo)
    return await publicar(db, analise, content_md=texto, status=status, evidence_hash=evidence_hash,
                          model_call_id=call_id, guardrail_eventos=eventos)


async def publicar_bloqueado(db, analise: an.AnaliseRow, *, texto: str, motivo: str) -> Relatorio:
    """Relatório `blocked` (orçamento) com texto seguro — sem LLM; o banco não exige evidência para blocked."""
    return await publicar(db, analise, content_md=texto, status=an.STATUS_BLOQUEADA, evidence_hash=None,
                          model_call_id=None, guardrail_eventos=[("limite_orcamento_llm", "bloqueado", motivo)])
