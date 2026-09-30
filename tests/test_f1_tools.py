"""
F1 — Registro de tools, sync (espelho auditável) e executor.

Regras provadas: o decorator gera o param_schema do Pydantic (nunca cópia manual); o sync grava
git_sha + sha256 do fonte e respeita 'uma versão corrente por tool'; o executor valida, resolve,
usa cache content-addressed, registra as políticas usadas e é barrado pelos gates do BANCO
(família T18, plano mínimo T51, política aprovada T52); a parte de cálculo é pura e travada por
golden master; nenhuma premissa numérica vive no código das tools.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import pathlib

import pytest

from tests.conftest import abrir_conversa

from app.db.errors import FamilyNotAllowed, QuotaExceeded  # noqa: F401  (QuotaExceeded: F2)
from app.db.repos import policies as policies_repo
from app.tools import carregar_tools
from app.tools.assessor import orcamento
from app.tools.executor import ToolInsumoFaltante, ToolParamsInvalid, executar_tool
from app.tools.hashing import sha256_fonte, sha256_fonte_crlf, sha256_fontes
from app.tools.registry import spec_de, specs_registradas
from app.tools.sync import SyncConflito, _e_sha_legado_crlf, sincronizar

GOLDEN = pathlib.Path(__file__).parent / "golden"

carregar_tools()


# ---------------------------------------------------------------- registro
def test_decorator_gera_param_schema_valido():
    spec = spec_de("orcamento.reserva_emergencia")
    assert spec.family == "orcamento" and spec.min_plan == "free"
    schema = spec.param_schema
    assert schema["type"] == "object" and schema.get("additionalProperties") is False
    assert "meses_alvo" in schema["properties"]
    assert len(spec.source_sha256) == 64 and spec.semver.count(".") == 2
    assert spec.exposed_to_llm is True
    assert spec.source_files == (spec.module_file,)  # tools atuais preservam exatamente o fingerprint legado
    assert spec.description and "PENDENTE" not in spec.description


def test_registro_tem_as_duas_tools_de_orcamento():
    codes = {s.code for s in specs_registradas()}
    assert {"orcamento.reserva_emergencia", "orcamento.capacidade_aporte"} <= codes


# ---------------------------------------------------------------- sync
async def test_sync_cria_tool_e_versao_com_git_sha_e_sha256(db):
    # código sintético: o teste não pode depender de a tool já existir (ou não) no banco de dev
    spec = dataclasses.replace(spec_de("orcamento.reserva_emergencia"), code="orcamento.zz_sync_teste")
    async with db.service_session() as conn:
        rel = await sincronizar(conn, [spec], git_sha="a" * 40)
        assert "orcamento.zz_sync_teste" in rel.criadas
        cur = await conn.execute(
            "select t.family::text, t.min_plan::text, v.git_sha, v.source_sha256, v.semver "
            "from tools.tools t join tools.tool_versions v on v.tool_code = t.code "
            "where t.code = 'orcamento.zz_sync_teste' and v.deprecated_at is null")
        family, min_plan, git_sha, sha, semver = await cur.fetchone()
    assert (family, min_plan) == ("orcamento", "free")
    assert git_sha == "a" * 40 and sha == spec.source_sha256 and semver == spec.semver


async def test_sync_mesma_semver_com_fonte_diferente_falha(db):
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        adulterada = dataclasses.replace(spec_de("orcamento.reserva_emergencia"), source_sha256="f" * 64)
        with pytest.raises(SyncConflito):
            await sincronizar(conn, [adulterada], git_sha="b" * 40)


def test_source_sha256_independe_de_quebra_de_linha(tmp_path):
    """O sha prova QUAL código, não em que sistema o checkout foi feito. CRLF (Windows,
    core.autocrlf) e LF (runner Linux) do mesmo arquivo têm de dar o mesmo sha — senão o
    `tools sync --check` do CI acusa drift eterno no commit que o dev acabou de sincronizar."""
    lf = tmp_path / "lf.py"
    crlf = tmp_path / "crlf.py"
    lf.write_bytes(b"def calcular(x):\n    return x\n")
    crlf.write_bytes(b"def calcular(x):\r\n    return x\r\n")
    assert sha256_fonte(lf) == sha256_fonte(crlf)
    assert sha256_fonte_crlf(lf) == sha256_fonte_crlf(crlf) != sha256_fonte(lf)


def test_source_sha256_composto_cobre_dependencias_e_preserva_lf(tmp_path):
    """Engine/helper declarado faz parte da identidade da tool; EOL e ordem dos arquivos não."""
    facade = tmp_path / "tool.py"
    engine = tmp_path / "engine.py"
    facade.write_bytes(b"def calcular(x):\n    return engine(x)\n")
    engine.write_bytes(b"def engine(x):\n    return x + 1\n")
    h1 = sha256_fontes((facade, engine))
    assert h1 == sha256_fontes((engine, facade))

    engine.write_bytes(b"def engine(x):\r\n    return x + 1\r\n")
    assert sha256_fontes((facade, engine)) == h1

    engine.write_bytes(b"def engine(x):\n    return x + 2\n")
    assert sha256_fontes((facade, engine)) != h1
    assert sha256_fontes((facade,)) == sha256_fonte(facade)  # compatibilidade com as tools atuais


def test_sha_crlf_legado_nao_mascara_fingerprint_composto(tmp_path):
    """A correção de EOL publicada no legado vale só para tools de um arquivo."""
    base = spec_de("orcamento.reserva_emergencia")
    engine = tmp_path / "engine.py"
    engine.write_text("def f():\n    return 1\n", encoding="utf-8")
    composta = dataclasses.replace(
        base,
        source_files=(base.module_file, str(engine)),
        source_sha256=sha256_fontes((base.module_file, engine)),
    )
    assert not _e_sha_legado_crlf(composta, sha256_fonte_crlf(base.module_file))


async def test_sync_corrige_sha_legado_crlf_sem_versao_nova(db):
    """Legado (≤ 2026-08-26): sha gravado na forma CRLF. Mesmo fonte ⇒ o sync corrige a impressão
    digital no lugar, sem bump e sem versão nova — o bump falso é que sujaria a auditoria."""
    spec = dataclasses.replace(spec_de("orcamento.reserva_emergencia"), code="orcamento.zz_crlf_teste")
    async with db.service_session() as conn:
        await sincronizar(conn, [spec], git_sha="a" * 40)
        await conn.execute(
            "update tools.tool_versions set source_sha256 = %s where tool_code = %s and deprecated_at is null",
            (sha256_fonte_crlf(spec.module_file), spec.code))

        rel = await sincronizar(conn, [spec], git_sha="a" * 40)
        assert rel.corrigidas == ["orcamento.zz_crlf_teste@" + spec.semver] and not rel.versionadas
        cur = await conn.execute(
            "select source_sha256, count(*) over () from tools.tool_versions "
            "where tool_code = %s and deprecated_at is null", (spec.code,))
        sha, correntes = await cur.fetchone()
        assert (sha, correntes) == (spec.source_sha256, 1)

        # e o `--check` do CI aponta o caminho certo em vez de "faça o bump"
        await conn.execute(
            "update tools.tool_versions set source_sha256 = %s where tool_code = %s and deprecated_at is null",
            (sha256_fonte_crlf(spec.module_file), spec.code))
        rel = await sincronizar(conn, [spec], git_sha="a" * 40, somente_verificar=True)
        assert rel.tem_drift and "NÃO bumpe a semver" in rel.drift[0]


async def test_sync_nova_semver_deprecia_anterior_e_mantem_uma_corrente(db):
    base = dataclasses.replace(spec_de("orcamento.reserva_emergencia"), code="orcamento.zz_semver_teste")
    async with db.service_session() as conn:
        await sincronizar(conn, [base], git_sha="a" * 40)
        nova = dataclasses.replace(base, semver="9.9.9", source_sha256="e" * 64)
        rel = await sincronizar(conn, [nova], git_sha="b" * 40)
        assert "orcamento.zz_semver_teste@9.9.9" in rel.versionadas
        cur = await conn.execute(
            "select count(*) filter (where deprecated_at is null), count(*) "
            "from tools.tool_versions where tool_code = 'orcamento.zz_semver_teste'")
        correntes, total = await cur.fetchone()
        assert (correntes, total) == (1, 2)


async def test_sync_tool_ausente_do_registro_e_desativada(db):
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        so_uma = [spec_de("orcamento.capacidade_aporte")]
        rel = await sincronizar(conn, so_uma, git_sha="a" * 40, desativar_ausentes=True)
        assert "orcamento.reserva_emergencia" in rel.desativadas
        cur = await conn.execute("select is_active from tools.tools where code = 'orcamento.reserva_emergencia'")
        assert (await cur.fetchone())[0] is False


# ---------------------------------------------------------------- executor
@pytest.fixture
async def escopo_com_dados(db, escopos):
    """Renda, custo e reserva do escopo s1 — inseridos como serviço, revertidos no fim."""
    async with db.service_session() as conn:
        await conn.execute(
            "insert into budget.monthly_summaries (scope_id, month, income_brl, expense_brl) "
            "select %s, (date_trunc('month', current_date) - (n || ' months')::interval)::date, 20000, 8000 "
            "from generate_series(1, 6) n", (escopos.s1,))
        await conn.execute(
            "insert into budget.income_summaries (scope_id, month, fixed_brl, variable_brl, "
            " variable_p10_brl, committable_brl, variable_share, months_observed) "
            "values (%s, date_trunc('month', current_date)::date, 12000, 8000, 2000, 14000, 0.4, 12)",
            (escopos.s1,))
        await conn.execute(
            "insert into budget.reserve_settings (scope_id, target_months) values (%s, 6.0)", (escopos.s1,))
        await conn.execute(
            "insert into budget.debts (scope_id, kind, description, outstanding_brl, annual_rate, "
            " monthly_payment_brl, is_expensive) values "
            "(%s, 'cartao_rotativo', 'cartão', 15000, 0.9, 1500, true), "
            "(%s, 'financiamento_imovel', 'financiamento', 300000, 0.11, 2800, false)",
            (escopos.s1, escopos.s1))
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        for code in ("FOUNDATION_THRESHOLDS", "INCOME_HAIRCUT"):
            await policies_repo.approve_current(conn, code, approved_by=escopos.u1)
    return escopos


async def test_executor_recusa_params_invalidos(db, escopo_com_dados):
    e = escopo_com_dados
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        with pytest.raises(ToolParamsInvalid):
            await executar_tool(conn, "orcamento.reserva_emergencia",
                                {"meses_alvo": -2}, scope_id=e.s1, conversation_id=None)


async def test_executor_executa_grava_proveniencia_e_politicas(db, escopo_com_dados):
    e = escopo_com_dados
    conversa = await abrir_conversa(db, e, agente="assessor", plano="free")
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "orcamento.capacidade_aporte", {}, scope_id=e.s1, conversation_id=conversa)
        assert r.cache_hit is False
        cur = await conn.execute(
            "select status::text, output_payload is not null, resolved_params ? '_policies', "
            " cardinality(policy_version_ids) > 0, output_hash is not null "
            "from tools.tool_executions where id = %s", (r.execution_id,))
        assert (await cur.fetchone()) == ("succeeded", True, True, True, True)
    # A capacidade passou a ser a SOBRA (renda comprometível − despesa), não a renda
    # comprometível: 14.000 com que dá para contar menos 8.000 de despesa. A asserção
    # antiga congelava o número que fazia a tela dizer a um cliente que ele podia
    # aportar R$ 26.000 por mês gastando R$ 16.800.
    assert r.output.capacidade_mensal_brl == pytest.approx(6000.0)
    assert r.output.renda_com_que_da_para_contar_brl == pytest.approx(14000.0)
    # A regra ganhou a segunda metade: continua sendo o PISO da renda variável (nunca
    # a média), e agora é a sobra SOBRE ela — depois das despesas.
    assert r.output.regra == "sobra_sobre_o_piso_da_renda"


async def test_executor_cache_hit_aponta_origem(db, escopo_com_dados):
    e = escopo_com_dados
    conversa = await abrir_conversa(db, e, agente="assessor", plano="free")
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r1 = await executar_tool(conn, "orcamento.capacidade_aporte", {}, scope_id=e.s1, conversation_id=conversa)
        r2 = await executar_tool(conn, "orcamento.capacidade_aporte", {}, scope_id=e.s1, conversation_id=conversa)
        assert r1.cache_hit is False and r2.cache_hit is True
        cur = await conn.execute(
            "select cache_hit, cached_from_execution_id::text, status::text "
            "from tools.tool_executions where id = %s", (r2.execution_id,))
        assert (await cur.fetchone()) == (True, r1.execution_id, "succeeded")
        assert r2.output == r1.output


async def test_executor_barrado_pelo_gate_de_familia_do_banco(db, escopo_com_dados):
    e = escopo_com_dados
    conversa_educador = await abrir_conversa(db, e, agente="educador", plano="free")
    with pytest.raises(FamilyNotAllowed):
        async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
            await executar_tool(conn, "orcamento.capacidade_aporte", {},
                                scope_id=e.s1, conversation_id=conversa_educador)


async def test_executor_barrado_por_politica_nao_aprovada(db, escopos):
    """Com INCOME_HAIRCUT em rascunho (nova versão draft criada AQUI — estado próprio do teste),
    execução client-facing é recusada pelo gate da 29 (T52 visto do Python)."""
    async with db.service_session() as conn:
        await conn.execute(
            "insert into budget.income_summaries (scope_id, month, fixed_brl, variable_brl, "
            " variable_p10_brl, committable_brl, months_observed) "
            "values (%s, date_trunc('month', current_date)::date, 10000, 0, 0, 10000, 6)", (escopos.s1,))
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        atual = await policies_repo.get_current(conn, "INCOME_HAIRCUT")
        await policies_repo.set_policy(conn, "INCOME_HAIRCUT", atual.payload if atual else
                                       {"meses_minimos_para_p10": 6, "haircut_por_estabilidade": {}})
    conversa = await abrir_conversa(db, escopos, agente="assessor", plano="free")
    from app.db.errors import DbError
    with pytest.raises(DbError):
        async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
            await executar_tool(conn, "orcamento.capacidade_aporte", {},
                                scope_id=escopos.s1, conversation_id=conversa)


async def test_reserva_emergencia_ponta_a_ponta(db, escopo_com_dados):
    e = escopo_com_dados
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "orcamento.reserva_emergencia",
                                {"saldo_reserva_brl": 46000, "aporte_mensal_brl": 2000},
                                scope_id=e.s1, conversation_id=None)
    assert r.output.custo_mensal_brl == pytest.approx(8000.0)   # média dos monthly_summaries
    assert r.output.alvo_brl == pytest.approx(48000.0)          # 6 meses (reserve_settings)
    assert r.output.meses_cobertos == pytest.approx(5.75)
    assert r.output.acima_do_minimo is True and r.output.no_alvo is False


async def test_reserva_sem_custo_conhecido_declara_insumo_faltante(db, escopos):
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        with pytest.raises(ToolInsumoFaltante):
            await executar_tool(conn, "orcamento.reserva_emergencia", {}, scope_id=escopos.s1, conversation_id=None)


# ---------------------------------------------------------------- golden masters (parte pura)
@pytest.mark.parametrize("nome,calcular,resolvido_model", [
    ("orcamento_reserva_emergencia", orcamento.calcular_reserva, orcamento.ReservaResolvida),
    ("orcamento_capacidade_aporte", orcamento.calcular_capacidade, orcamento.CapacidadeResolvida),
])
def test_golden_master(nome, calcular, resolvido_model):
    dados = json.loads((GOLDEN / f"{nome}.json").read_text(encoding="utf-8"))
    saida = calcular(resolvido_model.model_validate(dados["resolvido"]))
    assert saida.model_dump(mode="json") == dados["esperado"], (
        "Saída difere do golden master — se a mudança é intencional, atualize o golden no mesmo "
        "commit explicando POR QUE o número mudou (engine_version/premissa).")


# ---------------------------------------------------------------- config-first
def test_tools_de_orcamento_sem_literal_numerico_de_premissa():
    """Premissa numérica vive em engine.policy_versions. No código, só 0/1 (identidade) e 12 (meses/ano)."""
    permitidos = {0, 1, 12, 0.0, 1.0}
    fonte = pathlib.Path(orcamento.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    ofensores = [n.value for n in ast.walk(arvore)
                 if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                 and not isinstance(n.value, bool) and n.value not in permitidos]
    assert ofensores == [], f"números fora de policy no código das tools: {ofensores}"
