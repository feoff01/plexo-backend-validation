"""F15 — derivação da estrutura para o catálogo, e a janela operável do motor.

O que estes testes protegem, e que a suíte SQL (T103–T109) não alcança: as duas regras do job
(não derivar o que o cliente confirmou; não regravar valor igual) e as decisões de MODELAGEM da
parte pura — que são onde um motor de diagnóstico erra de verdade.

A mais importante delas: `fluxo.aporte_mensal` **não** é derivado. O superávit do orçamento é
capacidade ("quanto caberia"); o aporte é comportamento ("quanto de fato vai"). Derivar um pelo
outro faria todo plano parecer mais fácil do que é.
"""
from __future__ import annotations

import json

import pytest

from app.context import catalogo as cat
from app.context.derivacao import Bruto, derivar, derivar_escopo

pytestmark = pytest.mark.asyncio


# =============================================================================
# Parte pura — sem banco
# =============================================================================
def _bruto_completo() -> Bruto:
    return Bruto(
        income_summary={"fixed_brl": 20000.0, "variable_brl": 7800.0, "variable_p10_brl": 4000.0,
                        "committable_brl": 24000.0, "months_observed": 12, "variable_share": 0.28},
        income_breakdown={"monthly_gross_brl": 29300.0, "fixed_brl": 20000.0,
                          "variable_brl": 7800.0, "variable_share": 0.28},
        fontes_de_renda=4,
        custo_medio_mensal=12400.0,
        meses_de_orcamento=12,
        essencial_mensal=8200.0,
        fixo_contratado=6100.0,
        dividas=[{"descricao": "financiamento", "outstanding_brl": 300000.0, "annual_rate": 0.11,
                  "monthly_payment_brl": 4000.0, "is_expensive": False},
                 {"descricao": "consignado", "outstanding_brl": 29500.0, "annual_rate": 0.22,
                  "monthly_payment_brl": 600.0, "is_expensive": True}],
        patrimonio={"investivel": 486000.0, "nao_financeiro": 1365000.0, "liquido": 1521500.0},
        familia={"dependentes": 3, "membros": 4},
        objetivo={"valor": 2800000.0, "prioridade": 1, "prazo_meses": 208.1},
        reserva=None,
    )


def test_derivacao_cobre_as_familias_a_partir_do_que_o_banco_ja_sabe():
    fatos = {f.fact_key: f.valor for f in derivar(_bruto_completo())}
    assert fatos["renda.mensal_liquida"] == 27800.0
    assert fatos["renda.mensal_bruta"] == 29300.0
    # [F16] o piso, que julga sustentabilidade — a migration 24 já mandava usá-lo
    assert fatos["renda.comprometivel"] == 24000.0
    assert fatos["renda.fontes_ativas"] == 4
    assert fatos["despesa.total_mensal"] == 12400.0
    assert fatos["despesa.essencial_mensal"] == 8200.0
    assert fatos["despesa.fixa_contratada"] == 6100.0
    assert fatos["patrimonio.liquido"] == 1521500.0
    assert fatos["protecao.dependentes_financeiros"] == 3
    assert fatos["objetivo.valor_alvo"] == 2800000.0


def test_aporte_mensal_nao_e_derivado_do_superavit():
    """A decisão de modelagem mais consequente deste módulo.

    Superávit é CAPACIDADE; aporte é COMPORTAMENTO. `destino.esforco_requerido` divide o
    aporte necessário justamente por `fluxo.aporte_mensal` — derivar capacidade ali faria
    todo plano parecer factível. Sem série de aportes efetivos, ele é pergunta.
    """
    fatos = {f.fact_key for f in derivar(_bruto_completo())}
    assert "fluxo.aporte_mensal" not in fatos


def test_custo_da_divida_e_ponderado_pelo_saldo():
    """Média simples esconderia o rotativo pequeno e caro — que é exatamente o que decide."""
    fatos = {f.fact_key: f.valor for f in derivar(_bruto_completo())}
    esperado = (300000 * 0.11 + 29500 * 0.22) / 329500
    assert fatos["divida.custo_medio"] == pytest.approx(esperado)
    assert fatos["divida.saldo_total"] == 329500.0
    assert fatos["divida.parcela_mensal"] == 4600.0


def test_sem_divida_registrada_os_TRES_zeros_sao_fato():
    """[F16] Mudou de propósito: os três nascem, não só o saldo.

    Com apenas `saldo_total`, a cobertura de Estoque caía a 40% e o cliente SEM dívida
    ficava sem score enquanto o endividado ganhava um. Consultado e não há dívida ⇒ custo
    zero e parcela zero são FATOS, e são a melhor notícia possível.
    """
    b = _bruto_completo()
    b.dividas = []
    fatos = {f.fact_key: f.valor for f in derivar(b)}
    assert fatos["divida.saldo_total"] == 0.0
    assert fatos["divida.custo_medio"] == 0.0
    assert fatos["divida.parcela_mensal"] == 0.0


def test_insumo_ausente_nao_vira_zero():
    """A regra que atravessa a camada inteira: ausência é ausência, não zero."""
    fatos = {f.fact_key for f in derivar(Bruto())}
    assert fatos == set(), "Bruto não populado não afirma nada — `None` ≠ `[]`"

    b = Bruto(patrimonio={"investivel": 100.0, "nao_financeiro": None, "liquido": 100.0})
    fatos = {f.fact_key for f in derivar(b)}
    assert "patrimonio.imobilizado" not in fatos
    assert "patrimonio.investido" in fatos


def test_toda_derivacao_declara_de_onde_veio():
    """`source_ref` guarda a tabela/view que sustentou o número — é a proveniência que a
    inspeção regulatória pede, e o que permite refazer a conta."""
    for f in derivar(_bruto_completo()):
        assert f.origem, f"{f.fact_key} sem origem declarada"
        assert (f.valor is not None) != (f.bruto is not None), (
            f"{f.fact_key}: ou traz número, ou traz o jsonb do fato não numérico")


# =============================================================================
# Com banco
# =============================================================================
async def _confirmar(conn, escopos, fact_key: str, valor: float) -> None:
    cur = await conn.execute(
        "select subject_kind::text, attribute, unit from context.fact_definitions where fact_key = %s",
        (fact_key,))
    subject_kind, attribute, unit = await cur.fetchone()
    cur = await conn.execute(
        "insert into context.assertions (scope_id, user_id, fact_key, subject_kind, attribute, "
        "  value, unit, modality, source) "
        "values (%s, %s, %s, %s::context.subject_kind, %s, %s, %s, 'fato', 'formulario') returning id::text",
        (escopos.s1, escopos.u1, fact_key, subject_kind, attribute,
         json.dumps({"amount": valor}), unit))
    aid = (await cur.fetchone())[0]
    await conn.execute(
        "update context.assertions set status = 'confirmado', confirmed_at = now(), confirmed_by = %s "
        "where id = %s", (escopos.u1, aid))


async def _orcamento(conn, escopos, *, renda: float, despesa: float, essencial: float) -> None:
    await conn.execute(
        "insert into budget.income_summaries (scope_id, month, fixed_brl, variable_brl, "
        "  variable_p10_brl, committable_brl, months_observed) "
        "values (%s, date_trunc('month', current_date)::date, %s, 0, 0, %s, 12)",
        (escopos.s1, renda, renda))
    await conn.execute(
        "insert into budget.monthly_summaries (scope_id, month, income_brl, expense_brl, "
        "  essential_expense_brl) "
        "values (%s, date_trunc('month', current_date)::date, %s, %s, %s)",
        (escopos.s1, renda, despesa, essencial))


async def test_derivacao_grava_como_inferido_e_com_confianca_descontada(db, escopos):
    async with db.service_session() as conn:
        await _orcamento(conn, escopos, renda=10000, despesa=6800, essencial=5000)
        r = await derivar_escopo(conn, escopos.s1, escopos.u1)
        assert "renda.mensal_liquida" in r.gravados

        cur = await conn.execute(
            "select status::text, source::text, confidence::float, source_ref "
            "from context.assertions where scope_id = %s and fact_key = 'renda.mensal_liquida'",
            (escopos.s1,))
        status, source, confianca, ref = await cur.fetchone()
        assert status == "inferido", "derivação NUNCA nasce confirmada — C22a"
        assert source == "inferencia_motor"
        assert confianca < 1.0, "fato deduzido entra com confiança descontada pela política"
        assert ref["derivado_de"]

        # o motor enxerga; o agente não
        assert (await cat.fato_vigente(conn, escopos.s1, "renda.mensal_liquida")) is None
        cur = await conn.execute(
            "select numero::float, confirmado from context.v_fact_operavel "
            "where scope_id = %s and fact_key = 'renda.mensal_liquida'", (escopos.s1,))
        numero, confirmado = await cur.fetchone()
        assert numero == 10000.0 and confirmado is False


async def test_derivacao_e_idempotente(db, escopos):
    """Asserção é append-only: sem esta regra o job diário viraria log de execução do motor."""
    async with db.service_session() as conn:
        await _orcamento(conn, escopos, renda=10000, despesa=6800, essencial=5000)
        primeira = await derivar_escopo(conn, escopos.s1, escopos.u1)
        segunda = await derivar_escopo(conn, escopos.s1, escopos.u1)
        assert primeira.gravados and not segunda.gravados
        assert set(primeira.gravados) <= set(segunda.pulados_iguais)

        cur = await conn.execute(
            "select count(*) from context.assertions "
            "where scope_id = %s and fact_key = 'despesa.total_mensal'", (escopos.s1,))
        assert (await cur.fetchone())[0] == 1


async def test_derivacao_nao_toca_no_que_o_cliente_confirmou(db, escopos):
    """Se o cliente disse, o cliente manda — e o motor não gera conflito por cima."""
    async with db.service_session() as conn:
        await _orcamento(conn, escopos, renda=10000, despesa=6800, essencial=5000)
        await _confirmar(conn, escopos, "renda.mensal_liquida", 12000.0)

        r = await derivar_escopo(conn, escopos.s1, escopos.u1)
        assert "renda.mensal_liquida" in r.pulados_confirmados
        assert "renda.mensal_liquida" not in r.gravados

        atual = await cat.fato_vigente(conn, escopos.s1, "renda.mensal_liquida")
        assert atual["numero"] == 12000.0, "o número do cliente permanece"

        cur = await conn.execute(
            "select count(*) from context.assertions where scope_id = %s "
            "and fact_key = 'renda.mensal_liquida' and status = 'conflitante'", (escopos.s1,))
        assert (await cur.fetchone())[0] == 0, "derivar não pode gerar conflito com o cliente"


async def test_cobertura_e_perfil_saem_do_zero(db, escopos):
    """O critério de aceite da onda: dado que o banco já tinha vira score."""
    from app.engine.perfil import calcular_perfil

    async with db.service_session() as conn:
        antes = await cat.cobertura(conn, escopos.s1)
        assert antes["fatos_presentes"] == 0

        await _orcamento(conn, escopos, renda=10000, despesa=6800, essencial=5000)
        await conn.execute(
            "insert into budget.debts (scope_id, kind, description, outstanding_brl, annual_rate, "
            "  monthly_payment_brl) values (%s, 'cartao_rotativo', 'cartão', 8000, 3.5, 900)",
            (escopos.s1,))
        await derivar_escopo(conn, escopos.s1, escopos.u1)

        depois = await cat.cobertura(conn, escopos.s1)
        assert depois["fatos_presentes"] >= 5

        r = await calcular_perfil(conn, escopos.s1, client_facing=False)
        por_codigo = {i["indicator_code"]: i for i in r.indicadores}
        assert por_codigo["fluxo.taxa_poupanca"]["value"] == pytest.approx(0.32)
        assert por_codigo["estoque.custo_da_divida"]["value"] == pytest.approx(3.5)
        # o que continua sem base continua indisponível — derivar não inventa
        assert por_codigo["destino.esforco_requerido"]["is_unavailable"]


async def test_lacuna_de_seguro_exige_saber_se_ha_seguro(db, escopos):
    """Correção da migration 44: sem dado de cobertura, "lacuna" seria afirmação sobre o
    que não se sabe. O indicador fica indisponível e a pergunta entra na fila."""
    from app.engine.perfil import calcular_perfil

    async with db.service_session() as conn:
        await _orcamento(conn, escopos, renda=10000, despesa=6800, essencial=5000)
        await _confirmar(conn, escopos, "protecao.dependentes_financeiros", 2)
        await derivar_escopo(conn, escopos.s1, escopos.u1)

        r = await calcular_perfil(conn, escopos.s1, client_facing=False)
        lacuna = next(i for i in r.indicadores if i["indicator_code"] == "protecao.lacuna_seguro_vida")
        assert lacuna["is_unavailable"]
        assert "protecao.cobertura_vida" in lacuna["faltando"]

        # informado o seguro, o indicador passa a existir
        await _confirmar(conn, escopos, "protecao.cobertura_vida", 300000.0)
        r2 = await calcular_perfil(conn, escopos.s1, client_facing=False)
        lacuna2 = next(i for i in r2.indicadores if i["indicator_code"] == "protecao.lacuna_seguro_vida")
        assert not lacuna2["is_unavailable"]
        # 2 dependentes × 5.000 × 12 × 5 anos = 600.000, menos 300.000 de cobertura
        assert lacuna2["value"] == pytest.approx(300000.0)


async def test_todo_fato_perguntavel_tem_pergunta(db):
    """A onda das perguntas depende disto — e o CHECK do banco o garante, mas o catálogo
    real precisa estar realmente preenchido."""
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select fact_key from context.fact_definitions "
            "where is_active and allows_conversation_update and pergunta is null")
        assert await cur.fetchall() == []

def test_o_limiar_de_regravacao_vem_do_catalogo_nao_do_codigo():
    """A regressão de um defeito silencioso e PROGRESSIVO.

    `objetivo.prazo_meses` é contagem regressiva: derivado em dias, ele mudava todo dia
    (23,10 → 23,06 → 23,03). A derivação usava um `0.005` cravado no código para decidir
    "valor igual", então toda execução gravava asserção nova, e o gate C38c marcava a nova e
    a anterior como `conflitante` — as duas fora da janela operável. **Duas execuções
    bastavam para o fato sumir para sempre**, levando junto o `destino.esforco_requerido`, e
    nada falhava em lugar nenhum.

    O catálogo já declarava materialidade de 3 meses para esse fato. Ninguém lia. Número
    mágico contra config-first não é questão de estilo — aqui ele apagava um indicador.
    """
    from app.context.derivacao import _mudou

    # prazo: materialidade 3 meses (abs) / 10% (rel) — a variação de um dia não é mudança
    assert not _mudou(23.10, 23.06, 3.0, 0.1)
    assert not _mudou(23.10, 23.00, 3.0, 0.1)
    # e o maior dos dois limiares manda: 10% de 23 = 2,3, menor que os 3 meses
    assert not _mudou(23.0, 20.5, 3.0, 0.1)
    assert _mudou(23.0, 19.0, 3.0, 0.1)

    # renda: 500 reais (abs) / 5% (rel) — aqui o relativo é que manda numa renda alta
    assert not _mudou(20000.0, 20400.0, 500.0, 0.05)      # 400 < max(500, 1000)
    assert _mudou(20000.0, 21500.0, 500.0, 0.05)          # 1500 > 1000
    # sem materialidade declarada, qualquer diferença conta — o comportamento antigo, mas
    # agora é o catálogo quem escolhe, não o código
    assert _mudou(10.0, 10.001, 0.0, 0.0)
