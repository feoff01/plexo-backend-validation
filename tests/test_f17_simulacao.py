"""F17 — o Monte Carlo de metas e a elegibilidade de risco, sem banco.

O QUE ESTA CAMADA PROTEGE
    O motor de simulação é o único do sistema cujo resultado ninguém consegue conferir de
    cabeça: "p5 = R$ 752.419" não tem plausibilidade óbvia, e um erro de compounding ou de
    unidade produz números que PARECEM certos. Então as asserções aqui são de dois tipos, e
    os dois importam:

      · propriedades que valem para qualquer entrada (diversificação nunca aumenta a
        volatilidade; percentil é monótono; probabilidade cai quando o alvo sobe);
      · âncoras FECHADAS — casos em que a resposta correta é conhecida analiticamente
        (volatilidade zero vira uma anuidade de fórmula, e a conta tem que bater na casa
        do centavo). É a âncora que pega erro de compounding, e propriedade nenhuma pegaria.

    Mais a inversão do aporte necessário, que é a asserção mais forte do arquivo: simular
    de novo COM o aporte que o motor disse ser suficiente para 90% tem que devolver ~90% de
    probabilidade. Ela liga as duas metades do motor e falha se qualquer uma se mover.
"""
from __future__ import annotations

import math

import pytest

from app.engine.elegibilidade import avaliar
from app.engine.simulacao import (
    Distribuicao,
    Meta,
    Premissas,
    parametros_lognormais,
    percentil,
    retorno_da_carteira,
    simular,
    volatilidade_da_carteira,
)

# Premissas de teste, próximas da PLEXO_BASE mas FIXAS aqui: um teste que muda de resultado
# quando compliance recalibra a premissa não prova o motor, prova a premissa.
PREMISSAS = Premissas(
    retornos={"caixa": 0.0050, "selic": 0.0450, "ipca": 0.0550,
              "acoes_br": 0.0700, "acoes_int": 0.0600},
    volatilidades={"caixa": 0.0050, "selic": 0.0100, "ipca": 0.0800,
                   "acoes_br": 0.2200, "acoes_int": 0.2000},
    correlacoes={("acoes_br", "acoes_int"): 0.550, ("acoes_br", "caixa"): -0.050,
                 ("acoes_br", "ipca"): 0.250, ("acoes_br", "selic"): -0.150,
                 ("acoes_int", "caixa"): -0.100, ("acoes_int", "ipca"): 0.100,
                 ("acoes_int", "selic"): -0.200, ("caixa", "ipca"): 0.100,
                 ("caixa", "selic"): 0.900, ("ipca", "selic"): 0.200})

CONSERVADORA = {"caixa": 0.10, "selic": 0.70, "ipca": 0.20}
BALANCEADA = {"caixa": 0.05, "selic": 0.45, "ipca": 0.30, "acoes_br": 0.12, "acoes_int": 0.08}
ARROJADA = {"caixa": 0.05, "selic": 0.20, "ipca": 0.25, "acoes_br": 0.30, "acoes_int": 0.20}


# ---------------------------------------------------------------- a matemática da carteira
def test_diversificacao_nunca_aumenta_a_volatilidade():
    """σ_p ≤ Σ wᵢσᵢ, com igualdade só se tudo for perfeitamente correlacionado.

    É a única coisa que a matriz de correlação faz pelo resultado. Se esta desigualdade
    quebrar, a covariância está sendo somada errada e toda a cauda da simulação mente.
    """
    for pesos in (CONSERVADORA, BALANCEADA, ARROJADA):
        media_ponderada = sum(w * PREMISSAS.volatilidades[c] for c, w in pesos.items())
        assert volatilidade_da_carteira(pesos, PREMISSAS) < media_ponderada


def test_correlacao_ausente_levanta_em_vez_de_virar_zero():
    """A lição da F16 aplicada a outro insumo: ausência silenciosa é o defeito caro.

    Um par faltando lido como zero subestimaria a volatilidade — e o número que sofre é
    justamente o p5, que é o que a regra de elegibilidade usa para vetar risco.
    """
    incompleta = Premissas(retornos={"a": 0.05, "b": 0.07},
                           volatilidades={"a": 0.02, "b": 0.20}, correlacoes={})
    with pytest.raises(ValueError, match="correlação ausente"):
        volatilidade_da_carteira({"a": 0.5, "b": 0.5}, incompleta)


def test_correlacao_e_simetrica_e_a_diagonal_e_um():
    assert PREMISSAS.correlacao("selic", "acoes_br") == PREMISSAS.correlacao("acoes_br", "selic")
    assert PREMISSAS.correlacao("selic", "selic") == 1.0


@pytest.mark.parametrize("pesos", [{"caixa": 0.9}, {"caixa": 0.5, "selic": 0.6}, {}])
def test_alocacao_que_nao_soma_um_e_recusada(pesos):
    with pytest.raises(ValueError):
        retorno_da_carteira(pesos, PREMISSAS)


def test_lognormal_preserva_a_media_aritmetica():
    """E[exp(X)] = 1 + μ. Sem o casamento de momentos, usar μ como média do LOG embutiria
    um viés otimista que cresce com a volatilidade — favorecendo a carteira arrojada por
    erro de conta em vez de por mérito."""
    for mu, sigma in ((0.045, 0.019), (0.07, 0.22), (0.0, 0.15)):
        m, s = parametros_lognormais(mu, sigma)
        assert math.exp(m + s * s / 2) == pytest.approx(1 + mu, rel=1e-12)


def test_percentil_e_monotono():
    ordenados = [float(v) for v in range(100)]
    valores = [percentil(ordenados, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
    assert valores == sorted(valores)


# ---------------------------------------------------------------- as âncoras fechadas
def test_volatilidade_zero_bate_com_a_anuidade_fechada():
    """A âncora que pega erro de compounding, e que propriedade nenhuma pegaria.

    Sem volatilidade, o Monte Carlo tem que devolver EXATAMENTE a anuidade ordinária:
    saldo·(1+i)ⁿ + aporte·((1+i)ⁿ−1)/i, com i mensal derivado do anual. Um erro de meio
    mês no timing do aporte, ou raiz de 12 no lugar de divisão por 12, aparece aqui e em
    lugar nenhum mais.
    """
    determinista = Premissas(retornos={"unica": 0.06}, volatilidades={"unica": 0.0})
    meses = 120
    meta = Meta(valor_alvo=1.0, meses=meses, aporte_mensal=1000.0, saldo_inicial=10000.0)
    d = simular({"unica": 1.0}, determinista, meta, caminhos=5, semente=1)

    i = (1 + 0.06) ** (1 / 12) - 1
    esperado = 10000.0 * (1 + i) ** meses + 1000.0 * ((1 + i) ** meses - 1) / i
    assert d.mediana == pytest.approx(esperado, rel=1e-9)
    assert d.percentis[5] == pytest.approx(d.percentis[95], rel=1e-9)


def test_sem_volatilidade_e_com_retorno_positivo_nao_ha_arrependimento():
    determinista = Premissas(retornos={"unica": 0.05}, volatilidades={"unica": 0.0})
    d = simular({"unica": 1.0}, determinista,
                Meta(valor_alvo=1.0, meses=36, aporte_mensal=500.0), caminhos=5, semente=1)
    assert d.prob_abaixo_do_depositado == 0.0
    assert d.prob_sucesso == 1.0


# ---------------------------------------------------------------- a simulação
def test_mesma_semente_mesmo_resultado():
    """Reprodutibilidade não é boa prática aqui, é exigência de auditoria (RCVM 19)."""
    meta = Meta(valor_alvo=100000, meses=60, aporte_mensal=1200, saldo_inicial=8000)
    a = simular(BALANCEADA, PREMISSAS, meta, caminhos=800, semente=20260823)
    b = simular(BALANCEADA, PREMISSAS, meta, caminhos=800, semente=20260823)
    assert a.percentis == b.percentis
    assert a.prob_sucesso == b.prob_sucesso

    outra = simular(BALANCEADA, PREMISSAS, meta, caminhos=800, semente=999)
    assert outra.percentis != a.percentis
    # ...mas perto: se duas sementes divergissem muito, o número de caminhos seria baixo
    # demais para o resultado significar alguma coisa.
    assert outra.mediana == pytest.approx(a.mediana, rel=0.03)


def test_percentis_saem_ordenados():
    d = simular(ARROJADA, PREMISSAS,
                Meta(valor_alvo=200000, meses=120, aporte_mensal=1000), caminhos=1500, semente=7)
    ordem = [d.percentis[q] for q in (5, 10, 25, 50, 75, 90, 95)]
    assert ordem == sorted(ordem)


def test_alvo_maior_nunca_aumenta_a_probabilidade():
    meta_base = Meta(valor_alvo=80000, meses=48, aporte_mensal=1500)
    anterior = 1.1
    for alvo in (60000, 80000, 100000, 140000):
        d = simular(BALANCEADA, PREMISSAS,
                    Meta(alvo, meta_base.meses, meta_base.aporte_mensal), caminhos=1200, semente=3)
        assert d.prob_sucesso <= anterior
        anterior = d.prob_sucesso


def test_aporte_necessario_inverte_a_simulacao():
    """A asserção mais forte do arquivo: simular COM o aporte que o motor disse ser
    suficiente para 90% tem que devolver ~90% de probabilidade.

    Ela liga as duas metades do motor — a decomposição `A + aporte·B` e a contagem de
    sucessos — e falha se qualquer uma se mover. O erro amostral com 3.000 caminhos é da
    ordem de 1 ponto, daí a folga.
    """
    meta = Meta(valor_alvo=150000, meses=72, aporte_mensal=1500, saldo_inicial=20000)
    d = simular(BALANCEADA, PREMISSAS, meta, caminhos=3000, semente=11,
                confianca_do_aporte=0.90)
    assert d.aporte_necessario is not None

    refeita = simular(BALANCEADA, PREMISSAS,
                      Meta(meta.valor_alvo, meta.meses, d.aporte_necessario, meta.saldo_inicial),
                      caminhos=3000, semente=11)
    assert refeita.prob_sucesso == pytest.approx(0.90, abs=0.02)


def test_prazo_curto_o_risco_encolhe_o_piso():
    """O achado que contraria a intuição, e a razão de a regra do §4 existir.

    Em 24 meses, mais risco baixa o p5 e NÃO sobe a probabilidade — a volatilidade cresce
    com √t e o prêmio com t, então a dispersão vence. Se esta asserção parar de valer, ou
    as premissas mudaram muito, ou o motor parou de compor o risco no prazo.
    """
    meta = Meta(valor_alvo=60000, meses=24, aporte_mensal=2200, saldo_inicial=5000)
    cons = simular(CONSERVADORA, PREMISSAS, meta, caminhos=2000, semente=5, alocacao="conservadora")
    arr = simular(ARROJADA, PREMISSAS, meta, caminhos=2000, semente=5, alocacao="arrojada")
    assert arr.cenario_ruim < cons.cenario_ruim
    assert arr.prob_sucesso <= cons.prob_sucesso


def test_prazo_longo_o_risco_compra_probabilidade():
    """E o outro lado: em 240 meses a mesma carteira arrojada sobe muito a probabilidade.
    É por isso que vetar risco sempre — o que a política fazia com tolerância zero do p5 —
    não protege ninguém."""
    meta = Meta(valor_alvo=1200000, meses=240, aporte_mensal=2500, saldo_inicial=50000)
    cons = simular(CONSERVADORA, PREMISSAS, meta, caminhos=1200, semente=5, alocacao="conservadora")
    bal = simular(BALANCEADA, PREMISSAS, meta, caminhos=1200, semente=5, alocacao="balanceada")
    assert bal.prob_sucesso - cons.prob_sucesso > 0.10


# ---------------------------------------------------------------- elegibilidade de risco
def _dist(nome: str, p5: float, prob: float) -> Distribuicao:
    """Distribuição sintética: aqui se testa a REGRA, não a simulação."""
    return Distribuicao(alocacao=nome,
                        percentis={5: p5, 10: p5, 25: p5, 50: p5, 75: p5, 90: p5, 95: p5},
                        prob_sucesso=prob, prob_abaixo_do_depositado=0.0,
                        aporte_necessario=None, total_depositado=0.0,
                        retorno_aa=0.05, volatilidade_aa=0.1, caminhos=10, semente=1)


ORDEM = ["conservadora", "balanceada", "arrojada"]


def test_risco_que_nao_compra_probabilidade_e_recusado():
    v = avaliar([_dist("conservadora", 100.0, 0.70),
                 _dist("balanceada", 98.0, 0.72),
                 _dist("arrojada", 90.0, 0.74)],
                ordem=ORDEM, limiar_materialidade_prob=0.10, piora_maxima_do_p5=0.10, meses=24)
    assert v.alocacao == "conservadora"
    assert not v.risco_liberado
    assert "2 pontos" in v.motivo


def test_piora_grande_do_piso_veta_mesmo_com_ganho_material():
    """A condição que não pode faltar: 20 pontos de probabilidade não compram um piso 30%
    menor. Sem esta regra, a busca pelo maior número escolheria sempre a mais arrojada."""
    v = avaliar([_dist("conservadora", 100.0, 0.50),
                 _dist("balanceada", 70.0, 0.70),
                 _dist("arrojada", 60.0, 0.80)],
                ordem=ORDEM, limiar_materialidade_prob=0.10, piora_maxima_do_p5=0.10, meses=240)
    assert v.alocacao == "conservadora"
    assert "30%" in v.motivo


def test_a_caminhada_para_no_primeiro_degrau_reprovado():
    """A arrojada nem é considerada depois de a balanceada reprovar: o degrau reprovado é a
    resposta, e saltá-lo transformaria a regra em busca pelo maior número."""
    v = avaliar([_dist("conservadora", 100.0, 0.50),
                 _dist("balanceada", 60.0, 0.55),
                 _dist("arrojada", 99.0, 0.95)],
                ordem=ORDEM, limiar_materialidade_prob=0.10, piora_maxima_do_p5=0.10, meses=120)
    assert v.alocacao == "conservadora"
    assert [c.alocacao for c in v.comparacoes] == ["balanceada"]


def test_risco_elegivel_avanca_ate_onde_se_sustenta():
    v = avaliar([_dist("conservadora", 100.0, 0.30),
                 _dist("balanceada", 95.0, 0.60),
                 _dist("arrojada", 80.0, 0.75)],
                ordem=ORDEM, limiar_materialidade_prob=0.10, piora_maxima_do_p5=0.10, meses=240)
    assert v.alocacao == "balanceada"
    assert v.risco_liberado


def test_o_veredito_sempre_cita_um_numero():
    """"Risco vetado" sem número é arbitrário, e arbitrário é o que o cliente não consegue
    contestar. Toda recusa carrega o valor que a produziu."""
    for cenario in ([_dist("conservadora", 100.0, 0.70), _dist("balanceada", 98.0, 0.71),
                     _dist("arrojada", 90.0, 0.72)],
                    [_dist("conservadora", 100.0, 0.30), _dist("balanceada", 60.0, 0.80),
                     _dist("arrojada", 50.0, 0.90)]):
        v = avaliar(cenario, ordem=ORDEM, limiar_materialidade_prob=0.10,
                    piora_maxima_do_p5=0.10, meses=60)
        assert any(ch.isdigit() for ch in v.motivo), v.motivo


PROIBIDO = ("recomend", "melhor", "compre", "venda", "oportunidade", "garantido")


def test_o_veredito_nao_usa_vocabulario_de_recomendacao():
    """RCVM 19: o texto é diagnóstico de uma simulação, nunca conselho."""
    cenarios = [
        [_dist("conservadora", 100.0, 0.70), _dist("balanceada", 98.0, 0.71),
         _dist("arrojada", 90.0, 0.72)],
        [_dist("conservadora", 100.0, 0.30), _dist("balanceada", 95.0, 0.60),
         _dist("arrojada", 80.0, 0.75)],
        [_dist("conservadora", 100.0, 0.50), _dist("balanceada", 60.0, 0.90),
         _dist("arrojada", 55.0, 0.95)],
    ]
    for cenario in cenarios:
        v = avaliar(cenario, ordem=ORDEM, limiar_materialidade_prob=0.10,
                    piora_maxima_do_p5=0.10, meses=120)
        baixo = v.motivo.lower()
        for termo in PROIBIDO:
            assert termo not in baixo, f"'{termo}' no veredito: {v.motivo}"


def test_alocacao_sem_simulacao_e_erro_e_nao_omissao():
    with pytest.raises(ValueError, match="alocação sem simulação"):
        avaliar([_dist("conservadora", 100.0, 0.5)], ordem=ORDEM,
                limiar_materialidade_prob=0.10, piora_maxima_do_p5=0.10, meses=60)

# ---------------------------------------------------------------- divisão do aporte (F18)
def test_um_objetivo_recebe_a_sobra_inteira():
    from app.engine.projecao import repartir_aporte

    r = repartir_aporte([("g1", 1, None)], 9200.0)
    assert r["g1"]["aporte"] == 9200.0
    assert r["g1"]["origem"] == "unico_objetivo"


def test_dois_objetivos_nao_recebem_o_mesmo_dinheiro_duas_vezes():
    """O defeito que a conversa real expôs.

    Uma cliente com R$ 9.200 por mês e dois objetivos via a faculdade (alvo de R$ 600 mil)
    com mediana de R$ 1,96 milhão, porque a projeção dava a ela TODO o dinheiro — e dava o
    mesmo dinheiro à aposentadoria. As duas probabilidades eram verdadeiras isoladamente e
    impossíveis juntas.
    """
    from app.engine.projecao import repartir_aporte

    r = repartir_aporte([("faculdade", 1, None), ("aposentadoria", 2, None)], 9200.0)
    total = r["faculdade"]["aporte"] + r["aposentadoria"]["aporte"]
    assert total == pytest.approx(9200.0, abs=0.02), (
        f"a soma dos aportes ({total}) não pode passar do que a cliente tem")
    # peso 1/prioridade: a de prioridade 1 recebe o dobro da de prioridade 2
    assert r["faculdade"]["aporte"] == pytest.approx(r["aposentadoria"]["aporte"] * 2, rel=0.01)
    assert all(v["origem"] == "rateio_por_prioridade" for v in r.values())


def test_aporte_declarado_manda_e_o_resto_e_repartido():
    """O cliente sabe da vida dele: se declarou quanto vai para um objetivo, é isso."""
    from app.engine.projecao import repartir_aporte

    r = repartir_aporte([("casa", 1, 5000.0), ("carro", 2, None), ("viagem", 3, None)], 9200.0)
    assert r["casa"] == {"aporte": 5000.0, "origem": "declarado", "fatia": None}
    restante = r["carro"]["aporte"] + r["viagem"]["aporte"]
    assert restante == pytest.approx(4200.0, abs=0.02)
    assert r["carro"]["aporte"] > r["viagem"]["aporte"]


def test_declarado_alem_da_sobra_nao_vira_aporte_negativo():
    from app.engine.projecao import repartir_aporte

    r = repartir_aporte([("casa", 1, 12000.0), ("carro", 2, None)], 9200.0)
    assert r["carro"]["aporte"] == 0.0, "sem dinheiro sobrando, o aporte é zero — nunca negativo"


def test_sem_sobra_conhecida_nao_se_inventa_divisao():
    from app.engine.projecao import repartir_aporte

    r = repartir_aporte([("g1", 1, None), ("g2", 2, None)], None)
    assert all(v["aporte"] is None for v in r.values()), (
        "sem saber quanto sobra, a resposta é 'não sei' — não um rateio de um número inventado")
