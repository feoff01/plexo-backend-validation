"""
F2a — Tools de planejamento e produto do Assessor.

Regras provadas: projeção determinística com premissas SÓ de policy (sem distribuição — Monte
Carlo é do motor, ver META_PROBABILIDADE_DE_SUCESSO.md); aporte de referência usa o committable
(piso), com fonte declarada; insumo ausente vira pergunta (ToolInsumoFaltante), nunca chute;
custo de produto compara com REFERÊNCIA de classe (policy) sem dizer "melhor"; comparação marca
incompatibilidade com veto do cliente (C26) em vez de esconder ou ranquear.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from tests.conftest import abrir_conversa  # noqa: F401  (usado em F2b)

from app.db.repos import policies as policies_repo
from app.tools import carregar_tools
from app.tools.assessor import patrimonio, planejamento, produto
from app.tools.executor import ToolInsumoFaltante, executar_tool
from app.tools.registry import specs_registradas
from app.tools.sync import sincronizar

GOLDEN = pathlib.Path(__file__).parent / "golden"

carregar_tools()


def test_registro_tem_as_seis_tools_do_assessor():
    codes = {s.code for s in specs_registradas()}
    assert {"orcamento.reserva_emergencia", "orcamento.capacidade_aporte",
            "planejamento.projecao_objetivo", "planejamento.aposentadoria_antecipada",
            "produto.custo_fundo", "produto.comparar_alternativas"} <= codes
    familias = {s.code: s.family for s in specs_registradas()}
    assert familias["planejamento.projecao_objetivo"] == "planejamento"
    assert familias["produto.custo_fundo"] == "produto"


@pytest.fixture
async def escopo_planejamento(db, escopos):
    """Renda com piso + policies de premissa aprovadas + catálogo sincronizado."""
    async with db.service_session() as conn:
        await conn.execute(
            "insert into budget.income_summaries (scope_id, month, fixed_brl, variable_brl, "
            " variable_p10_brl, committable_brl, months_observed) "
            "values (%s, date_trunc('month', current_date)::date, 12000, 8000, 2000, 14000, 12)",
            (escopos.s1,))
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        for code in ("PREMISSAS_FALLBACK", "PLANEJAMENTO_PREMISSAS", "PRODUTO_REFERENCIAS",
                     "FOUNDATION_THRESHOLDS", "INCOME_HAIRCUT"):
            if await policies_repo.get_current(conn, code) is None:
                # banco de teste pode não ter os seeds de dev — cria com o payload do seed
                payloads = {
                    "PLANEJAMENTO_PREMISSAS": {"taxa_retirada_anual": 0.04},
                    "PRODUTO_REFERENCIAS": {"referencia_taxa_adm_aa": {"renda_fixa": 0.005, "multimercado": 0.02, "acoes": 0.015}},
                }
                await policies_repo.set_policy(conn, code, payloads[code])
            await policies_repo.approve_current(conn, code, approved_by=escopos.u1)
    return escopos


# ---------------------------------------------------------------- projeção de objetivo
async def test_projecao_objetivo_e2e(db, escopo_planejamento):
    e = escopo_planejamento
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "planejamento.projecao_objetivo",
                                {"valor_alvo_brl": 200000, "prazo_meses": 120,
                                 "saldo_inicial_brl": 0, "aporte_mensal_brl": 1000},
                                scope_id=e.s1, conversation_id=None)
    out = r.output
    assert out.fonte_aporte == "parametro" and out.aporte_considerado_brl == pytest.approx(1000.0)
    rf, rv = out.cenarios["renda_fixa"], out.cenarios["renda_variavel"]
    assert rf["atingivel"] is False and rv["atingivel"] is False
    assert rf["aporte_necessario_brl"] > rv["aporte_necessario_brl"] > 1000
    # O método é exibido AO CLIENTE, na proveniência do bloco. A asserção antiga exigia que
    # ele começasse com "projecao_deterministica_sem_distribuicao" e mandasse o cliente ver um
    # arquivo .md do repositório. O que precisa continuar verdadeiro é o conteúdo: dois
    # cenários fixos e nenhuma distribuição de probabilidade.
    assert "dois cenários" in out.nota_metodo.lower()
    assert "distribuição de probabilidade" in out.nota_metodo.lower()
    assert "_" not in out.nota_metodo and ".md" not in out.nota_metodo
    assert "retorno_real_rf_aa" in out.premissas_usadas


async def test_projecao_usa_committable_como_aporte_de_referencia(db, escopo_planejamento):
    e = escopo_planejamento
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "planejamento.projecao_objetivo",
                                {"valor_alvo_brl": 100000, "prazo_meses": 12},
                                scope_id=e.s1, conversation_id=None)
    assert r.output.fonte_aporte == "committable"
    assert r.output.aporte_considerado_brl == pytest.approx(14000.0)   # piso, nunca média


async def test_projecao_sem_aporte_e_sem_renda_declara_insumo(db, escopos):
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        for code, payload in (("PREMISSAS_FALLBACK", None),):
            if await policies_repo.get_current(conn, code) is None:
                await policies_repo.set_policy(conn, code, payload or {})
            await policies_repo.approve_current(conn, code, approved_by=escopos.u1)
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        with pytest.raises(ToolInsumoFaltante):
            await executar_tool(conn, "planejamento.projecao_objetivo",
                                {"valor_alvo_brl": 100000, "prazo_meses": 12},
                                scope_id=escopos.s1, conversation_id=None)


def test_golden_projecao_objetivo():
    dados = json.loads((GOLDEN / "planejamento_projecao_objetivo.json").read_text(encoding="utf-8"))
    saida = planejamento.calcular_projecao(planejamento.ProjecaoResolvida.model_validate(dados["resolvido"]))
    assert saida.model_dump(mode="json") == dados["esperado"], (
        "Saída difere do golden — mudança de número exige justificativa no commit.")


# ---------------------------------------------------------------- aposentadoria antecipada
async def test_aposentadoria_antecipada_e2e(db, escopo_planejamento):
    e = escopo_planejamento
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "planejamento.aposentadoria_antecipada",
                                {"idade_alvo": 55, "idade_atual": 35,
                                 "renda_desejada_mensal_brl": 10000,
                                 "patrimonio_atual_brl": 100000, "aporte_mensal_brl": 5000},
                                scope_id=e.s1, conversation_id=None)
    out = r.output
    # 10.000/mês ÷ taxa de retirada 4% a.a. (policy) = R$ 3 mi
    assert out.patrimonio_necessario_brl == pytest.approx(3_000_000.0)
    assert out.anos_ate_alvo == 20
    assert out.cenarios["renda_fixa"]["atingivel"] is False
    assert out.cenarios["renda_variavel"]["atingivel"] is False
    assert out.premissas_usadas["taxa_retirada_anual"] == pytest.approx(0.04)


async def test_aposentadoria_sem_idade_atual_declara_insumo(db, escopo_planejamento):
    e = escopo_planejamento
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        with pytest.raises(ToolInsumoFaltante):
            await executar_tool(conn, "planejamento.aposentadoria_antecipada",
                                {"idade_alvo": 55, "renda_desejada_mensal_brl": 10000},
                                scope_id=e.s1, conversation_id=None)


# ---------------------------------------------------------------- custo de produto
async def test_custo_fundo_com_parametros_manuais(db, escopo_planejamento):
    e = escopo_planejamento
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "produto.custo_fundo",
                                {"descricao": "Fundo X", "taxa_adm_aa": 0.02, "classe": "multimercado",
                                 "valor_aplicado_brl": 100000, "horizonte_anos": 5,
                                 "indicado_por_terceiro": True},
                                scope_id=e.s1, conversation_id=None)
    out = r.output
    assert out.custo_adm_total_estimado_brl == pytest.approx(10000.0)   # aproximação linear declarada
    assert out.metodo == "aproximacao_linear_sem_rendimento"
    assert out.referencia_classe_aa == pytest.approx(0.02) and out.acima_da_referencia is False
    assert out.indicado_por_terceiro is True and out.fonte == "parametros"


async def test_custo_fundo_busca_no_catalogo(db, escopo_planejamento):
    e = escopo_planejamento
    async with db.service_session() as conn:
        await conn.execute(
            "insert into market.instruments (id, kind, name, ticker, asset_class_code) "
            "values ('f2f2f2f2-0000-0000-0000-000000000001', 'fundo', 'Fundo Catalogado', 'FUNDX11', null)")
        await conn.execute(
            "insert into market.fund_facts (instrument_id, management_fee, come_cotas) "
            "values ('f2f2f2f2-0000-0000-0000-000000000001', 0.025, true)")
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "produto.custo_fundo",
                                {"identificador": "FUNDX11", "valor_aplicado_brl": 50000,
                                 "horizonte_anos": 2},
                                scope_id=e.s1, conversation_id=None)
    assert r.output.fonte == "fund_facts"
    assert r.output.taxa_adm_aa == pytest.approx(0.025)
    assert r.output.custo_adm_total_estimado_brl == pytest.approx(2500.0)
    assert r.output.come_cotas is True


async def test_custo_fundo_sem_taxa_declara_insumo(db, escopo_planejamento):
    e = escopo_planejamento
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        with pytest.raises(ToolInsumoFaltante):
            await executar_tool(conn, "produto.custo_fundo",
                                {"descricao": "Fundo misterioso", "valor_aplicado_brl": 10000,
                                 "horizonte_anos": 1},
                                scope_id=e.s1, conversation_id=None)


async def test_comparar_alternativas_marca_veto_do_cliente(db, escopo_planejamento):
    e = escopo_planejamento
    async with db.service_session() as conn:
        await conn.execute(
            "insert into preferences.constraints (scope_id, user_id, kind, enforcement, "
            " asset_class_code, reason, confirmed_at, confirmed_by) "
            "values (%s, %s, 'veto_classe', 'bloqueante', 'cripto', 'teste', now(), %s)",
            (e.s1, e.u1, e.u1))
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "produto.comparar_alternativas",
                                {"valor_aplicado_brl": 50000, "horizonte_anos": 2, "produtos": [
                                    {"descricao": "ETF cripto", "taxa_adm_aa": 0.01, "classe": "cripto"},
                                    {"descricao": "Fundo RF", "taxa_adm_aa": 0.005, "classe": "renda_fixa"},
                                ]},
                                scope_id=e.s1, conversation_id=None)
    out = r.output
    por_desc = {p.descricao: p for p in out.produtos}
    assert por_desc["ETF cripto"].compativel_com_vetos is False
    assert por_desc["Fundo RF"].compativel_com_vetos is True
    assert por_desc["Fundo RF"].custo_adm_total_estimado_brl == pytest.approx(500.0)
    assert not hasattr(out, "melhor") and not hasattr(out, "ranking")   # comparação, nunca escolha


# ---------------------------------------------------------------- config-first
@pytest.mark.parametrize("modulo", [planejamento, patrimonio, produto])
def test_tools_novas_sem_literal_numerico_de_premissa(modulo):
    permitidos = {0, 1, 2, 12, 100, 0.0, 1.0}   # 2 = aridade mínima da comparação (estrutural, não premissa)
    arvore = ast.parse(pathlib.Path(modulo.__file__).read_text(encoding="utf-8"))
    ofensores = [n.value for n in ast.walk(arvore)
                 if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                 and not isinstance(n.value, bool) and n.value not in permitidos]
    assert ofensores == [], f"números fora de policy em {modulo.__name__}: {ofensores}"
