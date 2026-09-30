"""F16 — propriedades que valem para QUALQUER cliente e QUALQUER indicador.

POR QUE ESTE ARQUIVO EXISTE
    A F15 fechou com cinco correções e nenhuma delas veio de ler código. Todas apareceram
    rodando o motor com números reais, e três passariam em qualquer teste derivado da
    especificação — porque o defeito ERA a especificação:

      · a lacuna de seguro afirmava R$ 1,8 mi para quem não se sabia se tinha apólice
        (um insumo estava marcado como opcional e a fórmula lia ausência como zero);
      · o "elo mais fraco" comparava um conjunto de um;
      · o gate de compliance valia na escrita e vazava na leitura.

    Teste de exemplo ("taxa_poupanca == 0,32") não pega nada disso: ele confere o número que
    o autor esperava contra o número que o autor escreveu. O que pega é PROPRIEDADE — uma
    afirmação que precisa valer para todo indicador, inclusive os que ainda não existem.

O QUE FAZ ESTA REDE ESCALAR
    A parametrização vem do CATÁLOGO NO BANCO, não de uma lista à mão. Indicador acrescentado
    amanhã nasce coberto por todas as propriedades sem ninguém escrever caso novo — e é isso
    que separa uma rede de uma coleção de testes.

AS QUATRO FAMÍLIAS
    monotonicidade   piorar a situação do cliente nunca melhora o score
    completude       nenhum número sai com insumo requerido ausente
    honestidade      insumo "opcional" que muda o resultado não é opcional
    plausibilidade   o que o score promete sobre si mesmo (cobertura, motivo, elo)
"""
from __future__ import annotations

import pathlib
import re
import sys
import urllib.parse

import psycopg
import pytest
from dotenv import dotenv_values

from app.engine import indicadores as formulas
from app.engine.scores import compor, interpolar

ROOT = pathlib.Path(__file__).resolve().parent.parent


# =============================================================================
# O catálogo real, lido do banco na COLETA — é o que permite parametrizar por
# indicador e ver uma linha de resultado por indicador em vez de um teste opaco.
# =============================================================================
def _conninfo() -> str:
    url = (dotenv_values(ROOT / ".env").get("DATABASE_URL") or "")
    if not url:
        pytest.skip("DATABASE_URL ausente")
    url = re.sub(r"^postgres(ql)?\+[a-z0-9]+://", "postgresql://", url)
    partes = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(partes.query))
    q.setdefault("sslmode", "require")
    return urllib.parse.urlunsplit(partes._replace(query=urllib.parse.urlencode(q)))


def _catalogo() -> tuple[list[dict], dict]:
    """(definições de indicador, payload de CLIENT_SCORES). Uma conexão, na coleta."""
    with psycopg.connect(_conninfo()) as conn:
        cur = conn.execute(
            "select code, formula_ref, higher_is_better, required_fact_keys::text[], "
            "       optional_fact_keys::text[], unit "
            "from diagnostics.indicator_definitions where is_active order by code")
        chaves = ("code", "formula_ref", "higher_is_better", "requeridos", "opcionais", "unit")
        indicadores = [dict(zip(chaves, r)) for r in cur.fetchall()]
        cur = conn.execute(
            "select payload from engine.policy_versions "
            "where code = 'CLIENT_SCORES' and effective_to is null")
        linha = cur.fetchone()
    return indicadores, (linha[0] if linha else {})


try:
    INDICADORES, POLITICA = _catalogo()
except Exception as exc:                              # noqa: BLE001 — sem banco, sem rede
    print(f"[f16] catálogo indisponível: {exc}", file=sys.stderr)
    INDICADORES, POLITICA = [], {}

NORMALIZACAO = POLITICA.get("normalizacao") or {}
PREMISSAS = POLITICA.get("premissas_indicadores") or {}
CODIGOS = [i["code"] for i in INDICADORES]
POR_CODIGO = {i["code"]: i for i in INDICADORES}

pytestmark = pytest.mark.skipif(not INDICADORES, reason="catálogo de indicadores vazio")


# =============================================================================
# O cliente de referência e a direção do PIOR
#
# Cada linha abaixo é uma afirmação que não depende de implementação nenhuma:
# "mais dívida é pior", "mais renda é melhor". São as únicas declarações deste
# arquivo, e foram escolhidas por serem óbvias — uma especificação que mente
# aqui mentiria em qualquer lugar.
# =============================================================================
REFERENCIA: dict[str, float] = {
    "renda.mensal_liquida": 10000.0,
    "renda.mensal_bruta": 12000.0,
    "renda.comprometivel": 8000.0,       # fixo + piso p10: abaixo da líquida, como manda a 24
    "renda.fontes_ativas": 2.0,
    "despesa.total_mensal": 6800.0,
    "despesa.essencial_mensal": 5000.0,
    "despesa.fixa_contratada": 3000.0,
    "fluxo.aporte_mensal": 2000.0,
    # [F17] Derivado pela projeção (`objetivo.probabilidade_sucesso`): 0,72 = plano que
    # fecha na maioria dos cenários mas ainda não nos 0,90 em que a curva satura.
    "objetivo.probabilidade_sucesso": 0.72,
    "protecao.reserva_atual": 21000.0,
    "protecao.cobertura_vida": 300000.0,
    "protecao.dependentes_financeiros": 2.0,
    "patrimonio.liquido": 400000.0,
    "patrimonio.investido": 250000.0,
    "patrimonio.imobilizado": 150000.0,
    "divida.saldo_total": 30000.0,
    "divida.custo_medio": 0.12,
    "divida.parcela_mensal": 900.0,
    "objetivo.valor_alvo": 500000.0,
    "objetivo.prazo_meses": 120.0,
    "objetivo.prioridade": 1.0,
    "destino.idade_aposentadoria": 60.0,
    "vida.data_nascimento": 40.0,              # o motor entrega IDADE, não data
    "comportamento.aporte_regular": 1.0,
    "comportamento.reacao_queda": 1.0,
}

# +1 = aumentar este fato PIORA a situação do cliente · −1 = melhora
PIORA_QUANDO_SOBE: dict[str, int] = {
    # probabilidade maior é sempre melhor: o pior é ela CAIR
    "objetivo.probabilidade_sucesso": False,
    "renda.mensal_liquida": -1,
    "renda.mensal_bruta": -1,
    "renda.comprometivel": -1,
    "renda.fontes_ativas": -1,
    "despesa.total_mensal": +1,
    "despesa.essencial_mensal": +1,
    "despesa.fixa_contratada": +1,
    "fluxo.aporte_mensal": -1,
    "protecao.reserva_atual": -1,
    "protecao.cobertura_vida": -1,
    "protecao.dependentes_financeiros": +1,
    "patrimonio.liquido": -1,
    "patrimonio.investido": -1,
    "patrimonio.imobilizado": -1,
    "divida.saldo_total": +1,
    "divida.custo_medio": +1,
    "divida.parcela_mensal": +1,
    "objetivo.valor_alvo": +1,      # objetivo maior é mais difícil
    "objetivo.prazo_meses": -1,     # mais tempo é mais fácil
    "destino.idade_aposentadoria": -1,   # parar mais tarde dá mais horizonte
    "vida.data_nascimento": +1,          # mais velho, menos horizonte
    "comportamento.aporte_regular": -1,
    "comportamento.reacao_queda": -1,
}

PASSO = 0.15          # perturbação relativa; grossa de propósito — o que se testa é DIREÇÃO
TOLERANCIA = 1e-9


def _normalizar(code: str, valor: float) -> float | None:
    curva = NORMALIZACAO.get(code) or {}
    pontos = curva.get("pontos") or []
    if not pontos:
        return None
    return interpolar(pontos, valor, clamp=bool(curva.get("clamp", True)))


def _calcular(ind: dict, fatos: dict[str, float]) -> float | None:
    return formulas.calcular(ind["formula_ref"], fatos, PREMISSAS)


def _base(ind: dict) -> dict[str, float]:
    chaves = list(ind["requeridos"]) + list(ind["opcionais"] or [])
    return {k: REFERENCIA[k] for k in chaves if k in REFERENCIA}


# =============================================================================
# Reconciliação — o catálogo e o código não podem divergir em silêncio
# =============================================================================
def test_todo_indicador_ativo_tem_formula_e_curva():
    """Indicador sem fórmula grava `motor_ausente` — o que é honesto, mas se for por
    esquecimento ninguém descobre. Indicador sem curva sai da conta do score sem aviso."""
    sem_formula = [i["code"] for i in INDICADORES if not formulas.formula_existe(i["formula_ref"])]
    sem_curva = [i["code"] for i in INDICADORES if i["code"] not in NORMALIZACAO]
    assert sem_formula == [], f"indicador ativo sem fórmula em app/engine/indicadores.py: {sem_formula}"
    assert sem_curva == [], f"indicador ativo sem curva em CLIENT_SCORES.normalizacao: {sem_curva}"


def test_todo_insumo_do_catalogo_tem_valor_de_referencia():
    """Guarda de manutenção: fato novo no catálogo sem valor aqui deixaria as propriedades
    abaixo pulando o indicador em silêncio — a rede furaria sem ninguém notar."""
    usados = {k for i in INDICADORES for k in list(i["requeridos"]) + list(i["opcionais"] or [])}
    faltando = sorted(usados - set(REFERENCIA))
    assert faltando == [], f"acrescente ao REFERENCIA e ao PIORA_QUANDO_SOBE: {faltando}"
    sem_direcao = sorted(usados - set(PIORA_QUANDO_SOBE))
    assert sem_direcao == [], f"falta declarar a direção do pior: {sem_direcao}"


# =============================================================================
# Monotonicidade — a propriedade que pega erro de sinal e curva invertida
# =============================================================================
@pytest.mark.parametrize("code", CODIGOS)
def test_curva_e_monotonica_na_direcao_declarada(code):
    """A curva sozinha, sem fórmula: se `higher_is_better`, valor maior nunca vale menos.

    Curva com ponto fora de ordem ou invertida por engano faz o cliente ser premiado por
    piorar — e isso não aparece em nenhum caso de exemplo, porque o exemplo usa um ponto só.
    """
    curva = NORMALIZACAO.get(code) or {}
    pontos = sorted(([float(x), float(y)] for x, y in curva.get("pontos", [])), key=lambda p: p[0])
    if len(pontos) < 2:
        pytest.skip(f"{code} sem curva com dois pontos")

    ys = [y for _, y in pontos]
    if POR_CODIGO[code]["higher_is_better"]:
        assert all(b >= a - TOLERANCIA for a, b in zip(ys, ys[1:])), (
            f"{code} declara higher_is_better mas a curva desce: {pontos}")
    else:
        assert all(b <= a + TOLERANCIA for a, b in zip(ys, ys[1:])), (
            f"{code} declara que MENOS é melhor mas a curva sobe: {pontos}")


@pytest.mark.parametrize("code", CODIGOS)
def test_piorar_a_situacao_nunca_melhora_o_score(code):
    """A propriedade de ponta a ponta: fato piora ⇒ score normalizado não sobe.

    Cobre fórmula E curva juntas, que é onde o erro de sinal se esconde: uma fórmula
    invertida com uma curva também invertida passaria nos dois testes isolados.
    """
    ind = POR_CODIGO[code]
    base = _base(ind)
    valor_base = _calcular(ind, base)
    if valor_base is None:
        pytest.skip(f"{code} não calcula com o cliente de referência")
    score_base = _normalizar(code, valor_base)
    if score_base is None:
        pytest.skip(f"{code} sem curva")

    testou_alguma = False
    for chave in ind["requeridos"]:
        direcao = PIORA_QUANDO_SOBE.get(chave)
        if direcao is None or chave not in base:
            continue
        piorado = dict(base)
        # move o fato NA DIREÇÃO QUE PIORA a vida do cliente
        piorado[chave] = base[chave] * (1 + PASSO * direcao) or base[chave] + direcao
        valor = _calcular(ind, piorado)
        if valor is None:
            continue
        score = _normalizar(code, valor)
        testou_alguma = True
        assert score <= score_base + TOLERANCIA, (
            f"{code}: piorar `{chave}` de {base[chave]:g} para {piorado[chave]:g} "
            f"MELHOROU o score ({score_base:.4f} → {score:.4f}). "
            "Ou a fórmula tem sinal trocado, ou a curva está invertida.")

    if not testou_alguma:
        pytest.skip(f"{code}: nenhum insumo com direção testável")


# =============================================================================
# Completude e honestidade — as duas que pegam a lacuna de seguro
# =============================================================================
@pytest.mark.parametrize("code", CODIGOS)
def test_sem_insumo_requerido_a_formula_nao_devolve_numero(code):
    """Insumo requerido ausente tem que virar ausência, nunca um número calculado com
    um default silencioso. É a regra que atravessa a camada inteira: não medido ≠ zero."""
    ind = POR_CODIGO[code]
    base = _base(ind)
    if _calcular(ind, base) is None:
        pytest.skip(f"{code} não calcula com o cliente de referência")

    for chave in ind["requeridos"]:
        sem = {k: v for k, v in base.items() if k != chave}
        assert _calcular(ind, sem) is None, (
            f"{code} devolveu número sem `{chave}`, que é insumo REQUERIDO. "
            "Provavelmente há um `or 0` ou `.get(k, 0)` tratando ausência como valor.")


@pytest.mark.parametrize("code", CODIGOS)
def test_insumo_opcional_que_muda_o_resultado_nao_e_opcional(code):
    """A propriedade que teria pego a lacuna de seguro.

    `protecao.lacuna_seguro_vida` publicou R$ 1.805.500 para uma cliente de quem o sistema
    NÃO SABIA se tinha apólice: a cobertura estava como insumo opcional e a fórmula lia
    ausência como zero. Se remover um opcional muda o resultado, ele não é opcional — é
    requerido, e sem ele o indicador tem que ficar indisponível.
    """
    ind = POR_CODIGO[code]
    base = _base(ind)
    com = _calcular(ind, base)
    if com is None:
        pytest.skip(f"{code} não calcula com o cliente de referência")

    for chave in (ind["opcionais"] or []):
        if chave not in base:
            continue
        sem = {k: v for k, v in base.items() if k != chave}
        valor = _calcular(ind, sem)
        assert valor is not None and abs(valor - com) <= TOLERANCIA, (
            f"{code}: remover o insumo OPCIONAL `{chave}` mudou o resultado "
            f"({com} → {valor}). Insumo que muda o número não é opcional: ou ele entra em "
            "required_fact_keys, ou a fórmula para de assumir um valor para a ausência dele.")


def test_formula_so_le_fatos_declarados():
    """Fórmula que lê um fato fora de `required ∪ optional` produz um número que depende de
    algo que a cobertura não conta — e a cobertura é o que autoriza o score a sair."""

    class Espia(dict):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.lidas: set[str] = set()

        def get(self, chave, default=None):          # noqa: D102
            self.lidas.add(chave)
            return super().get(chave, default)

    problemas = []
    for ind in INDICADORES:
        declaradas = set(ind["requeridos"]) | set(ind["opcionais"] or [])
        espia = Espia({k: REFERENCIA[k] for k in declaradas if k in REFERENCIA})
        try:
            _calcular(ind, espia)
        except Exception:                             # noqa: BLE001 — a leitura é o que interessa
            continue
        indevidas = espia.lidas - declaradas
        if indevidas:
            problemas.append(f"{ind['code']} lê {sorted(indevidas)} sem declarar")
    assert problemas == [], "; ".join(problemas)


# =============================================================================
# Plausibilidade — o que o score promete sobre si mesmo
# =============================================================================
def _compor(valores: dict[str, float], codes: list[str], pesos: dict[str, float],
            *, min_coverage=0.6, fundacao=False):
    return compor(indicator_codes=codes, valores=valores,
                  confiancas={c: 1.0 for c in valores}, normalizacao=NORMALIZACAO,
                  pesos=pesos, min_coverage=min_coverage, fundacao_critica=fundacao)


def test_score_desativado_nunca_carrega_valor():
    """A regra que o banco também impõe (CHECK disabled XOR value), aqui na origem: se o
    Python produzisse os dois, o INSERT estouraria em produção em vez de na conta."""
    codes = CODIGOS[:2]
    pesos = {c: 0.5 for c in codes}
    for kwargs in ({"fundacao": True}, {"min_coverage": 0.99}):
        s = _compor({codes[0]: 1.0}, codes, pesos, **kwargs)
        assert s.indisponivel and s.valor is None and s.motivo, (
            "score indisponível tem que vir sem valor E com motivo")


def test_toda_ausencia_carrega_motivo():
    """"Indisponível" sem motivo é pior que ausência: o cliente vê um buraco e não sabe o
    que fazer com ele. O motivo é o que vira a próxima pergunta."""
    s = _compor({}, CODIGOS[:2], {c: 0.5 for c in CODIGOS[:2]})
    assert s.indisponivel and s.motivo in ("dados_insuficientes", "cobertura_insuficiente")


def test_peso_de_indicador_ausente_nao_vira_zero():
    """Um cliente com reserva excelente e seguro não informado não pode receber score baixo:
    ele recebe score alto com COBERTURA baixa, que é a verdade sobre o que se sabe dele."""
    codes = CODIGOS[:2]
    pesos = {codes[0]: 0.5, codes[1]: 0.5}
    curva = {c: {"pontos": [[0, 0.0], [10, 1.0]]} for c in codes}
    parcial = compor(indicator_codes=codes, valores={codes[0]: 10.0},
                     confiancas={codes[0]: 1.0}, normalizacao=curva, pesos=pesos,
                     min_coverage=0.5, fundacao_critica=False)
    assert parcial.valor == pytest.approx(1.0), "o peso do ausente foi redistribuído"
    assert parcial.cobertura == pytest.approx(0.5), "e a cobertura caiu para dizer isso"


def test_score_maximo_exige_cobertura_maxima():
    """1,00 com metade dos indicadores medidos é um número que promete mais do que sabe.
    Não é proibido pelo desenho — mas se acontecer, a tela precisa mostrar a cobertura junto,
    e este teste existe para que a decisão seja consciente, não acidental."""
    codes = CODIGOS[:2]
    curva = {c: {"pontos": [[0, 0.0], [10, 1.0]]} for c in codes}
    s = compor(indicator_codes=codes, valores={codes[0]: 10.0}, confiancas={codes[0]: 1.0},
               normalizacao=curva, pesos={c: 0.5 for c in codes},
               min_coverage=0.5, fundacao_critica=False)
    assert not (s.valor == 1.0 and s.cobertura >= 0.99), (
        "score 1,00 saiu com cobertura parcial sem que a cobertura o acompanhasse")
    assert s.cobertura < 1.0, "a cobertura tem que denunciar o que não foi medido"


def test_fundacao_critica_vence_qualquer_cobertura():
    """D11: a Fundação decide ANTES da conta. Um cliente com cobertura perfeita e reserva
    inexistente não recebe score bom — recebe ausência de score."""
    codes = CODIGOS[:1]
    curva = {codes[0]: {"pontos": [[0, 0.0], [10, 1.0]]}}
    s = compor(indicator_codes=codes, valores={codes[0]: 10.0}, confiancas={codes[0]: 1.0},
               normalizacao=curva, pesos={codes[0]: 1.0}, min_coverage=0.0,
               fundacao_critica=True)
    assert s.indisponivel and s.motivo == "fundacao_critica"


def test_interpolacao_satura_e_nao_extrapola_com_clamp():
    """Acima do suficiente, mais reserva não é mais saúde. Sem saturação, um cliente com
    dez anos de reserva receberia score fora de [0,1] e o CHECK do banco recusaria a linha."""
    curva = [[0, 0.0], [3, 0.50], [6, 0.85], [12, 1.0]]
    assert interpolar(curva, 10_000) == 1.0
    assert interpolar(curva, -10_000) == 0.0
    for code in CODIGOS:
        pontos = (NORMALIZACAO.get(code) or {}).get("pontos") or []
        if not pontos:
            continue
        for x in (-1e9, 1e9):
            y = interpolar(pontos, x, clamp=True)
            assert 0.0 <= y <= 1.0, f"{code} normaliza fora de [0,1] em x={x}: {y}"


# =============================================================================
# Unidade — a classe de erro mais silenciosa que existe num motor financeiro
# =============================================================================
def test_taxa_de_indice_e_convertida_para_a_unidade_da_divida():
    """`market.index_values` guarda taxa em PERCENTUAL; `budget.debts.annual_rate` é FRAÇÃO.

    Comparar os dois direto fazia o motor da Fundação ler um rotativo a 400% ao ano
    (`annual_rate` 4.0) como mais barato que o CDI (14.0), e a Fundação nunca ficava crítica
    por dívida com o CDI ingerido. Um gate meio morto é pior que um ausente: parece funcionar.

    Foi a persona `endividado_rotativo` que expôs — o semáforo da dívida saiu VERDE para
    quem tinha rotativo a 400%.
    """
    from app.engine.fundacao import taxa_anual_em_fracao as taxa

    assert taxa(14.0, "taxa_aa") == pytest.approx(0.14)
    assert taxa(0.0, "taxa_aa") == 0.0
    # o que não é taxa anual não vira taxa anual por conveniência
    assert taxa(140000.0, "pontos") is None
    assert taxa(1.1, "taxa_am") is None
    assert taxa(None, "taxa_aa") is None

    # e a comparação que importa: rotativo a 400% supera CDI + spread, sempre
    cdi = taxa(14.0, "taxa_aa")
    assert 4.00 > cdi + 0.06, "rotativo a 400% a.a. tem que superar o limite de dívida cara"
