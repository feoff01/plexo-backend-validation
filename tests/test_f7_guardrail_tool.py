"""F7 (correção) — marcação de tool vazada pelo provedor em modo thinking, nas variantes que apareceram em
produção (barras fullwidth duplas, tag truncada, valores de parâmetro soltos), e o que a tela recebe depois:
uma síntese REFEITA a partir das tools já executadas, nunca o texto do simulador do Educador."""
from __future__ import annotations

from tests.test_f4_educador import _resp, _rodar, _tc, mundo  # noqa: F401  (fixture reexportada)

from app.agents import eventos as ev
from app.agents import guardrails
from app.llm.client import ToolCall


# ---------------------------------------------------------------- limpeza
def test_limpeza_corta_variante_fullwidth_truncada_sem_vazar_parametros():
    bruto = ("<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name=\"quant.dependencia\">"
             "<｜｜DSML｜｜parameter name=\"ticker_a\">VALE3</｜｜DSML｜｜parameter>"
             "<｜｜DSML｜｜parameter name=\"ticker_b\">PETR4</｜｜DSML｜｜parameter>"
             "<｜｜DSML｜｜parameter name=\"de")
    limpo, vazou = guardrails.limpar_marcacao_de_tool(bruto)
    assert vazou and limpo == ""
    assert "VALE3" not in limpo and "PETR4" not in limpo


def test_limpeza_preserva_o_texto_anterior_e_corta_do_vazamento_em_diante():
    bruto = "A VALE3 rendeu 12,3% no período. <｜DSML｜tool_calls><｜DSML｜invoke name=\"x\"><｜DSML｜parameter name=\"a\">1"
    limpo, vazou = guardrails.limpar_marcacao_de_tool(bruto)
    assert vazou and limpo == "A VALE3 rendeu 12,3% no período."


def test_texto_seguro_diz_quantas_medicoes_e_nunca_o_nome_das_tools():
    """Este teste congelava o defeito, e um teste verde é o melhor esconderijo de um.

    A versão anterior EXIGIA que os códigos das tools aparecessem no texto ao cliente. O
    resultado, numa conversa real: "Medi o que coube neste turno
    (planejamento.projecao_objetivo, contexto.verificar_mudanca)". Nome de função não é
    informação para quem perguntou sobre a própria aposentadoria — é o sistema falando de
    si mesmo num momento em que já falhou.

    O que continua sendo verdade: dizer QUANTAS medições houve é útil, porque elas estão
    logo abaixo, com rótulo em português.
    """
    t = guardrails.texto_seguro_tool(["quant.risco_retorno", "quant.dependencia"])
    assert "2 medições" in t
    assert "quant." not in t and "_" not in t, f"código de tool vazou: {t}"
    assert "uma medição" in guardrails.texto_seguro_tool(["orcamento.capacidade_aporte"])
    assert "aporte" not in t.lower()
    assert "aporte" not in guardrails.texto_seguro_tool([]).lower()


# ---------------------------------------------------------------- turno
async def test_turno_refaz_a_sintese_quando_a_marcacao_vaza_apos_tool(db, mundo):
    e = mundo
    fake = FakeLLM_de([
        _resp(tool_calls=[_tc("educacao.glossario", {"termo": "f4-come-cotas"})]),
        _resp(texto="<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name=\"educacao__simulador\"><｜｜DSML｜｜parameter name=\"de"),
        _resp(texto="Come-cotas é a antecipação semestral do IR (fonte: f4-come-cotas)."),
    ])
    eventos = await _rodar(db, fake, texto="o que é come-cotas?", user_id=e.u1, scope_id=e.s1, agent_code="educador")
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert texto.startswith("Come-cotas é a antecipação semestral do IR")
    assert fake.requisicoes[2].tools == [] and fake.requisicoes[2].tool_choice == "none"
    assert fake.requisicoes[2].metadata.purpose == "guardrail"
    # o texto vazado NÃO volta ao modelo (ele continuaria o padrão); vai só a instrução
    assert all("DSML" not in (m.content or "") for m in fake.requisicoes[2].messages)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select action_taken::text from agents.guardrail_events where message_id = %s and kind = 'outro'",
            (done.message_id,))
        assert [r[0] for r in await cur.fetchall()] == ["reescrito"]


async def test_turno_cai_no_texto_seguro_do_agente_se_o_reparo_tambem_vaza(db, mundo):
    e = mundo
    fake = FakeLLM_de([
        _resp(tool_calls=[_tc("educacao.glossario", {"termo": "f4-come-cotas"})]),
        _resp(texto="<｜DSML｜tool_calls><｜DSML｜invoke name=\"x\"></｜DSML｜invoke></｜DSML｜tool_calls>"),
        _resp(texto="<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name=\"y\">"),
    ])
    eventos = await _rodar(db, fake, texto="o que é come-cotas?", user_id=e.u1, scope_id=e.s1, agent_code="educador")
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert "DSML" not in texto and "uma medição" in texto and "aporte" not in texto.lower()
    done = eventos[-1]
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select action_taken::text from agents.guardrail_events where message_id = %s and kind = 'outro'",
            (done.message_id,))
        assert [r[0] for r in await cur.fetchall()] == ["bloqueado"]


async def test_reparo_sem_orcamento_fica_registrado(db, mundo):
    """Com max_model_calls_por_turno apertado, o reparo não cabe: texto seguro do agente + evento
    'limite_orcamento_llm' dizendo que o reparo foi descartado (antes: `pass` silencioso)."""
    from app.db.repos import policies as policies_repo
    e = mundo
    async with db.service_session() as conn:
        atual = await policies_repo.get_current(conn, "LLM_BUDGETS")
        await policies_repo.set_policy(conn, "LLM_BUDGETS", {**atual.payload, "max_model_calls_por_turno": 2}, created_by=e.u1)
        await policies_repo.approve_current(conn, "LLM_BUDGETS", approved_by=e.u1)
    fake = FakeLLM_de([
        _resp(tool_calls=[_tc("educacao.glossario", {"termo": "f4-come-cotas"})]),
        _resp(texto="<｜DSML｜tool_calls><｜DSML｜invoke name=\"x\"></｜DSML｜invoke></｜DSML｜tool_calls>"),
    ])
    eventos = await _rodar(db, fake, texto="o que é come-cotas?", user_id=e.u1, scope_id=e.s1, agent_code="educador")
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert "uma medição" in texto and "DSML" not in texto and "educacao." not in texto
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select kind::text, action_taken::text from agents.guardrail_events where message_id = %s order by kind",
            (done.message_id,))
        assert (await cur.fetchall()) == [("limite_orcamento_llm", "registrado"), ("outro", "bloqueado")]


async def test_parametro_invalido_no_meio_da_cadeia_volta_ao_modelo_para_corrigir(db, mundo):
    """A 2ª chamada vem com campo a mais (extra=forbid). Antes: a cadeia abortava com texto genérico.
    Agora: o erro de validação volta como resultado da tool e o modelo corrige (uma vez)."""
    e = mundo
    fake = FakeLLM_de([
        _resp(tool_calls=[_tc("educacao.glossario", {"termo": "f4-come-cotas"})]),
        _resp(tool_calls=[ToolCall(id="tc2", name="educacao.glossario", arguments={"termo": "f4-come-cotas", "janela": "x"})]),
        _resp(tool_calls=[ToolCall(id="tc3", name="educacao.glossario", arguments={"termo": "f4-come-cotas"})]),
        _resp(texto="Come-cotas é a antecipação semestral do IR (fonte: f4-come-cotas)."),
    ])
    eventos = await _rodar(db, fake, texto="o que é come-cotas?", user_id=e.u1, scope_id=e.s1, agent_code="educador")
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert texto.startswith("Come-cotas é a antecipação semestral")
    devolvidos = [m for r in fake.requisicoes for m in r.messages
                  if m.role == "tool" and m.tool_call_id == "tc2" and "parametros_invalidos" in (m.content or "")]
    assert devolvidos, "o erro de validação da chamada tc2 tem de voltar ao modelo como resultado da tool"
    assert [x.code for x in eventos if isinstance(x, ev.ToolDone)] == ["educacao.glossario", "educacao.glossario"]


def FakeLLM_de(respostas):
    from app.llm.fake import FakeLLM
    return FakeLLM(respostas)
