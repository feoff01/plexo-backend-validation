"""
F6 — Analista research (DAG). Parte a: DSL, compiler, executor com checkpoints, orçamento — sem LLM.

Regras provadas: nó inválido do plano é descartado com motivo (e quem dependia dele também); o compiler
recusa ciclo (Python) e o BANCO recusa dependência de nó inexistente (T65); tool fora da família ou de
plano superior não entra; params inválidos vão para o validation_report; `max_tasks` é teto; o segundo
plano supersede o primeiro e o banco conta o replan (T66) — o terceiro é recusado; o executor roda em
ordem topológica, grava findings por task com proveniência, deixa dependente de `required` falho como
`skipped`, transforma `important` falho em `warning`, retoma só o que está pendente (checkpoint), não
reexecuta task `running` (claim CAS), aplica timeout/retentativas e os gates do banco valem pela análise
(T63); o orçamento bloqueia antes da chamada; nenhuma premissa numérica no código.
Preços vêm da fixture COTAHIST ingerida na transação (fixture `mundo` da F5).
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from datetime import date

import pytest

from tests.conftest import abrir_conversa
from tests.test_f5_analista_tools import ANALISE_PARAMS, CUTOFF, mundo  # noqa: F401  (fixture reexportada)

from app.agents import analysis as an
from app.config.policies import PolicyStore
from app.db.errors import DbError, FamilyNotAllowed
from app.db.repos import policies as policies_repo
from app.llm.budget import BudgetExceeded
from app.tools.executor import ToolExecutionFailed, executar_tool

CFG_RESEARCH = {"max_tasks": 4, "max_paralelo": 1, "timeout_task_s": 5, "max_tentativas": 2,
                "dsl_version": "1", "analise_travada_minutos": 30}
PERIODO = {"de": "2024-01-01", "ate": "2024-01-31"}


def _no(node_id, tool="quant.risco_retorno", params=None, depends_on=(), criticality="required", motivo="teste"):
    return {"node_id": node_id, "tool_code": tool, "params": params if params is not None else {"ticker": "F5PETR", **PERIODO},
            "depends_on": list(depends_on), "criticality": criticality, "motivo": motivo}


def _plano(*nos, objetivo="PETR4 em janeiro de 2024"):
    return {"dsl_version": "1", "objetivo": objetivo, "nodes": list(nos)}


@pytest.fixture
async def mundo6(db, mundo):
    """mundo da F5 + policy ANALISE_RESEARCH + uma análise research aberta numa conversa do Analista."""
    from app.analysis.config import ConfigResearch

    e = mundo["e"]
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_RESEARCH", CFG_RESEARCH)
        await policies_repo.set_policy(conn, "LLM_BUDGETS", {"max_model_calls_por_turno": 6, "max_output_tokens_por_turno": 4000,
                                                             "max_output_tokens_por_relatorio": 12000,
                                                             "max_usd_por_analise": 0.5, "max_replans_por_analise": 2})
    cid = await abrir_conversa(db, e, agente="analista")
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        aid, cutoff = await an.criar(conn, scope_id=e.s1, user_id=e.u1, conversation_id=cid,
                                     question="PETR4 em janeiro de 2024: retorno e correlação", mode="research",
                                     max_replans=2, budget={"max_usd": 0.5, "max_tasks": 4})
    return {**mundo, "cid": cid, "aid": aid, "cutoff": cutoff, "cfg": ConfigResearch.from_policy(CFG_RESEARCH)}


async def _analise(db, mundo6):
    async with db.service_session() as conn:
        return await an.carregar(conn, mundo6["aid"])


async def _compilar(db, mundo6, plano_dict, *, familias=("quant", "dados"), plano_conta="free"):
    from app.analysis import compiler, dsl

    plano, descartados = dsl.validar_plano(plano_dict)
    a = await _analise(db, mundo6)
    async with db.service_session() as conn:
        return await compiler.compilar(conn, a, plano, familias=familias, plano_conta=plano_conta,
                                       cfg=mundo6["cfg"], descartados=descartados)


async def _tasks(db, plan_id):
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select node_id, status::text, tool_execution_id is not null, attempt, error_code from analysis.tasks "
            "where plan_id = %s order by node_id", (plan_id,))
        return {r[0]: {"status": r[1], "exec": r[2], "attempt": r[3], "erro": r[4]} for r in await cur.fetchall()}


# ---------------------------------------------------------------- DSL (pura)
def test_dsl_plano_valido_e_parseado():
    from app.analysis import dsl

    plano, descartados = dsl.validar_plano(_plano(_no("a"), _no("b", depends_on=["a"], criticality="optional")))
    assert descartados == [] and [n.node_id for n in plano.nodes] == ["a", "b"]
    assert plano.dsl_version == dsl.DSL_VERSION and plano.nodes[1].criticality == "optional"


def test_dsl_no_invalido_descartado_com_motivo_e_dependentes_propagam():
    from app.analysis import dsl

    plano, descartados = dsl.validar_plano(_plano(
        _no("a"), {"node_id": "b", "tool_code": "", "params": {}, "depends_on": []},        # tool vazia
        _no("c", depends_on=["b"]), _no("d", depends_on=["zz"]), _no("a")))                # dup de a
    assert [n.node_id for n in plano.nodes] == ["a"]
    motivos = {d["node_id"]: d["motivo"] for d in descartados}
    assert set(motivos) == {"b", "c", "d", "a"}
    assert "b" in motivos["c"] and "zz" in motivos["d"] and "duplicado" in motivos["a"]


def test_dsl_plano_vazio_apos_descartes_levanta():
    from app.analysis import dsl

    with pytest.raises(dsl.PlanoVazio):
        dsl.validar_plano(_plano({"node_id": "x", "tool_code": "", "params": {}, "depends_on": []}))


# ---------------------------------------------------------------- compiler
async def test_compiler_grava_plans_e_tasks_pending_com_params(db, mundo6):
    c = await _compilar(db, mundo6, _plano(_no("a"), _no("b", tool="quant.dependencia",
                                                        params={"ticker_a": "F5PETR", "serie_b": {"tipo": "indice", "codigo": "f5_cdi"}}, depends_on=["a"])))
    assert c.version == 1 and c.ordem == ["a", "b"]
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select node_id, status::text, params, depends_on, criticality::text from analysis.tasks where plan_id = %s order by node_id",
            (c.plan_id,))
        rows = await cur.fetchall()
        assert [r[0] for r in rows] == ["a", "b"] and all(r[1] == "pending" for r in rows)
        assert rows[0][2]["ticker"] == "F5PETR" and rows[1][3] == ["a"] and rows[0][4] == "required"
        cur = await conn.execute("select is_active, validation_report, dsl_version from analysis.plans where id = %s", (c.plan_id,))
        ativo, report, dsl_v = await cur.fetchone()
        assert ativo and report["ordem"] == ["a", "b"] and dsl_v == "1"
        cur = await conn.execute("select status::text from analysis.analyses where id = %s", (mundo6["aid"],))
        assert (await cur.fetchone())[0] == "compiled"


async def test_compiler_ciclo_recusado_em_python_e_no_banco(db, mundo6):
    from app.analysis import compiler, dsl

    plano, _ = dsl.validar_plano(_plano(_no("a", depends_on=["b"]), _no("b", depends_on=["a"])))
    a = await _analise(db, mundo6)
    with pytest.raises(compiler.CicloNoPlano):
        async with db.service_session() as conn:
            await compiler.compilar(conn, a, plano, familias=("quant", "dados"), plano_conta="free", cfg=mundo6["cfg"])
    # e o banco, sozinho, recusa dependência de nó que ainda não existe (T65a)
    import psycopg
    with pytest.raises((DbError, psycopg.errors.CheckViolation)):
        async with db.service_session() as conn:
            cur = await conn.execute("insert into analysis.plans (analysis_id, dsl_version, plan) values (%s, '1', '{}') returning id::text",
                                     (mundo6["aid"],))
            pid = (await cur.fetchone())[0]
            await conn.execute("insert into analysis.tasks (analysis_id, plan_id, node_id, tool_code, depends_on) values (%s, %s, 'x', 'quant.dependencia', '{y}')",
                               (mundo6["aid"], pid))


async def test_compiler_tool_fora_da_familia_ou_do_plano_vai_para_o_report(db, mundo6):
    c = await _compilar(db, mundo6, _plano(_no("a"), _no("orc", tool="orcamento.reserva_emergencia", params={"custo_mensal_brl": 5000})))
    assert c.ordem == ["a"] and any(d["node_id"] == "orc" and "família" in d["motivo"] for d in c.validation_report["descartados"])


def test_compiler_recusa_tool_registrada_mas_oculta_do_planner():
    """Legacy segue executável/auditável, mas um plano NOVO não pode adotá-la após o cutover."""
    from app.analysis import compiler, dsl
    from app.tools.registry import spec_de

    legacy = spec_de("quant.retorno_volatilidade")
    assert legacy.exposed_to_llm is False
    plano, _ = dsl.validar_plano(_plano(_no("a", tool=legacy.code)))
    catalogo = {legacy.code: {"family": "quant", "min_plan": "free", "is_active": True}}

    params, motivo = compiler._validar_no(plano.nodes[0], catalogo, ("quant", "dados"), "free")
    assert params is None and motivo is not None and "não é exposta" in motivo


async def test_compiler_params_invalidos_vao_para_validation_report(db, mundo6):
    c = await _compilar(db, mundo6, _plano(_no("a"), _no("ruim", params={"ticker": "F5PETR", "janela_dias": -3})))
    assert c.ordem == ["a"]
    ruim = next(d for d in c.validation_report["descartados"] if d["node_id"] == "ruim")
    assert "janela_dias" in ruim["motivo"]


async def test_compiler_excede_max_tasks_recusa(db, mundo6):
    from app.analysis import compiler

    with pytest.raises(compiler.PlanoInvalido):
        await _compilar(db, mundo6, _plano(*[_no(f"n{i}") for i in range(5)]))   # max_tasks = 4


async def test_compiler_tudo_descartado_e_plano_invalido(db, mundo6):
    from app.analysis import compiler

    with pytest.raises(compiler.PlanoInvalido) as exc:
        await _compilar(db, mundo6, _plano(_no("orc", tool="orcamento.reserva_emergencia", params={})))
    assert exc.value.validation_report["descartados"]


async def test_compiler_segundo_plano_supersede_e_terceiro_replan_recusado_pelo_banco(db, mundo6):
    c1 = await _compilar(db, mundo6, _plano(_no("a")))
    c2 = await _compilar(db, mundo6, _plano(_no("a"), _no("b", depends_on=["a"])))
    c3 = await _compilar(db, mundo6, _plano(_no("c")))
    assert (c1.version, c2.version, c3.version) == (1, 2, 3)
    async with db.service_session() as conn:
        cur = await conn.execute("select is_active, superseded_by::text from analysis.plans where id = %s", (c1.plan_id,))
        assert (await cur.fetchone()) == (False, c2.plan_id)
        cur = await conn.execute("select replan_count from analysis.analyses where id = %s", (mundo6["aid"],))
        assert (await cur.fetchone())[0] == 2
    import psycopg
    with pytest.raises((DbError, psycopg.errors.CheckViolation)):     # replans_bounded (23514) não tem tradução própria
        await _compilar(db, mundo6, _plano(_no("d")))


# ---------------------------------------------------------------- executor
async def _executar(db, mundo6, plan_id):
    from app.analysis import executor

    a = await _analise(db, mundo6)
    return await executor.executar_plano(db, a, plan_id, mundo6["cfg"])


async def test_executor_roda_em_ordem_topologica_e_grava_findings_por_task(db, mundo6):
    c = await _compilar(db, mundo6, _plano(
        _no("b", tool="quant.dependencia", params={"ticker_a": "F5PETR", "serie_b": {"tipo": "ativo", "codigo": "F5VALE"}, "janela_dias": 60,
                                                   "data_referencia": "2024-01-17"}, depends_on=["a"]),
        _no("a", params={"ticker": "F5PETR", "data_referencia": "2024-01-17", **PERIODO})))
    assert c.ordem == ["a", "b"]
    r = await _executar(db, mundo6, c.plan_id)
    assert r.succeeded == ["a", "b"] and r.failed_required == [] and r.skipped == []
    tasks = await _tasks(db, c.plan_id)
    assert all(t["status"] == "succeeded" and t["exec"] for t in tasks.values())
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select f.kind, f.provenance from analysis.evidence_findings f where f.analysis_id = %s order by f.created_at", (mundo6["aid"],))
        findings = await cur.fetchall()
        quant = [p for k, p in findings if k == "quantitative"]
        assert len(quant) == 2 and all(p[0]["tool_execution_id"] for p in quant)
        cur = await conn.execute(
            "select count(*) from tools.tool_executions e join analysis.tasks t on t.tool_execution_id = e.id "
            "where t.plan_id = %s and e.analysis_id = %s and e.conversation_id = %s", (c.plan_id, mundo6["aid"], mundo6["cid"]))
        assert (await cur.fetchone())[0] == 2


async def test_executor_dependente_de_required_falho_fica_skipped(db, mundo6, monkeypatch):
    from app.analysis import executor

    c = await _compilar(db, mundo6, _plano(_no("a", params={"ticker": "F5VALE", **PERIODO}), _no("b", depends_on=["a"]), _no("c")))
    original = executor.executar_tool

    async def falha_em_a(conn, code, params, **kw):
        if params.get("ticker") == "F5VALE":
            raise ToolExecutionFailed(code, "00000000-0000-0000-0000-000000000000", RuntimeError("provedor caiu"))
        return await original(conn, code, params, **kw)
    monkeypatch.setattr(executor, "executar_tool", falha_em_a)
    r = await _executar(db, mundo6, c.plan_id)
    assert r.failed_required == ["a"] and r.skipped == ["b"] and r.succeeded == ["c"]
    tasks = await _tasks(db, c.plan_id)
    assert tasks["a"]["status"] == "failed" and tasks["a"]["attempt"] == 2 and tasks["a"]["erro"] == "ToolExecutionFailed"
    assert tasks["b"]["status"] == "skipped" and tasks["c"]["status"] == "succeeded"


async def test_executor_important_falho_vira_warning_e_segue(db, mundo6, monkeypatch):
    from app.analysis import executor

    c = await _compilar(db, mundo6, _plano(_no("a", criticality="important"), _no("b", depends_on=["a"])))

    async def sempre_falha(conn, code, params, **kw):
        raise ToolExecutionFailed(code, "00000000-0000-0000-0000-000000000000", RuntimeError("x"))
    monkeypatch.setattr(executor, "executar_tool", sempre_falha)
    r = await _executar(db, mundo6, c.plan_id)
    assert r.failed_required == [] and r.warnings == ["a"] and r.skipped == ["b"]
    async with db.service_session() as conn:
        cur = await conn.execute("select finding->>'node_id' from analysis.evidence_findings where analysis_id = %s and kind = 'warning'", (mundo6["aid"],))
        assert [x[0] for x in await cur.fetchall()] == ["a"]


async def test_executor_retomada_so_roda_pendentes(db, mundo6, monkeypatch):
    from app.analysis import executor

    c = await _compilar(db, mundo6, _plano(_no("a"), _no("b", depends_on=["a"]), _no("c", depends_on=["b"])))
    original, chamadas = executor.executar_tool, []

    async def cai_depois_de_uma(conn, code, params, **kw):
        chamadas.append(code)
        if len(chamadas) == 2:
            raise asyncio.CancelledError()          # "processo morreu" no meio da 2ª task
        return await original(conn, code, params, **kw)
    monkeypatch.setattr(executor, "executar_tool", cai_depois_de_uma)
    with pytest.raises(asyncio.CancelledError):
        await _executar(db, mundo6, c.plan_id)
    monkeypatch.setattr(executor, "executar_tool", original)
    tasks = await _tasks(db, c.plan_id)
    assert tasks["a"]["status"] == "succeeded" and tasks["b"]["status"] == "running"   # claim ficou órfão
    # o que o job de varredura faz com task running abandonada: devolve a pending (o claim é por CAS, T65)
    async with db.service_session() as conn:
        await conn.execute("update analysis.tasks set status = 'pending' where plan_id = %s and status = 'running'", (c.plan_id,))
    r = await _executar(db, mundo6, c.plan_id)      # retomada: a já está feita (Execucao reflete o estado do plano)
    assert r.succeeded == ["a", "b", "c"] and r.pendentes == []
    async with db.service_session() as conn:
        # nós com os mesmos params: b e c são cache hits de a — mas cada task tem a SUA linha de execução
        cur = await conn.execute("select count(*), count(*) filter (where not cache_hit) from tools.tool_executions where analysis_id = %s", (mundo6["aid"],))
        assert (await cur.fetchone()) == (3, 1)


async def test_executor_claim_cas_nao_executa_task_running(db, mundo6):
    c = await _compilar(db, mundo6, _plano(_no("a"), _no("b")))
    async with db.service_session() as conn:
        await conn.execute("update analysis.tasks set status = 'running', started_at = now() where plan_id = %s and node_id = 'a'", (c.plan_id,))
    r = await _executar(db, mundo6, c.plan_id)
    assert r.succeeded == ["b"] and r.pendentes == ["a"]
    assert (await _tasks(db, c.plan_id))["a"]["status"] == "running"


async def test_executor_timeout_marca_failed_e_retenta_ate_max_tentativas(db, mundo6, monkeypatch):
    from app.analysis import executor
    from app.analysis.config import ConfigResearch

    c = await _compilar(db, mundo6, _plano(_no("a")))

    async def lenta(conn, code, params, **kw):
        await asyncio.sleep(1)
    monkeypatch.setattr(executor, "executar_tool", lenta)
    a = await _analise(db, mundo6)
    cfg = ConfigResearch.from_policy({**CFG_RESEARCH, "timeout_task_s": 0.05})
    r = await executor.executar_plano(db, a, c.plan_id, cfg)
    t = (await _tasks(db, c.plan_id))["a"]
    assert r.failed_required == ["a"] and t["status"] == "failed" and t["attempt"] == 2 and t["erro"] == "TimeoutError"


async def test_executor_gates_de_familia_valem_pela_analise(db, mundo6):
    """Execução com analysis_id e SEM conversation_id: o banco julga pela conversa da análise (T63)."""
    e = mundo6["e"]
    with pytest.raises(FamilyNotAllowed):
        async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
            await executar_tool(conn, "orcamento.reserva_emergencia", {"custo_mensal_brl": 5000},
                                scope_id=e.s1, conversation_id=None, cutoff_date=CUTOFF, analysis_id=mundo6["aid"])


# ---------------------------------------------------------------- orçamento
async def test_budget_estouro_de_usd_bloqueia_antes_da_chamada(db, mundo6):
    from app.analysis.budget import AnalysisBudget

    a = await _analise(db, mundo6)
    b = AnalysisBudget.from_analysis(a, cfg=mundo6["cfg"])
    assert b.max_usd == 0.5 and b.max_tasks == 4 and b.max_replans == 2
    async with db.service_session() as conn:
        await b.checar(conn)                                   # nada gasto ainda
        await conn.execute(
            "insert into llm.model_calls (purpose, provider, model, agent_code, scope_id, conversation_id, analysis_id, "
            "input_tokens, cached_tokens, output_tokens, cost_usd, latency_ms, status) "
            "values ('planejamento', 'fake', 'fake-m', 'analista', %s, %s, %s, 10, 0, 10, 0.75, 1, 'succeeded')",
            (a.scope_id, a.conversation_id, a.id))
        with pytest.raises(BudgetExceeded):
            await b.checar(conn)
        assert await b.custo_acumulado(conn) == pytest.approx(0.75)


# ---------------------------------------------------------------- transições de status
async def test_avancar_status_exige_estado_de_origem(db, mundo6):
    async with db.service_session() as conn:
        await an.avancar_status(conn, mundo6["aid"], de=("received",), para="planned")
        with pytest.raises(an.TransicaoInvalida):
            await an.avancar_status(conn, mundo6["aid"], de=("received",), para="planned")
        a = await an.carregar(conn, mundo6["aid"])
        assert a.status == "planned" and a.mode == "research" and a.max_replans == 2 and a.cutoff_date == date.today()


# ---------------------------------------------------------------- config-first
@pytest.mark.parametrize("nome", ["dsl", "compiler", "executor", "budget", "config"])
def test_analysis_sem_literal_numerico_de_premissa(nome):
    import importlib

    modulo = importlib.import_module(f"app.analysis.{nome}")
    permitidos = {0, 1, 2, 12, 100, 0.0, 1.0}
    arvore = ast.parse(pathlib.Path(modulo.__file__).read_text(encoding="utf-8"))
    ofensores = [n.value for n in ast.walk(arvore)
                 if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                 and not isinstance(n.value, bool) and n.value not in permitidos]
    assert ofensores == [], f"números fora de policy em {modulo.__name__}: {ofensores}"
