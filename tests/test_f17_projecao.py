"""F17 — a projeção contra o banco real: premissa, meta, gravação e auditoria.

O QUE SÓ ESTA CAMADA ALCANÇA
    `test_f17_simulacao.py` prova a matemática sem banco. Aqui se prova o resto, que é onde
    a F16 achou onze defeitos: de onde cada insumo vem, o que acontece quando um falta, e se
    o que ficou GRAVADO corresponde ao que foi calculado.

    Em particular, a pergunta que a F16 ensinou a fazer sempre — **quem escreve esta
    tabela?** `planning.goal_projections` existia desde a migration 07 e nunca teve produtor;
    o gate `C48e` (semente registrada) nasce junto com quem o alimenta, e o
    `test_projecao_grava_o_que_calculou` existe para que a relação continue viva.

    Tudo roda dentro da transação do teste e some no rollback.
"""
from __future__ import annotations

import pytest

from app.context.derivacao import derivar_escopo
from app.engine.projecao import carregar_premissas, projetar_escopo
from app.seeds.personas import POR_NOME, aplicar

pytestmark = pytest.mark.asyncio


async def test_premissas_vigentes_carregam_com_a_matriz_completa(db):
    """A matriz precisa fechar: 5 classes ⇒ 10 pares. Par ausente viraria zero, e zero
    subestima a volatilidade da carteira — o número que decide o cenário ruim."""
    async with db.service_session() as conn:
        set_id, premissas, status = await carregar_premissas(conn, "PLEXO_BASE")

    assert set_id and status in ("draft", "approved", "in_review")
    n = len(premissas.retornos)
    assert n >= 2
    assert len(premissas.correlacoes) == n * (n - 1) // 2, (
        "a matriz de correlação da PLEXO_BASE está aberta — o C48b só a exige na APROVAÇÃO, "
        "então um rascunho incompleto passaria pelo banco e quebraria aqui, que é onde a "
        "simulação de fato precisa dela")
    for classe, vol in premissas.volatilidades.items():
        assert 0 <= vol <= 1, f"{classe}: volatilidade {vol} fora de faixa — unidade errada?"
        assert -0.3 <= premissas.retornos[classe] <= 0.3


async def test_meta_curta_veta_risco_e_diz_por_que(db):
    """A demonstração do §5 do documento, com persona real: 24 meses, e o risco a mais
    trabalha contra o prazo. O veredito precisa CITAR o número que o decidiu."""
    a = POR_NOME["aposentado"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        resultados = await projetar_escopo(conn, ids["scope_id"])

    assert len(resultados) == 1
    r = resultados[0]
    assert not r.indisponivel, r.motivo_indisponivel
    assert r.meses <= 36, "a persona precisa continuar com meta curta para este teste valer"
    assert r.veredito.alocacao == "conservadora"
    assert not r.veredito.risco_liberado
    assert any(ch.isdigit() for ch in r.veredito.motivo), r.veredito.motivo


async def test_quem_nao_tem_sobra_recebe_diagnostico_do_orcamento_nao_do_objetivo(db):
    """A autônoma, e o que a mudança para a renda COMPROMETÍVEL revelou.

    `autonomo_volatil` tem renda média de R$ 13.500, mas o piso observado é R$ 4.200 e a
    despesa é R$ 8.900. Sobre a renda média sobrava dinheiro; sobre a renda com que ela pode
    CONTAR, não sobra nada — e é essa a conta que vale para um compromisso mensal (migration
    24). O indicador de rigidez já dizia isso desde a F16; a projeção passou a dizer também.

    Simular com aporte zero devolveria "0% de chance de chegar ao alvo", o que soa como um
    veredito sobre o objetivo quando é um veredito sobre o orçamento. A resposta honesta é
    nomear o que falta.
    """
    a = POR_NOME["autonomo_volatil"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        resultados = await projetar_escopo(conn, ids["scope_id"])

    r = resultados[0]
    assert r.indisponivel and r.motivo_indisponivel == "sem_sobra_para_aportar"
    assert r.distribuicoes is None, "sem aporte não se simula nada"


async def test_meta_folgada_nao_precisa_de_risco(db):
    """Quando o plano já fecha, risco a mais não compra probabilidade — só dispersão.

    O aporte é DECLARADO na meta, de propósito: este teste é sobre a regra de risco, e
    misturar a pergunta do orçamento com a da carteira faria duas variáveis mudarem juntas.
    """
    a = POR_NOME["autonomo_volatil"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        await conn.execute(
            "update planning.goals set monthly_contribution_brl = 6000 where scope_id = %s",
            (ids["scope_id"],))
        resultados = await projetar_escopo(conn, ids["scope_id"])

    r = resultados[0]
    assert not r.indisponivel, r.motivo_indisponivel
    assert r.origem_do_aporte == "declarado"
    conservadora = next(d for d in r.distribuicoes if d.alocacao == "conservadora")
    assert conservadora.prob_sucesso > 0.9, "a meta precisa estar folgada para o teste valer"
    assert not r.veredito.risco_liberado
    assert r.veredito.alocacao == "conservadora"


async def test_meta_longa_e_apertada_libera_risco_ate_onde_ele_se_sustenta(db):
    """E o caso simétrico: a mesma persona, o mesmo prazo, alvo que o conservador não
    alcança. Aqui o risco compra probabilidade e a regra o libera — até o degrau em que a
    piora do piso passa do que a política tolera.

    O alvo NÃO é um múltiplo arbitrário: a primeira versão deste teste triplicou o valor e
    descobriu que aí a meta fica inalcançável para as três carteiras — e risco também não
    compra probabilidade quando ninguém chega. A faixa em que a regra tem algo a dizer é
    estreita, e por isso o alvo sai da PRÓPRIA distribuição conservadora: o p95 dela, que é
    o teto do que ela alcança. Abaixo disso o conservador basta; acima, nada basta.
    """
    a = POR_NOME["autonomo_volatil"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        # Aporte DECLARADO: a persona autônoma não tem sobra sobre o piso da renda
        # (é o achado do teste irmão), e este teste é sobre outra coisa. Uma
        # variável por vez.
        await conn.execute(
            "update planning.goals set monthly_contribution_brl = 2500 where scope_id = %s",
            (ids["scope_id"],))
        primeira = (await projetar_escopo(conn, ids["scope_id"]))[0]
        teto_do_conservador = next(
            d for d in primeira.distribuicoes if d.alocacao == "conservadora").percentis[95]
        await conn.execute(
            "update planning.goals set target_amount_brl = %s where scope_id = %s",
            (round(teto_do_conservador, 2), ids["scope_id"]))
        resultados = await projetar_escopo(conn, ids["scope_id"])

    r = resultados[0]
    assert not r.indisponivel, r.motivo_indisponivel
    conservadora = next(d for d in r.distribuicoes if d.alocacao == "conservadora")
    assert conservadora.prob_sucesso < 0.15, "o alvo precisa apertar para o teste valer"
    assert r.veredito.risco_liberado, (
        f"com o conservador em {conservadora.prob_sucesso:.0%}, o risco precisa comprar "
        f"probabilidade; veredito: {r.veredito.motivo}")
    assert r.veredito.alocacao != "conservadora"
    assert any(ch.isdigit() for ch in r.veredito.motivo), r.veredito.motivo


async def test_a_ordem_de_risco_nao_vem_da_ordem_das_chaves_do_jsonb(db):
    """A regressão do defeito que ficou verde enquanto invertia a regra inteira.

    `jsonb` reordena chaves por tamanho e bytes: `{"conservadora","balanceada","arrojada"}`
    volta como `arrojada, balanceada, conservadora`. Quem lesse `list(payload)` tomaria a
    carteira mais arrojada como BASE da comparação. A ordem tem que sair da volatilidade.
    """
    from app.engine.projecao import _politica, carregar_premissas, ordem_de_risco
    from app.engine.simulacao import volatilidade_da_carteira

    async with db.service_session() as conn:
        _id, payload, _status = await _politica(conn)
        _set, premissas, _st = await carregar_premissas(
            conn, payload.get("conjunto_de_premissas", "PLEXO_BASE"))

    alocacoes = payload["alocacoes"]
    ordem = ordem_de_risco(alocacoes, premissas)
    assert ordem[0] == "conservadora" and ordem[-1] == "arrojada"
    vols = [volatilidade_da_carteira(alocacoes[n], premissas) for n in ordem]
    assert vols == sorted(vols)


async def test_projecao_grava_o_que_calculou(db):
    """A pergunta que a F16 ensinou: quem escreve esta tabela?

    Três alocações ⇒ três runs ⇒ três linhas, cada uma com sua semente no `params` do run
    (C48e) e sua proveniência de premissa. Uma delas, e só uma, é a eleita.
    """
    a = POR_NOME["autonomo_volatil"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        # Aporte DECLARADO: a persona autônoma não tem sobra sobre o piso da renda
        # (é o achado do teste irmão), e este teste é sobre outra coisa. Uma
        # variável por vez.
        await conn.execute(
            "update planning.goals set monthly_contribution_brl = 2500 where scope_id = %s",
            (ids["scope_id"],))
        resultados = await projetar_escopo(conn, ids["scope_id"])
        r = resultados[0]

        # Filtra pelos runs QUE ESTA EXECUÇÃO criou, não por `goal_id`. A primeira versão
        # contava todas as linhas da meta e passou até o dia em que um smoke de CLI deixou
        # projeções persistidas no banco de dev — aí eram 9, não 3. Teste que depende do que
        # sobrou de outra execução não prova nada; ele só ainda não falhou.
        cur = await conn.execute(
            """select p.alocacao_code, p.success_prob::float, p.p5_brl::float,
                      p.p50_brl::float, p.p95_brl::float, p.assumption_set_id is not null,
                      (p.assumptions ->> 'eleita')::boolean, r.params ? 'semente'
                 from planning.goal_projections p
                 join engine.runs r on r.id = p.run_id
                where p.run_id = any(%s) order by p.alocacao_code""",
            (list(r.run_ids.values()),))
        linhas = await cur.fetchall()

    assert len(linhas) == 3, "uma linha por alocação candidata"
    eleitas = [l for l in linhas if l[6]]
    assert len(eleitas) == 1 and eleitas[0][0] == r.veredito.alocacao

    for alocacao, prob, p5, p50, p95, tem_premissa, _eleita, tem_semente in linhas:
        assert tem_premissa, f"{alocacao}: projeção sem proveniência de premissa"
        assert tem_semente, f"{alocacao}: run sem semente — C48e deveria ter recusado"
        assert 0 <= prob <= 1
        assert p5 <= p50 <= p95

    calculado = {d.alocacao: d for d in r.distribuicoes}
    for alocacao, prob, p5, _p50, _p95, *_ in linhas:
        assert prob == pytest.approx(calculado[alocacao].prob_sucesso, abs=0.0001)
        assert p5 == pytest.approx(calculado[alocacao].cenario_ruim, abs=0.01)


async def test_mesma_semente_mesmo_input_hash(db):
    """Reprodutibilidade como a RCVM 19 pede: duas execuções com a mesma semente e os
    mesmos insumos produzem o MESMO `input_hash` e o mesmo `output_hash`."""
    a = POR_NOME["aposentado"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        r1 = (await projetar_escopo(conn, ids["scope_id"]))[0]
        r2 = (await projetar_escopo(conn, ids["scope_id"]))[0]

        cur = await conn.execute(
            "select id::text, input_hash, output_hash from engine.runs "
            "where id = any(%s)",
            (list(r1.run_ids.values()) + list(r2.run_ids.values()),))
        por_id = {i: (ih, oh) for i, ih, oh in await cur.fetchall()}

    for alocacao, run1 in r1.run_ids.items():
        run2 = r2.run_ids[alocacao]
        assert por_id[run1] == por_id[run2], (
            f"{alocacao}: duas execuções idênticas com hashes diferentes — a projeção "
            "deixou de ser refazível")


async def test_projeta_em_escopo_sem_nenhum_fato_derivado_antes(db):
    """A regressão do defeito que passou aqui e quebrou no CI.

    A projeção LÊ `renda.mensal_liquida` e `despesa.total_mensal`, que são fatos DERIVADOS —
    não vêm do seed da persona, que escreve nas tabelas de orçamento. Enquanto o banco de dev
    tinha esses dois persistidos de execuções anteriores de `perfil derivar`, chamar a
    projeção antes da derivação funcionava. Num banco limpo, não: a projeção saía
    `aporte_desconhecido` para TODA persona, e os testes que dependiam dela caíam em cascata.

    Este teste apaga da janela operável o que porventura já esteja derivado, e só então roda
    o pipeline na ordem certa. É o estado do CI reproduzido de propósito: se alguém inverter
    a ordem de novo, quebra aqui, e não só na máquina de outra pessoa.
    """
    a = POR_NOME["aposentado"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await conn.execute(
            "update context.assertions set status = 'obsoleto' "
            "where scope_id = %s and source = 'inferencia_motor'", (ids["scope_id"],))

        # sem derivar: é o que o CI encontrava, e a resposta honesta é dizer o que falta
        sem_derivar = await projetar_escopo(conn, ids["scope_id"])
        assert sem_derivar[0].indisponivel
        assert sem_derivar[0].motivo_indisponivel == "aporte_desconhecido"

        # com a derivação na frente, a projeção sai
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        resultados = await projetar_escopo(conn, ids["scope_id"])

    r = resultados[0]
    assert not r.indisponivel, (
        f"a projeção precisa sair depois da derivação; motivo: {r.motivo_indisponivel} "
        f"· falta: {r.faltando}")
    assert r.distribuicoes and r.veredito and r.run_ids
    assert r.meta.aporte_mensal > 0


async def test_sem_aporte_conhecido_a_projecao_diz_o_que_falta(db):
    """Ausência declarada, nunca zero imputado.

    Sem renda nem despesa e sem aporte na meta, não existe projeção — e a resposta certa é
    o nome do que falta, não uma probabilidade calculada sobre aporte zero, que diria ao
    cliente que ele não chega lá quando na verdade ninguém mediu.
    """
    a = POR_NOME["autonomo_volatil"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        # DE PROPÓSITO sem `derivar_escopo`: aqui se prova a ausência, não a presença.
        # apaga a janela operável de renda e despesa deste escopo
        await conn.execute(
            "update context.assertions set status = 'obsoleto' "
            "where scope_id = %s and fact_key in ('renda.mensal_liquida','despesa.total_mensal')",
            (ids["scope_id"],))
        await conn.execute(
            "update planning.goals set monthly_contribution_brl = null where scope_id = %s",
            (ids["scope_id"],))
        resultados = await projetar_escopo(conn, ids["scope_id"])

    r = resultados[0]
    assert r.indisponivel and r.motivo_indisponivel == "aporte_desconhecido"
    assert r.faltando, "a indisponibilidade precisa dizer QUAL fato falta"
    assert r.distribuicoes is None


async def test_projecao_nao_e_client_facing_sobre_premissa_em_rascunho(db):
    """O C48c visto do lado de quem escreve: enquanto a PLEXO_BASE for rascunho, nenhum run
    de projeção nasce client-facing. O gate do banco recusaria — o motor não chega lá."""
    a = POR_NOME["aposentado"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        r = (await projetar_escopo(conn, ids["scope_id"]))[0]

        cur = await conn.execute(
            "select bool_or(is_client_facing) from engine.runs where id = any(%s)",
            (list(r.run_ids.values()),))
        algum = (await cur.fetchone())[0]

        cur = await conn.execute(
            "select compliance_status::text from market.assumption_sets "
            "where code = 'PLEXO_BASE' and effective_to is null")
        status = (await cur.fetchone())[0]

    if status != "approved":
        assert not algum, (
            "premissa de mercado em rascunho não pode produzir número client-facing (C48c)")
