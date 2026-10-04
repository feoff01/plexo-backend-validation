"""
F13b — O trecho do documento vira BLOCO (nasce da tool, não da prosa do modelo) e o texto de
terceiro passa por checagem de vocabulário em tempo de resposta.

Regra que isto prova: a evidência documental deixa de depender de o modelo lembrar de citá-la —
o bloco sai do `output_payload`, com proveniência obrigatória, como todo bloco desde a F11.
"""
from __future__ import annotations

import ast
import json
import pathlib
import uuid

import pytest

from tests.test_f2_turno import _resp, _rodar, _tc, mundo  # noqa: F401  (fixture reutilizada)

from app.agents import guardrails
from app.llm.fake import FakeLLM
from app.agents.blocos import blocos_de
from app.tools.analista import expectativas
from app.tools.analista.expectativas import ExpectativasResolvida, calcular_expectativas

GOLDEN = pathlib.Path(__file__).parent / "golden"


def _saida_documento() -> dict:
    return json.loads((GOLDEN / "contexto_documento_oficial.json").read_text(encoding="utf-8"))["esperado"]


def test_bloco_citacao_nasce_da_tool():
    blocos = blocos_de("contexto.documento_oficial", _saida_documento(), execution_id="EXEC")
    assert blocos, "a tool cita documento — precisa de mapeador em blocos.py"
    citacao = blocos[0]
    assert citacao["tipo"] == "citacao"
    item = citacao["dados"]["itens"][0]
    assert item["trecho"] and item["titulo"] and item["publicado_em"]
    assert item["url"].startswith("https://")


def test_bloco_citacao_carrega_fonte_e_nota():
    """Regra da F11: sem proveniência, sem bloco."""
    for bloco in blocos_de("contexto.documento_oficial", _saida_documento(), execution_id="EXEC"):
        assert bloco["proveniencia"]["fonte"]
        assert bloco["proveniencia"]["as_of"]
        assert bloco["nota"] and "projeção de rentabilidade" not in bloco["nota"]


def test_sem_documento_nao_ha_bloco():
    """Sabotagem: payload sem documento não pode virar moldura vazia na tela."""
    assert blocos_de("contexto.documento_oficial", {"documentos": []}, execution_id="EXEC") == []


# ---------------------------------------------------------------- guardrail sobre texto de terceiro
def test_vocabulario_em_tool_acha_termo_vetado_no_texto_de_terceiro():
    """Até a F13b, NENHUM ponto do sistema olhava a saída de tool: `vocabulario()` só via texto do
    LLM. Com documento externo na tela, isto é a rede de segurança (o gate de verdade é a aprovação)."""
    payload = {"documentos": [{"titulo": "Boletim", "trecho": "Este é o melhor investimento do mercado."}],
               "nota": "trecho literal"}
    assert guardrails.vocabulario_em_tool(payload) == ["melhor investimento"]


def test_vocabulario_em_tool_ignora_numero_e_texto_limpo():
    payload = {"documentos": [{"trecho": "O comitê decidiu manter a taxa em 14,00% a.a."}], "n": 3, "ok": True}
    assert guardrails.vocabulario_em_tool(payload) == []


def test_vocabulario_em_tool_respeita_excecao_do_yaml():
    """`custo de oportunidade` é vocabulário técnico neutro — a exceção vale aqui também."""
    assert guardrails.vocabulario_em_tool({"trecho": "Avalia o custo de oportunidade da decisão."}) == []


def test_vocabulario_em_tool_varre_estrutura_aninhada():
    """O payload de uma tool é aninhado: lista de dicionários dentro de dicionário."""
    payload = {"a": {"b": [{"c": "compre agora"}]}}
    assert guardrails.vocabulario_em_tool(payload) == ["compre"]


async def test_turno_registra_vocabulario_de_tool_sem_derrubar_a_resposta(db, mundo):
    """Sabotagem: documento APROVADO cujo texto tem termo vetado que a ingestão não pegou (o CHECK
    do banco só olha `vocabulario_achados`). A resposta continua de pé — e o achado fica na trilha."""
    e = mundo
    doc = str(uuid.uuid4())
    async with db.service_session() as conn:
        await conn.execute(
            "insert into docs.sources (code, display_name, publisher, license_note) "
            "values ('f13b_teste', 'Fonte F13b', 'Emissor F13b', 'somente teste') on conflict do nothing")
        await conn.execute(
            "insert into docs.documents (id, source_code, kind, external_id, title, published_on, url, "
            " body_text, body_sha256, review_status, reviewed_by, reviewed_at) values (%s, 'f13b_teste', "
            " 'nota', %s, 'Boletim de teste', current_date, 'https://exemplo.invalido/b', "
            " 'Segundo o boletim, este seria o melhor investimento disponível.', %s, 'pendente', null, null)",
            (doc, f"f13b-{doc[:8]}", "c" * 64))
        # o gate exige trilha; `vocabulario_achados` vazio simula o termo que passou pela ingestão
        await conn.execute("insert into docs.document_reviews (document_id, decision, reviewer_id) "
                           "values (%s, 'aprovado', %s)", (doc, e.u1))
        await conn.execute("update docs.documents set review_status = 'aprovado', reviewed_by = %s, "
                           "reviewed_at = now() where id = %s", (e.u1, doc))

    fake = FakeLLM([
        _resp(tool_calls=[_tc("contexto.documento_oficial", {"fonte": "f13b_teste"})]),
        _resp(texto="O boletim citado trata do cenário; a decisão é sua."),
    ])
    eventos = await _rodar(db, fake, texto="o que dizem os boletins?", user_id=e.u1, scope_id=e.s1,
                           agent_code="analista")
    done = eventos[-1]
    assert done.nome == "done", "a resposta NÃO pode ser derrubada — o guardrail aqui só registra"

    async with db.service_session() as conn:
        cur = await conn.execute(
            "select action_taken, details->>'detalhe' from agents.guardrail_events "
            " where conversation_id = %s and kind = 'vocabulario_proibido'", (done.conversation_id,))
        linhas = await cur.fetchall()
    assert linhas, "o termo vetado no texto de terceiro tem de deixar trilha"
    assert linhas[0][0] == "registrado"
    assert "melhor investimento" in linhas[0][1]


# ---------------------------------------------------------------- expectativas de mercado (Focus)
def _resolvido_focus() -> ExpectativasResolvida:
    dados = json.loads((GOLDEN / "dados_expectativas_mercado.json").read_text(encoding="utf-8"))
    return ExpectativasResolvida.model_validate(dados["resolvido"])


def test_expectativas_golden():
    dados = json.loads((GOLDEN / "dados_expectativas_mercado.json").read_text(encoding="utf-8"))
    assert calcular_expectativas(_resolvido_focus()).model_dump(mode="json") == dados["esperado"]


def test_expectativas_declaram_a_janela_e_os_respondentes():
    """`base_calculo` é premissa: sem dizer a janela, dois números diferentes viram o mesmo."""
    saida = calcular_expectativas(_resolvido_focus())
    assert saida.janela and saida.data_coleta
    assert all(h.respondentes and h.respondentes > 0 for h in saida.horizontes)
    assert saida.evidencia.fonte == "bacen_focus" and saida.evidencia.suficiente
    assert saida.evidencia.ingestion_batch_ids, "sem lote de ingestão não há como auditar o número"


def test_expectativas_sem_horizonte_nao_vira_bloco():
    """Sabotagem: coleta vazia não pode virar gráfico vazio na tela."""
    vazio = _resolvido_focus().model_copy(update={"horizontes": []})
    saida = calcular_expectativas(vazio)
    assert saida.evidencia.suficiente is False
    assert blocos_de("dados.expectativas_mercado", saida.model_dump(mode="json"), execution_id="E") == []


def test_bloco_das_expectativas_tem_fonte_e_respondentes():
    saida = calcular_expectativas(_resolvido_focus())
    blocos = blocos_de("dados.expectativas_mercado", saida.model_dump(mode="json"), execution_id="E")
    assert blocos and blocos[0]["tipo"] == "barras"
    assert blocos[0]["proveniencia"]["fonte"] == "bacen_focus"
    assert "respondentes" in blocos[0]["dados"]["itens"][0]["detalhe"]


def test_tool_de_expectativas_sem_literal_numerico_de_premissa():
    permitidos = {0, 1, 2, 12, 100, 0.0, 1.0}
    arvore = ast.parse(pathlib.Path(expectativas.__file__).read_text(encoding="utf-8"))
    ofensores = [n.value for n in ast.walk(arvore)
                 if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                 and not isinstance(n.value, bool) and n.value not in permitidos]
    assert ofensores == [], f"números fora de policy em {expectativas.__name__}: {ofensores}"


# ---------------------------------------------------------------- regressão da citação no turno
async def test_turno_sem_tool_nao_quebra_ao_montar_cited_refs(db, mundo):
    """Regressão (CI de 2026-08-27): a linha de `cited_refs` documentais ficou FORA do laço e o
    turno estourava `UnboundLocalError` sempre que nenhuma tool rodava — resposta puramente textual,
    saudação, encaminhamento. Este é o caminho mais comum do produto."""
    e = mundo
    fake = FakeLLM([_resp(texto="Oi. Meço retorno e volatilidade de ativos cobertos. Por onde começamos?")])
    eventos = await _rodar(db, fake, texto="oi", user_id=e.u1, scope_id=e.s1, agent_code="analista")
    assert eventos[-1].nome == "done"
    assert eventos[-1].cited_refs == []


async def test_turno_com_duas_tools_cita_o_documento_da_primeira(db, mundo, documento_para_citar):
    """Regressão do mesmo bug: fora do laço, só a ÚLTIMA tool era lida — o documento citado pela
    primeira sumia do `cited_refs` sem erro nenhum (7 refs, zero `document`, no smoke da F13b)."""
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("contexto.documento_oficial", {"fonte": "f13b_ordem"}),
                          _tc("dados.expectativas_mercado", {"indicador": "Selic"})]),
        _resp(texto="O comunicado explica a decisão e o mercado projeta queda. A decisão é sua."),
    ])
    eventos = await _rodar(db, fake, texto="por que mudou e o que esperam?", user_id=e.u1,
                           scope_id=e.s1, agent_code="analista")
    done = eventos[-1]
    kinds = [r["kind"] for r in done.cited_refs]
    assert "document" in kinds, f"o documento da PRIMEIRA tool sumiu; refs: {kinds}"


@pytest.fixture
async def documento_para_citar(db, escopos):
    """Documento aprovado, para a tool de contexto ter o que citar na ordem do teste acima."""
    doc = str(uuid.uuid4())
    async with db.service_session() as conn:
        await conn.execute(
            "insert into docs.sources (code, display_name, publisher, license_note) "
            "values ('f13b_ordem', 'Fonte ordem', 'Emissor', 'teste') on conflict do nothing")
        await conn.execute(
            "insert into docs.documents (id, source_code, kind, external_id, title, published_on, url, "
            " body_text, body_sha256) values (%s, 'f13b_ordem', 'comunicado', %s, 'Comunicado sobre a Selic', "
            " current_date, 'https://exemplo.invalido/o', 'O comitê decidiu sobre a taxa Selic.', %s)",
            (doc, f"ord-{doc[:8]}", "d" * 64))
        await conn.execute("insert into docs.document_reviews (document_id, decision, reviewer_id) "
                           "values (%s, 'aprovado', %s)", (doc, escopos.u1))
        await conn.execute("update docs.documents set review_status = 'aprovado', reviewed_by = %s, "
                           "reviewed_at = now() where id = %s", (escopos.u1, doc))
    return doc
