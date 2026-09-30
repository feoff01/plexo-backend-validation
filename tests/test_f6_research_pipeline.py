"""
F6 — Analista research (DAG). Parte b: planner (LLM → plano), síntese do relatório, pipeline assíncrono,
turno em modo research, job/CLI e API.

Regras provadas: o planner recebe o catálogo filtrado por família/plano e grava `model_calls` com
`purpose='planejamento'` e `analysis_id`; JSON inválido → 1 reparo → análise `failed` com audit; o replan
recebe as falhas anteriores; o relatório tem `evidence_hash` determinístico, é imutável, vira mensagem do
agente NA conversa com `cited_refs` e custo em `cost_ledger ref_kind='analysis'`; vocabulário vetado é
reescrito/bloqueado ANTES do INSERT; orçamento estourado ⇒ `blocked` com texto seguro; o turno research
cria a análise, enfileira e não executa tool nem LLM; agente ≠ analista não tem modo research; a API
esconde análise de outro escopo (404) e a RLS das filhas (32) vale sob plexo_app; nada em `decisions`.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import abrir_conversa
from tests.test_f5_analista_tools import mundo  # noqa: F401
from tests.test_f6_research import CFG_RESEARCH, PERIODO, _no, _plano, mundo6  # noqa: F401

from app.agents import analysis as an
from app.agents import eventos as ev
from app.agents.turn import TurnoCopiloto, TurnoInput
from app.config.policies import PolicyStore
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.db.repos.prompts import encontrar_vocabulario_proibido
from app.llm.client import ChatResponse, ToolCall, Usage
from app.llm.fake import FakeLLM
from app.llm.prompts import variaveis_do_template
from app.main import criar_app

RAIZ = pathlib.Path(__file__).parent.parent
PROMPT_PLANNER = (RAIZ / "prompts" / "analista.planner.j2").read_text(encoding="utf-8")
PROMPT_REPORT = (RAIZ / "prompts" / "analista.report.j2").read_text(encoding="utf-8")
HEADERS = lambda u, s: {"X-Plexo-User-Id": u, "X-Plexo-Scope-Id": s}  # noqa: E731


def _resp(texto="", tool_calls=(), out=40):
    return ChatResponse(text=texto, tool_calls=list(tool_calls), usage=Usage(input_tokens=100, cached_tokens=0, output_tokens=out),
                        finish_reason="stop", model="fake-m", provider="fake", latency_ms=5)


def _json(obj):
    return _resp(json.dumps(obj, ensure_ascii=False))


PLANO_OK = _plano(_no("ret", params={"ticker": "F5PETR", "data_referencia": "2024-01-17", **PERIODO}),
                  _no("corr", tool="quant.dependencia", params={"ticker_a": "F5PETR", "ticker_b": "F5VALE", "janela_dias": 60,
                                                              "data_referencia": "2024-01-17"}, criticality="important"))
RELATORIO = ("## Pergunta\nPETR4 em janeiro de 2024.\n\n## Métricas\nRetorno acumulado conforme a evidência, as_of 2024-01-17, "
             "fonte B3, 12 observações, método log. Retorno passado não indica retorno futuro; correlação não é causalidade.\n\n"
             "Relatório descritivo sobre dados passados, ILUSTRATIVO; retorno passado não indica retorno futuro, correlação não é "
             "causalidade e isto não é indicação de compra ou venda. A decisão é sua.")


@pytest.fixture
async def mundo7(db, mundo6):
    """mundo6 + prompts REAIS do planner e do relatório aprovados na transação + pricing do provedor fake."""
    e = mundo6["e"]
    async with db.service_session() as conn:
        for code, template in (("analista.planner", PROMPT_PLANNER), ("analista.report", PROMPT_REPORT)):
            await prompts_repo.reabrir_rascunho(conn, code, template)
            atual = await prompts_repo.get_current(conn, code)
            await prompts_repo.approve(conn, code, version=atual.version, approved_by=e.u1)
        atual = await policies_repo.get_current(conn, "LLM_PRICING")
        payload = dict(atual.payload) if atual else {}
        payload["fake"] = {"fake-m": {"usd_por_m_input": 1.0, "usd_por_m_cache_hit": 0.1, "usd_por_m_output": 2.0}}
        await policies_repo.set_policy(conn, "LLM_PRICING", payload)
    return mundo6


def _policies(db):
    return PolicyStore(db, ttl_s=0)


async def _pipeline(db, fake, mundo7):
    from app.analysis.pipeline import executar_analise

    return await executar_analise(db, fake, _policies(db), mundo7["aid"])


async def _status(db, aid):
    async with db.service_session() as conn:
        cur = await conn.execute("select status::text, replan_count from analysis.analyses where id = %s", (aid,))
        return await cur.fetchone()


# ---------------------------------------------------------------- prompts
def test_prompts_f6_aprovaveis():
    for texto in (PROMPT_PLANNER, PROMPT_REPORT):
        assert "[PENDENTE" not in texto and encontrar_vocabulario_proibido(texto) == []
    assert variaveis_do_template(PROMPT_PLANNER) == ["catalogo_tools", "cutoff_date", "falhas_anteriores", "max_tasks", "pergunta"]
    assert variaveis_do_template(PROMPT_REPORT) == ["avisos", "cutoff_date", "findings", "objetivo", "pergunta"]
    baixo = PROMPT_REPORT.lower()
    assert "retorno passado não indica" in baixo and "correlação não é causalidade" in baixo and "ilustrativ" in baixo


# ---------------------------------------------------------------- planner
async def test_planner_recebe_catalogo_filtrado_e_grava_model_call_planejamento(db, mundo7):
    from app.analysis import planner

    fake = FakeLLM([_json(PLANO_OK)])
    a = await an.carregar_service(db, mundo7["aid"])
    plano, descartados, call_id = await planner.planejar(db, fake, _policies(db), a, cfg=mundo7["cfg"])
    assert [n.node_id for n in plano.nodes] == ["ret", "corr"] and descartados == [] and call_id
    system = fake.requisicoes[0].messages[0].content
    assert "quant.event_study" in system and "dados.serie_indice" in system and "orcamento.reserva_emergencia" not in system
    assert fake.requisicoes[0].response_format == {"type": "json_object"}
    async with db.service_session() as conn:
        cur = await conn.execute("select purpose::text, analysis_id::text from llm.model_calls where id = %s", (call_id,))
        assert (await cur.fetchone()) == ("planejamento", mundo7["aid"])


async def test_planner_json_invalido_repara_uma_vez_depois_analise_falha(db, mundo7):
    fake = FakeLLM([_resp("não é json"), _resp("ainda não é json")])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "failed" and len(fake.requisicoes) == 2
    assert (await _status(db, mundo7["aid"]))[0] == "failed"
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from audit.activity_log where action = 'analysis.failed' and object_id = %s", (mundo7["aid"],))
        assert (await cur.fetchone())[0] == 1


# ---------------------------------------------------------------- pipeline ponta a ponta
async def test_pipeline_ponta_a_ponta_final(db, mundo7):
    from app.tools.hashing import canonical_json, sha256_hex

    fake = FakeLLM([_json(PLANO_OK), _resp(RELATORIO)])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "final_with_warnings" and r.report_id and r.message_id
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select content_md, evidence_hash, status, synthesis_model_call_id is not null, version from analysis.reports where id = %s", (r.report_id,))
        content, ehash, status, tem_call, versao = await cur.fetchone()
        assert status == "final" and tem_call and versao == 1 and "ilustrativ" in content.lower()
        # Ordem canônica do bundle = (kind, id), a mesma de `an.listar_findings`, que é o que o
        # relatório hasheia. NÃO ordene por created_at: o default da coluna é `now()`, que é o
        # timestamp da TRANSAÇÃO — as evidências gravadas na mesma Tx empatam (aqui, 2 por kind) e
        # o desempate fica por conta do plano do Postgres. Com isso o hash batia no Windows e
        # falhava no runner Linux (CI de 2026-08-26), sem uma linha de código diferente.
        cur = await conn.execute(
            "select kind, finding, provenance from analysis.evidence_findings where analysis_id = %s order by kind, id", (mundo7["aid"],))
        findings = [{"kind": k, "finding": f, "provenance": p} for k, f, p in await cur.fetchall()]
        assert ehash == sha256_hex(canonical_json(findings))          # hash do bundle que fundamentou o texto
        assert {f["kind"] for f in findings} >= {"quantitative", "methodology", "warning"}
        warnings = {f["finding"]["aviso"] for f in findings if f["kind"] == "warning"}
        assert "adjusted_close_retrospective" in warnings
        cur = await conn.execute(
            "select role, content_json, cited_refs from agents.messages where conversation_id = %s order by seq desc limit 1", (mundo7["cid"],))
        role, cj, refs = await cur.fetchone()
        assert role == "agent" and cj["report_id"] == r.report_id and cj["analysis_id"] == mundo7["aid"]
        kinds = {c["kind"] for c in refs}
        assert {"analysis_report", "analysis_finding", "tool_execution", "price_asof"} <= kinds
        cur = await conn.execute("select estimated_usd > 0, tool_executions from llm.cost_ledger where ref_kind = 'analysis' and ref_id = %s", (mundo7["aid"],))
        assert (await cur.fetchone()) == (True, 2)
        cur = await conn.execute("select count(*) from decisions.records where scope_id = %s", (mundo7["e"].s1,))
        assert (await cur.fetchone())[0] == 0
        cur = await conn.execute("select status::text, plan_id::text from analysis.tasks where analysis_id = %s", (mundo7["aid"],))
        assert {s for s, _ in await cur.fetchall()} == {"succeeded"}


async def test_pipeline_required_falho_replaneja_e_conclui(db, mundo7, monkeypatch):
    """1º plano tem nó required que o compiler reprova inteiro (tool de outra família) ⇒ replan com as falhas ⇒ 2º plano ok."""
    plano_ruim = _plano(_no("orc", tool="orcamento.reserva_emergencia", params={"custo_mensal_brl": 5000}))
    fake = FakeLLM([_json(plano_ruim), _json(PLANO_OK), _resp(RELATORIO)])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "final_with_warnings" and r.replans == 1
    status, replans = await _status(db, mundo7["aid"])
    assert status == "final_with_warnings" and replans == 1
    segundo = fake.requisicoes[1].messages[0].content
    assert "orcamento.reserva_emergencia" in segundo and "família" in segundo        # falhas anteriores no prompt do replan


async def test_pipeline_esgota_replans_e_fica_failed(db, mundo7):
    plano_ruim = _plano(_no("orc", tool="orcamento.reserva_emergencia", params={"custo_mensal_brl": 5000}))
    fake = FakeLLM([_json(plano_ruim), _json(plano_ruim), _json(plano_ruim), _json(plano_ruim)])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "failed"
    status, replans = await _status(db, mundo7["aid"])
    assert status == "failed" and replans == 2 and len(fake.requisicoes) == 3     # 1 plano + 2 replans (max_replans)


async def test_report_status_final_with_warnings_quando_ha_missing(db, mundo7):
    plano = _plano(_no("ret", params={"ticker": "F5PETR", "data_referencia": "2024-01-17", **PERIODO}),
                   _no("vazio", params={"ticker": "F5PETR", "de": "2019-01-01", "ate": "2019-01-31", "data_referencia": "2019-01-31"},
                       criticality="optional"))
    fake = FakeLLM([_json(plano), _resp(RELATORIO)])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "final_with_warnings"
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from analysis.evidence_findings where analysis_id = %s and kind = 'missing'", (mundo7["aid"],))
        assert (await cur.fetchone())[0] == 1


async def test_report_vocabulario_vetado_reescrito_ou_bloqueado_antes_do_insert(db, mundo7):
    from app.agents import guardrails

    fake = FakeLLM([_json(PLANO_OK), _resp("Recomendamos comprar PETR4, é a melhor opção."),
                    _resp("A métrica descreve o passado. " + RELATORIO)])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "final_with_warnings"
    async with db.service_session() as conn:
        cur = await conn.execute("select content_md from analysis.reports where id = %s", (r.report_id,))
        content = (await cur.fetchone())[0]
        assert guardrails.vocabulario(content) == [] and "recomendamos" not in content.lower()
        cur = await conn.execute(
            "select action_taken from agents.guardrail_events where message_id = %s and kind = 'vocabulario_proibido'", (r.message_id,))
        assert (await cur.fetchone())[0] == "reescrito"


async def test_report_bloqueado_por_orcamento_grava_report_blocked_e_texto_seguro(db, mundo7):
    from app.agents import guardrails

    async with db.service_session() as conn:
        await conn.execute("update analysis.analyses set budget = '{\"max_usd\": 0.0000001, \"max_tasks\": 4}' where id = %s", (mundo7["aid"],))
    fake = FakeLLM([_json(PLANO_OK), _resp(RELATORIO)])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "blocked"
    async with db.service_session() as conn:
        cur = await conn.execute("select status, content_md from analysis.reports where id = %s", (r.report_id,))
        assert (await cur.fetchone()) == ("blocked", guardrails.TEXTO_SEGURO_ORCAMENTO)
        cur = await conn.execute("select content from agents.messages where id = %s", (r.message_id,))
        assert (await cur.fetchone())[0] == guardrails.TEXTO_SEGURO_ORCAMENTO


async def test_report_sintese_vazia_vira_blocked_com_texto_seguro(db, mundo7):
    """Reasoning engoliu o teto de saída e o texto veio vazio: não se publica 'final' vazio."""
    from app.agents import guardrails

    fake = FakeLLM([_json(PLANO_OK), _resp("")])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "blocked"
    assert fake.requisicoes[1].max_output_tokens == 12000          # teto próprio da síntese (policy)
    async with db.service_session() as conn:
        cur = await conn.execute("select status, content_md from analysis.reports where id = %s", (r.report_id,))
        assert (await cur.fetchone()) == ("blocked", guardrails.TEXTO_SEGURO_RELATORIO)
        cur = await conn.execute("select details->>'detalhe' from agents.guardrail_events where message_id = %s", (r.message_id,))
        assert "sintese_vazia" in (await cur.fetchone())[0]


async def test_pipeline_idempotente_segunda_chamada_noop(db, mundo7):
    fake = FakeLLM([_json(PLANO_OK), _resp(RELATORIO)])
    r1 = await _pipeline(db, fake, mundo7)
    r2 = await _pipeline(db, fake, mundo7)
    assert r1.status == "final_with_warnings" and r2.status == "final_with_warnings" and r2.noop and len(fake.requisicoes) == 2


async def test_pipeline_prompt_nao_aprovado_falha_com_audit(db, mundo7):
    async with db.service_session() as conn:
        await prompts_repo.reabrir_rascunho(conn, "analista.planner", "[PENDENTE] {{ pergunta }}")
    fake = FakeLLM([_json(PLANO_OK)])
    r = await _pipeline(db, fake, mundo7)
    assert r.status == "failed" and fake.requisicoes == [] and "PromptNotApproved" in (r.erro or "")


async def test_report_imutavel(db, mundo7):
    from app.db.errors import PermissionDenied

    fake = FakeLLM([_json(PLANO_OK), _resp(RELATORIO)])
    r = await _pipeline(db, fake, mundo7)
    with pytest.raises(PermissionDenied):
        async with db.service_session() as conn:
            await conn.execute("update analysis.reports set content_md = 'x' where id = %s", (r.report_id,))


# ---------------------------------------------------------------- turno em modo research
async def _rodar(db, fake, enfileirados=None, **kw):
    async def enfileirar(analysis_id):
        (enfileirados if enfileirados is not None else []).append(analysis_id)
    turno = TurnoCopiloto(db=db, llm=fake, policies=_policies(db), enfileirar_analise=enfileirar)
    return [e async for e in turno.executar(TurnoInput(**kw))]


async def test_turno_research_cria_analise_enfileira_e_nao_executa_tool(db, mundo7):
    e = mundo7["e"]
    fila = []
    fake = FakeLLM([])
    eventos = await _rodar(db, fake, fila, user_id=e.u1, scope_id=e.s1, texto="análise aprofundada da F5PETR",
                           agent_code="analista", mode="research")
    nomes = [x.nome for x in eventos]
    assert nomes[0] == "routed" and "analysis_queued" in nomes and nomes[-1] == "done" and "tool_done" not in nomes
    queued = next(x for x in eventos if isinstance(x, ev.AnalysisQueued))
    done = next(x for x in eventos if isinstance(x, ev.Done))
    assert fila == [queued.analysis_id] and fake.requisicoes == []
    async with db.service_session() as conn:
        cur = await conn.execute("select mode, status::text, max_replans, conversation_id::text from analysis.analyses where id = %s", (queued.analysis_id,))
        assert (await cur.fetchone()) == ("research", "received", 2, done.conversation_id)
        cur = await conn.execute("select role, content_json from agents.messages where id = %s", (done.message_id,))
        role, cj = await cur.fetchone()
        assert role == "agent" and cj["analysis_id"] == queued.analysis_id
        cur = await conn.execute("select count(*) from llm.model_calls where conversation_id = %s", (done.conversation_id,))
        assert (await cur.fetchone())[0] == 0


async def test_turno_research_com_agente_nao_analista_e_recusado(db, mundo7):
    e = mundo7["e"]
    await abrir_conversa(db, e, agente="assessor")      # aprova o prompt do Assessor NA transação (não depende do dev)
    eventos = await _rodar(db, FakeLLM([]), user_id=e.u1, scope_id=e.s1, texto="oi", agent_code="assessor", mode="research")
    assert any(isinstance(x, ev.Erro) and x.tipo == "modo_indisponivel" for x in eventos)


async def test_chip_analise_aprofundada_roteia_em_research(db, mundo7):
    e = mundo7["e"]
    fila = []
    eventos = await _rodar(db, FakeLLM([]), fila, user_id=e.u1, scope_id=e.s1, texto="", chip_id="analise_aprofundada")
    assert len(fila) == 1 and any(isinstance(x, ev.AnalysisQueued) for x in eventos)


# ---------------------------------------------------------------- job / CLI (sem Redis)
async def test_task_analisar_via_ctx_direto_conclui(db, mundo7):
    from app.jobs import tasks

    fake = FakeLLM([_json(PLANO_OK), _resp(RELATORIO)])
    ctx = {"db": db, "llm": fake, "policies": _policies(db), "enfileirar": None, "enfileirar_analise": None}
    r = await tasks.analisar(ctx, mundo7["aid"])
    assert r["status"] == "final_with_warnings" and r["report_id"]
    pendentes = await tasks.varrer_analises_pendentes(ctx)
    assert mundo7["aid"] not in pendentes


async def test_varrer_analises_travadas_reabre_task_running_e_reenfileira(db, mundo7):
    from app.jobs import tasks

    fila = []

    async def enfileirar_analise(aid):
        fila.append(aid)
    async with db.service_session() as conn:
        # updated_at é mantido por trigger (não dá para retroagir): a policy com 0 minutos torna qualquer não-terminal "travada"
        await conn.execute("update analysis.analyses set status = 'executing' where id = %s", (mundo7["aid"],))
        await policies_repo.set_policy(conn, "ANALISE_RESEARCH", {**CFG_RESEARCH, "analise_travada_minutos": 0})
    ctx = {"db": db, "llm": None, "policies": _policies(db), "enfileirar": None, "enfileirar_analise": enfileirar_analise}
    n = await tasks.varrer_analises_travadas(ctx)
    assert n >= 1 and mundo7["aid"] in fila


# ---------------------------------------------------------------- API e RLS
async def test_api_get_analyses_e_report_404_para_outro_escopo(db, mundo7):
    e = mundo7["e"]
    fake = FakeLLM([_json(PLANO_OK), _resp(RELATORIO)])
    r = await _pipeline(db, fake, mundo7)
    app = criar_app(db, fake, _policies(db))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.get(f"/analyses/{mundo7['aid']}", headers=HEADERS(e.u1, e.s1))
        assert ok.status_code == 200
        corpo = ok.json()
        assert corpo["status"] == "final_with_warnings" and corpo["plano"]["version"] == 1 and len(corpo["tasks"]) == 2 and corpo["findings"] >= 2
        rep = await c.get(f"/analyses/{mundo7['aid']}/report", headers=HEADERS(e.u1, e.s1))
        assert rep.status_code == 200 and rep.json()["report"]["id"] == r.report_id and "ilustrativ" in rep.json()["report"]["content_md"].lower()
        lista = await c.get("/analyses", headers=HEADERS(e.u1, e.s1))
        assert any(a["id"] == mundo7["aid"] for a in lista.json())
        alheio = await c.get(f"/analyses/{mundo7['aid']}", headers=HEADERS(e.u2, e.s2))
        assert alheio.status_code == 404
        alheio = await c.get(f"/analyses/{mundo7['aid']}/report", headers=HEADERS(e.u2, e.s2))
        assert alheio.status_code == 404


async def test_api_report_antes_de_publicar_devolve_status(db, mundo7):
    e = mundo7["e"]
    app = criar_app(db, FakeLLM([]), _policies(db))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        rep = await c.get(f"/analyses/{mundo7['aid']}/report", headers=HEADERS(e.u1, e.s1))
        assert rep.status_code == 200 and rep.json() == {"status": "received", "report": None}


async def test_rls_filhas_de_analysis_invisiveis_para_outro_escopo(db, mundo7):
    e = mundo7["e"]
    fake = FakeLLM([_json(PLANO_OK), _resp(RELATORIO)])
    await _pipeline(db, fake, mundo7)
    async with db.app_session(user_id=e.u2, scope_id=e.s2) as conn:
        for tabela in ("plans", "tasks", "evidence_findings", "reports"):
            cur = await conn.execute(f"select count(*) from analysis.{tabela} where analysis_id = %s", (mundo7["aid"],))
            assert (await cur.fetchone())[0] == 0, tabela
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        cur = await conn.execute("select count(*) from analysis.reports where analysis_id = %s", (mundo7["aid"],))
        assert (await cur.fetchone())[0] == 1
