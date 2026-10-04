"""Planner: a pergunta vira um AnalysisPlan por LLM (`purpose='planejamento'`), no molde do extrator (F3):
prompt versionado/aprovado `analista.planner`, catálogo = `param_schema` das tools filtradas por família e
plano da conversa (nunca schema copiado no texto), `json_object` + temperature 0 + 1 reparo. O JSON é
validado pela DSL (nó inválido descartado com motivo). Cada chamada fica em `llm.model_calls` com
`analysis_id`; o orçamento da análise é conferido ANTES de cada chamada."""
from __future__ import annotations

import json
from typing import Any

from app.agents import analysis as an
from app.agents import conversations as convs
from app.agents.turn import filtrar_tools
from app.analysis.budget import AnalysisBudget
from app.analysis.config import ConfigResearch
from app.analysis.dsl import AnalysisPlan, validar_plano
from app.context.schemas import parse_json_tolerante
from app.llm.budget import TurnBudget
from app.llm.client import CallMeta, ChatRequest, Message
from app.llm.prompts import PromptLoader
from app.llm.recorder import ModelCallRecorder
from app.tools.registry import specs_registradas

PROMPT_CODE = "analista.planner"
PURPOSE = "planejamento"
AGENT_CODE = "analista"
INSTRUCAO_REPARO = ("A resposta anterior não era um JSON válido. Responda SOMENTE com o objeto JSON no formato "
                    "{\"dsl_version\": \"1\", \"objetivo\": \"...\", \"nodes\": [...]}, sem texto fora dele.")


class SaidaInvalida(RuntimeError):
    """O LLM não devolveu JSON parseável mesmo após o reparo."""


async def contexto_do_agente(conn, analise: an.AnaliseRow) -> tuple[tuple[str, ...], str]:
    """(famílias permitidas, plano congelado da conversa) — os mesmos que os gates do banco usam."""
    agente = await convs.agente(conn, AGENT_CODE)
    cur = await conn.execute("select plan_code_at_start::text from agents.conversations where id = %s", (analise.conversation_id,))
    row = await cur.fetchone()
    return tuple(agente.allowed_tool_families), (row[0] if row else "free")


def catalogo_para_prompt(familias: tuple[str, ...], plano_conta: str) -> list[dict[str, Any]]:
    return [{"tool_code": s.code, "descricao": s.description, "param_schema": s.param_schema}
            for s in filtrar_tools(specs_registradas(), familias=familias, plano=plano_conta)]


def formatar_falhas(falhas: list[dict[str, Any]] | None) -> str:
    if not falhas:
        return "(nenhuma — primeira tentativa)"
    return "\n".join(f"- tentativa {f.get('tentativa')}: {f.get('motivo')}" for f in falhas)


async def planejar(db, llm, policies, analise: an.AnaliseRow, *, cfg: ConfigResearch,
                   falhas_anteriores: list[dict[str, Any]] | None = None,
                   budget: AnalysisBudget | None = None) -> tuple[AnalysisPlan, list[dict[str, Any]], str | None]:
    """Devolve (plano validado pela DSL, descartados, model_call_id). Levanta SaidaInvalida / PlanoVazio."""
    async with db.service_session() as conn:
        prompt = await PromptLoader(conn).carregar_por_code(PROMPT_CODE)      # PromptNotApproved se draft (gate 19)
        familias, plano_conta = await contexto_do_agente(conn, analise)
    catalogo = catalogo_para_prompt(familias, plano_conta)
    sistema = prompt.render(pergunta=analise.question, cutoff_date=str(analise.cutoff_date),
                            catalogo_tools=json.dumps(catalogo, ensure_ascii=False, indent=1),
                            max_tasks=cfg.max_tasks, falhas_anteriores=formatar_falhas(falhas_anteriores))
    turno = TurnBudget.from_policy(await policies.payload("LLM_BUDGETS"))
    meta = CallMeta(purpose=PURPOSE, agent_code=AGENT_CODE, scope_id=analise.scope_id,
                    conversation_id=analise.conversation_id, prompt_version_id=prompt.id, analysis_id=analise.id)
    historico = [Message(role="system", content=sistema),
                 Message(role="user", content="Monte o plano agora. Responda apenas o objeto JSON.")]
    obj: dict[str, Any] | None = None
    call_id: str | None = None
    for _tentativa in range(2):
        if budget is not None:
            async with db.service_session() as conn:
                await budget.checar(conn)
        turno.reservar_chamada(PURPOSE)
        resp = await llm.chat(ChatRequest(messages=list(historico), metadata=meta, response_format={"type": "json_object"},
                                          max_output_tokens=turno.tokens_restantes(), temperature=0.0))
        async with db.service_session() as conn:
            call_id = await ModelCallRecorder(conn).gravar(resp, meta)
        turno.registrar(resp)
        obj = parse_json_tolerante(resp.text)
        if obj is not None:
            break
        historico += [Message(role="assistant", content=resp.text), Message(role="user", content=INSTRUCAO_REPARO)]
    if obj is None:
        raise SaidaInvalida("o planner não devolveu JSON válido após o reparo")
    plano, descartados = validar_plano(obj)            # PlanoVazio se nada sobrou
    return plano, descartados, call_id
