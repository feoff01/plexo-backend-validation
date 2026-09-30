"""
F2b — Orquestrador do turno do Copiloto (Assessor ponta a ponta), API/SSE e regras de conversa.

O LLM é roteirizado (FakeLLM): cada teste prova o que o TURNO grava e recusa — proveniência
completa (messages ↔ tool_executions ↔ model_calls ↔ cost_ledger), paywall pela cota do banco,
guardrails de vocabulário e de orçamento, roteador (forçado/chip/auto/clarify), handoff sem abrir
conversa sozinho, 2ª opinião em decisions.*, e RLS de ponta a ponta pela API.
"""
from __future__ import annotations

import json

import pytest

from tests.conftest import TEMPLATE_MINIMO

from app.agents import eventos as ev
from app.agents.turn import TurnoCopiloto, TurnoInput, filtrar_tools
from app.config.policies import PolicyStore
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.llm.client import ChatResponse, ToolCall, Usage
from app.llm.fake import FakeLLM
from app.tools import carregar_tools
from app.tools.registry import specs_registradas
from app.tools.sync import sincronizar

carregar_tools()

PROMPT_ASSESSOR = ("Você é o Assessor. Diagnóstico e simulação; todo número é ILUSTRATIVO.\n"
                   "Contexto: {{ contexto_escopo }}")


def _resp(texto="", tool_calls=(), out=40):
    return ChatResponse(text=texto, tool_calls=list(tool_calls),
                        usage=Usage(input_tokens=100, cached_tokens=0, output_tokens=out),
                        finish_reason="stop", model="fake-m", provider="fake", latency_ms=5)


def _tc(name, args):
    return ToolCall(id="tc1", name=name, arguments=args)


@pytest.fixture
async def mundo(db, escopos):
    """Escopo com dados de orçamento, tools sincronizadas, policies aprovadas e prompts aprovados."""
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
            ("PRODUTO_REFERENCIAS", {"referencia_taxa_adm_aa": {"multimercado": 0.02}}),
            ("AGENT_ROUTING", {"min_confidence": 0.6}),
            ("AGENT_CONVERSATIONS", {"inatividade_minutos": 30, "max_historico_mensagens": 20}),
        ):
            if await policies_repo.get_current(conn, code) is None:
                await policies_repo.set_policy(conn, code, payload or {})
            await policies_repo.approve_current(conn, code, approved_by=escopos.u1)
        for code, template in (("agent.assessor.system", PROMPT_ASSESSOR),
                               ("copiloto.router", "Roteie. {{ pergunta }}")):
            await prompts_repo.reabrir_rascunho(conn, code, template)
            atual = await prompts_repo.get_current(conn, code)
            await prompts_repo.approve(conn, code, version=atual.version, approved_by=escopos.u1)
    return escopos


def _turno(db, fake):
    return TurnoCopiloto(db=db, llm=fake, policies=PolicyStore(db, ttl_s=0))


async def _rodar(db, fake, **kw):
    turno = _turno(db, fake)
    return [e async for e in turno.executar(TurnoInput(**kw))]


def _tipos(eventos):
    return [type(e).__name__ for e in eventos]


# ---------------------------------------------------------------- turno completo
async def test_turno_completo_grava_proveniencia_e_custo(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Sua capacidade estimada é R$ 14.000,00 por mês, usando o piso da renda variável."),
    ])
    eventos = await _rodar(db, fake, texto="quanto posso aportar?", user_id=e.u1, scope_id=e.s1,
                           agent_code="assessor")
    assert _tipos(eventos)[-1] == "Done"
    done = eventos[-1]
    assert any(isinstance(x, ev.ToolDone) for x in eventos)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select m.role::text, m.tool_execution_id is not null, m.model_call_id is not null, "
            "       m.content like %s, jsonb_array_length(m.cited_refs) > 0 "
            "from agents.messages m where m.conversation_id = %s order by m.seq", ("%ILUSTRATIV%", done.conversation_id))
        linhas = await cur.fetchall()
        assert [l[0] for l in linhas] == ["user", "agent"]
        assert linhas[1][1] and linhas[1][2] and linhas[1][3] and linhas[1][4]
        cur = await conn.execute(
            "select count(*) from llm.model_calls where conversation_id = %s", (done.conversation_id,))
        assert (await cur.fetchone())[0] >= 2
        cur = await conn.execute(
            "select model_calls, tool_executions from llm.cost_ledger "
            "where ref_kind = 'conversation' and ref_id = %s", (done.conversation_id,))
        mc, te = await cur.fetchone()
        assert mc >= 2 and te == 1


async def test_cota_excedida_vira_paywall_e_impressao(db, mundo):
    e = mundo
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "AGENT_QUOTAS", {"free": {"assessor": 1}})
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]), _resp(texto="ok um"),
    ])
    ok = await _rodar(db, fake, texto="primeira", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert _tipos(ok)[-1] == "Done"
    bloqueado = await _rodar(db, FakeLLM([]), texto="segunda", user_id=e.u1, scope_id=e.s1,
                             agent_code="assessor")
    assert _tipos(bloqueado)[-1] == "Paywall"
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select gate_code from analytics.paywall_impressions where scope_id = %s "
            "order by occurred_at desc limit 1", (e.s1,))
        assert (await cur.fetchone())[0] == "agente_assessor_cota"


async def test_prompt_nao_aprovado_bloqueia_antes_de_gravar(db, mundo):
    e = mundo
    async with db.service_session() as conn:
        await prompts_repo.reabrir_rascunho(conn, "agent.assessor.system", "[PENDENTE] {{ contexto_escopo }}")
    eventos = await _rodar(db, FakeLLM([]), texto="oi", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert _tipos(eventos) == ["Erro"] and eventos[0].tipo == "prompt_nao_aprovado"
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from agents.conversations where scope_id = %s", (e.s1,))
        assert (await cur.fetchone())[0] == 0


def test_filtrar_tools_por_familia_e_plano():
    import dataclasses
    specs = specs_registradas()
    cara = dataclasses.replace(next(s for s in specs if s.code == "orcamento.capacidade_aporte"),
                               min_plan="essential")
    universo = [s for s in specs if s.code != cara.code] + [cara]
    do_assessor_free = filtrar_tools(universo, familias=("orcamento", "planejamento", "produto"), plano="free")
    codes = {s.code for s in do_assessor_free}
    assert "orcamento.capacidade_aporte" not in codes            # min_plan essential filtrada no free
    assert "planejamento.projecao_objetivo" in codes
    do_educador = filtrar_tools(universo, familias=("educacao",), plano="advanced")
    assert do_educador and {s.family for s in do_educador} == {"educacao"}   # Educador não vê orçamento (T18 no app; F4 trouxe as suas)

    legacy_oculta = dataclasses.replace(next(s for s in specs if s.code == "orcamento.reserva_emergencia"),
                                        exposed_to_llm=False)
    universo_com_oculta = [s for s in specs if s.code != legacy_oculta.code] + [legacy_oculta]
    assert legacy_oculta.code not in {s.code for s in filtrar_tools(
        universo_com_oculta, familias=("orcamento", "planejamento", "produto"), plano="advanced")}


# ---------------------------------------------------------------- guardrails
async def test_guardrail_vocabulario_reescreve_e_registra(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Recomendamos aplicar tudo, é garantido."),
        _resp(texto="Comparando os cenários, a capacidade é R$ 14.000,00; a decisão é sua."),
    ])
    eventos = await _rodar(db, fake, texto="e aí?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    done = eventos[-1]
    async with db.service_session() as conn:
        cur = await conn.execute("select content from agents.messages where conversation_id = %s and role = 'agent'",
                                 (done.conversation_id,))
        (content,) = await cur.fetchone()
        assert "Recomendamos" not in content and "garantido" not in content
        cur = await conn.execute(
            "select kind, action_taken from agents.guardrail_events where conversation_id = %s", (done.conversation_id,))
        assert ("vocabulario_proibido", "reescrito") in [tuple(r) for r in await cur.fetchall()]


async def test_guardrail_bloqueia_quando_reescrita_falha(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Recomendamos o melhor fundo."),
        _resp(texto="Recomendamos mesmo assim."),
    ])
    eventos = await _rodar(db, fake, texto="?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    done = eventos[-1]
    async with db.service_session() as conn:
        cur = await conn.execute("select content from agents.messages where conversation_id = %s and role = 'agent'",
                                 (done.conversation_id,))
        (content,) = await cur.fetchone()
        assert "recomendamos" not in content.lower()
        cur = await conn.execute(
            "select action_taken from agents.guardrail_events where conversation_id = %s and kind = 'vocabulario_proibido' "
            "order by id desc limit 1", (done.conversation_id,))
        assert (await cur.fetchone())[0] == "bloqueado"


async def test_orcamento_de_chamadas_bloqueia_e_registra(db, mundo):
    e = mundo
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "LLM_BUDGETS",
                                       {"max_model_calls_por_turno": 1, "max_output_tokens_por_turno": 4000,
                                        "max_usd_por_analise": 1, "max_replans_por_analise": 2})
    fake = FakeLLM([_resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})])])
    eventos = await _rodar(db, fake, texto="?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    async with db.service_session() as conn:
        cur = await conn.execute("select content from agents.messages where conversation_id = %s and role = 'agent'",
                                 (done.conversation_id,))
        assert "orçamento" in (await cur.fetchone())[0].lower()
        cur = await conn.execute(
            "select count(*) from agents.guardrail_events where conversation_id = %s and kind = 'limite_orcamento_llm'",
            (done.conversation_id,))
        assert (await cur.fetchone())[0] == 1


# ---------------------------------------------------------------- roteador
async def test_roteador_forcado_nao_chama_llm_de_intencao(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]), _resp(texto="ok"),
    ])
    eventos = await _rodar(db, fake, texto="?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert isinstance(eventos[0], ev.Routed) and eventos[0].mode == "forced"
    assert len(fake.requisicoes) == 2
    assert fake.requisicoes[0].metadata.purpose == "parametrizacao"


async def test_roteador_chip_roteia_sem_llm(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]), _resp(texto="ok"),
    ])
    eventos = await _rodar(db, fake, texto="", chip_id="capacidade", user_id=e.u1, scope_id=e.s1)
    assert isinstance(eventos[0], ev.Routed) and eventos[0].mode == "chip"
    assert eventos[0].agent_code == "assessor"


async def test_roteador_auto_com_baixa_confianca_devolve_clarify_sem_cobrar(db, mundo):
    e = mundo
    fake = FakeLLM([_resp(texto=json.dumps({"agent_code": "analista", "confidence": 0.3, "reason": "?"}))])
    eventos = await _rodar(db, fake, texto="me ajuda", user_id=e.u1, scope_id=e.s1)
    assert _tipos(eventos)[-1] == "Clarify" and len(eventos[-1].opcoes) >= 2
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from agents.conversations where scope_id = %s", (e.s1,))
        assert (await cur.fetchone())[0] == 0     # sem conversa, sem cota


async def test_roteador_auto_roteia_com_confianca(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(texto=json.dumps({"agent_code": "assessor", "confidence": 0.92, "reason": "orçamento"})),
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="ok"),
    ])
    eventos = await _rodar(db, fake, texto="quanto posso aportar?", user_id=e.u1, scope_id=e.s1)
    assert isinstance(eventos[0], ev.Routed) and eventos[0].mode == "auto" and eventos[0].agent_code == "assessor"
    assert _tipos(eventos)[-1] == "Done"


async def test_handoff_sugere_sem_abrir_conversa_nova(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[ToolCall(id="h1", name="encaminhar",
                                   arguments={"agent_code": "analista", "motivo": "tese de mercado"})]),
    ])
    eventos = await _rodar(db, fake, texto="petrobras sobe com juros?", user_id=e.u1, scope_id=e.s1,
                           agent_code="assessor")
    assert any(isinstance(x, ev.HandoffSuggested) and x.para == "analista" for x in eventos)
    done = eventos[-1]
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from agents.conversations where scope_id = %s", (e.s1,))
        assert (await cur.fetchone())[0] == 1     # nenhuma conversa aberta em nome do usuário
        cur = await conn.execute(
            "select content_json->'handoff'->>'para' from agents.messages "
            "where conversation_id = %s and role = 'agent'", (done.conversation_id,))
        assert (await cur.fetchone())[0] == "analista"


async def test_insumo_faltante_vira_pergunta_do_agente(db, mundo):
    """F8: o insumo faltante volta ao modelo como resultado da tool e ELE formula a pergunta
    (antes: frase fixa). O que continua valendo: pergunta, não chute; nada calculado."""
    e = mundo
    fake = FakeLLM([_resp(tool_calls=[_tc("orcamento.reserva_emergencia", {})]),
                    _resp(texto="Qual é o seu custo de vida mensal aproximado? Sem ele não meço a reserva.")])
    eventos = await _rodar(db, fake, texto="como está minha reserva?", user_id=e.u1, scope_id=e.s1,
                           agent_code="assessor")
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    async with db.service_session() as conn:
        cur = await conn.execute("select content from agents.messages where conversation_id = %s and role = 'agent'",
                                 (done.conversation_id,))
        assert "custo" in (await cur.fetchone())[0].lower()      # pergunta, não chute


async def test_segunda_opiniao_grava_decisions_e_assercao(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("produto.custo_fundo",
                              {"descricao": "COE X", "taxa_adm_aa": 0.03, "classe": "multimercado",
                               "valor_aplicado_brl": 50000, "horizonte_anos": 3,
                               "indicado_por_terceiro": True})]),
        _resp(texto="O custo estimado do COE X no horizonte é R$ 4.500,00, acima da referência da classe."),
    ])
    eventos = await _rodar(db, fake, texto="meu gerente indicou o COE X, vale?", user_id=e.u1,
                           scope_id=e.s1, agent_code="assessor")
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select d.headline, (select count(*) from decisions.rationale_items r where r.record_id = d.id and r.is_material), "
            "       (select count(*) from decisions.inputs i where i.record_id = d.id) "
            "from decisions.records d where d.scope_id = %s and d.kind = 'segunda_opiniao'", (e.s1,))
        headline, materiais, insumos = await cur.fetchone()
        assert "recomend" not in headline.lower() and materiais >= 1 and insumos >= 1
        cur = await conn.execute(
            "select status::text, modality::text from context.assertions "
            "where scope_id = %s and subject_kind = 'recomendacao_externa'", (e.s1,))
        assert (await cur.fetchone()) == ("declarado", "fato")


# ---------------------------------------------------------------- API (SSE + RLS)
@pytest.fixture
async def api(db, mundo):
    import httpx
    from app.main import criar_app
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Capacidade: R$ 14.000,00."),
    ])
    aplicacao = criar_app(db=db, llm=fake, policies=PolicyStore(db, ttl_s=0))
    transport = httpx.ASGITransport(app=aplicacao)
    async with httpx.AsyncClient(transport=transport, base_url="http://teste") as cliente:
        yield cliente, fake


async def test_api_sse_eventos_em_ordem_e_close(db, mundo, api):
    cliente, _ = api
    e = mundo
    headers = {"X-Plexo-User-Id": e.u1, "X-Plexo-Scope-Id": e.s1}
    nomes = []
    async with cliente.stream("POST", "/copilot/turns",
                              json={"texto": "quanto posso aportar?", "agent_code": "assessor"},
                              headers=headers) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for linha in resp.aiter_lines():
            if linha.startswith("event: "):
                nomes.append(linha.removeprefix("event: "))
    assert nomes[0] == "routed" and nomes[-1] == "done" and "tool_done" in nomes
    # encerra a conversa
    done_data = None  # o id vem no done: refaz parse rápido? usa listagem
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select id::text from agents.conversations where scope_id = %s order by started_at desc limit 1", (e.s1,))
        conv = (await cur.fetchone())[0]
    r = await cliente.post(f"/conversations/{conv}/close", headers=headers)
    assert r.status_code == 200
    async with db.service_session() as conn:
        cur = await conn.execute("select status::text, ended_at is not null from agents.conversations where id = %s", (conv,))
        assert (await cur.fetchone()) == ("encerrada", True)


async def test_api_cliente_a_nao_le_conversa_de_b(db, mundo, api):
    cliente, _ = api
    e = mundo
    headers_a = {"X-Plexo-User-Id": e.u1, "X-Plexo-Scope-Id": e.s1}
    r = await cliente.post("/copilot/turns", params={"stream": "false"},
                           json={"texto": "quanto posso aportar?", "agent_code": "assessor"},
                           headers=headers_a)
    assert r.status_code == 200
    conv = r.json()["conversation_id"]
    ok = await cliente.get(f"/conversations/{conv}/messages", headers=headers_a)
    assert ok.status_code == 200 and len(ok.json()["mensagens"]) == 2
    headers_b = {"X-Plexo-User-Id": e.u2, "X-Plexo-Scope-Id": e.s2}
    proibido = await cliente.get(f"/conversations/{conv}/messages", headers=headers_b)
    assert proibido.status_code == 404      # RLS: para B, a conversa de A não existe
