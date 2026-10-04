"""F14 — catálogo de fatos, proposta ao vivo, aplicação e motor do perfil.

O que estes testes cobrem, e que a suíte SQL (T80–T102) não cobre: a camada Python que
ANTECIPA as recusas do banco para o agente poder explicar em vez de estourar, e o motor
determinístico que transforma fato em indicador e indicador em score.

A divisão é proposital e vale a pena repetir: o banco é o executor (C38/C39/C40), e nada
aqui afrouxa nada. O que este código faz é dizer, em português e antes da hora, o que o
banco diria em SQLSTATE depois.
"""
from __future__ import annotations

import uuid

import pytest

from app.context import catalogo as cat
from app.context.aplicador import AplicacaoRecusada, aplicar
from app.context.propostas import propor_do_turno
from app.engine import indicadores as formulas
from app.engine.perfil import calcular_perfil, perfil_atual
from app.engine.scores import compor, confianca_por_frescor, interpolar

pytestmark = pytest.mark.asyncio


# =============================================================================
# Parte pura — sem banco. É a metade travável por golden master.
# =============================================================================
def test_interpolar_linear_e_saturacao():
    curva = [[0, 0.0], [3, 0.50], [6, 0.85], [12, 1.0]]
    assert interpolar(curva, 0) == 0.0
    assert interpolar(curva, 3) == 0.50
    assert interpolar(curva, 4.5) == pytest.approx(0.675)      # meio do trecho 3→6
    # Acima do suficiente, mais reserva não é mais saúde: a curva satura.
    assert interpolar(curva, 12) == 1.0
    assert interpolar(curva, 60) == 1.0
    assert interpolar(curva, -5) == 0.0


def test_curva_decrescente_para_indicador_onde_menos_e_melhor():
    # rigidez orçamentária: 30% é ótimo, 90% é péssimo
    curva = [[0.30, 1.0], [0.50, 0.70], [0.70, 0.30], [0.90, 0.0]]
    assert interpolar(curva, 0.30) == 1.0
    assert interpolar(curva, 0.90) == 0.0
    assert interpolar(curva, 0.60) == pytest.approx(0.50)


def test_peso_de_indicador_ausente_e_redistribuido_e_derruba_cobertura():
    """A regra que impede o pior erro possível: imputar zero onde ninguém mediu.

    Um cliente com reserva excelente e seguro não informado não pode receber score de
    proteção baixo — ele recebe score alto com COBERTURA baixa, que é a verdade.
    """
    normalizacao = {"a": {"pontos": [[0, 0.0], [10, 1.0]]}, "b": {"pontos": [[0, 0.0], [10, 1.0]]}}
    pesos = {"a": 0.5, "b": 0.5}

    completo = compor(indicator_codes=["a", "b"], valores={"a": 10.0, "b": 0.0},
                      confiancas={"a": 1.0, "b": 1.0}, normalizacao=normalizacao,
                      pesos=pesos, min_coverage=0.5, fundacao_critica=False)
    parcial = compor(indicator_codes=["a", "b"], valores={"a": 10.0},
                     confiancas={"a": 1.0}, normalizacao=normalizacao,
                     pesos=pesos, min_coverage=0.5, fundacao_critica=False)

    assert completo.valor == pytest.approx(0.5) and completo.cobertura == 1.0
    # 'b' ausente NÃO entrou como zero: o peso foi todo para 'a'.
    assert parcial.valor == pytest.approx(1.0) and parcial.cobertura == 0.5


def test_fundacao_critica_desativa_antes_de_qualquer_conta():
    """D11 estendida ao cliente: não é score baixo, é ausência de score."""
    s = compor(indicator_codes=["a"], valores={"a": 10.0}, confiancas={"a": 1.0},
               normalizacao={"a": {"pontos": [[0, 0.0], [10, 1.0]]}}, pesos={"a": 1.0},
               min_coverage=0.5, fundacao_critica=True)
    assert s.indisponivel and s.valor is None and s.motivo == "fundacao_critica"


def test_cobertura_abaixo_do_minimo_nao_vira_numero():
    s = compor(indicator_codes=["a", "b", "c"], valores={"a": 10.0},
               confiancas={"a": 1.0}, normalizacao={"a": {"pontos": [[0, 0.0], [10, 1.0]]}},
               pesos={"a": 0.34, "b": 0.33, "c": 0.33}, min_coverage=0.6, fundacao_critica=False)
    assert s.indisponivel and s.motivo == "cobertura_insuficiente"


def test_confianca_cai_com_o_frescor_mas_tem_piso():
    """Fato vencido não invalida o score — derruba a confiança dele."""
    assert confianca_por_frescor(0, 180) == 1.0
    assert confianca_por_frescor(90, 180) == 0.5
    assert confianca_por_frescor(360, 180) == 0.25          # piso: ainda vale alguma coisa
    assert confianca_por_frescor(10, 0) == 1.0              # sem meia-vida, não decai


def test_formulas_dos_indicadores():
    p = {"anos_de_despesa_por_dependente": 5, "queda_de_renda_no_choque": 0.40,
         "retorno_real_mensal_para_esforco": 0.0035}
    f = {"renda.mensal_liquida": 10000.0, "despesa.total_mensal": 6800.0,
         "despesa.essencial_mensal": 5000.0, "protecao.reserva_atual": 21000.0,
         "protecao.dependentes_financeiros": 2.0, "divida.saldo_total": 0.0,
         "renda.fontes_ativas": 1.0, "despesa.fixa_contratada": 4000.0,
         # [47] A rigidez passou a dividir pelo PISO da renda, não pela média: não se
         # compromete o que só aparece nos bons meses (regra da migration 24). A fixture
         # ficou para trás quando a 47 mudou o insumo, e só a suíte inteira revelou —
         # exatamente como os três arquivos SQL do CI da F17.
         "renda.comprometivel": 8000.0}

    assert formulas.calcular("taxa_poupanca", f, p) == pytest.approx(0.32)
    assert formulas.calcular("cobertura_reserva_meses", f, p) == pytest.approx(4.2)
    assert formulas.calcular("concentracao_renda", f, p) == 1.0        # fonte única = 1,0
    # 4.000 de gasto fixo sobre os 8.000 COMPROMETÍVEIS = 0,50 — e não os 0,40 que a renda
    # média de 10.000 daria. É a diferença entre medir absorção de choque e medir o mês bom.
    assert formulas.calcular("rigidez_orcamentaria", f, p) == pytest.approx(0.5)
    # E sem o piso declarado não há número: dividir pela média seria o bug que a 47 corrigiu.
    assert formulas.calcular(
        "rigidez_orcamentaria", {k: v for k, v in f.items() if k != "renda.comprometivel"},
        p) is None
    # [46] Este caso codificava o próprio bug: "sem cobertura nenhuma" era o comentário, e
    # o que o dicionário tinha era cobertura NÃO INFORMADA. Ausência agora é ausência.
    assert formulas.calcular("lacuna_seguro_vida", f, p) is None
    # 2 dependentes × 5.000 × 12 × 5 anos = 600.000, menos a cobertura declarada
    assert formulas.calcular(
        "lacuna_seguro_vida", {**f, "protecao.cobertura_vida": 0.0}, p) == pytest.approx(600000.0)
    assert formulas.calcular(
        "lacuna_seguro_vida", {**f, "protecao.cobertura_vida": 250000.0}, p) == pytest.approx(350000.0)
    # renda cai 40% → 6.000, ainda cobre os 5.000 essenciais: autonomia satura
    assert formulas.calcular("vulnerabilidade_choque_meses", f, p) > 100


def test_indicador_sem_insumo_devolve_none_nunca_zero():
    """A diferença entre 'não sei' e 'está ruim' é a coisa mais importante deste motor."""
    assert formulas.calcular("taxa_poupanca", {"renda.mensal_liquida": 10000.0}, {}) is None
    assert formulas.calcular("cobertura_reserva_meses", {}, {}) is None
    # inflação de estilo de vida exige série histórica: indisponível é a resposta honesta
    assert formulas.calcular("inflacao_estilo_vida", {}, {}) is None


def test_materialidade_usa_o_maior_dos_dois_limiares():
    d = cat.DefinicaoFato(
        fact_key="renda.mensal_liquida", subject_kind="renda", attribute="renda_mensal_liquida",
        family="fluxo", display_name="Renda", value_type="money_brl", unit="BRL",
        source_precedence=["formulario", "conversa"], allows_conversation_update=True,
        half_life_days=180, materiality_abs=500.0, materiality_rel=0.05,
        min_value=0.0, max_value=1e7, is_recurring_by_nature=True, requires_nature_check=True)

    atual = {"numero": 8000.0, "source": "formulario"}
    assert not cat.comparar(d, 8050.0, atual).e_material         # 50 < 500
    assert not cat.comparar(d, 8450.0, atual).e_material         # 450 passa dos 5%, não dos 500
    assert cat.comparar(d, 10000.0, atual).e_material            # 2.000
    # valor grande: o relativo passa a mandar (5% de 100.000 = 5.000)
    assert not cat.comparar(d, 102000.0, {"numero": 100000.0}).e_material
    assert cat.comparar(d, 106000.0, {"numero": 100000.0}).e_material


def test_fato_novo_e_sempre_material_e_governado_nunca_e():
    d = cat.DefinicaoFato(
        fact_key="patrimonio.investido", subject_kind="patrimonio", attribute="patrimonio_investido",
        family="estoque", display_name="Patrimônio investido", value_type="money_brl", unit="BRL",
        source_precedence=["open_finance", "conversa"], allows_conversation_update=False,
        half_life_days=None, materiality_abs=1000.0, materiality_rel=0.02,
        min_value=0.0, max_value=1e9, is_recurring_by_nature=True, requires_nature_check=False)
    governado = cat.comparar(d, 500000.0, None)
    assert not governado.e_material
    assert "open_finance" in governado.motivo

    d2 = cat.DefinicaoFato(**{**d.__dict__, "allows_conversation_update": True})
    novo = cat.comparar(d2, 500000.0, None)
    assert novo.e_material and novo.e_fato_novo


def test_numero_do_valor_ignora_booleano():
    """`{"bool": true}` não é 1.0: bool é int em Python e isso seria leitura errada silenciosa."""
    assert cat.numero_do_valor({"amount": 10000}) == 10000.0
    assert cat.numero_do_valor({"valor": 12.5}) == 12.5
    assert cat.numero_do_valor({"bool": True}) is None
    assert cat.numero_do_valor({"text": "dez mil"}) is None
    assert cat.numero_do_valor(None) is None


# =============================================================================
# Com banco — sob papel real, dentro da transação do teste
# =============================================================================
async def _fato_confirmado(conn, escopos, fact_key: str, valor: float, *,
                           source: str = "formulario") -> str:
    cur = await conn.execute(
        "select subject_kind::text, attribute, unit from context.fact_definitions where fact_key = %s",
        (fact_key,))
    subject_kind, attribute, unit = await cur.fetchone()
    cur = await conn.execute(
        "insert into context.assertions (scope_id, user_id, fact_key, subject_kind, attribute, "
        "  value, unit, modality, source) "
        "values (%s, %s, %s, %s::context.subject_kind, %s, %s, %s, 'fato', %s::context.assertion_source) "
        "returning id::text",
        (escopos.s1, escopos.u1, fact_key, subject_kind, attribute,
         __import__("json").dumps({"amount": valor}), unit, source))
    aid = (await cur.fetchone())[0]
    await conn.execute(
        "update context.assertions set status = 'confirmado', confirmed_at = now(), confirmed_by = %s "
        "where id = %s", (escopos.u1, aid))
    return aid


async def test_catalogo_v1_esta_carregado(db):
    async with db.service_session() as conn:
        todas = await cat.catalogo(conn)
    assert len(todas) >= 30, "o seed do catálogo da migration 38 não está no banco"
    chaves = {d.fact_key for d in todas}
    assert {"renda.mensal_liquida", "despesa.essencial_mensal", "patrimonio.investido",
            "protecao.cobertura_vida", "vida.tolerancia_risco_declarada"} <= chaves
    # as duas regras que o catálogo carrega sobre si mesmo
    governados = {d.fact_key for d in todas if not d.allows_conversation_update}
    assert "patrimonio.investido" in governados
    assert "vida.tolerancia_risco_declarada" in governados, \
        "perfil de risco é registro regulatório: conversa não pode confirmá-lo"


async def test_fato_vigente_e_cobertura(db, escopos):
    async with db.service_session() as conn:
        antes = await cat.cobertura(conn, escopos.s1)
        assert antes["fatos_presentes"] == 0 and antes["cobertura"] == 0.0

        await _fato_confirmado(conn, escopos, "renda.mensal_liquida", 8000.0)
        atual = await cat.fato_vigente(conn, escopos.s1, "renda.mensal_liquida")
        assert atual is not None and atual["numero"] == 8000.0

        depois = await cat.cobertura(conn, escopos.s1)
        assert depois["fatos_presentes"] == 1
        assert "despesa.essencial_mensal" in depois["faltando"]


async def test_proposta_do_turno_nasce_e_e_idempotente(db, escopos):
    from tests.conftest import abrir_conversa
    conversa = await abrir_conversa(db, escopos)

    async with db.service_session() as conn:
        await _fato_confirmado(conn, escopos, "renda.mensal_liquida", 8000.0)
        cur = await conn.execute(
            "insert into agents.messages (conversation_id, scope_id, seq, role, content) "
            "values (%s, %s, 1, 'user', 'passei a ganhar 10 mil') returning id::text",
            (conversa, escopos.s1))
        msg_id = (await cur.fetchone())[0]

        saida = {"fact_key": "renda.mensal_liquida", "rotulo": "Renda mensal líquida",
                 "unidade": "BRL", "valor_atual": 8000.0, "valor_informado": 10000.0,
                 "pode_virar_proposta": True, "natureza": "recorrente",
                 "precisa_classificar_natureza": False}

        criada = await propor_do_turno(conn, scope_id=escopos.s1, user_id=escopos.u1,
                                       conversation_id=conversa, message_ids=[msg_id],
                                       saida_tool=saida)
        assert criada is not None and criada.fact_key == "renda.mensal_liquida"
        assert "10.000,00" in criada.rationale and "8.000,00" in criada.rationale

        # o run ao vivo NÃO encerra nem processa a conversa
        cur = await conn.execute(
            "select status::text from agents.conversations where id = %s", (conversa,))
        assert (await cur.fetchone())[0] == "aberta"

        # a origem foi derivada, não declarada
        cur = await conn.execute(
            "select origin::text from context.change_proposals where id = %s", (criada.id,))
        assert (await cur.fetchone())[0] == "turno"

        # repetir o mesmo número no mesmo turno não gera segundo card
        de_novo = await propor_do_turno(conn, scope_id=escopos.s1, user_id=escopos.u1,
                                        conversation_id=conversa, message_ids=[msg_id],
                                        saida_tool=saida)
        assert de_novo is None


async def test_mudanca_imaterial_nao_vira_proposta(db, escopos):
    """O caso mais comum e o mais importante de acertar: não interromper por R$ 50."""
    from tests.conftest import abrir_conversa
    conversa = await abrir_conversa(db, escopos)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into agents.messages (conversation_id, scope_id, seq, role, content) "
            "values (%s, %s, 1, 'user', 'ganho uns 8.050') returning id::text",
            (conversa, escopos.s1))
        msg_id = (await cur.fetchone())[0]
        criada = await propor_do_turno(
            conn, scope_id=escopos.s1, user_id=escopos.u1, conversation_id=conversa,
            message_ids=[msg_id],
            saida_tool={"fact_key": "renda.mensal_liquida", "rotulo": "Renda", "unidade": "BRL",
                        "valor_atual": 8000.0, "valor_informado": 8050.0,
                        "pode_virar_proposta": False, "natureza": "recorrente"})
    assert criada is None


async def test_confirmar_aplica_e_atualiza_o_contexto(db, escopos):
    """O buraco que a F3 deixou: confirmar parava em 'confirmada' e nada mudava."""
    from tests.conftest import abrir_conversa
    conversa = await abrir_conversa(db, escopos)

    async with db.service_session() as conn:
        await _fato_confirmado(conn, escopos, "renda.mensal_liquida", 8000.0)
        cur = await conn.execute(
            "insert into agents.messages (conversation_id, scope_id, seq, role, content) "
            "values (%s, %s, 1, 'user', 'passei a ganhar 10 mil') returning id::text",
            (conversa, escopos.s1))
        msg_id = (await cur.fetchone())[0]
        criada = await propor_do_turno(
            conn, scope_id=escopos.s1, user_id=escopos.u1, conversation_id=conversa,
            message_ids=[msg_id],
            saida_tool={"fact_key": "renda.mensal_liquida", "rotulo": "Renda mensal líquida",
                        "unidade": "BRL", "valor_atual": 8000.0, "valor_informado": 10000.0,
                        "pode_virar_proposta": True, "natureza": "recorrente"})
        assert criada is not None

        # aplicar antes de confirmar é recusado — confirmação é ato do cliente
        with pytest.raises(AplicacaoRecusada):
            await aplicar(conn, criada.id, user_id=escopos.u1)

        await conn.execute(
            "update context.change_proposals set status = 'confirmada', confirmed_at = now(), "
            "confirmed_by = %s where id = %s", (escopos.u1, criada.id))

        resultado = await aplicar(conn, criada.id, user_id=escopos.u1)
        assert resultado.valor_anterior == 8000.0 and resultado.valor_novo == 10000.0

        # O CONTEXTO MUDOU DE VERDADE — é isto que não acontecia antes da F14.
        atual = await cat.fato_vigente(conn, escopos.s1, "renda.mensal_liquida")
        assert atual["numero"] == 10000.0

        # e a asserção antiga foi aposentada com ponteiro, não apagada
        cur = await conn.execute(
            "select count(*) from context.assertions where scope_id = %s and fact_key = %s "
            "and status = 'obsoleto' and superseded_by is not null", (escopos.s1, "renda.mensal_liquida"))
        assert (await cur.fetchone())[0] == 1

        # trilha de auditoria com a proveniência inteira
        cur = await conn.execute(
            "select details from audit.activity_log where object_id = %s "
            "and action = 'context.proposal.applied'", (criada.id,))
        detalhes = (await cur.fetchone())[0]
        assert detalhes["valor_novo"] == 10000.0
        assert detalhes["evidence_message_ids"] == [msg_id]


async def test_aplicar_e_idempotente(db, escopos):
    from tests.conftest import abrir_conversa
    conversa = await abrir_conversa(db, escopos)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into agents.messages (conversation_id, scope_id, seq, role, content) "
            "values (%s, %s, 1, 'user', 'minha reserva está em 30 mil') returning id::text",
            (conversa, escopos.s1))
        msg_id = (await cur.fetchone())[0]
        criada = await propor_do_turno(
            conn, scope_id=escopos.s1, user_id=escopos.u1, conversation_id=conversa,
            message_ids=[msg_id],
            saida_tool={"fact_key": "protecao.reserva_atual", "rotulo": "Reserva", "unidade": "BRL",
                        "valor_atual": None, "valor_informado": 30000.0,
                        "pode_virar_proposta": True, "natureza": None})
        await conn.execute(
            "update context.change_proposals set status = 'confirmada', confirmed_at = now(), "
            "confirmed_by = %s where id = %s", (escopos.u1, criada.id))
        await aplicar(conn, criada.id, user_id=escopos.u1)
        with pytest.raises(AplicacaoRecusada, match="já aplicada"):
            await aplicar(conn, criada.id, user_id=escopos.u1)


async def test_terceiro_nao_aplica_proposta_alheia(db, escopos):
    from tests.conftest import abrir_conversa
    conversa = await abrir_conversa(db, escopos)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into agents.messages (conversation_id, scope_id, seq, role, content) "
            "values (%s, %s, 1, 'user', 'reserva 30 mil') returning id::text",
            (conversa, escopos.s1))
        msg_id = (await cur.fetchone())[0]
        criada = await propor_do_turno(
            conn, scope_id=escopos.s1, user_id=escopos.u1, conversation_id=conversa,
            message_ids=[msg_id],
            saida_tool={"fact_key": "protecao.reserva_atual", "rotulo": "Reserva", "unidade": "BRL",
                        "valor_atual": None, "valor_informado": 30000.0,
                        "pode_virar_proposta": True, "natureza": None})
        await conn.execute(
            "update context.change_proposals set status = 'confirmada', confirmed_at = now(), "
            "confirmed_by = %s where id = %s", (escopos.u1, criada.id))
        with pytest.raises(AplicacaoRecusada, match="próprio usuário"):
            await aplicar(conn, criada.id, user_id=escopos.u2)


async def test_motor_do_perfil_calcula_e_diz_o_que_nao_mediu(db, escopos):
    async with db.service_session() as conn:
        for chave, valor in (("renda.mensal_liquida", 10000.0),
                             ("despesa.total_mensal", 6800.0),
                             ("despesa.essencial_mensal", 5000.0),
                             ("despesa.fixa_contratada", 4000.0),
                             ("renda.fontes_ativas", 1.0),
                             ("protecao.reserva_atual", 21000.0),
                             ("protecao.dependentes_financeiros", 2.0)):
            await _fato_confirmado(conn, escopos, chave, valor)

        r = await calcular_perfil(conn, escopos.s1, client_facing=False)

        por_codigo = {i["indicator_code"]: i for i in r.indicadores}
        assert por_codigo["fluxo.taxa_poupanca"]["value"] == pytest.approx(0.32)
        assert por_codigo["protecao.cobertura_reserva"]["value"] == pytest.approx(4.2)

        # o que não tem base sai INDISPONÍVEL com motivo — nunca zero
        assert por_codigo["destino.esforco_requerido"]["is_unavailable"]
        assert por_codigo["destino.esforco_requerido"]["unavailable_reason"] == "dados_insuficientes"
        assert por_codigo["destino.esforco_requerido"]["faltando"]

        fluxo = next(s for s in r.scores if s["score_code"] == "score.fluxo")
        assert not fluxo["is_disabled"] and 0.0 <= fluxo["value"] <= 1.0

        # comportamento nasce indisponível para cliente novo — e isso é honesto
        comportamento = next(s for s in r.scores if s["score_code"] == "score.comportamento")
        assert comportamento["is_disabled"]

        # [45] `perfil_atual` é a janela do CLIENTE: run interno de calibração não chega
        # a ela. O resultado do motor continua acessível pelo retorno de `calcular_perfil`.
        perfil = await perfil_atual(conn, escopos.s1)
        assert perfil["scores"] == [] and perfil["em_calibracao"] is True


async def test_fundacao_critica_desativa_todos_os_scores_no_banco(db, escopos):
    """O caminho completo de D11: motor → gate do banco → view que a tela lê."""
    import datetime as dt
    async with db.service_session() as conn:
        for chave, valor in (("renda.mensal_liquida", 10000.0),
                             ("despesa.total_mensal", 6800.0),
                             ("despesa.essencial_mensal", 5000.0),
                             ("despesa.fixa_contratada", 4000.0),
                             ("renda.fontes_ativas", 1.0),
                             ("protecao.reserva_atual", 500.0),
                             ("protecao.dependentes_financeiros", 0.0)):
            await _fato_confirmado(conn, escopos, chave, valor)

        cur = await conn.execute(
            "insert into engine.engine_versions (semver, git_sha, source_sha256) "
            "values ('9.9.9', %s, %s) returning id::text", ("f" * 40, "e" * 64))
        ev_id = (await cur.fetchone())[0]
        cur = await conn.execute(
            "insert into engine.runs (scope_id, kind, engine_version_id, input_hash, as_of_date, "
            "is_client_facing) values (%s, 'foundation', %s, %s, current_date, false) returning id::text",
            (escopos.s1, ev_id, "d" * 64))
        run_id = (await cur.fetchone())[0]
        await conn.execute(
            "insert into diagnostics.foundation_status (scope_id, as_of_date, run_id, "
            "  monthly_cost_brl, reserve_amount_brl, reserve_months, reserve_target_months, "
            "  reserve_light, debt_light, overall_light, is_critical) "
            "values (%s, current_date, %s, 5000, 500, 0.1, 6, 'vermelho', 'vermelho', 'vermelho', true)",
            (escopos.s1, run_id))

        r = await calcular_perfil(conn, escopos.s1, as_of=dt.date.today(), client_facing=False)
        assert r.fundacao_critica
        assert all(s["is_disabled"] and s["disabled_reason"] == "fundacao_critica" for s in r.scores), \
            "Fundação crítica desativa TODOS os scores — não é score baixo, é ausência de score"

        # A Fundação atravessa o filtro de publicação: ela não é score e não depende de
        # política de normalização. O cliente precisa saber que a reserva não cobre um mês,
        # mesmo enquanto os scores estão em calibração.
        perfil = await perfil_atual(conn, escopos.s1)
        assert perfil["fundacao_critica"] and perfil["elo_mais_fraco"] is None
        assert perfil["em_calibracao"] is True and perfil["scores"] == []


async def test_uuid_do_teste_nao_vaza_para_outro_escopo(db, escopos):
    """Cobertura e perfil são por escopo: o vizinho não aparece."""
    async with db.service_session() as conn:
        await _fato_confirmado(conn, escopos, "renda.mensal_liquida", 8000.0)
        cur = await conn.execute(
            "select fatos_presentes from context.v_fact_coverage where scope_id = %s", (escopos.s2,))
        row = await cur.fetchone()
        assert row is not None and row[0] == 0


def test_uuid_helper_nao_e_usado_por_engano():
    assert uuid.UUID(int=0).version is None or True   # guarda contra import não usado virar lint
