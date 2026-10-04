"""Monte Carlo de metas — a metade PURA, sem banco e sem efeito colateral.

O QUE ESTE MÓDULO RESPONDE, E O QUE ELE DELIBERADAMENTE NÃO RESPONDE
    Responde: "dado este aporte, este prazo e esta carteira, qual é a distribuição do valor
    final?" Não responde: "qual carteira o cliente deve ter" — isso é o Builder, que não
    existe, e fingir que existe seria construir o motor errado por conveniência.

A SIMPLIFICAÇÃO QUE CARREGA O DESENHO
    Não se simula uma série por classe de ativo. A volatilidade da carteira sai
    ANALITICAMENTE da matriz de covariância — σ_p = √(wᵀΣw) — e o retorno, de μ_p = wᵀμ.
    Simula-se UMA série agregada de log-retornos normais.

    Para o valor TERMINAL isso é equivalente a simular classe por classe e correlacionar,
    com uma fração do custo e sem decomposição de Cholesky para alguém revisar depois. A
    equivalência se perde se um dia a simulação precisar de rebalanceamento periódico ou de
    aporte que muda de destino no meio do caminho — quando esse dia chegar, é aqui que a
    conta muda, e o comentário existe para que ninguém descubra isso por acidente.

A PREMISSA QUE MAIS LIMITA O RESULTADO, DECLARADA
    Log-retornos NORMAIS. A distribuição real tem cauda mais gorda: crise de verdade é pior
    que o p5 daqui. Isto está escrito na `metodologia` do conjunto de premissas (migration
    48) e precisa aparecer na tela junto com o número. Premissa explícita e revisável vale
    mais que precisão silenciosa — o erro grave não é a normal, é a normal escondida.

REPRODUTIBILIDADE
    `random.Random(semente)` (Mersenne Twister) e `normalvariate`, que não guarda estado
    entre chamadas. Mesma semente, mesmo resultado, em qualquer máquina — e a semente vive
    em `engine.runs.params`, que entra no `input_hash`. Uma projeção que ninguém consegue
    refazer não é auditável, e a RCVM 19 pede que seja.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

MESES_POR_ANO = 12
PERCENTIS = (5, 10, 25, 50, 75, 90, 95)


@dataclass(frozen=True)
class Premissas:
    """Retorno real, volatilidade e correlação por classe — o insumo arbitrado.

    `correlacoes` é indexada pelo par ORDENADO (a < b), como a tabela guarda. Par ausente
    aqui é erro, não zero: no banco o C48b garante a matriz fechada na aprovação, e aqui
    `covariancia` levanta em vez de assumir independência — zero silencioso subestimaria a
    volatilidade da carteira inteira.
    """
    retornos: dict[str, float]
    volatilidades: dict[str, float]
    correlacoes: dict[tuple[str, str], float] = field(default_factory=dict)

    def correlacao(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        chave = (a, b) if a < b else (b, a)
        if chave not in self.correlacoes:
            raise ValueError(
                f"correlação ausente entre '{a}' e '{b}'. Par faltando seria lido como zero, "
                "e zero subestima o risco da carteira — declare a premissa (C48b).")
        return float(self.correlacoes[chave])


@dataclass(frozen=True)
class Meta:
    """O que se quer, quando, e com o que se conta para chegar lá."""
    valor_alvo: float
    meses: int
    aporte_mensal: float
    saldo_inicial: float = 0.0

    @property
    def total_depositado(self) -> float:
        return self.saldo_inicial + self.aporte_mensal * self.meses


@dataclass(frozen=True)
class Distribuicao:
    """O resultado de uma alocação candidata. Os três números que importam juntos:
    a mediana (o que costuma acontecer), o p5 (o cenário ruim) e o arrependimento."""
    alocacao: str
    percentis: dict[int, float]
    prob_sucesso: float
    prob_abaixo_do_depositado: float
    aporte_necessario: float | None
    total_depositado: float
    retorno_aa: float
    volatilidade_aa: float
    caminhos: int
    semente: int

    @property
    def mediana(self) -> float:
        return self.percentis[50]

    @property
    def cenario_ruim(self) -> float:
        return self.percentis[5]


def retorno_da_carteira(pesos: dict[str, float], p: Premissas) -> float:
    """μ_p = wᵀμ. Retorno REAL anual, em fração."""
    _validar_pesos(pesos)
    return sum(w * p.retornos[c] for c, w in pesos.items())


def volatilidade_da_carteira(pesos: dict[str, float], p: Premissas) -> float:
    """σ_p = √(wᵀΣw) — a diversificação entra por aqui, e só por aqui.

    É este número, e não o retorno, que decide o quanto o cenário ruim é ruim. Uma carteira
    com retorno maior e volatilidade maior pode ter p5 PIOR: é exatamente a possibilidade
    que a regra de elegibilidade de risco existe para detectar.
    """
    _validar_pesos(pesos)
    classes = list(pesos)
    variancia = 0.0
    for a in classes:
        for b in classes:
            variancia += (pesos[a] * pesos[b] * p.volatilidades[a] * p.volatilidades[b]
                          * p.correlacao(a, b))
    return math.sqrt(max(0.0, variancia))


def parametros_lognormais(mu_aa: float, sigma_aa: float) -> tuple[float, float]:
    """Média e desvio ARITMÉTICOS anuais → parâmetros (m, s) do log-retorno anual.

    Casamento de momentos da lognormal. Sem isto, usar μ direto como média do log embutiria
    um viés otimista: a média geométrica é sempre menor que a aritmética, e a diferença
    cresce com a volatilidade — justamente onde a carteira arrojada seria favorecida por um
    erro de conta em vez de por mérito.
    """
    um_mais = 1.0 + mu_aa
    if um_mais <= 0:
        raise ValueError(f"retorno real de {mu_aa} implica perda total ao ano")
    s2 = math.log(1.0 + (sigma_aa ** 2) / (um_mais ** 2))
    return math.log(um_mais) - s2 / 2.0, math.sqrt(s2)


def percentil(ordenados: list[float], q: float) -> float:
    """Percentil por interpolação linear entre estatísticas de ordem (q em [0, 1])."""
    if not ordenados:
        raise ValueError("distribuição vazia")
    if len(ordenados) == 1:
        return ordenados[0]
    pos = q * (len(ordenados) - 1)
    baixo = math.floor(pos)
    alto = min(baixo + 1, len(ordenados) - 1)
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * (pos - baixo)


def simular(pesos: dict[str, float], premissas: Premissas, meta: Meta, *,
            caminhos: int = 10_000, semente: int = 20260823,
            alocacao: str = "carteira",
            confianca_do_aporte: float | None = 0.90) -> Distribuicao:
    """Uma alocação, N caminhos, a distribuição do valor terminal.

    O aporte entra no FIM de cada mês (anuidade ordinária): é a hipótese conservadora, e a
    que corresponde a quem investe o que sobrou depois de viver o mês.

    Cada caminho é decomposto em `A + aporte · B`, onde A é o crescimento do saldo inicial e
    B a soma dos fatores de crescimento de cada aporte. A decomposição não é otimização
    prematura: é o que permite responder "de quanto teria que ser o aporte para chegar a 90%
    de confiança?" EXATAMENTE, sem busca iterativa — o valor sai do percentil da distribuição
    de aportes necessários, caminho a caminho.
    """
    if meta.meses <= 0:
        raise ValueError("meta sem prazo: não há o que projetar")
    if caminhos <= 0:
        raise ValueError("simulação sem caminhos")

    mu = retorno_da_carteira(pesos, premissas)
    sigma = volatilidade_da_carteira(pesos, premissas)
    m_anual, s_anual = parametros_lognormais(mu, sigma)
    m_mes = m_anual / MESES_POR_ANO
    s_mes = s_anual / math.sqrt(MESES_POR_ANO)

    rng = random.Random(semente)
    normal = rng.normalvariate
    exp = math.exp
    meses = meta.meses
    aporte = meta.aporte_mensal
    inicial = meta.saldo_inicial

    finais: list[float] = []
    aportes_necessarios: list[float] = []
    for _ in range(caminhos):
        crescimento_do_saldo = 1.0   # A/inicial: produto dos fatores do período inteiro
        fator_dos_aportes = 0.0      # B: cada aporte cresce do mês em que entrou até o fim
        for _mes in range(meses):
            fator = exp(m_mes + s_mes * normal(0.0, 1.0))
            crescimento_do_saldo *= fator
            # aporte do mês entra no fim: cresce nos meses seguintes, não neste
            fator_dos_aportes = fator_dos_aportes * fator + 1.0
        a = inicial * crescimento_do_saldo
        finais.append(a + aporte * fator_dos_aportes)
        if fator_dos_aportes > 0:
            aportes_necessarios.append(max(0.0, (meta.valor_alvo - a) / fator_dos_aportes))

    finais.sort()
    alvo = meta.valor_alvo
    depositado = meta.total_depositado

    necessario: float | None = None
    if confianca_do_aporte is not None and aportes_necessarios:
        aportes_necessarios.sort()
        necessario = percentil(aportes_necessarios, confianca_do_aporte)

    return Distribuicao(
        alocacao=alocacao,
        percentis={q: percentil(finais, q / 100.0) for q in PERCENTIS},
        prob_sucesso=sum(1 for v in finais if v >= alvo) / len(finais),
        prob_abaixo_do_depositado=sum(1 for v in finais if v < depositado) / len(finais),
        aporte_necessario=necessario,
        total_depositado=depositado,
        retorno_aa=mu,
        volatilidade_aa=sigma,
        caminhos=caminhos,
        semente=semente,
    )


def _validar_pesos(pesos: dict[str, float]) -> None:
    if not pesos:
        raise ValueError("alocação sem classe nenhuma")
    soma = sum(pesos.values())
    if abs(soma - 1.0) > 1e-4:
        raise ValueError(f"pesos somam {soma:.4f}; alocação precisa somar 1")
    negativos = [c for c, w in pesos.items() if w < 0]
    if negativos:
        raise ValueError(f"peso negativo em {negativos}: não se simula posição vendida aqui")
