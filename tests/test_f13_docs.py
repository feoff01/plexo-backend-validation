"""
F13a — Camada documental: documento oficial vira evidência `documentary` citável.

Regras provadas: o parser do Copom é puro (roda sem rede) e o hash prova o texto; a tool lê SÓ
`docs.v_documentos_citaveis`, então documento pendente não chega ao cliente; sem material aprovado a
tool diz que não há (`ToolConteudoIndisponivel`), nunca improvisa; a execução gera finding
`documentary` com proveniência NÃO VAZIA — o kind existe no schema desde a F5 e esta é a primeira
linha de código do projeto que o escreve; e o `cited_refs` do documento leva url e data para a tela.
"""
from __future__ import annotations

import ast
import json
import pathlib
import uuid

import pytest

from tests.conftest import abrir_conversa

from app.agents import analysis as an
from app.docs import copom
from app.tools import carregar_tools
from app.tools.contexto import oficial
from app.tools.contexto.oficial import (
    DocumentoOficialParams, DocumentoOficialResolvido, calcular_documento_oficial,
    preparar_documento_oficial,
)
from app.tools.executor import ToolContext, ToolConteudoIndisponivel

GOLDEN = pathlib.Path(__file__).parent / "golden"

carregar_tools()

LISTA = json.dumps({"conteudo": [
    {"nro_reuniao": 999, "dataReferencia": "2026-08-05", "titulo": "999ª reunião - teste"},
    {"nro_reuniao": None, "dataReferencia": "2026-06-17", "titulo": "sem número — descartado"},
]}, ensure_ascii=False)
DETALHE = json.dumps({"conteudo": [{"nro_reuniao": 999, "textoComunicado":
    "<p>O Copom decidiu <b>manter</b> a taxa Selic.</p><style>.x{}</style><p>Segundo par&aacute;grafo.</p>"}]},
    ensure_ascii=False)


# ---------------------------------------------------------------- parser (sem rede, sem banco)
def test_parse_lista_descarta_item_incompleto():
    itens = copom.parse_lista(LISTA)
    assert len(itens) == 1
    assert itens[0] == {"nro_reuniao": "999", "data": "2026-08-05", "titulo": "999ª reunião - teste"}


def test_html_para_texto_tira_marcacao_e_resolve_entidade():
    texto = copom.parse_detalhe("comunicado", DETALHE)
    assert "<p>" not in texto and "<b>" not in texto
    assert ".x{}" not in texto                       # <style> some inteiro
    assert "parágrafo" in texto                      # entidade HTML resolvida
    assert "O Copom decidiu manter a taxa Selic." in texto


def test_montar_exige_texto_e_congela_hash():
    item = copom.parse_lista(LISTA)[0]
    texto = copom.parse_detalhe("comunicado", DETALHE)
    doc = copom.montar("comunicado", item, texto)
    assert doc is not None and doc.external_id == "999"
    assert doc.sha256 == copom.hash_texto(texto) and len(doc.sha256) == 64
    assert copom.montar("comunicado", item, "") is None      # sem texto não há evidência


# ---------------------------------------------------------------- a tool
@pytest.fixture
async def documento_pendente(db, escopos):
    """Um documento APROVADO e um PENDENTE, na transação do teste."""
    aprovado, pendente = str(uuid.uuid4()), str(uuid.uuid4())
    async with db.service_session() as conn:
        await conn.execute(
            "insert into docs.sources (code, display_name, publisher, license_note) "
            "values ('f13_teste', 'Fonte F13', 'Emissor F13', 'somente teste') on conflict do nothing")
        await conn.execute(
            "insert into docs.documents (id, source_code, kind, external_id, title, published_on, url, "
            " body_text, body_sha256) values (%s, 'f13_teste', 'comunicado', %s, "
            " 'Comunicado sobre a taxa Selic', current_date, 'https://exemplo.invalido/a', "
            " 'O comitê decidiu manter a taxa Selic em patamar contracionista.', %s)",
            (aprovado, f"f13-{aprovado[:8]}", "a" * 64))
        await conn.execute(
            "insert into docs.document_reviews (document_id, decision, reviewer_id) values (%s, 'aprovado', %s)",
            (aprovado, escopos.u1))
        await conn.execute(
            "update docs.documents set review_status = 'aprovado', reviewed_by = %s, reviewed_at = now() "
            "where id = %s", (escopos.u1, aprovado))
        await conn.execute(
            "insert into docs.documents (id, source_code, kind, external_id, title, published_on, "
            " body_text, body_sha256) values (%s, 'f13_teste', 'nota', %s, "
            " 'Nota ainda não revisada sobre a taxa Selic', current_date, 'texto pendente', %s)",
            (pendente, f"f13p-{pendente[:8]}", "b" * 64))
    return {"aprovado": aprovado, "pendente": pendente}


async def test_tool_le_so_documento_aprovado(db, escopos, documento_pendente):
    """Sabotagem: documento pendente de curadoria não pode chegar ao cliente."""
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        ctx = ToolContext(conn=conn, scope_id=escopos.s1, conversation_id=None)
        resolvido = await preparar_documento_oficial(
            DocumentoOficialParams(termo="Selic", fonte="f13_teste"), ctx)
    saida = calcular_documento_oficial(resolvido)

    ids = {d.id for d in saida.documentos}
    assert documento_pendente["aprovado"] in ids
    assert documento_pendente["pendente"] not in ids
    assert all(d.trecho for d in saida.documentos)
    assert saida.evidencia_documental.n_documentos == len(saida.documentos)


async def test_tool_sem_material_aprovado_nao_improvisa(db, escopos):
    """O mesmo caminho do glossário: sem conteúdo aprovado, a tool declara — o agente não inventa."""
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        ctx = ToolContext(conn=conn, scope_id=escopos.s1, conversation_id=None)
        with pytest.raises(ToolConteudoIndisponivel):
            await preparar_documento_oficial(
                DocumentoOficialParams(termo="assunto que nenhum documento aprovado cobre zzz"), ctx)


# ---------------------------------------------------------------- evidência e citação
async def test_execucao_gera_finding_documentary_com_proveniencia(db, escopos, documento_pendente):
    """O kind `documentary` existe no schema desde a F5 e nunca tinha sido escrito. Esta é a prova —
    e a proveniência NÃO pode vir vazia: `material_needs_provenance` (20) recusaria."""
    from app.tools.executor import executar_tool

    conversation_id = await abrir_conversa(db, escopos, agente="analista")
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        resultado = await executar_tool(conn, "contexto.documento_oficial",
                                        {"termo": "Selic", "fonte": "f13_teste"},
                                        scope_id=escopos.s1, conversation_id=conversation_id)
    async with db.service_session() as conn:
        analysis_id, _ = await an.criar(conn, scope_id=escopos.s1, user_id=escopos.u1,
                                        conversation_id=conversation_id, question="por que a Selic mudou?")
        ids, _ = await an.registrar_findings(conn, analysis_id, [("contexto.documento_oficial", resultado)])
        cur = await conn.execute(
            "select kind, finding, provenance from analysis.evidence_findings "
            "where analysis_id = %s and kind = 'documentary'", (analysis_id,))
        linhas = await cur.fetchall()

    assert ids and len(linhas) == 1
    kind, finding, provenance = linhas[0]
    assert kind == "documentary"
    assert provenance and provenance[0]["documents"]           # material exige proveniência
    assert finding["fonte"] == "f13_teste" and finding["n_documentos"] >= 1


def test_cited_refs_do_documento_levam_url_e_data():
    """A tela precisa de url e data — sem isso a citação vira texto sem como conferir."""
    dados = json.loads((GOLDEN / "contexto_documento_oficial.json").read_text(encoding="utf-8"))
    saida = calcular_documento_oficial(DocumentoOficialResolvido.model_validate(dados["resolvido"]))
    refs = an.cited_refs_documentais(saida.evidencia_documental)
    assert refs and all(r["kind"] == "document" for r in refs)
    assert all(r["url"] and r["as_of"] and r["titulo"] and r["publisher"] for r in refs)


def test_documento_oficial_golden():
    dados = json.loads((GOLDEN / "contexto_documento_oficial.json").read_text(encoding="utf-8"))
    saida = calcular_documento_oficial(DocumentoOficialResolvido.model_validate(dados["resolvido"]))
    assert saida.model_dump() == dados["esperado"]


def test_tool_de_contexto_sem_literal_numerico_de_premissa():
    """Tamanho do trecho e teto de documentos são policy, não número no código."""
    permitidos = {0, 1, 2, 12, 100, 0.0, 1.0}
    arvore = ast.parse(pathlib.Path(oficial.__file__).read_text(encoding="utf-8"))
    ofensores = [n.value for n in ast.walk(arvore)
                 if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                 and not isinstance(n.value, bool) and n.value not in permitidos]
    assert ofensores == [], f"números fora de policy em {oficial.__name__}: {ofensores}"
