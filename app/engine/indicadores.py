"""As fórmulas dos indicadores — a metade PURA do motor do perfil.

Cada função recebe um dicionário {fact_key: número} e as premissas da política, e devolve
um número com unidade declarada no catálogo. Nenhuma lê banco, relógio ou aleatório: é isso
que as torna travadas por golden master e inspecionáveis sob a RCVM 19 (art. 17).

O nome de cada função é o `formula_ref` cadastrado em `diagnostics.indicator_definitions`.
Indicador cadastrado sem fórmula correspondente aqui é erro de carga, não silêncio: o motor
grava `is_unavailable` com motivo `motor_ausente`, e o cliente lê "ainda não calculamos isto"
em vez de um zero inventado.

CONVENÇÃO DE UNIDADE
  fração   0,145 = 14,5%          meses/anos   contagem simples          BRL   reais
"""
from __future__ import annotations

from typing import Any, Callable

MESES_POR_ANO = 12          # unidade de calendário, não premissa de negócio

Fatos = dict[str, float]
Premissas = dict[str, Any]

_FORMULAS: dict[str, Callable[[Fatos, Premissas], float | None]] = {}


def formula(nome: str):
    def deco(fn: Callable[[Fatos, Premissas], float | None]):
        _FORMULAS[nome] = fn
        return fn
    return deco


def calcular(formula_ref: str, fatos: Fatos, premissas: Premissas) -> float | None:
    """Devolve o valor, ou None quando os insumos não sustentam a conta."""
    fn = _FORMULAS.get(formula_ref)
    if fn is None:
        return None
    return fn(fatos, premissas)


def formula_existe(formula_ref: str) -> bool:
    return formula_ref in _FORMULAS


# =============================================================================
# fluxo
# =============================================================================
@formula("taxa_poupanca")
def taxa_poupanca(f: Fatos, _p: Premissas) -> float | None:
    """(renda − despesa) / renda. O número-herói do Orçamento."""
    renda, despesa = f.get("renda.mensal_liquida"), f.get("despesa.total_mensal")
    if renda is None or despesa is None or renda <= 0:
        return None
    return (renda - despesa) / renda


@formula("rigidez_orcamentaria")
def rigidez_orcamentaria(f: Fatos, _p: Premissas) -> float | None:
    """Gasto fixo contratado sobre a renda COMPROMETÍVEL — a do mês pior, não a média.

    A migration 24 já decidiu isto: "não se compromete o que só aparece nos bons meses".
    Dividir pela média fazia a persona autônoma (média 13.500, piso 4.200) sair com Fluxo
    0,86 — quase ótimo — sendo que num mês de piso ela não cobre a própria despesa. Quem
    mede ABSORÇÃO DE CHOQUE não pode usar o mês bom.
    """
    fixa, renda = f.get("despesa.fixa_contratada"), f.get("renda.comprometivel")
    if fixa is None or renda is None or renda <= 0:
        return None
    return fixa / renda


@formula("concentracao_renda")
def concentracao_renda(f: Fatos, _p: Premissas) -> float | None:
    """1 / número de fontes. Uma fonte só = 1,0 — risco tão real quanto emissor único."""
    fontes = f.get("renda.fontes_ativas")
    if fontes is None or fontes <= 0:
        return None
    return 1.0 / fontes


@formula("inflacao_estilo_vida")
def inflacao_estilo_vida(_f: Fatos, _p: Premissas) -> float | None:
    """Δdespesa ÷ Δrenda em 12 meses.

    Exige série histórica, não fato vigente — enquanto `budget.monthly_summaries` não
    alimentar o motor, o indicador sai INDISPONÍVEL. Devolver 0 aqui seria dizer ao
    cliente que ele não tem inflação de estilo de vida, o que é uma afirmação sem base.
    """
    return None


# =============================================================================
# protecao
# =============================================================================
@formula("cobertura_reserva_meses")
def cobertura_reserva_meses(f: Fatos, _p: Premissas) -> float | None:
    """Quantos meses de despesa essencial a reserva cobre. O indicador que se MOSTRA."""
    reserva, essencial = f.get("protecao.reserva_atual"), f.get("despesa.essencial_mensal")
    if reserva is None or essencial is None or essencial <= 0:
        return None
    return reserva / essencial


@formula("lacuna_seguro_vida")
def lacuna_seguro_vida(f: Fatos, p: Premissas) -> float | None:
    """(dívida + N anos de despesa por dependente) − capital segurado, com piso em zero.

    TODOS os quatro insumos são requeridos, e isso foi aprendido errando duas vezes:

    · a cobertura ausente lida como zero fez o indicador publicar R$ 1,8 mi de lacuna para
      uma cliente de quem o sistema NÃO SABIA se tinha apólice (corrigido no catálogo pela
      migration 44 e aqui, na fórmula, pela 46 — a 44 tinha corrigido só metade);
    · a dívida ausente lida como zero SUBESTIMA a lacuna, e errar para menos numa lacuna
      de proteção é o silêncio que custa caro.

    Sem dependentes a lacuna é zero, e isso é verdade e não ausência: quem não sustenta
    ninguém não precisa de seguro de vida para proteger renda de terceiro.
    """
    dependentes = f.get("protecao.dependentes_financeiros")
    essencial = f.get("despesa.essencial_mensal")
    cobertura = f.get("protecao.cobertura_vida")
    divida = f.get("divida.saldo_total")
    anos = p.get("anos_de_despesa_por_dependente")
    if None in (dependentes, essencial, cobertura, divida, anos):
        return None
    necessidade = dependentes * essencial * MESES_POR_ANO * anos + divida
    return max(0.0, necessidade - cobertura)


@formula("vulnerabilidade_choque_meses")
def vulnerabilidade_choque_meses(f: Fatos, p: Premissas) -> float | None:
    """Meses de autonomia com a renda reduzida pelo choque da política.

    Se a renda reduzida ainda cobre a despesa essencial, a autonomia não é "infinita":
    ela é o teto da curva de normalização. Devolver infinito quebraria o score.
    """
    reserva = f.get("protecao.reserva_atual")
    essencial = f.get("despesa.essencial_mensal")
    renda = f.get("renda.mensal_liquida")
    queda = p.get("queda_de_renda_no_choque")
    if reserva is None or essencial is None or renda is None or queda is None:
        return None
    deficit = essencial - renda * (1.0 - queda)
    if deficit <= 0:
        return float(MESES_POR_ANO * 100)   # saturado: a curva satura muito antes
    return reserva / deficit


# =============================================================================
# estoque
# =============================================================================
@formula("patrimonio_meses_despesa")
def patrimonio_meses_despesa(f: Fatos, _p: Premissas) -> float | None:
    patrimonio, essencial = f.get("patrimonio.liquido"), f.get("despesa.essencial_mensal")
    if patrimonio is None or essencial is None or essencial <= 0:
        return None
    return patrimonio / essencial


@formula("custo_medio_divida")
def custo_medio_divida(f: Fatos, _p: Premissas) -> float | None:
    """Custo médio ponderado da dívida, em fração ao ano.

    Sem dívida registrada o custo é zero — e zero aqui é a melhor notícia possível,
    não ausência de dado.
    """
    custo = f.get("divida.custo_medio")
    if custo is None:
        return 0.0 if (f.get("divida.saldo_total") == 0) else None
    return custo


@formula("comprometimento_divida")
def comprometimento_divida(f: Fatos, _p: Premissas) -> float | None:
    parcela, renda = f.get("divida.parcela_mensal"), f.get("renda.mensal_liquida")
    if parcela is None or renda is None or renda <= 0:
        return None
    return parcela / renda


# =============================================================================
# destino
# =============================================================================
@formula("esforco_requerido")
def esforco_requerido(f: Fatos, p: Premissas) -> float | None:
    """Aporte necessário ÷ aporte disponível.

    Acima de 1,0 o plano é infactível — e dizer isso cedo é a coisa mais fiduciária que
    o produto faz. O aporte necessário usa o retorno real da política: assumir zero
    superestimaria o esforço e assustaria sem motivo.
    """
    alvo = f.get("objetivo.valor_alvo")
    prazo = f.get("objetivo.prazo_meses")
    aporte = f.get("fluxo.aporte_mensal")
    taxa = p.get("retorno_real_mensal_para_esforco")
    if alvo is None or prazo is None or aporte is None or taxa is None or prazo <= 0 or aporte <= 0:
        return None
    if taxa <= 0:
        necessario = alvo / prazo
    else:
        # valor futuro de série uniforme: PMT = FV · i / ((1+i)^n − 1)
        fator = (1.0 + taxa) ** prazo - 1.0
        necessario = alvo * taxa / fator if fator > 0 else alvo / prazo
    return necessario / aporte


@formula("probabilidade_meta")
def probabilidade_meta(f: Fatos, _p: Premissas) -> float | None:
    """A chance de alcançar o objetivo, vinda do Monte Carlo (F17).

    Identidade sobre o fato — e é assim de propósito. A conta que produz este número mora em
    `app/engine/projecao.py`, com run auditável, semente e premissa de mercado versionada;
    repeti-la aqui criaria dois lugares onde a probabilidade é calculada, e um deles
    envelheceria. O indicador só EXPÕE o que a projeção derivou.

    Ausente quando a projeção nunca rodou — e nesse caso o Destino sai com cobertura menor,
    nunca com probabilidade zero. Zero diria que o cliente não chega; ausência diz que
    ninguém calculou, que é a verdade.
    """
    return f.get("objetivo.probabilidade_sucesso")


@formula("horizonte_aposentadoria")
def horizonte_aposentadoria(f: Fatos, _p: Premissas) -> float | None:
    """Anos até a idade-alvo. `vida.data_nascimento` chega como idade já derivada."""
    idade_alvo = f.get("destino.idade_aposentadoria")
    idade_hoje = f.get("vida.data_nascimento")     # o motor converte data → idade
    if idade_alvo is None or idade_hoje is None:
        return None
    return max(0.0, idade_alvo - idade_hoje)


# =============================================================================
# comportamento
# =============================================================================
@formula("regularidade_aporte")
def regularidade_aporte(f: Fatos, _p: Premissas) -> float | None:
    regular = f.get("comportamento.aporte_regular")
    return None if regular is None else float(regular)


@formula("disciplina_na_queda")
def disciplina_na_queda(f: Fatos, _p: Premissas) -> float | None:
    """1,0 aportou · 0,5 manteve · 0,0 vendeu. Sem observação, indisponível."""
    return f.get("comportamento.reacao_queda")
