"""
F19 — o Raio-X: o produtor que a taxonomia da migration 15 esperava desde 2026.

O QUE ESTES TESTES PROVAM

  · a metade PURA detecta cada achado com o número certo, e a lista está travada por golden;
  · concentração se mede sobre a carteira INTEIRA, não sobre a parte com emissor cadastrado
    (a diferença entre 30% e 60% numa carteira metade sem cadastro);
  · a cobertura do FGC exige emissor associado E instrumento garantido — ação de banco não;
  · caixa parado se mede contra a reserva REQUERIDA, não contra o saldo dela: reserva cheia é
    justamente a condição que transforma o resto do caixa em dinheiro parado;
  · o motor GRAVA o que detectou, e apaga o que deixou de ser verdade;
  · a tool não deixa o modelo redigir alerta — a frase vem de dicionário na fronteira;
  · o gate de plano esconde o diagnóstico mas REVELA quantos e de que famílias.
"""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import date

import pytest

from app.engine.raiox import Carteira, Posicao, detectar, executar
from app.tools.assessor.atencao import (
    AtencaoParams, AtencaoResolvida, calcular_atencao, preparar_atencao,
)
from app.tools.executor import ToolContext, ToolInsumoFaltante

GOLDEN = pathlib.Path(__file__).parent / "golden"

# Os mesmos limiares da migration 54, escritos aqui para que o teste da parte pura não
# dependa do banco — e para que uma mudança de política apareça como diferença no golden.
LIMIARES = {
    "concentracao_emissor_max": 0.20, "concentracao_classe_max": 0.50,
    "teto_fgc_brl": 250000, "caixa_ocioso_multiplo_da_reserva": 1.0,
    "iliquido_dias_min": 30, "iliquido_share_max": 0.10,
    "taxa_fundo_folga_sobre_referencia": 0.005, "impacto_padrao_confianca": 0.80,
}
REFERENCIAS = {"multimercado": 0.02, "acoes": 0.015, "renda_fixa": 0.005}


def _pos(**kw) -> Posicao:
    base = dict(instrument_id=str(uuid.uuid4()), nome="Papel", kind="acao", classe="acoes_br",
                grupo="renda_variavel", emissor_id=None, emissor_nome=None, emissor_fgc=False,
                valor_brl=10000.0, liquidez_dias=2, taxa_adm_aa=None)
    return Posicao(**{**base, **kw})


def _carteira(posicoes, *, saldo=None, requerida=None) -> Carteira:
    return Carteira(posicoes=tuple(posicoes),
                    total_brl=round(sum(p.valor_brl for p in posicoes), 2),
                    reserva_saldo_brl=saldo, reserva_requerida_brl=requerida)


# =============================================================================
# Metade pura
# =============================================================================
def test_concentracao_se_mede_sobre_a_carteira_inteira():
    """`v_issuer_concentration` divide pela parte COM emissor — correto para a view, errado
    para o alerta. Aqui metade da carteira não tem emissor: pela view seriam 60%, e o alerta
    dispararia sobre um número que não descreve a carteira de ninguém."""
    banco = str(uuid.uuid4())
    c = _carteira([
        _pos(valor_brl=30000.0, emissor_id=banco, emissor_nome="Banco X"),
        _pos(valor_brl=70000.0),                                   # sem emissor cadastrado
    ])
    a = next(x for x in detectar(c, LIMIARES, REFERENCIAS)
             if x.tipo == "risco.concentracao_emissor")
    # 30.000 / 100.000. Pelo denominador da view seriam 30.000/30.000 = 100%, e o achado sairia
    # CRÍTICO — sobre uma carteira em que o banco é menos de um terço.
    assert a.quantificacao["share_pct"] == 30.0
    assert a.severidade == "alta", "com o denominador errado isto viraria crítico"
    assert a.evidencia["total_carteira_brl"] == 100000.0


def test_concentracao_dispara_e_consolida_conglomerado():
    grupo = str(uuid.uuid4())
    c = _carteira([
        _pos(valor_brl=20000.0, emissor_id=grupo, emissor_nome="Grupo X"),
        _pos(valor_brl=25000.0, emissor_id=grupo, emissor_nome="Grupo X", kind="cdb", classe="selic"),
        _pos(valor_brl=55000.0),
    ])
    a = next(x for x in detectar(c, LIMIARES, REFERENCIAS)
             if x.tipo == "risco.concentracao_emissor")
    assert a.quantificacao["exposicao_brl"] == 45000.0      # as duas somadas
    assert a.quantificacao["share_pct"] == 45.0
    assert a.severidade == "critica"                        # 45% ≥ 2 × 20%
    assert a.impacto_brl_ano is None, (
        "concentração não tem custo por ano; inventar um número aqui polui a fila inteira")


def test_fgc_conta_so_instrumento_garantido():
    """Ação de banco associado NÃO entra no teto — a cobertura é do instrumento."""
    banco = str(uuid.uuid4())
    c = _carteira([
        _pos(valor_brl=200000.0, emissor_id=banco, emissor_nome="Banco X", emissor_fgc=True,
             kind="cdb", classe="selic"),
        _pos(valor_brl=100000.0, emissor_id=banco, emissor_nome="Banco X", emissor_fgc=True,
             kind="acao", classe="acoes_br"),
    ])
    fgc = [a for a in detectar(c, LIMIARES, REFERENCIAS) if a.tipo == "risco.exposicao_acima_do_fgc"]
    assert fgc == [], "200.000 em CDB está abaixo do teto; a ação não deve somar ao coberto"

    c2 = _carteira([
        _pos(valor_brl=200000.0, emissor_id=banco, emissor_nome="Banco X", emissor_fgc=True,
             kind="cdb", classe="selic"),
        _pos(valor_brl=90000.0, emissor_id=banco, emissor_nome="Banco X", emissor_fgc=True,
             kind="lci_lca", classe="selic"),
    ])
    a = next(x for x in detectar(c2, LIMIARES, REFERENCIAS) if x.tipo == "risco.exposicao_acima_do_fgc")
    assert a.quantificacao["coberto_brl"] == 290000.0
    assert a.quantificacao["excedente_brl"] == 40000.0
    assert a.evidencia["unidade_do_impacto"] == "valor_exposto_brl", (
        "40.000 é valor exposto, não custo por ano — a tela precisa saber a diferença")


def test_caixa_parado_se_mede_contra_a_reserva_REQUERIDA():
    """O defeito que a primeira execução expôs: comparando o caixa contra o SALDO da reserva,
    quem tem reserva cheia mais dinheiro parado passava como se estivesse em ordem."""
    posicoes = [_pos(valor_brl=18000.0, classe="caixa", kind="conta", grupo="caixa"),
                _pos(valor_brl=82000.0)]
    # Reserva cheia (95.000) e requerida de 69.000: 18.000 na corretora + 95.000 guardados
    # são 113.000 de caixa contra 69.000 de necessidade.
    c = _carteira(posicoes, saldo=95000.0, requerida=69000.0)
    a = next(x for x in detectar(c, LIMIARES, REFERENCIAS)
             if x.tipo == "alocacao.caixa_parado_excessivo")
    assert a.quantificacao["caixa_total_brl"] == 113000.0
    assert a.quantificacao["excedente_brl"] == 44000.0

    # E o outro lado: sem saber quanto a reserva PRECISA ser, não há alerta nenhum.
    c2 = _carteira(posicoes, saldo=95000.0, requerida=None)
    assert not [x for x in detectar(c2, LIMIARES, REFERENCIAS)
                if x.tipo == "alocacao.caixa_parado_excessivo"]


def test_quem_ainda_constroi_a_reserva_nao_e_alertado():
    """Dizer 'você tem dinheiro parado' a quem está abaixo da reserva é o oposto do certo."""
    c = _carteira([_pos(valor_brl=20000.0, classe="caixa", kind="conta", grupo="caixa"),
                   _pos(valor_brl=30000.0)], saldo=10000.0, requerida=69000.0)
    assert not [x for x in detectar(c, LIMIARES, REFERENCIAS)
                if x.tipo == "alocacao.caixa_parado_excessivo"]


def test_custo_de_fundo_usa_a_referencia_ja_aprovada():
    """Reusa `PRODUTO_REFERENCIAS`: uma segunda referência daria duas respostas para a mesma
    pergunta na mesma tela — o defeito que a F18 corrigiu na capacidade de aporte."""
    c = _carteira([_pos(valor_brl=30000.0, kind="fundo", classe="multimercado",
                        grupo="alternativos", taxa_adm_aa=0.028),
                   # dentro da folga de 0,5 p.p.: não dispara
                   _pos(valor_brl=30000.0, kind="fundo", classe="multimercado",
                        grupo="alternativos", taxa_adm_aa=0.023),
                   _pos(valor_brl=40000.0)])
    caros = [x for x in detectar(c, LIMIARES, REFERENCIAS) if x.tipo == "custo.taxa_fundo_alta"]
    assert len(caros) == 1
    assert caros[0].quantificacao["custo_ano_brl"] == 240.0     # 0,8 p.p. × 30.000
    assert caros[0].impacto_brl_ano == 240.0
    assert caros[0].evidencia["unidade_do_impacto"] == "custo_ano_brl"


def test_fundo_de_classe_sem_referencia_nao_e_avaliado():
    """Limitação declarada: as chaves de `PRODUTO_REFERENCIAS` não são os códigos de
    `market.asset_classes`. Inventar aqui um mapa faria a mesma pergunta ter duas respostas
    dependendo do caminho — melhor não avaliar do que avaliar por um mapa privado."""
    c = _carteira([_pos(valor_brl=30000.0, kind="fundo", classe="acoes_br",
                        grupo="renda_variavel", taxa_adm_aa=0.05),
                   _pos(valor_brl=70000.0)])
    assert not [x for x in detectar(c, LIMIARES, REFERENCIAS) if x.tipo == "custo.taxa_fundo_alta"]


def test_carteira_vazia_nao_produz_achado():
    """Sabotagem: sem carteira, 'nenhum problema encontrado' seria uma afirmação falsa."""
    assert detectar(_carteira([]), LIMIARES, REFERENCIAS) == []


def test_raiox_golden():
    """Parte pura travada: mudança de detecção exige justificativa no commit."""
    dados = json.loads((GOLDEN / "raiox_detectar.json").read_text(encoding="utf-8"))
    c = Carteira(posicoes=tuple(Posicao(**p) for p in dados["carteira"]["posicoes"]),
                 total_brl=dados["carteira"]["total_brl"],
                 reserva_saldo_brl=dados["carteira"]["reserva_saldo_brl"],
                 reserva_requerida_brl=dados["carteira"]["reserva_requerida_brl"])
    achados = detectar(c, dados["limiares"], dados["referencias"])
    obtido = [{"tipo": a.tipo, "chave": a.chave, "severidade": a.severidade,
               "impacto_brl_ano": a.impacto_brl_ano, "quantificacao": a.quantificacao}
              for a in achados]
    assert obtido == dados["esperado"]


# =============================================================================
# Metade impura + a tool
# =============================================================================
async def _com_carteira(db, escopos) -> None:
    async with db.service_session() as conn:
        conta = str(uuid.uuid4())
        await conn.execute(
            "insert into wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) "
            "values (%s, %s, 'corretora', 'Corretora F19R', 'Instituição', current_date - 10)",
            (conta, escopos.s1))
        banco = str(uuid.uuid4())
        await conn.execute(
            "insert into market.issuers (id, name, kind, fgc_covered) "
            "values (%s, 'Banco F19R', 'banco', true)", (banco,))
        for codigo, nome, kind, classe, valor in (
                ("F19RCDB", "CDB F19R", "cdb", "selic", 300000),
                ("F19RACAO", "Ação F19R", "acao", "acoes_br", 100000)):
            cur = await conn.execute(
                "insert into market.instruments (kind, name, ticker, asset_class_code, issuer_id, "
                "  liquidity_days) values (%s::market.instrument_kind, %s, %s, %s, %s, 2) "
                "returning id::text", (kind, nome, codigo, classe, banco))
            iid = (await cur.fetchone())[0]
            await conn.execute(
                "insert into wealth.holdings_snapshots (scope_id, account_id, instrument_id, "
                "  as_of_date, value_brl, origin) values (%s, %s, %s, current_date, %s, 'manual')",
                (escopos.s1, conta, iid, valor))


async def test_o_motor_grava_o_que_detectou(db, escopos):
    """A primeira linha que este projeto escreve em `diagnostics.findings`."""
    await _com_carteira(db, escopos)
    async with db.service_session() as conn:
        r = await executar(conn, escopos.s1)
        assert r["run_id"] is not None
        cur = await conn.execute(
            "select finding_type_code, quantification, is_current from diagnostics.findings "
            " where scope_id = %s order by finding_type_code", (escopos.s1,))
        gravados = await cur.fetchall()
        cur = await conn.execute(
            "select count(*) from diagnostics.finding_observations o "
            "  join diagnostics.findings f on f.id = o.finding_id where f.scope_id = %s",
            (escopos.s1,))
        observacoes = (await cur.fetchone())[0]
        cur = await conn.execute(
            "select total_value_brl::float, coverage_pct::float from diagnostics.coverage_reports "
            " where scope_id = %s", (escopos.s1,))
        cobertura = await cur.fetchone()

    tipos = {t for t, _, _ in gravados}
    assert "risco.concentracao_emissor" in tipos      # 100% num emissor só
    assert "risco.exposicao_acima_do_fgc" in tipos    # 300.000 de CDB > 250.000
    assert all(atual for _, _, atual in gravados)
    assert observacoes == len(gravados), "cada achado precisa da observação da série temporal"
    assert cobertura == (400000.0, 1.0)


async def test_o_que_deixou_de_ser_verdade_e_fechado(db, escopos):
    """Fechar é tão importante quanto abrir: sem isto, um alerta resolvido ficaria na tela
    para sempre — e o cliente aprenderia a ignorar a lista inteira."""
    await _com_carteira(db, escopos)
    async with db.service_session() as conn:
        await executar(conn, escopos.s1)
        # A carteira do dia seguinte não tem mais o CDB estourado: metade do valor.
        cur = await conn.execute(
            "select account_id::text, instrument_id::text from wealth.v_latest_holdings "
            " where scope_id = %s order by value_brl desc limit 1", (escopos.s1,))
        conta, cdb = await cur.fetchone()
        await conn.execute(
            "insert into wealth.holdings_snapshots (scope_id, account_id, instrument_id, "
            "  as_of_date, value_brl, origin) values (%s, %s, %s, current_date + 1, 100000, 'manual')",
            (escopos.s1, conta, cdb))
        await executar(conn, escopos.s1, as_of=date.today())

        cur = await conn.execute(
            "select finding_type_code, is_current, resolution from diagnostics.findings "
            " where scope_id = %s and finding_type_code = 'risco.exposicao_acima_do_fgc'",
            (escopos.s1,))
        fgc = await cur.fetchone()
    assert fgc is not None
    assert fgc[1] is False and fgc[2] == "disappeared"


async def test_a_tool_nao_deixa_o_modelo_redigir_o_alerta(db, escopos):
    """A frase de cada ponto vem de dicionário, não do LLM. É a zona sem detector automático:
    "vender", "venda" e "melhor" isolados NÃO estão no vocabulário proibido."""
    await _com_carteira(db, escopos)
    async with db.service_session() as conn:
        await executar(conn, escopos.s1)
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        ctx = ToolContext(conn=conn, scope_id=escopos.s1, conversation_id=None)
        resolvido = await preparar_atencao(AtencaoParams(), ctx)
    saida = calcular_atencao(resolvido)

    assert saida.pontos, "a carteira tem achados: a tool precisa devolvê-los"
    for p in saida.pontos:
        assert p.leitura and not p.leitura.startswith(p.tipo)
        baixo = p.leitura.lower()
        for imperativo in ("você deveria", "recomend", "compre", "venda já", "melhor opção"):
            assert imperativo not in baixo, f"leitura instrui em vez de descrever: {p.leitura}"


async def test_sem_raio_x_a_tool_diz_que_falta_rodar(db, escopos):
    """Zero findings não é 'carteira sem problema': é diagnóstico que não existe."""
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        ctx = ToolContext(conn=conn, scope_id=escopos.s1, conversation_id=None)
        with pytest.raises(ToolInsumoFaltante) as erro:
            await preparar_atencao(AtencaoParams(), ctx)
    assert "não há diagnóstico" in str(erro.value)


def test_o_plano_esconde_o_diagnostico_mas_revela_quantos():
    """A regra da migration 06: mostra O QUE foi encontrado e QUANTO vale; esconde por que e
    como resolver. Sem blur."""
    dados = json.loads((GOLDEN / "planejamento_pontos_de_atencao.json").read_text(encoding="utf-8"))
    r = AtencaoResolvida.model_validate(dados["resolvido"])
    saida = calcular_atencao(r)
    assert saida.ocultos == 1
    assert saida.ocultos_familias == ["alocacao"]
    # Nenhum ponto oculto vaza título ou leitura.
    assert all(p.tipo != "alocacao.sem_exposicao_internacional" for p in saida.pontos)
    assert "ha_pontos_fora_do_plano" in saida.avisos


def test_atencao_golden():
    dados = json.loads((GOLDEN / "planejamento_pontos_de_atencao.json").read_text(encoding="utf-8"))
    saida = calcular_atencao(AtencaoResolvida.model_validate(dados["resolvido"]))
    assert saida.model_dump() == dados["esperado"]


def test_bloco_da_atencao_nao_promete_acao():
    from app.agents.blocos import blocos_de

    dados = json.loads((GOLDEN / "planejamento_pontos_de_atencao.json").read_text(encoding="utf-8"))
    blocos = blocos_de("planejamento.pontos_de_atencao", dados["esperado"], execution_id="exec-1")
    assert len(blocos) == 1 and blocos[0]["tipo"] == "atencao"
    assert blocos[0]["proveniencia"]["fonte"]
    assert "não o que fazer com o dinheiro" in blocos[0]["nota"]
    golden = json.loads((GOLDEN / "blocos_planejamento_pontos_de_atencao.json").read_text(encoding="utf-8"))
    assert blocos == golden["blocos"]


async def test_carteira_sem_achado_nenhum_fecha_tudo_sem_quebrar(db, escopos):
    """Caminho de lista VAZIA no fechamento — o que trava um motor em produção.

    Uma carteira diversificada, com exposição internacional e sem nada fora do lugar, produz
    zero achados. O `update ... where not (id = any(%s))` recebe então uma lista vazia, e a
    semântica tem de ser "fecha tudo o que estava aberto", não erro de tipo polimórfico.
    """
    async with db.service_session() as conn:
        conta = str(uuid.uuid4())
        await conn.execute(
            "insert into wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) "
            "values (%s, %s, 'corretora', 'Corretora limpa', 'Instituição', current_date - 10)",
            (conta, escopos.s1))
        # Quatro emissores distintos, quatro classes, tudo líquido, com internacional: nenhum
        # limiar é ultrapassado.
        for i, (codigo, classe) in enumerate((("F19LIMPA1", "acoes_br"), ("F19LIMPA2", "acoes_int"),
                                              ("F19LIMPA3", "ipca"), ("F19LIMPA4", "fii"),
                                              ("F19LIMPA5", "prefixado"), ("F19LIMPA6", "selic"))):
            emissor = str(uuid.uuid4())
            await conn.execute(
                "insert into market.issuers (id, name, kind) values (%s, %s, 'empresa')",
                (emissor, f"Emissor limpo {i}"))
            cur = await conn.execute(
                "insert into market.instruments (kind, name, ticker, asset_class_code, issuer_id, "
                "  liquidity_days) values ('acao', %s, %s, %s, %s, 2) returning id::text",
                (f"Papel limpo {i}", codigo, classe, emissor))
            iid = (await cur.fetchone())[0]
            await conn.execute(
                "insert into wealth.holdings_snapshots (scope_id, account_id, instrument_id, "
                "  as_of_date, value_brl, origin) values (%s, %s, %s, current_date, 100000, 'manual')",
                (escopos.s1, conta, iid))

        r = await executar(conn, escopos.s1)
        assert r["achados"] == [], f"carteira limpa não deveria ter achado: {r['achados']}"
        cur = await conn.execute(
            "select count(*) from diagnostics.findings where scope_id = %s and is_current",
            (escopos.s1,))
        assert (await cur.fetchone())[0] == 0


async def test_plano_em_trial_nao_leva_paywall(db, escopos):
    """Achado do /code-review: a tool lia `status = 'active'` à mão enquanto o helper
    canônico aceita `('trialing','active','past_due')` — e `trialing` é o DEFAULT da coluna.

    O efeito era um assinante em teste receber `plano='free'` aqui e o paywall esconder
    metade do diagnóstico, enquanto o MESMO cliente, no mesmo turno, era admitido como
    `advanced` pelo `turn.py`, que usa o helper. Duas respostas para a mesma pergunta.
    """
    await _com_carteira(db, escopos)
    async with db.service_session() as conn:
        await executar(conn, escopos.s1)
        await conn.execute(
            "insert into billing.subscriptions (scope_id, payer_user_id, plan_code, interval, "
            "  status, current_period_start, current_period_end) "
            "values (%s, %s, 'advanced', 'monthly', 'trialing', now(), now() + interval '30 days')",
            (escopos.s1, escopos.u1))

    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        ctx = ToolContext(conn=conn, scope_id=escopos.s1, conversation_id=None)
        saida = calcular_atencao(await preparar_atencao(AtencaoParams(), ctx))

    assert saida.plano == "advanced", "assinatura em trial é assinatura"
    assert saida.ocultos == 0, "nada pode ficar atrás do paywall para quem paga"


def test_caixa_da_conta_de_reserva_nao_e_contado_duas_vezes():
    """Achado do /code-review: `caixa_total` somava as posições de classe `caixa` ao saldo
    das contas de reserva, sem excluir a interseção.

    Não dispara nos seeds, porque eles põem a reserva numa conta e a carteira em outra. Numa
    importação real é o contrário: a conta de reserva É a que costuma ter caixa parado, e o
    mesmo dinheiro entraria como posição e como saldo. O número inflado vai para
    `impact_brl_year`, que alimenta `priority_score` — ou seja, o alerta errado subiria ao
    topo da lista do cliente.
    """
    reserva = [_pos(valor_brl=95000.0, classe="caixa", kind="conta", grupo="caixa",
                    conta_e_reserva=True)]
    fora = [_pos(valor_brl=18000.0, classe="caixa", kind="conta", grupo="caixa")]
    carteira = _carteira(reserva + fora + [_pos(valor_brl=400000.0)],
                         saldo=95000.0, requerida=69000.0)

    a = next(x for x in detectar(carteira, LIMIARES, REFERENCIAS)
             if x.tipo == "alocacao.caixa_parado_excessivo")
    # 95.000 (saldo) + 18.000 (caixa fora da reserva) = 113.000 — e NÃO 208.000.
    assert a.quantificacao["caixa_total_brl"] == 113000.0
    assert a.quantificacao["caixa_na_carteira_brl"] == 18000.0
    assert a.quantificacao["excedente_brl"] == 44000.0
    assert a.impacto_brl_ano == 44000.0


async def test_divida_sem_taxa_nao_sai_verde(db, escopos):
    """Achado do /code-review: `annual_rate` é nullable e o filtro era `annual_rate > limite`.

    `NULL > 0.06` é NULL, a linha era descartada, a soma dava zero e a Fundação saía VERDE —
    para um cliente com dívida aberta cuja taxa ninguém importou. E sem aviso, ao contrário
    do ramo do CDI ausente, que declara a limitação e usa piso conservador. O próprio
    docstring do arquivo diz por que isso é pior que um gate ausente: "parece funcionar".
    """
    from app.engine.fundacao import avaliar

    async with db.service_session() as conn:
        await conn.execute(
            "insert into budget.monthly_summaries (scope_id, month, income_brl, expense_brl, "
            "  essential_expense_brl) values (%s, date_trunc('month', current_date)::date, "
            "  12000, 8000, 6000)", (escopos.s1,))
        # Dívida ABERTA, valor conhecido, taxa desconhecida — o caso que saía verde.
        await conn.execute(
            "insert into budget.debts (scope_id, kind, description, outstanding_brl, annual_rate) "
            "values (%s, 'cartao_rotativo', 'Rotativo sem taxa importada', 40000, null)",
            (escopos.s1,))
        f = await avaliar(conn, escopos.s1)

    assert f.divida_luz == "amarelo", (
        f"dívida aberta sem taxa não pode sair {f.divida_luz}: não se sabe se é cara")
    assert f.luz_geral != "verde", "a Fundação não pode ficar verde por ignorância"
    assert any("sem taxa registrada" in a for a in f.avisos), (
        "a ignorância precisa ir DECLARADA, como o ramo do CDI ausente já faz")
    # A dívida NÃO é o que torna esta Fundação crítica — a reserva ausente é, e essa regra
    # já existia ("sem leitura de reserva é VERMELHO"). O que se afirma aqui é que taxa
    # desconhecida não vira acusação: amarelo, não vermelho.
    assert f.divida_luz != "vermelho", "não se sabe que a dívida é cara, tampouco"
    assert f.reserva_luz == "vermelho" and f.critica, (
        "a criticidade desta fixture vem da reserva ausente, não da dívida")


async def test_reserva_com_duas_contas_de_datas_diferentes(db, escopos):
    """Achado do /code-review: a derivação da reserva tomava um `max(as_of_date)` GLOBAL.

    Com duas contas de reserva cujo último snapshot é de dias diferentes, só a mais recente
    casa o filtro e a outra some do total. `app/engine/projecao.py:208` faz exatamente o
    mesmo trabalho com `group by account_id` — a assimetria é o defeito.

    O estrago não para no número: reserva subestimada faz `fundacao.avaliar` acender
    VERMELHO, `critica` vira True e a regra D11 DESATIVA todos os scores de família. Um
    cliente com reserva saudável recebe "Fundação crítica" e o diagnóstico inteiro apagado.
    """
    from app.context.derivacao import derivar_escopo

    async with db.service_session() as conn:
        contas = []
        for rotulo, saldo, dias in (("Conta corrente", 5000, 0), ("CDB liquidez", 25000, 60)):
            cid = str(uuid.uuid4())
            await conn.execute(
                "insert into wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) "
                "values (%s, %s, 'banco', %s, 'Instituição', current_date - 400)",
                (cid, escopos.s1, rotulo))
            await conn.execute(
                "insert into wealth.account_balances (account_id, scope_id, as_of_date, balance, "
                "  balance_brl, origin) values (%s, %s, current_date - %s, %s, %s, 'manual')",
                (cid, escopos.s1, dias, saldo, saldo))
            contas.append(cid)
        await conn.execute(
            "insert into budget.reserve_settings (scope_id, target_months, reserve_account_ids) "
            "values (%s, 6.0, %s::uuid[])", (escopos.s1, contas))
        await conn.execute(
            "insert into budget.monthly_summaries (scope_id, month, income_brl, expense_brl, "
            "  essential_expense_brl) values (%s, date_trunc('month', current_date)::date, "
            "  12000, 8000, 8000)", (escopos.s1,))

        await derivar_escopo(conn, escopos.s1, escopos.u1)
        cur = await conn.execute(
            "select numero::float from context.v_fact_operavel "
            " where scope_id = %s and fact_key = 'protecao.reserva_atual'", (escopos.s1,))
        linha = await cur.fetchone()

    assert linha is not None, "a reserva não foi derivada"
    assert linha[0] == 30000.0, (
        f"a reserva derivou {linha[0]}, não 30.000: o snapshot mais antigo foi descartado "
        f"por um max(as_of_date) global em vez de por conta")
