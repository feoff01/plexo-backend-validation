"""
F3 — Agente de Contexto: extrator (conversa ENCERRADA → sinais → asserções → propostas), jobs de
manutenção (encerrar inativas, expirar, varrer execuções travadas) e API de propostas.

O LLM é roteirizado (FakeLLM devolve JSON pronto). Cada teste prova duas coisas: o que o extrator
GRAVA (com proveniência: seq → message_id, model_call, cost_ledger) e o que o BANCO RECUSA quando
alguém tenta contornar (T22 conversa aberta, T23 evidência, C22a nasce declarado, likelihood,
T24 só o próprio usuário confirma e risco exige novo suitability). Nada é aplicado em tabela
estruturada nesta fase — a proposta para, no máximo, em 'confirmada'.
"""
from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from tests.conftest import abrir_conversa

from app.agents import conversations as convs
from app.config.policies import PolicyStore
from app.db.errors import (AssertionBornConfirmed, ConversationNotEnded, EvidenceInvalid, LikelihoodRule,
                           SelfConfirmationOnly, SuitabilityRequired)
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.llm.client import ChatResponse, Usage
from app.llm.fake import FakeLLM

PROMPT_EXTRATOR = "context.extractor"
TEMPLATE_EXTRATOR = ("Extraia sinais da conversa como JSON estrito. Referencie mensagens por seq.\n"
                     "Perfil atual: {{ perfil_atual }}\nConversa:\n{{ conversa }}")

HEADERS = lambda u, s: {"X-Plexo-User-Id": u, "X-Plexo-Scope-Id": s}  # noqa: E731


def _json(obj, out=60) -> ChatResponse:
    return ChatResponse(text=json.dumps(obj, ensure_ascii=False), tool_calls=[],
                        usage=Usage(input_tokens=200, cached_tokens=0, output_tokens=out),
                        finish_reason="stop", model="fake-m", provider="fake", latency_ms=5)


def _texto(texto: str) -> ChatResponse:
    return ChatResponse(text=texto, tool_calls=[], usage=Usage(200, 0, 10), finish_reason="stop",
                        model="fake-m", provider="fake", latency_ms=5)


def _sinal(seqs=(1,), kind="mudanca_renda", confidence=0.9, summary="Cliente informou renda nova"):
    return {"kind": kind, "summary": summary, "confidence": confidence, "evidence_seqs": list(seqs)}


def _assercao(seqs=(1,), attribute="renda_mensal", value=None, modality="fato", status="declarado",
              likelihood=None, confidence=0.9, signal_index=0, subject_kind="renda"):
    item = {"subject_kind": subject_kind, "attribute": attribute, "value": value or {"amount": 12000},
            "unit": "BRL", "modality": modality, "status": status, "confidence": confidence,
            "evidence_seqs": list(seqs), "signal_index": signal_index}
    if likelihood is not None:
        item["likelihood"] = likelihood
    return item


def _proposta(signal_index=0, kind="budget_field", proposed=None):
    return {"signal_index": signal_index, "kind": kind,
            "target_ref": {"table": "budget.income_sources", "field": "amount"},
            "proposed_value": proposed or {"amount": 12000},
            "rationale": "Você mencionou uma renda mensal diferente da registrada."}


def _saida(signals=None, assertions=None, proposals=None):
    return {"signals": signals if signals is not None else [_sinal()],
            "assertions": assertions if assertions is not None else [_assercao()],
            "proposals": proposals if proposals is not None else [_proposta()]}


@pytest.fixture
async def mundo(db, escopos):
    """Policies de contexto conhecidas, cota folgada e prompt do extrator aprovado NA transação."""
    async with db.service_session() as conn:
        for code, payload in (
            ("CONTEXT_EXTRACTION", {"min_confidence_para_proposta": 0.7, "validade_proposta_dias": 30,
                                    "max_propostas_pendentes_por_escopo": 5}),
            ("CONTEXT_ASSERTIONS", {"validade_dias": {"renda_mensal": 180, "preferencia": None},
                                    "min_confidence_para_perguntar": 0.5,
                                    "min_likelihood_para_virar_objetivo": 0.8,
                                    "max_perguntas_abertas_por_escopo": 5}),
            ("AGENT_CONVERSATIONS", {"inatividade_minutos": 30, "max_historico_mensagens": 20}),
            ("JOBS_MANUTENCAO", {"execucao_travada_minutos": 15}),
            ("AGENT_QUOTAS", {"free": {"assessor": 50, "analista": 50, "educador": 50}}),
        ):
            await policies_repo.set_policy(conn, code, payload)
        if await policies_repo.get_current(conn, "LLM_BUDGETS") is None:
            await policies_repo.set_policy(conn, "LLM_BUDGETS", {"max_model_calls_por_turno": 4,
                                                                 "max_output_tokens_por_turno": 4000})
        await prompts_repo.reabrir_rascunho(conn, PROMPT_EXTRATOR, TEMPLATE_EXTRATOR)
        atual = await prompts_repo.get_current(conn, PROMPT_EXTRATOR)
        await prompts_repo.approve(conn, PROMPT_EXTRATOR, version=atual.version, approved_by=escopos.u1)
    return escopos


async def conversa_encerrada(db, e, mensagens=(("user", "Minha renda agora é 12 mil por mês"),
                                               ("agent", "Entendi. Quer que eu simule com esse valor?"))):
    """Conversa real (prompt aprovado + conversations + messages como serviço) já ENCERRADA.
    Devolve (conversation_id, {seq: message_id})."""
    cid = await abrir_conversa(db, e)
    ids = {}
    async with db.service_session() as conn:
        for seq, (role, content) in enumerate(mensagens, start=1):
            ids[seq] = await convs.inserir_mensagem(conn, conversation_id=cid, scope_id=e.s1, seq=seq,
                                                    role=role, content=content)
        assert await convs.encerrar(conn, cid)
    return cid, ids


def _policies(db):
    return PolicyStore(db, ttl_s=0)


async def _processar(db, fake, cid):
    from app.context.extractor import processar_conversa
    return await processar_conversa(db, fake, _policies(db), cid)


def _ctx(db, fake, enfileirados=None):
    async def enfileirar(conversation_id: str):
        (enfileirados if enfileirados is not None else []).append(conversation_id)
    return {"db": db, "llm": fake, "policies": _policies(db), "enfileirar": enfileirar}


# ---------------------------------------------------------------- gate T22
async def test_nao_processa_conversa_aberta(db, mundo):
    e = mundo
    cid = await abrir_conversa(db, e)      # aberta: sem ended_at
    fake = FakeLLM([_json(_saida())])
    with pytest.raises(ConversationNotEnded):
        await _processar(db, fake, cid)
    assert fake.requisicoes == [], "o LLM não pode ser chamado para conversa aberta"


# ---------------------------------------------------------------- seq → message_id + gate T23
async def test_extracao_traduz_seq_e_banco_valida_evidencia(db, mundo):
    e = mundo
    cid, ids = await conversa_encerrada(db, e)
    fake = FakeLLM([_json(_saida(signals=[_sinal(seqs=(1,)), _sinal(seqs=(99,), kind="outro")],
                                 assertions=[], proposals=[]))])
    r = await _processar(db, fake, cid)
    assert r.status == "succeeded"
    prompt_enviado = "\n".join(m.content or "" for m in fake.requisicoes[0].messages)
    assert "#1 user:" in prompt_enviado and ids[1] not in prompt_enviado, "o LLM vê seq, nunca UUID"
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select evidence_message_ids::text[] from context.signals where extraction_run_id = %s", (r.run_id,))
        linhas = await cur.fetchall()
        assert linhas == [([ids[1]],)]
        cur = await conn.execute(
            "select count(*) from audit.activity_log where action = 'context.extraction.item_descartado' "
            "and object_id = %s", (r.run_id,))
        assert (await cur.fetchone())[0] == 1
    assert len(r.descartados) == 1 and "seq" in r.descartados[0]["motivo"]
    # sabotagem: evidência de OUTRA conversa, direto no banco
    outra, outros_ids = await conversa_encerrada(db, e)
    with pytest.raises(EvidenceInvalid):
        async with db.service_session() as conn:
            await conn.execute(
                "insert into context.signals (extraction_run_id, scope_id, user_id, kind, summary, confidence, evidence_message_ids) "
                "values (%s, %s, %s, 'outro', 'x', 0.5, %s::uuid[])", (r.run_id, e.s1, e.u1, [outros_ids[1]]))


# ---------------------------------------------------------------- C22a
async def test_assercao_nasce_declarado_ou_inferido(db, mundo):
    e = mundo
    cid, ids = await conversa_encerrada(db, e)
    fake = FakeLLM([_json(_saida(assertions=[_assercao(status="confirmado"), _assercao(status="inferido")],
                                 proposals=[]))])
    r = await _processar(db, fake, cid)
    async with db.service_session() as conn:
        cur = await conn.execute("select status::text from context.assertions where signal_id in "
                                 "(select id from context.signals where extraction_run_id = %s)", (r.run_id,))
        assert [l[0] for l in await cur.fetchall()] == ["inferido"]
    assert any("confirmado" in d["motivo"] for d in r.descartados)
    with pytest.raises(AssertionBornConfirmed):
        async with db.service_session() as conn:
            await conn.execute(
                "insert into context.assertions (scope_id, user_id, subject_kind, attribute, value, modality, status, source, evidence_message_ids) "
                "values (%s, %s, 'renda', 'renda_mensal', '{\"amount\": 1}', 'fato', 'confirmado', 'conversa', %s::uuid[])",
                (e.s1, e.u1, [ids[1]]))


# ---------------------------------------------------------------- likelihood bicondicional
async def test_hipotese_sem_likelihood_e_descartada(db, mundo):
    e = mundo
    cid, ids = await conversa_encerrada(db, e)
    fake = FakeLLM([_json(_saida(assertions=[
        _assercao(attribute="aposentar_aos_55", modality="hipotese"),                       # sem likelihood → fora
        _assercao(attribute="renda_mensal", modality="fato", likelihood=0.9),               # fato COM likelihood → fora
        _assercao(attribute="trocar_de_carro", modality="intencao", likelihood=0.8, subject_kind="objetivo"),
    ], proposals=[]))])
    r = await _processar(db, fake, cid)
    async with db.service_session() as conn:
        cur = await conn.execute("select attribute, modality::text, likelihood from context.assertions "
                                 "where scope_id = %s and source = 'conversa'", (e.s1,))
        linhas = await cur.fetchall()
    assert [(l[0], l[1]) for l in linhas] == [("trocar_de_carro", "intencao")] and float(linhas[0][2]) == 0.8
    assert len(r.descartados) == 2
    with pytest.raises(LikelihoodRule):
        async with db.service_session() as conn:
            await conn.execute(
                "insert into context.assertions (scope_id, user_id, subject_kind, attribute, value, modality, source, evidence_message_ids) "
                "values (%s, %s, 'objetivo', 'x', '{}', 'hipotese', 'conversa', %s::uuid[])", (e.s1, e.u1, [ids[1]]))


# ---------------------------------------------------------------- policy CONTEXT_EXTRACTION
async def test_proposta_abaixo_do_limiar_nao_e_criada(db, mundo):
    e = mundo
    cid, _ = await conversa_encerrada(db, e)
    fake = FakeLLM([_json(_saida(signals=[_sinal(confidence=0.5)], assertions=[]))])
    r = await _processar(db, fake, cid)
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from context.signals where extraction_run_id = %s", (r.run_id,))
        assert (await cur.fetchone())[0] == 1
        cur = await conn.execute("select count(*) from context.change_proposals where scope_id = %s", (e.s1,))
        assert (await cur.fetchone())[0] == 0
    assert any("confian" in d["motivo"] for d in r.descartados)


async def test_max_propostas_pendentes_respeitado(db, mundo):
    e = mundo
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "CONTEXT_EXTRACTION", {
            "min_confidence_para_proposta": 0.7, "validade_proposta_dias": 30, "max_propostas_pendentes_por_escopo": 1})
    cid, _ = await conversa_encerrada(db, e)
    fake = FakeLLM([_json(_saida(signals=[_sinal(), _sinal(kind="novo_objetivo")], assertions=[],
                                 proposals=[_proposta(0), _proposta(1, kind="goal_create")]))])
    r = await _processar(db, fake, cid)
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from context.change_proposals where scope_id = %s and status = 'proposta'", (e.s1,))
        assert (await cur.fetchone())[0] == 1
    assert any("pendentes" in d["motivo"] for d in r.descartados)


# ---------------------------------------------------------------- regra-estrela
async def test_proposta_nunca_nasce_aplicada(db, mundo):
    e = mundo
    cid, _ = await conversa_encerrada(db, e)
    p = _proposta()
    p.update(status="aplicada", applied_at="2026-01-01T00:00:00Z", confirmed_at="2026-01-01T00:00:00Z")
    fake = FakeLLM([_json(_saida(assertions=[], proposals=[p]))])
    r = await _processar(db, fake, cid)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select status::text, confirmed_at, applied_at, expires_at >= current_date from context.change_proposals "
            "where scope_id = %s", (e.s1,))
        assert (await cur.fetchall()) == [("proposta", None, None, True)]
    assert r.proposals == 1


# ---------------------------------------------------------------- API de propostas
@pytest.fixture
async def api(db, mundo):
    import httpx
    from app.main import criar_app
    aplicacao = criar_app(db=db, llm=FakeLLM([]), policies=_policies(db))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=aplicacao), base_url="http://teste") as cliente:
        yield cliente


async def _uma_proposta(db, e, **kw):
    cid, _ = await conversa_encerrada(db, e)
    r = await _processar(db, FakeLLM([_json(_saida(assertions=[], proposals=[_proposta(**kw)]))]), cid)
    async with db.service_session() as conn:
        cur = await conn.execute("select id::text from context.change_proposals where signal_id in "
                                 "(select id from context.signals where extraction_run_id = %s)", (r.run_id,))
        return (await cur.fetchone())[0]


async def test_confirmar_pelo_proprio_funciona(db, mundo, api):
    e = mundo
    pid = await _uma_proposta(db, e)
    lista = await api.get("/proposals", headers=HEADERS(e.u1, e.s1))
    assert lista.status_code == 200 and [p["id"] for p in lista.json()["propostas"]] == [pid]
    assert lista.json()["propostas"][0]["status"] == "proposta"
    r = await api.post(f"/proposals/{pid}/confirm", headers=HEADERS(e.u1, e.s1))
    assert r.status_code == 200 and r.json()["status"] == "confirmada"
    async with db.service_session() as conn:
        cur = await conn.execute("select status::text, confirmed_by::text, applied_at from context.change_proposals where id = %s", (pid,))
        assert (await cur.fetchone()) == ("confirmada", e.u1, None)
    de_novo = await api.post(f"/proposals/{pid}/confirm", headers=HEADERS(e.u1, e.s1))
    assert de_novo.status_code == 409
    assert (await api.get("/proposals", headers=HEADERS(e.u1, e.s1))).json()["propostas"] == []


async def test_confirmar_por_terceiro_recusado(db, mundo, api):
    e = mundo
    pid = await _uma_proposta(db, e)
    r = await api.post(f"/proposals/{pid}/confirm", headers=HEADERS(e.u2, e.s1))   # mesmo escopo, outro usuário
    assert r.status_code == 403
    async with db.service_session() as conn:
        cur = await conn.execute("select status::text from context.change_proposals where id = %s", (pid,))
        assert (await cur.fetchone()) == ("proposta",)
    with pytest.raises(SelfConfirmationOnly):
        async with db.service_session() as conn:
            await conn.execute("update context.change_proposals set status = 'confirmada', confirmed_at = now(), "
                               "confirmed_by = %s where id = %s", (e.u2, pid))


async def test_escopo_alheio_nao_ve_proposta(db, mundo, api):
    e = mundo
    pid = await _uma_proposta(db, e)
    assert (await api.get("/proposals", headers=HEADERS(e.u2, e.s2))).json()["propostas"] == []
    assert (await api.post(f"/proposals/{pid}/confirm", headers=HEADERS(e.u2, e.s2))).status_code == 404
    rej = await api.post(f"/proposals/{pid}/reject", json={"note": "não é isso"}, headers=HEADERS(e.u1, e.s1))
    assert rej.status_code == 200 and rej.json()["status"] == "rejeitada"


async def test_risco_aplicado_exige_novo_suitability(db, mundo, api):
    e = mundo
    pid = await _uma_proposta(db, e, kind="suitability_risk_profile", proposed={"perfil": "moderado"})
    r = await api.post(f"/proposals/{pid}/confirm", headers=HEADERS(e.u1, e.s1))
    assert r.status_code == 200 and r.json()["status"] == "confirmada"
    assert "suitability" in r.json()["orientacao"].lower()
    async with db.service_session() as conn:
        cur = await conn.execute("select applied_at, applied_suitability_id from context.change_proposals where id = %s", (pid,))
        assert (await cur.fetchone()) == (None, None)
    with pytest.raises(SuitabilityRequired):        # T24c pelo caminho do serviço
        async with db.service_session() as conn:
            await conn.execute("update context.change_proposals set status = 'aplicada', applied_at = now() where id = %s", (pid,))


# ---------------------------------------------------------------- ciclo do run
async def test_sucesso_marca_conversa_processada(db, mundo):
    e = mundo
    cid, _ = await conversa_encerrada(db, e)
    r = await _processar(db, FakeLLM([_json(_saida(signals=[_sinal(), _sinal(kind="evento_de_vida")], proposals=[]))]), cid)
    async with db.service_session() as conn:
        cur = await conn.execute("select status::text, processed_at is not null from agents.conversations where id = %s", (cid,))
        assert (await cur.fetchone()) == ("processada", True)
        cur = await conn.execute("select status, signals_found, model_call_id is not null, finished_at is not null "
                                 "from context.extraction_runs where id = %s", (r.run_id,))
        assert (await cur.fetchone()) == ("succeeded", 2, True, True)


async def test_falha_permite_reprocesso_e_um_so_sucesso(db, mundo):
    from app.context.extractor import ConversaJaProcessada
    e = mundo
    cid, _ = await conversa_encerrada(db, e)
    fake = FakeLLM([_texto("não sei responder em json"), _texto("ainda não")])   # original + 1 reparo
    r1 = await _processar(db, fake, cid)
    assert r1.status == "failed" and len(fake.requisicoes) == 2
    async with db.service_session() as conn:
        cur = await conn.execute("select status, finished_at is not null from context.extraction_runs where id = %s", (r1.run_id,))
        assert (await cur.fetchone()) == ("failed", True)
        cur = await conn.execute("select status::text from agents.conversations where id = %s", (cid,))
        assert (await cur.fetchone()) == ("encerrada",)
        cur = await conn.execute("select count(*) from audit.activity_log where action = 'context.extraction.falhou' and object_id = %s", (r1.run_id,))
        assert (await cur.fetchone())[0] == 1
    r2 = await _processar(db, FakeLLM([_json(_saida())]), cid)
    assert r2.status == "succeeded" and r2.run_id != r1.run_id
    fake3 = FakeLLM([_json(_saida())])
    with pytest.raises(ConversaJaProcessada):
        await _processar(db, fake3, cid)
    assert fake3.requisicoes == []
    # A unicidade deixou de ser "um sucesso por conversa" e passou a ser "um sucesso por
    # TRECHO" (migration 52): escrever numa conversa encerrada agora a REABRE, e o que for dito
    # depois precisa poder ser lido. Reprocessar o MESMO trecho continua recusado — é o que
    # esta asserção prova, agora com o `ate_seq` do run que já teve sucesso.
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select ate_seq from context.extraction_runs where id = %s", (r2.run_id,))
        ate_seq = (await cur.fetchone())[0]
    with pytest.raises(psycopg.errors.UniqueViolation):     # extraction_one_success
        async with db.service_session() as conn:
            await conn.execute(
                "insert into context.extraction_runs (conversation_id, scope_id, status, ate_seq) "
                "values (%s, %s, 'succeeded', %s)", (cid, e.s1, ate_seq))


# ---------------------------------------------------------------- proveniência e custo
async def test_extracao_grava_model_call_e_cost_ledger(db, mundo):
    e = mundo
    cid, _ = await conversa_encerrada(db, e)
    fake = FakeLLM([_json(_saida())])
    r = await _processar(db, fake, cid)
    assert fake.requisicoes[0].metadata.purpose == "extracao_contexto"
    assert fake.requisicoes[0].response_format == {"type": "json_object"}
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select mc.purpose::text, mc.agent_code::text, mc.conversation_id::text, mc.scope_id::text "
            "from context.extraction_runs r join llm.model_calls mc on mc.id = r.model_call_id where r.id = %s", (r.run_id,))
        assert (await cur.fetchone()) == ("extracao_contexto", "contexto", cid, e.s1)
        cur = await conn.execute("select model_calls, output_tokens from llm.cost_ledger where ref_kind = 'job' and ref_id = %s", (r.run_id,))
        assert (await cur.fetchone()) == (1, 60)


# ---------------------------------------------------------------- dedup
async def test_dedup_nao_recria_fato_vigente(db, mundo):
    e = mundo
    cid, ids = await conversa_encerrada(db, e)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into context.assertions (scope_id, user_id, subject_kind, attribute, value, modality, source) "
            "values (%s, %s, 'renda', 'renda_mensal', '{\"amount\": 12000}', 'fato', 'formulario') returning id", (e.s1, e.u1))
        aid = (await cur.fetchone())[0]
        await conn.execute("update context.assertions set status = 'confirmado', confirmed_at = now(), confirmed_by = %s where id = %s", (e.u1, aid))
    r = await _processar(db, FakeLLM([_json(_saida(assertions=[_assercao(value={"amount": 12000})], proposals=[]))]), cid)
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from context.assertions where scope_id = %s and attribute = 'renda_mensal'", (e.s1,))
        assert (await cur.fetchone())[0] == 1
    assert any("duplicad" in d["motivo"] for d in r.descartados) and r.assertions == 0


# ---------------------------------------------------------------- jobs
async def test_expiracao_diaria(db, mundo):
    from app.jobs.tasks import expirar
    e = mundo
    cid, ids = await conversa_encerrada(db, e)
    r = await _processar(db, FakeLLM([_json(_saida(assertions=[]))]), cid)
    async with db.service_session() as conn:
        await conn.execute("update context.change_proposals set expires_at = current_date - 1 where scope_id = %s", (e.s1,))
        await conn.execute(
            "insert into context.assertions (scope_id, user_id, subject_kind, attribute, value, modality, source, valid_from, valid_until) "
            "values (%s, %s, 'renda', 'renda_mensal', '{\"amount\": 1}', 'fato', 'formulario', current_date - 100, current_date - 1)", (e.s1, e.u1))
    res = await expirar(_ctx(db, FakeLLM([])))
    assert res["assercoes"] >= 1 and res["propostas"] >= 1
    async with db.service_session() as conn:
        cur = await conn.execute("select status::text from context.change_proposals where scope_id = %s", (e.s1,))
        assert (await cur.fetchall()) == [("expirada",)]
        cur = await conn.execute("select status::text from context.assertions where scope_id = %s and value = '{\"amount\": 1}'", (e.s1,))
        assert (await cur.fetchall()) == [("obsoleto",)]


async def test_encerrar_inativas_por_policy(db, mundo):
    from app.jobs.tasks import encerrar_inativas, varrer_encerradas
    e = mundo
    antiga = await abrir_conversa(db, e)
    recente = await abrir_conversa(db, e)
    async with db.service_session() as conn:
        await convs.inserir_mensagem(conn, conversation_id=antiga, scope_id=e.s1, seq=1, role="user", content="oi")
        await convs.inserir_mensagem(conn, conversation_id=recente, scope_id=e.s1, seq=1, role="user", content="oi")
        await conn.execute("update agents.conversations set last_message_at = now() - interval '2 hours' where id = %s", (antiga,))
    ctx = _ctx(db, FakeLLM([_json(_saida(assertions=[], proposals=[]))]))
    # o job é global (pode encerrar conversas inativas que já existiam no banco de dev): a prova é
    # sobre AS DUAS conversas deste teste — a antiga encerra, a recente não
    assert await encerrar_inativas(ctx) >= 1
    async with db.service_session() as conn:
        cur = await conn.execute("select id::text, status::text, ended_at is not null from agents.conversations where id in (%s, %s) order by status", (antiga, recente))
        assert (await cur.fetchall()) == [(recente, "aberta", False), (antiga, "encerrada", True)]
    enfileirados = []
    ctx = _ctx(db, ctx["llm"], enfileirados)
    assert await varrer_encerradas(ctx) >= 1 and antiga in enfileirados and recente not in enfileirados
    from app.jobs.tasks import extrair_conversa
    r = await extrair_conversa(ctx, antiga)
    assert r["status"] == "succeeded"
    enfileirados.clear()
    await varrer_encerradas(ctx)
    assert antiga not in enfileirados, "conversa processada sai da fila"


async def test_varrer_execucoes_travadas(db, mundo):
    from app.jobs.tasks import varrer_execucoes_travadas
    from app.tools import carregar_tools
    from app.tools.registry import specs_registradas
    from app.tools.sync import sincronizar
    carregar_tools()
    e = mundo
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        cur = await conn.execute("select id from tools.tool_versions limit 1")
        tv = (await cur.fetchone())[0]
        ids = []
        for atraso in ("2 hours", "1 minute"):
            cur = await conn.execute(
                "insert into tools.tool_executions (tool_version_id, scope_id, requested_params, input_hash, started_at) "
                f"values (%s, %s, '{{}}', %s, now() - interval '{atraso}') returning id::text", (tv, e.s1, "b" * 64))
            ids.append((await cur.fetchone())[0])
    assert await varrer_execucoes_travadas(_ctx(db, FakeLLM([]))) == 1
    async with db.service_session() as conn:
        cur = await conn.execute("select status::text, finished_at is not null, error_code from tools.tool_executions where id = %s", (ids[0],))
        assert (await cur.fetchone()) == ("timeout", True, "timeout")
        cur = await conn.execute("select status::text from tools.tool_executions where id = %s", (ids[1],))
        assert (await cur.fetchone()) == ("running",)


def test_worker_settings_declara_tasks_e_crons():
    """O worker Arq é só fiação: as tasks são puras e o cron existe sem conectar em Redis."""
    from app.jobs.worker import WorkerSettings
    nomes = {f.__name__ for f in WorkerSettings.functions}
    assert {"extrair_conversa", "varrer_encerradas", "encerrar_inativas", "expirar", "varrer_execucoes_travadas"} <= nomes
    crons = {c.name for c in WorkerSettings.cron_jobs}
    assert {"varrer_encerradas", "encerrar_inativas", "expirar", "varrer_execucoes_travadas"} <= crons
    assert callable(WorkerSettings.on_startup) and callable(WorkerSettings.on_shutdown)
