"""F7 — endpoints que a tela do Copiloto precisa: catálogo (agentes, chips), lista de conversas e
mensagens com proveniência. Autenticação por header de dev (conftest liga AUTH_HEADERS_DEV)."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from tests.conftest import abrir_conversa

from app.agents import conversations as convs
from app.config.policies import PolicyStore
from app.llm.fake import FakeLLM

HEADERS = lambda u, s: {"X-Plexo-User-Id": u, "X-Plexo-Scope-Id": s}  # noqa: E731


@pytest_asyncio.fixture
async def api(db):
    from app.main import criar_app
    aplicacao = criar_app(db=db, llm=FakeLLM([]), policies=PolicyStore(db, ttl_s=0))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=aplicacao), base_url="http://teste") as c:
        yield c


async def test_agents_lista_os_tres_visiveis(api, escopos):
    r = await api.get("/agents", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200
    agentes = r.json()["agentes"]
    assert {a["code"] for a in agentes} == {"assessor", "educador", "analista"}
    assert all(a["display_name"] for a in agentes)
    assert (await api.get("/agents")).status_code == 401


async def test_chips_do_yaml_filtrados_por_agente_visivel(api, db, escopos):
    h = HEADERS(escopos.u1, escopos.s1)
    r = await api.get("/chips", headers=h)
    assert r.status_code == 200
    chips = r.json()["chips"]
    # F15: os chips do YAML continuam sendo a base EDITORIAL; na frente deles entram as
    # perguntas de contexto do escopo (id `falta:<fact_key>`), com teto de política.
    editoriais = [c for c in chips if not c["id"].startswith("falta:")]
    dinamicos = [c for c in chips if c["id"].startswith("falta:")]
    assert len(editoriais) == 10 and all(c["modo"] in ("standard", "research") for c in chips)
    assert {c["id"] for c in chips if c["modo"] == "research"} == {"analise_aprofundada"}
    # pergunta de contexto é conversa normal com o Assessor, nunca modo research
    assert all(c["agente"] == "assessor" and c["modo"] == "standard" for c in dinamicos)
    assert chips[: len(dinamicos)] == dinamicos, "as perguntas do escopo vêm na frente"
    r = await api.get("/chips", params={"agente": "educador"}, headers=h)
    # filtrado por educador não traz pergunta de contexto (elas são do Assessor)
    assert [c["agente"] for c in r.json()["chips"]] == ["educador"] * 3
    assert (await api.get("/chips", params={"agente": "xyz"}, headers=h)).status_code == 422
    async with db.service_session() as conn:
        await conn.execute("update agents.agent_definitions set is_active = false where code = 'analista'")
    r = await api.get("/chips", headers=h)
    assert {c["agente"] for c in r.json()["chips"]} == {"assessor", "educador"}


async def _mensagem_user(db, escopos, conversa: str, seq: int, texto: str, scope_id: str) -> None:
    async with db.service_session() as conn:
        await convs.inserir_mensagem(conn, conversation_id=conversa, scope_id=scope_id, seq=seq, role="user", content=texto)
        # message_count é do trigger (17_agents); aqui só se força a ordem por last_message_at
        await conn.execute("update agents.conversations set last_message_at = now() + make_interval(secs => %s) "
                           "where id = %s", (seq, conversa))


async def test_conversations_lista_so_o_escopo_com_titulo_e_ordem(api, db, escopos):
    c1 = await abrir_conversa(db, escopos)
    c2 = await abrir_conversa(db, escopos, agente="educador")
    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into agents.conversations (scope_id, user_id, agent_code, plan_code_at_start) "
            "values (%s, %s, 'assessor', 'free') returning id::text", (escopos.s2, escopos.u2))
        c_alheia = (await cur.fetchone())[0]
    await _mensagem_user(db, escopos, c1, 1, "Como está a minha reserva de emergência? " + "x" * 100, escopos.s1)
    await _mensagem_user(db, escopos, c2, 1, "O que é come-cotas?", escopos.s1)
    await _mensagem_user(db, escopos, c2, 2, "E o IOF?", escopos.s1)

    r = await api.get("/conversations", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200
    conversas = r.json()["conversas"]
    ids = [c["id"] for c in conversas]
    assert c_alheia not in ids and ids[:2] == [c2, c1]          # last_message_at desc
    por_id = {c["id"]: c for c in conversas}
    assert por_id[c2]["titulo"] == "O que é come-cotas?" and por_id[c2]["message_count"] == 2
    assert len(por_id[c1]["titulo"]) <= 81 and por_id[c1]["titulo"].endswith("…")
    assert por_id[c1]["agent_code"] == "assessor" and por_id[c1]["status"] == "aberta"

    await api.post(f"/conversations/{c1}/close", headers=HEADERS(escopos.u1, escopos.s1))
    r = await api.get("/conversations", params={"status": "encerrada"}, headers=HEADERS(escopos.u1, escopos.s1))
    assert [c["id"] for c in r.json()["conversas"]] == [c1]
    assert (await api.get("/conversations", params={"status": "qualquer"}, headers=HEADERS(escopos.u1, escopos.s1))).status_code == 422


async def test_messages_devolve_cabecalho_e_proveniencia(api, db, escopos):
    c1 = await abrir_conversa(db, escopos)
    refs = [{"kind": "education_content", "slug": "come-cotas"}]
    async with db.service_session() as conn:
        await convs.inserir_mensagem(conn, conversation_id=c1, scope_id=escopos.s1, seq=1, role="user", content="oi")
        await convs.inserir_mensagem(conn, conversation_id=c1, scope_id=escopos.s1, seq=2, role="agent",
                                     content="resposta", cited_refs=refs)
    r = await api.get(f"/conversations/{c1}/messages", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["conversa"]["id"] == c1 and corpo["conversa"]["agent_code"] == "assessor" and corpo["conversa"]["status"] == "aberta"
    assert [m["role"] for m in corpo["mensagens"]] == ["user", "agent"]
    assert corpo["mensagens"][1]["cited_refs"] == refs and corpo["mensagens"][0]["cited_refs"] == []
    assert all("id" in m and "content_json" in m for m in corpo["mensagens"])
    assert (await api.get(f"/conversations/{c1}/messages", headers=HEADERS(escopos.u2, escopos.s2))).status_code == 404


async def test_todo_chip_que_a_api_oferece_e_roteavel(api, db, escopos):
    """A costura que faltava, e por onde o onboarding caiu.

    `GET /chips` põe as perguntas dinâmicas (`falta:<fact_key>`) NA FRENTE dos chips do
    YAML, e o roteador do turno só conhecia o YAML: clicar no primeiro botão da tela
    inicial devolvia `chip_desconhecido` e não abria conversa. Como quem tem fato faltando
    é o cliente NOVO, o atalho de onboarding inteiro estava morto.

    O teste anterior afirmava só que os dez ids do YAML existem — provava um lado da
    costura. Este afirma a propriedade que importa: **tudo o que a API oferece, o turno
    resolve.**
    """
    from app.agents.router import rota_por_chip

    r = await api.get("/chips", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200
    chips_oferecidos = r.json()["chips"]
    assert chips_oferecidos, "sem chip nenhum o teste não prova nada"
    # E, sobretudo, que os DINÂMICOS estejam entre eles: sem isso o teste passaria sem
    # tocar no caminho que estava quebrado — decoração com cara de prova.
    dinamicos = [c["id"] for c in chips_oferecidos if c["id"].startswith("falta:")]
    assert dinamicos, ("o escopo do teste não gerou pergunta dinâmica nenhuma; sem elas "
                       "este teste não exercita o defeito que existe para pegar")

    sem_rota = [c["id"] for c in chips_oferecidos if rota_por_chip(c["id"]) is None]
    assert not sem_rota, (
        f"a API oferece chips que o turno não sabe rotear: {sem_rota} — clicar neles "
        f"devolve 'Atalho desconhecido' sem criar conversa")

    for c in chips_oferecidos:
        rota = rota_por_chip(c["id"])
        assert rota.agent_code == c["agente"], (
            f"chip {c['id']}: a API diz agente {c['agente']}, o roteador manda para "
            f"{rota.agent_code}")
