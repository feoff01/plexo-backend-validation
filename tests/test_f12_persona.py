"""
F12 — Persona de patrimônio completo (`seeds/persona.sql`) e a tool de composição do patrimônio.

Regras provadas: a persona existe com patrimônio POSITIVO e assinatura paga (o escopo de dev tem
patrimônio líquido negativo e cai no fallback `free`); a tool `planejamento.composicao_patrimonio`
soma as posições por classe de ativo com proveniência, recusa-se a devolver zero quando não há
posição (`insumo_faltante`, nunca silêncio) e NÃO enxerga posição de outro escopo sob papel real;
o bloco da composição só nasce com fonte; a parte pura está travada por golden master; e o veto
bloqueante da persona chega ao contexto que o Assessor lê.

Estes testes dependem de `python -m app.cli seed persona` (dado commitado, como o `seed dev`).
"""
from __future__ import annotations

import json
import pathlib
import uuid

import pytest

from app.db.repos.identity import plano_do_escopo
from app.tools.assessor.patrimonio import (
    ComposicaoParams, ComposicaoResolvida, calcular_composicao, preparar_composicao,
)
from app.tools.context_pack import pacote_do_escopo
from app.tools.executor import ToolContext, ToolInsumoFaltante

GOLDEN = pathlib.Path(__file__).parent / "golden"

PERSONA_USER = "0fe0a000-0000-4000-8000-000000000001"
PERSONA_SCOPE = "0fe0a000-0000-4000-8000-000000000002"

# Conferidos à mão contra seeds/persona.sql:
INVESTIDO = 486000.00
NAO_FINANCEIRO = 850000.00 + 420000.00 + 95000.00      # apto + apto alugado + carro
PASSIVO = 320000.00 + 9500.00                          # financiamento + rotativo
LIQUIDO = INVESTIDO + NAO_FINANCEIRO - PASSIVO         # 1.521.500,00


# ---------------------------------------------------------------- o seed
async def test_persona_tem_patrimonio_positivo(db):
    """O escopo de dev conversa com alguém tecnicamente falido (investível 0, líquido -15.000).
    A persona é o oposto: patrimônio real, com imóveis e passivo do lado."""
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select investivel_brl::float, nao_financeiro_brl::float, passivo_brl::float, "
            "       patrimonio_liquido_brl::float, ativos_nao_financeiros "
            "from estate.v_net_worth where scope_id = %s", (PERSONA_SCOPE,))
        row = await cur.fetchone()
    assert row is not None, "escopo da persona não existe — rode `python -m app.cli seed persona`"
    investivel, nao_fin, passivo, liquido, ativos = row
    assert investivel == INVESTIDO
    assert nao_fin == NAO_FINANCEIRO and ativos == 3
    assert passivo == PASSIVO
    assert liquido == LIQUIDO and liquido > 0


async def test_persona_esta_em_plano_pago(db):
    """Sem linha em billing.subscriptions o escopo é `free` por fallback — a persona precisa da linha."""
    async with db.service_session() as conn:
        assert await plano_do_escopo(conn, PERSONA_SCOPE) == "essential"


async def test_persona_tem_renda_fixa_e_variavel_com_piso(db):
    """A capacidade de aporte se apoia no piso p10: renda só-fixa não exercita a regra."""
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select fixed_brl::float, variable_brl::float, variable_p10_brl::float, committable_brl::float "
            "from budget.income_summaries where scope_id = %s order by month desc limit 1", (PERSONA_SCOPE,))
        row = await cur.fetchone()
    assert row is not None, "sem income_summaries — rode `seed persona`"
    fixo, variavel, p10, comprometivel = row
    assert variavel > 0 and 0 < p10 < variavel
    assert comprometivel <= fixo + p10          # a regra do banco, conferida do lado de cá


async def test_veto_bloqueante_da_persona_chega_ao_contexto(db):
    """O prompt do Assessor manda respeitar os vetos do contexto; o veto precisa chegar lá."""
    async with db.app_session(user_id=PERSONA_USER, scope_id=PERSONA_SCOPE) as conn:
        texto = await pacote_do_escopo(conn, PERSONA_SCOPE)
    assert "Restrições do cliente" in texto
    assert "cripto" in texto.lower()


# ---------------------------------------------------------------- a tool
async def test_composicao_soma_as_classes(db):
    async with db.app_session(user_id=PERSONA_USER, scope_id=PERSONA_SCOPE) as conn:
        ctx = ToolContext(conn=conn, scope_id=PERSONA_SCOPE, conversation_id=None)
        resolvido = await preparar_composicao(ComposicaoParams(), ctx)
    saida = calcular_composicao(resolvido)

    assert saida.total_investido_brl == INVESTIDO
    assert sum(c.valor_brl for c in saida.composicao) == INVESTIDO
    assert {c.classe for c in saida.composicao} == {"ipca", "caixa", "acoes_br", "fii", "multimercado"}
    assert sum(c.share_pct for c in saida.composicao) == pytest.approx(100.0, abs=0.05)
    assert saida.composicao[0].valor_brl >= saida.composicao[-1].valor_brl   # ordenado por valor
    assert saida.maior_classe == "acoes_br" and saida.maior_classe_share_pct > 0
    assert saida.as_of is not None and saida.fonte == "wealth.holdings_snapshots"
    assert saida.patrimonio_liquido_brl == LIQUIDO


async def test_composicao_sem_posicoes_devolve_insumo_faltante(db, escopos):
    """Sabotagem: escopo sem carteira não pode devolver 'R$ 0,00 investidos' como se fosse medição."""
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        ctx = ToolContext(conn=conn, scope_id=escopos.s1, conversation_id=None)
        with pytest.raises(ToolInsumoFaltante):
            await preparar_composicao(ComposicaoParams(), ctx)


async def test_composicao_ignora_posicao_de_outro_escopo(db, escopos):
    """Sabotagem de RLS sob papel real: `avnadmin` tem BYPASSRLS e passaria por fora."""
    conta, instrumento = str(uuid.uuid4()), str(uuid.uuid4())
    async with db.service_session() as conn:
        await conn.execute(
            "insert into market.instruments (id, kind, name, ticker, asset_class_code, is_in_universe) "
            "values (%s, 'acao', 'Vizinha SA', %s, 'acoes_br', false)", (instrumento, f"VZ{conta[:4]}"))
        await conn.execute(
            "insert into wealth.accounts (id, scope_id, kind, label) values (%s, %s, 'corretora', 'Vizinha')",
            (conta, escopos.s2))
        await conn.execute(
            "insert into wealth.holdings_snapshots (scope_id, account_id, instrument_id, as_of_date, "
            " value_brl, origin) values (%s, %s, %s, current_date, 999999, 'manual')",
            (escopos.s2, conta, instrumento))
        await conn.execute(
            "insert into wealth.portfolio_snapshots (scope_id, as_of_date, total_brl, by_asset_class) "
            "values (%s, current_date, 999999, '{\"acoes_br\": 999999}'::jsonb)", (escopos.s2,))

    async with db.app_session(user_id=PERSONA_USER, scope_id=PERSONA_SCOPE) as conn:
        ctx = ToolContext(conn=conn, scope_id=PERSONA_SCOPE, conversation_id=None)
        resolvido = await preparar_composicao(ComposicaoParams(), ctx)
    saida = calcular_composicao(resolvido)
    assert saida.total_investido_brl == INVESTIDO      # a posição da vizinha NÃO entrou
    assert all(c.valor_brl != 999999 for c in saida.composicao)


def test_composicao_sem_nao_financeiro_zera_o_consolidado_inteiro():
    """Sabotagem: zerar os bens e manter o patrimônio líquido cheio produziria
    'líquido R$ 1.521.500 · bens não financeiros R$ 0' — o agente leria a carteira como 1,5 milhão."""
    dados = json.loads((GOLDEN / "planejamento_composicao_patrimonio.json").read_text(encoding="utf-8"))
    r = ComposicaoResolvida.model_validate({**dados["resolvido"], "incluir_nao_financeiro": False})
    saida = calcular_composicao(r)
    assert saida.total_investido_brl == INVESTIDO          # a carteira continua medida
    consolidado = (saida.nao_financeiro_brl, saida.imoveis_brl, saida.outros_bens_brl,
                   saida.iliquido_brl, saida.passivo_brl, saida.patrimonio_liquido_brl)
    assert consolidado == (0.0,) * len(consolidado)        # tudo-ou-nada
    assert "consolidado_omitido_a_pedido" in saida.avisos


def test_composicao_golden():
    """Parte pura travada: mudança de número exige justificativa no commit."""
    dados = json.loads((GOLDEN / "planejamento_composicao_patrimonio.json").read_text(encoding="utf-8"))
    saida = calcular_composicao(ComposicaoResolvida.model_validate(dados["resolvido"]))
    assert saida.model_dump() == dados["esperado"]


def test_bloco_da_composicao_tem_fonte():
    """Sem proveniência, sem bloco (regra da F11)."""
    from app.agents.blocos import blocos_de

    dados = json.loads((GOLDEN / "planejamento_composicao_patrimonio.json").read_text(encoding="utf-8"))
    blocos = blocos_de("planejamento.composicao_patrimonio", dados["esperado"],
                       execution_id=str(uuid.uuid4()))
    assert blocos, "a tool devolve número — precisa de mapeador em blocos.py"
    for bloco in blocos:
        assert bloco["proveniencia"]["fonte"] and bloco["proveniencia"]["as_of"]
        assert bloco["nota"] and "projeção de rentabilidade" not in bloco["nota"]   # não é simulação

    # Formato `{"blocos": [...]}` desde a F19, igual aos outros 15 — antes era um array no
    # topo, e era só por isso que este golden não cabia no parametrizado de test_f11_blocos.
    golden_blocos = json.loads((GOLDEN / "blocos_planejamento_composicao_patrimonio.json").read_text(encoding="utf-8"))["blocos"]
    assert [{**b, "id": None} for b in blocos] == [{**b, "id": None} for b in golden_blocos]
