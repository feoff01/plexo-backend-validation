"""
F4 — Educador: tools `educacao.*`, prompt aprovado, turno ponta a ponta.

Regras provadas: as tools só enxergam conteúdo APROVADO e PUBLICADO (view da migration 30); sem
conteúdo, a tool declara isso (nunca improvisa); o nível de linguagem vem da asserção confirmada
`nivel_conhecimento` ou da policy; o gate de família do BANCO (T18) vale nos dois sentidos; o
prompt real `prompts/agent.educador.system.j2` é aprovável (sem [PENDENTE], sem vocabulário vetado);
o turno cita o slug do conteúdo e grava proveniência; pergunta sobre ativo vira `encaminhar`;
glossário não recebe rodapé de simulação, simulador recebe; nenhuma premissa numérica no código.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from tests.conftest import abrir_conversa

from app.agents import eventos as ev
from app.agents import guardrails
from app.agents.turn import TurnoCopiloto, TurnoInput, filtrar_tools
from app.config.policies import PolicyStore
from app.db.errors import FamilyNotAllowed
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.db.repos.prompts import encontrar_vocabulario_proibido
from app.llm.client import ChatResponse, ToolCall, Usage
from app.llm.fake import FakeLLM
from app.tools import carregar_tools
from app.tools.educador import exemplo_didatico, glossario, juros_compostos
from app.tools.executor import ToolConteudoIndisponivel, ToolParamsInvalid, executar_tool
from app.tools.registry import spec_de, specs_registradas
from app.tools.sync import sincronizar

RAIZ = pathlib.Path(__file__).parent.parent
GOLDEN = pathlib.Path(__file__).parent / "golden"
PROMPT_EDUCADOR = (RAIZ / "prompts" / "agent.educador.system.j2").read_text(encoding="utf-8")

carregar_tools()

EDUCACAO_PARAMS = {
    "nivel_padrao": "basico", "max_itens": 3, "trecho_chars": 600,
    "prazo_max_anos": 50, "taxa_max_aa_pct": 100,
}
EDUCACAO_EXEMPLOS = {
    "valor_base_brl": 10000,
    # slugs PRÓPRIOS do teste: o banco de dev tem os verbetes reais comitados e o teste não depende deles
    "conteudo_slug": {"come_cotas": "f4-come-cotas", "taxa_administracao": "f4-taxa-adm",
                      "ir_regressivo": "f4-ir-regressivo"},
    "come_cotas": {"aliquota_curto_pct": 20, "aliquota_longo_pct": 15, "rendimento_semestre_pct": 5},
    "taxa_administracao": {"taxa_aa_pct": 2.0, "rendimento_bruto_aa_pct": 10, "anos": 10},
    "ir_regressivo": {"rendimento_aa_pct": 10, "dias_por_mes": 30, "prazo_meses_padrao": 24,
                      "faixas": [{"ate_dias": 180, "aliquota_pct": 22.5}, {"ate_dias": 360, "aliquota_pct": 20},
                                 {"ate_dias": 720, "aliquota_pct": 17.5}, {"ate_dias": None, "aliquota_pct": 15}]},
}


def _resp(texto="", tool_calls=(), out=40):
    return ChatResponse(text=texto, tool_calls=list(tool_calls),
                        usage=Usage(input_tokens=100, cached_tokens=0, output_tokens=out),
                        finish_reason="stop", model="fake-m", provider="fake", latency_ms=5)


def _tc(name, args):
    return ToolCall(id="tc1", name=name, arguments=args)


async def _rodar(db, fake, **kw):
    turno = TurnoCopiloto(db=db, llm=fake, policies=PolicyStore(db, ttl_s=0))
    return [e async for e in turno.executar(TurnoInput(**kw))]


async def _publicar(conn, revisor: str, slug: str, title: str, body: str, *, level="basico", tags=()):
    """Conteúdo aprovado + publicado com a trilha que o gate da 30 exige — tudo na transação do teste."""
    cur = await conn.execute(
        "insert into content.education_contents (slug, title, body_md, level, tags) "
        "values (%s, %s, %s, %s, %s) returning id::text", (slug, title, body, level, list(tags)))
    cid = (await cur.fetchone())[0]
    await conn.execute(
        "insert into content.compliance_reviews (subject_kind, subject_id, decision, reviewer_id) "
        "values ('education', %s, 'approved', %s)", (cid, revisor))
    await conn.execute(
        "update content.education_contents set review_status = 'approved', reviewed_by = %s, "
        "reviewed_at = now(), published_at = now() where id = %s", (revisor, cid))
    return cid


@pytest.fixture
async def mundo(db, escopos):
    """Tools sincronizadas, policies do Educador aprovadas, prompts (o REAL do Educador) aprovados,
    dois verbetes publicados e um rascunho — estado próprio do teste, nunca do banco de dev."""
    e = escopos
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        for code, payload in (("EDUCACAO_PARAMS", EDUCACAO_PARAMS), ("EDUCACAO_EXEMPLOS", EDUCACAO_EXEMPLOS),
                              ("AGENT_ROUTING", {"min_confidence": 0.6}),
                              ("AGENT_CONVERSATIONS", {"inatividade_minutos": 30, "max_historico_mensagens": 20,
                                                       "max_tools_por_turno": 2})):
            await policies_repo.set_policy(conn, code, payload)
            await policies_repo.approve_current(conn, code, approved_by=e.u1)
        for code, template in (("agent.educador.system", PROMPT_EDUCADOR),
                               ("copiloto.router", "Roteie. {{ pergunta }}")):
            await prompts_repo.reabrir_rascunho(conn, code, template)
            atual = await prompts_repo.get_current(conn, code)
            await prompts_repo.approve(conn, code, version=atual.version, approved_by=e.u1)
        await _publicar(conn, e.u1, "f4-come-cotas", "F4 Come-cotas",
                        "O come-cotas é a antecipação semestral do imposto de renda em fundos. " * 20,
                        tags=("f4-fundos", "f4-imposto"))
        await _publicar(conn, e.u1, "f4-ir-regressivo", "F4 IR regressivo na renda fixa",
                        "A alíquota cai conforme o prazo da aplicação.", level="intermediario",
                        tags=("f4-imposto", "f4-renda-fixa"))
        await conn.execute(
            "insert into content.education_contents (slug, title, body_md, tags) "
            "values ('f4-debenture', 'F4 Debênture incentivada', 'rascunho não aprovado', array['f4-imposto'])")
    return e


# ---------------------------------------------------------------- registro
def test_registro_tem_as_tres_tools_do_educador():
    codes = {s.code for s in specs_registradas()}
    assert {"educacao.glossario", "educacao.simulador_juros_compostos", "educacao.exemplo_didatico"} <= codes
    for code in ("educacao.glossario", "educacao.simulador_juros_compostos", "educacao.exemplo_didatico"):
        s = spec_de(code)
        assert s.family == "educacao" and s.min_plan == "free" and "PENDENTE" not in s.description
        assert not hasattr(s.output_model, "indicado_por_terceiro")   # nunca dispara 2ª opinião


def test_glossario_nao_emite_numero_e_simulador_emite():
    assert spec_de("educacao.glossario").emite_numero is False
    assert spec_de("educacao.simulador_juros_compostos").emite_numero is True
    assert spec_de("educacao.exemplo_didatico").emite_numero is True


def test_filtrar_tools_do_educador_so_ve_familia_educacao():
    do_educador = filtrar_tools(specs_registradas(), familias=("educacao",), plano="free")
    assert do_educador and {s.family for s in do_educador} == {"educacao"}
    do_assessor = filtrar_tools(specs_registradas(), familias=("orcamento", "planejamento", "produto"), plano="free")
    assert not any(s.family == "educacao" for s in do_assessor)


# ---------------------------------------------------------------- prompt real
def test_prompt_educador_real_sem_pendente_nem_vocabulario_proibido():
    assert "[PENDENTE" not in PROMPT_EDUCADOR
    assert encontrar_vocabulario_proibido(PROMPT_EDUCADOR) == []
    assert "{{ contexto_escopo }}" in PROMPT_EDUCADOR


def test_verbetes_do_seed_sem_vocabulario_proibido():
    seed = (RAIZ / "seeds" / "dev.sql").read_text(encoding="utf-8")
    assert "content.education_contents" in seed
    assert encontrar_vocabulario_proibido(seed) == []


# ---------------------------------------------------------------- glossário
async def test_glossario_ignora_conteudo_nao_aprovado(db, mundo):
    e = mundo
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "educacao.glossario", {"termo": "F4 Debênture incentivada"},
                                scope_id=e.s1, conversation_id=None)
    assert r.output.encontrado is False and r.output.itens == []


async def test_glossario_encontra_por_slug_titulo_e_tag_sob_plexo_app(db, mundo):
    e = mundo
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        por_slug = await executar_tool(conn, "educacao.glossario", {"termo": "f4-come-cotas"}, scope_id=e.s1, conversation_id=None)
        por_titulo = await executar_tool(conn, "educacao.glossario", {"termo": "F4 COME-Cotas"}, scope_id=e.s1, conversation_id=None)
        por_tag = await executar_tool(conn, "educacao.glossario", {"termo": "f4-imposto"}, scope_id=e.s1, conversation_id=None)
    assert por_slug.output.encontrado and por_slug.output.itens[0].slug == "f4-come-cotas"
    assert por_titulo.output.itens[0].slug == "f4-come-cotas"
    assert {i.slug for i in por_tag.output.itens} == {"f4-come-cotas", "f4-ir-regressivo"}   # o rascunho fica fora
    assert len(por_slug.output.itens[0].trecho) <= EDUCACAO_PARAMS["trecho_chars"] + 1   # "…"
    assert por_slug.output.slugs == ["f4-come-cotas"]


async def test_glossario_sem_assercao_usa_nivel_padrao_da_policy(db, mundo):
    e = mundo
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "educacao.glossario", {"termo": "f4-come-cotas"}, scope_id=e.s1, conversation_id=None)
    assert (r.output.nivel_usado, r.output.fonte_nivel) == ("basico", "policy")


async def test_glossario_usa_nivel_da_assercao_confirmada(db, mundo):
    e = mundo
    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into context.assertions (scope_id, user_id, subject_kind, attribute, value, modality, "
            " status, source) values (%s, %s, 'titular', 'nivel_conhecimento', %s, 'fato', 'declarado', 'onboarding') "
            "returning id", (e.s1, e.u1, json.dumps({"text": "avancado"})))
        aid = (await cur.fetchone())[0]
        # C22a: nasce declarado; a confirmação é ato posterior do PRÓPRIO usuário
        await conn.execute(
            "update context.assertions set status = 'confirmado', confirmed_at = now(), confirmed_by = %s "
            "where id = %s", (e.u1, aid))
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "educacao.glossario", {"termo": "f4-come-cotas"}, scope_id=e.s1, conversation_id=None)
        forcado = await executar_tool(conn, "educacao.glossario", {"termo": "f4-come-cotas", "nivel": "basico"},
                                      scope_id=e.s1, conversation_id=None)
    assert (r.output.nivel_usado, r.output.fonte_nivel) == ("avancado", "assercao_confirmada")
    assert (forcado.output.nivel_usado, forcado.output.fonte_nivel) == ("basico", "parametro")


async def test_glossario_de_outro_escopo_nao_ve_assercao_alheia(db, mundo):
    """RLS: a asserção de s1 não vaza para s2 (o nível cai para a policy)."""
    e = mundo
    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into context.assertions (scope_id, user_id, subject_kind, attribute, value, modality, status, source) "
            "values (%s, %s, 'titular', 'nivel_conhecimento', %s, 'fato', 'declarado', 'onboarding') returning id",
            (e.s1, e.u1, json.dumps({"text": "avancado"})))
        aid = (await cur.fetchone())[0]
        await conn.execute("update context.assertions set status='confirmado', confirmed_at=now(), confirmed_by=%s where id=%s",
                           (e.u1, aid))
    async with db.app_session(user_id=e.u2, scope_id=e.s2) as conn:
        r = await executar_tool(conn, "educacao.glossario", {"termo": "f4-come-cotas"}, scope_id=e.s2, conversation_id=None)
    assert r.output.fonte_nivel == "policy"


# ---------------------------------------------------------------- gates do banco (T18 nos dois sentidos)
async def test_educador_nao_roda_tool_de_orcamento(db, mundo):
    """O gate vive no INSERT em tool_executions: a tool precisa chegar lá (com renda no escopo) para o banco recusar."""
    e = mundo
    async with db.service_session() as conn:
        await conn.execute(
            "insert into budget.income_summaries (scope_id, month, fixed_brl, variable_brl, variable_p10_brl, "
            " committable_brl, months_observed) values (%s, date_trunc('month', current_date)::date, 10000, 0, 0, 10000, 6)",
            (e.s1,))
        await policies_repo.approve_current(conn, "INCOME_HAIRCUT", approved_by=e.u1)
    conversa = await abrir_conversa(db, e, agente="educador")
    with pytest.raises(FamilyNotAllowed):
        async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
            await executar_tool(conn, "orcamento.capacidade_aporte", {}, scope_id=e.s1, conversation_id=conversa)


async def test_assessor_nao_roda_tool_de_educacao(db, mundo):
    e = mundo
    conversa = await abrir_conversa(db, e, agente="assessor")
    with pytest.raises(FamilyNotAllowed):
        async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
            await executar_tool(conn, "educacao.glossario", {"termo": "f4-come-cotas"}, scope_id=e.s1, conversation_id=conversa)


# ---------------------------------------------------------------- simulador
async def test_simulador_recusa_prazo_acima_da_policy(db, mundo):
    e = mundo
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        with pytest.raises(ToolParamsInvalid):
            await executar_tool(conn, "educacao.simulador_juros_compostos",
                                {"aporte_mensal_brl": 500, "taxa_anual_pct": 10, "prazo_anos": 99},
                                scope_id=e.s1, conversation_id=None)


async def test_simulador_ponta_a_ponta(db, mundo):
    e = mundo
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "educacao.simulador_juros_compostos",
                                {"valor_inicial_brl": 1000, "aporte_mensal_brl": 100, "taxa_anual_pct": 12, "prazo_anos": 2},
                                scope_id=e.s1, conversation_id=None)
    o = r.output
    assert o.total_aportado_brl == pytest.approx(1000 + 100 * 24)
    assert o.montante_final_brl > o.total_aportado_brl
    assert o.juros_totais_brl == pytest.approx(o.montante_final_brl - o.total_aportado_brl, abs=0.02)
    assert [s.ano for s in o.serie_anual] == [1, 2]
    assert o.serie_anual[-1].montante_brl == pytest.approx(o.montante_final_brl)


# ---------------------------------------------------------------- exemplo didático
async def test_exemplo_didatico_exige_conteudo_aprovado(db, mundo):
    e = mundo
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        with pytest.raises(ToolConteudoIndisponivel):   # 'f4-taxa-adm' não foi publicado neste mundo
            await executar_tool(conn, "educacao.exemplo_didatico", {"conceito": "taxa_administracao"},
                                scope_id=e.s1, conversation_id=None)
        r = await executar_tool(conn, "educacao.exemplo_didatico", {"conceito": "come_cotas"},
                                scope_id=e.s1, conversation_id=None)
    assert r.output.slug == "f4-come-cotas" and r.output.conceito == "come_cotas"
    assert r.output.linhas and all(l.valor_brl >= 0 for l in r.output.linhas)


# ---------------------------------------------------------------- turno ponta a ponta (FakeLLM)
async def test_turno_educador_cita_slug_e_grava_proveniencia_sem_rodape_de_simulacao(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("educacao.glossario", {"termo": "f4-come-cotas"})]),
        _resp(texto="Come-cotas é a antecipação semestral do imposto em fundos (fonte: f4-come-cotas)."),
    ])
    eventos = await _rodar(db, fake, texto="o que é come-cotas?", user_id=e.u1, scope_id=e.s1, agent_code="educador")
    assert isinstance(eventos[-1], ev.Done)
    done = eventos[-1]
    assert any(isinstance(x, ev.ToolDone) and x.code == "educacao.glossario" for x in eventos)
    assert {"kind": "education_content", "slug": "f4-come-cotas"} in done.cited_refs
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert "ilustrativ" not in texto.lower()          # glossário não é simulação
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select c.agent_code::text, m.tool_execution_id is not null, m.model_call_id is not null "
            "from agents.messages m join agents.conversations c on c.id = m.conversation_id "
            "where m.conversation_id = %s and m.role = 'agent'", (done.conversation_id,))
        assert (await cur.fetchone()) == ("educador", True, True)
        cur = await conn.execute(
            "select tool_executions from llm.cost_ledger where ref_kind = 'conversation' and ref_id = %s",
            (done.conversation_id,))
        assert (await cur.fetchone())[0] == 1


async def test_turno_educador_simulador_recebe_rodape_ilustrativo(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("educacao.simulador_juros_compostos",
                              {"aporte_mensal_brl": 500, "taxa_anual_pct": 10, "prazo_anos": 20})]),
        _resp(texto="Com esses parâmetros o montante estimado aparece na tabela abaixo."),
    ])
    eventos = await _rodar(db, fake, texto="500 por mês a 10% por 20 anos?", user_id=e.u1, scope_id=e.s1,
                           agent_code="educador")
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert "ilustrativ" in texto.lower()


async def test_turno_educador_pergunta_sobre_ativo_encaminha_sem_opinar(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[ToolCall(id="h1", name="encaminhar",
                                   arguments={"agent_code": "analista", "motivo": "tese sobre ativo específico"})]),
    ])
    eventos = await _rodar(db, fake, texto="Petrobras é boa compra?", user_id=e.u1, scope_id=e.s1, agent_code="educador")
    assert any(isinstance(x, ev.HandoffSuggested) and x.para == "analista" for x in eventos)
    assert not any(isinstance(x, ev.ToolDone) for x in eventos)
    done = eventos[-1]
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from decisions.records where scope_id = %s", (e.s1,))
        assert (await cur.fetchone())[0] == 0           # o Educador não produz decisão
        cur = await conn.execute("select count(*) from agents.conversations where scope_id = %s", (e.s1,))
        assert (await cur.fetchone())[0] == 1
        assert done.conversation_id


async def test_turno_educador_sem_conteudo_aprovado_diz_que_nao_ha(db, mundo):
    e = mundo
    # F8: `conteudo_indisponivel` volta ao modelo como resultado da tool e ele redige a negativa
    # (antes: frase fixa sem síntese). Continua valendo: nada calculado, nenhum número improvisado.
    fake = FakeLLM([
        _resp(tool_calls=[_tc("educacao.exemplo_didatico", {"conceito": "taxa_administracao"})]),
        _resp(texto="Ainda não há conteúdo aprovado sobre taxa de administração para montar um exemplo com números."),
    ])
    eventos = await _rodar(db, fake, texto="me dá um exemplo de taxa de administração",
                           user_id=e.u1, scope_id=e.s1, agent_code="educador")
    assert isinstance(eventos[-1], ev.Done)
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert "conteúdo aprovado" in texto.lower()
    assert len(fake.requisicoes) == 2                   # o erro voltou ao modelo; nenhuma execução gravada
    assert not any(isinstance(x, ev.ToolDone) for x in eventos)
    assert "ilustrativ" not in texto.lower()            # nada foi calculado


async def test_turno_educador_sem_prompt_aprovado_falha_no_gate(db, escopos):
    e = escopos
    async with db.service_session() as conn:
        await prompts_repo.reabrir_rascunho(conn, "agent.educador.system", "[PENDENTE] {{ contexto_escopo }}")
    eventos = await _rodar(db, FakeLLM([]), texto="o que é come-cotas?", user_id=e.u1, scope_id=e.s1,
                           agent_code="educador")
    assert isinstance(eventos[-1], ev.Erro) and eventos[-1].tipo == "prompt_nao_aprovado"


# ---------------------------------------------------------------- cadeia de tools e vazamento de marcação
async def test_turno_educador_encadeia_glossario_e_simulador_ate_o_limite_da_policy(db, mundo):
    """max_tools_por_turno=2: glossário → simulador → texto. Ambas as execuções ficam na proveniência;
    uma terceira tool não é oferecida (a síntese final vai sem tools)."""
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("educacao.glossario", {"termo": "f4-come-cotas"})]),
        _resp(tool_calls=[ToolCall(id="tc2", name="educacao.simulador_juros_compostos",
                                   arguments={"aporte_mensal_brl": 500, "taxa_anual_pct": 10, "prazo_anos": 20})]),
        _resp(texto="Juros sobre juros (fonte: f4-come-cotas). Montante na tabela. ILUSTRATIVO."),
    ])
    eventos = await _rodar(db, fake, texto="explica e simula", user_id=e.u1, scope_id=e.s1, agent_code="educador")
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    assert [x.code for x in eventos if isinstance(x, ev.ToolDone)] == ["educacao.glossario", "educacao.simulador_juros_compostos"]
    assert sum(1 for c in done.cited_refs if c["kind"] == "tool_execution") == 2
    assert {"kind": "education_content", "slug": "f4-come-cotas"} in done.cited_refs
    assert fake.requisicoes[1].tools and fake.requisicoes[1].tool_choice == "auto"     # 1ª síntese ainda oferece tools
    assert fake.requisicoes[2].tools == [] and fake.requisicoes[2].tool_choice == "none"  # limite atingido
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select tool_executions from llm.cost_ledger where ref_kind = 'conversation' and ref_id = %s",
            (done.conversation_id,))
        assert (await cur.fetchone())[0] == 2


def test_guardrail_remove_marcacao_de_tool_vazada_preservando_o_texto():
    bruto = ("Juros compostos rendem sobre juros. <｜DSML｜tool_calls><｜DSML｜invoke name=\"x\">"
             "<｜DSML｜parameter name=\"a\">1</｜DSML｜parameter></｜DSML｜invoke>"
             "</｜DSML｜tool_calls> Quer um exemplo?")
    limpo, vazou = guardrails.limpar_marcacao_de_tool(bruto)
    assert vazou and limpo == "Juros compostos rendem sobre juros. Quer um exemplo?"
    assert guardrails.limpar_marcacao_de_tool("texto normal") == ("texto normal", False)


async def test_turno_nunca_entrega_marcacao_de_tool_ao_cliente(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("educacao.glossario", {"termo": "f4-come-cotas"})]),
        _resp(texto="<｜DSML｜tool_calls><｜DSML｜invoke name=\"educacao__simulador\"></｜DSML｜invoke></｜DSML｜tool_calls>"),
        # F7: o turno tenta UM reparo sem tools; aqui ele vaza de novo → texto seguro + 'bloqueado'
        _resp(texto="<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name=\"educacao__simulador\">"),
    ])
    eventos = await _rodar(db, fake, texto="simula", user_id=e.u1, scope_id=e.s1, agent_code="educador")
    done = eventos[-1]
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert "DSML" not in texto and texto.strip()
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select content like '%%DSML%%', (select count(*) from agents.guardrail_events g "
            " where g.message_id = m.id and g.kind = 'outro' and g.action_taken = 'bloqueado') "
            "from agents.messages m where m.id = %s", (done.message_id,))
        assert (await cur.fetchone()) == (False, 1)


# ---------------------------------------------------------------- golden masters (parte pura)
@pytest.mark.parametrize("nome,calcular,resolvido_model", [
    ("educacao_juros_compostos", juros_compostos.calcular_juros, juros_compostos.JurosResolvida),
    ("educacao_exemplo_come_cotas", exemplo_didatico.calcular_exemplo, exemplo_didatico.ExemploResolvido),
    ("educacao_exemplo_ir_regressivo", exemplo_didatico.calcular_exemplo, exemplo_didatico.ExemploResolvido),
    ("educacao_exemplo_taxa_administracao", exemplo_didatico.calcular_exemplo, exemplo_didatico.ExemploResolvido),
    ("educacao_glossario", glossario.montar_glossario, glossario.GlossarioResolvido),
])
def test_golden_master(nome, calcular, resolvido_model):
    dados = json.loads((GOLDEN / f"{nome}.json").read_text(encoding="utf-8"))
    saida = calcular(resolvido_model.model_validate(dados["resolvido"]))
    assert saida.model_dump(mode="json") == dados["esperado"], (
        "Saída difere do golden — mudança de número exige justificativa no commit.")


# ---------------------------------------------------------------- config-first
@pytest.mark.parametrize("modulo", [glossario, juros_compostos, exemplo_didatico])
def test_tools_do_educador_sem_literal_numerico_de_premissa(modulo):
    permitidos = {0, 1, 2, 12, 100, 0.0, 1.0}   # identidade, aridade, meses/ano, percentual
    arvore = ast.parse(pathlib.Path(modulo.__file__).read_text(encoding="utf-8"))
    ofensores = [n.value for n in ast.walk(arvore)
                 if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                 and not isinstance(n.value, bool) and n.value not in permitidos]
    assert ofensores == [], f"números fora de policy em {modulo.__name__}: {ofensores}"
