"""
F8 — Turno conversacional (varredura dos agentes, 2026-08-25).

O que muda de contrato, provado aqui com LLM roteirizado (FakeLLM):
- erro de tool (insumo faltante, conteúdo indisponível, parâmetro inválido) VOLTA AO MODELO como
  resultado da chamada — ele redige a pergunta/negativa; texto fixo só quando o teto
  `AGENT_CONVERSATIONS.max_erros_de_tool_por_turno` é atingido;
- várias tool_calls na mesma resposta são todas executadas e todas voltam ao provedor;
- `encaminhar` com texto do modelo usa o texto (a frase fixa é só fallback);
- o histórico enviado ao LLM traz os dados medidos pelas tools de turnos anteriores;
- roteador com `resposta_curta` (saudação/fora de finanças) → Clarify com a mensagem do modelo, sem conversa;
- provedor indisponível vira evento `erro`, não exceção no stream.
"""
from __future__ import annotations

import json

import pytest

from app.agents import eventos as ev
from app.agents.turn import TurnoCopiloto, TurnoInput
from app.config.policies import PolicyStore
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.llm.client import ChatRequest, ChatResponse, ProviderUnavailable, ToolCall, Usage
from app.llm.fake import FakeLLM
from app.tools import carregar_tools
from app.tools.registry import specs_registradas
from app.tools.sync import sincronizar
from tests.test_f4_educador import EDUCACAO_EXEMPLOS

carregar_tools()

PROMPT = "Você é o {{ '{' }}agente{{ '}' }}. Diagnóstico e simulação; todo número é ILUSTRATIVO. Contexto: {{ contexto_escopo }}"
PROMPT_ROUTER = "Roteie. {{ pergunta }}"
CONV_CFG = {"inatividade_minutos": 30, "max_historico_mensagens": 20, "max_tools_por_turno": 4,
            "max_erros_de_tool_por_turno": 2, "max_chars_resultado_no_historico": 300}


def _resp(texto="", tool_calls=(), out=40):
    return ChatResponse(text=texto, tool_calls=list(tool_calls),
                        usage=Usage(input_tokens=100, cached_tokens=0, output_tokens=out),
                        finish_reason="stop", model="fake-m", provider="fake", latency_ms=5)


def _tc(name, args, id="tc1"):
    return ToolCall(id=id, name=name, arguments=args)


class LLMQueCai:
    provider = "fake"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise ProviderUnavailable("timeout no provedor: simulado")


@pytest.fixture
async def mundo(db, escopos):
    """Renda registrada (sem meses de orçamento fechados: a reserva pede o custo mensal), tools
    sincronizadas, policies aprovadas com os tetos novos, prompts aprovados na transação."""
    async with db.service_session() as conn:
        await conn.execute(
            "insert into budget.income_summaries (scope_id, month, fixed_brl, variable_brl, "
            " variable_p10_brl, committable_brl, variable_share, months_observed) "
            "values (%s, date_trunc('month', current_date)::date, 12000, 8000, 2000, 14000, 0.4, 12)",
            (escopos.s1,))
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        for code, payload in (
            ("FOUNDATION_THRESHOLDS", None), ("INCOME_HAIRCUT", None), ("PREMISSAS_FALLBACK", None),
            ("PLANEJAMENTO_PREMISSAS", {"taxa_retirada_anual": 0.04}),
            ("EDUCACAO_PARAMS", None),
            ("AGENT_ROUTING", {"min_confidence": 0.6}),
        ):
            if await policies_repo.get_current(conn, code) is None:
                await policies_repo.set_policy(conn, code, payload or {})
            await policies_repo.approve_current(conn, code, approved_by=escopos.u1)
        # slugs próprios da F4 (não publicados nesta transação): exemplo didático sem verbete aprovado
        for code, payload in (("AGENT_CONVERSATIONS", CONV_CFG), ("EDUCACAO_EXEMPLOS", EDUCACAO_EXEMPLOS)):
            await policies_repo.set_policy(conn, code, payload)
            await policies_repo.approve_current(conn, code, approved_by=escopos.u1)
        for code, template in (("agent.assessor.system", PROMPT), ("agent.educador.system", PROMPT),
                               ("copiloto.router", PROMPT_ROUTER)):
            await prompts_repo.reabrir_rascunho(conn, code, template)
            atual = await prompts_repo.get_current(conn, code)
            await prompts_repo.approve(conn, code, version=atual.version, approved_by=escopos.u1)
    return escopos


@pytest.fixture
async def com_orcamento(db, mundo):
    """Seis meses fechados: a reserva de emergência tem custo mensal para medir."""
    async with db.service_session() as conn:
        for i in range(1, 7):
            await conn.execute(
                "insert into budget.monthly_summaries (scope_id, month, income_brl, expense_brl) "
                "values (%s, (date_trunc('month', current_date) - (%s || ' month')::interval)::date, 20000, 9000)",
                (mundo.s1, i))
    return mundo


async def _rodar(db, fake, **kw):
    turno = TurnoCopiloto(db=db, llm=fake, policies=PolicyStore(db, ttl_s=0))
    return [e async for e in turno.executar(TurnoInput(**kw))]


def _texto(eventos):
    return "".join(e.texto for e in eventos if isinstance(e, ev.Delta)).strip()


def _mensagens_tool(req: ChatRequest):
    return [m for m in req.messages if m.role == "tool"]


async def _conteudo_agente(db, conversation_id):
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select content, content_json, tool_execution_id is not null from agents.messages "
            "where conversation_id = %s and role = 'agent' order by seq", (conversation_id,))
        return await cur.fetchall()


# ---------------------------------------------------------------- erro de tool volta ao modelo
async def test_insumo_faltante_volta_ao_modelo_que_pergunta(db, mundo):
    e = mundo
    pergunta_do_modelo = "Para medir a reserva preciso do seu custo de vida mensal aproximado. Qual é?"
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.reserva_emergencia", {})]),
        _resp(texto=pergunta_do_modelo),
    ])
    eventos = await _rodar(db, fake, texto="como está minha reserva?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert isinstance(eventos[-1], ev.Done)
    assert not any(isinstance(x, ev.ToolDone) for x in eventos)
    assert len(fake.requisicoes) == 2
    erro = _mensagens_tool(fake.requisicoes[1])
    assert len(erro) == 1 and erro[0].tool_call_id == "tc1"
    payload = json.loads(erro[0].content)
    assert payload["erro"] == "insumo_faltante" and "custo" in payload["detalhe"].lower()
    (conteudo, _, com_execucao), = await _conteudo_agente(db, eventos[-1].conversation_id)
    assert conteudo == pergunta_do_modelo and not com_execucao
    assert "ilustrativ" not in conteudo.lower()               # nada foi calculado: sem rodapé


async def test_conteudo_indisponivel_volta_ao_modelo_sem_improvisar(db, mundo):
    e = mundo
    negativa = "Ainda não há material aprovado sobre taxa de administração para montar um exemplo. Posso explicar come-cotas."
    fake = FakeLLM([
        _resp(tool_calls=[_tc("educacao.exemplo_didatico", {"conceito": "taxa_administracao"})]),
        _resp(texto=negativa),
    ])
    eventos = await _rodar(db, fake, texto="me dá um exemplo de taxa de administração",
                           user_id=e.u1, scope_id=e.s1, agent_code="educador")
    assert isinstance(eventos[-1], ev.Done)
    assert len(fake.requisicoes) == 2
    payload = json.loads(_mensagens_tool(fake.requisicoes[1])[0].content)
    assert payload["erro"] == "conteudo_indisponivel"
    assert _texto(eventos) == negativa


async def test_teto_de_erros_de_tool_cai_no_texto_seguro(db, mundo):
    e = mundo
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "AGENT_CONVERSATIONS", {**CONV_CFG, "max_erros_de_tool_por_turno": 1})
        await policies_repo.approve_current(conn, "AGENT_CONVERSATIONS", approved_by=e.u1)
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.reserva_emergencia", {})]),
        _resp(tool_calls=[_tc("orcamento.reserva_emergencia", {}, id="tc2")]),   # insiste: 2º erro > teto 1
        _resp(texto="não deveria chegar aqui"),
    ])
    eventos = await _rodar(db, fake, texto="como está minha reserva?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert isinstance(eventos[-1], ev.Done)
    assert len(fake.requisicoes) == 2                        # o teto corta antes de uma 3ª chamada
    assert _texto(eventos).startswith("Antes de calcular, preciso de um dado seu")
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select count(*) from agents.guardrail_events where conversation_id = %s and kind = 'outro' "
            "and details->>'detalhe' like 'teto_de_erros_de_tool%%'", (eventos[-1].conversation_id,))
        assert (await cur.fetchone())[0] == 1


# ---------------------------------------------------------------- várias tool_calls numa resposta
async def test_duas_tool_calls_na_mesma_resposta_executam_as_duas_e_voltam_ao_provedor(db, com_orcamento):
    e = com_orcamento
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {}, id="tc1"),
                          _tc("orcamento.reserva_emergencia", {}, id="tc2")]),
        _resp(texto="Capacidade e reserva medidas; leitura abaixo."),
    ])
    eventos = await _rodar(db, fake, texto="quanto posso aportar e como está a reserva?",
                           user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    assert [x.code for x in eventos if isinstance(x, ev.ToolDone)] == \
        ["orcamento.capacidade_aporte", "orcamento.reserva_emergencia"]
    req = fake.requisicoes[1]
    assistant = [m for m in req.messages if m.role == "assistant" and m.tool_calls]
    assert len(assistant) == 1 and [c.id for c in assistant[0].tool_calls] == ["tc1", "tc2"]
    assert [m.tool_call_id for m in _mensagens_tool(req)] == ["tc1", "tc2"]
    assert sum(1 for r in done.cited_refs if r["kind"] == "tool_execution") == 2
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select tool_executions from llm.cost_ledger where ref_kind = 'conversation' and ref_id = %s",
            (done.conversation_id,))
        assert (await cur.fetchone())[0] == 2
    assert "ilustrativ" in _texto(eventos).lower()


# ---------------------------------------------------------------- encaminhar com texto do modelo
async def test_encaminhar_com_texto_do_modelo_usa_o_texto(db, mundo):
    e = mundo
    texto_modelo = "Isso é uma tese de mercado; quem mede isso com dados é o Analista. Quer que a próxima conversa seja com ele?"
    fake = FakeLLM([
        _resp(texto=texto_modelo,
              tool_calls=[ToolCall(id="h1", name="encaminhar", arguments={"agent_code": "analista", "motivo": "tese de mercado"})]),
    ])
    eventos = await _rodar(db, fake, texto="petrobras sobe com juros?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert any(isinstance(x, ev.HandoffSuggested) and x.para == "analista" for x in eventos)
    (conteudo, content_json, _), = await _conteudo_agente(db, eventos[-1].conversation_id)
    assert conteudo == texto_modelo and content_json["handoff"]["para"] == "analista"


# ---------------------------------------------------------------- histórico com dados medidos
async def test_historico_inclui_dados_medidos_da_tool_anterior(db, mundo):
    e = mundo
    primeiro = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Sua capacidade estimada aparece abaixo."),
    ])
    eventos = await _rodar(db, primeiro, texto="quanto posso aportar?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    conversa = eventos[-1].conversation_id
    segundo = FakeLLM([_resp(texto="Com esse valor, o cenário muda assim.")])
    await _rodar(db, segundo, texto="e se eu aportar metade disso?", user_id=e.u1, scope_id=e.s1, conversation_id=conversa)
    historico = [m for m in segundo.requisicoes[0].messages if m.role == "assistant"]
    assert len(historico) == 1
    assert "[dados medidos:" in historico[0].content
    assert "capacidade" in historico[0].content.lower()
    trecho = historico[0].content.split("[dados medidos:", 1)[1]
    assert len(trecho) <= CONV_CFG["max_chars_resultado_no_historico"] + 5   # truncado pela policy (+ "…]")


# ---------------------------------------------------------------- roteador com resposta curta
async def test_roteador_devolve_resposta_curta_sem_abrir_conversa(db, mundo):
    e = mundo
    curta = "Olá. Posso explicar conceitos, medir o seu orçamento ou testar hipóteses de mercado — por onde começamos?"
    fake = FakeLLM([_resp(texto=json.dumps({"agent_code": None, "confidence": 0.95, "reason": "saudação",
                                            "resposta_curta": curta}))])
    eventos = await _rodar(db, fake, texto="oi, tudo bem?", user_id=e.u1, scope_id=e.s1)
    assert isinstance(eventos[-1], ev.Clarify)
    assert eventos[-1].mensagem == curta and len(eventos[-1].opcoes) >= 3
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from agents.conversations where scope_id = %s", (e.s1,))
        assert (await cur.fetchone())[0] == 0


async def test_resposta_curta_com_vocabulario_vetado_cai_na_mensagem_padrao(db, mundo):
    e = mundo
    fake = FakeLLM([_resp(texto=json.dumps({"agent_code": None, "confidence": 0.9, "reason": "meta",
                                            "resposta_curta": "Recomendo o melhor fundo para você."}))])
    eventos = await _rodar(db, fake, texto="oi", user_id=e.u1, scope_id=e.s1)
    assert isinstance(eventos[-1], ev.Clarify)
    assert "recomendo" not in eventos[-1].mensagem.lower()


# ---------------------------------------------------------------- provedor fora do ar
async def test_provedor_indisponivel_vira_evento_erro(db, mundo):
    e = mundo
    eventos = await _rodar(db, LLMQueCai(), texto="quanto posso aportar?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert isinstance(eventos[-1], ev.Erro) and eventos[-1].tipo == "provedor_indisponivel"
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select role::text from agents.messages m join agents.conversations c on c.id = m.conversation_id "
            "where c.scope_id = %s order by m.seq", (e.s1,))
        assert [r[0] for r in await cur.fetchall()] == ["user"]   # a pergunta fica; nenhuma resposta inventada
