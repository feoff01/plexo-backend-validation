"""Elegibilidade de risco — quando mais risco é uma troca, e quando é só uma piora.

A REGRA (§4 de `META_PROBABILIDADE_DE_SUCESSO.md`)
    Risco só é elegível quando aumenta MATERIALMENTE a probabilidade de sucesso da meta.
    Não porque o cliente "aguenta", não porque o perfil "permite": porque, para ESTA meta,
    neste prazo, com este aporte, o risco compra probabilidade.

    A intuição que a regra contraria é forte e comum: mais risco, mais retorno, logo mais
    chance de chegar lá. Em prazo curto isso é falso, e o motivo é aritmético — a
    volatilidade cresce com √t e o retorno com t, então em 24 meses a dispersão domina o
    prêmio. A carteira arrojada sobe a mediana um pouco e derruba o p5 muito.

DUAS CONDIÇÕES, NÃO UMA
    (1) o ganho de probabilidade precisa passar do limiar de materialidade; E
    (2) o cenário ruim (p5) não pode piorar além do que a política tolera.

    Só a primeira deixaria passar uma alocação que sobe 1 ponto de probabilidade e derruba
    o p5 em 20% — isso não é uma troca, é uma piora com aparência de escolha. E só a segunda
    vetaria risco em metas longas onde ele é justamente o que torna a meta alcançável.

O VEREDITO CARREGA O NÚMERO QUE O DECIDIU
    "Risco vetado" sem número é arbitrário, e arbitrário é o que o cliente não consegue
    contestar. Toda recusa aqui vem com os dois valores que a produziram — o p5 de cada
    carteira e o ganho de probabilidade — para que a decisão seja discutível. É o mesmo
    princípio do elo mais fraco: a tela não afirma o que não consegue justificar.

VOCABULÁRIO (RCVM 19)
    O texto é DIAGNÓSTICO de uma simulação, nunca conselho. Diz o que a simulação mostra
    para esta meta; não diz o que fazer, não usa "melhor", não sugere comprar nem vender.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.engine.simulacao import Distribuicao


@dataclass(frozen=True)
class Comparacao:
    """Uma alocação candidata medida contra a base conservadora."""
    alocacao: str
    ganho_de_probabilidade: float      # em pontos de probabilidade (fração)
    variacao_do_p5: float              # fração: negativo = cenário ruim piorou
    p5: float
    prob_sucesso: float
    elegivel: bool
    motivo_da_recusa: str | None


@dataclass(frozen=True)
class Veredito:
    alocacao: str                      # a mais arrojada que passou nas duas condições
    motivo: str                        # em português, com os números que decidiram
    comparacoes: list[Comparacao]

    @property
    def risco_liberado(self) -> bool:
        return any(c.elegivel for c in self.comparacoes)


def avaliar(distribuicoes: list[Distribuicao], *, ordem: list[str],
            limiar_materialidade_prob: float,
            piora_maxima_do_p5: float,
            meses: int) -> Veredito:
    """Do mais conservador ao mais arrojado, aceitando enquanto as duas condições valerem.

    `ordem` vem da política (SIMULACAO_METAS), não do código: o que conta como "mais
    arrojado" é decisão de compliance sobre os vetores de peso, e é revisável.

    A caminhada PARA no primeiro degrau reprovado. Se a balanceada não compra probabilidade,
    não se pula para a arrojada na esperança de que ela compre — o degrau reprovado é a
    resposta, e saltá-lo transformaria a regra em busca pelo maior número.
    """
    if not distribuicoes:
        raise ValueError("nenhuma distribuição para avaliar")
    por_nome = {d.alocacao: d for d in distribuicoes}
    faltando = [n for n in ordem if n not in por_nome]
    if faltando:
        raise ValueError(f"alocação sem simulação: {faltando}")

    base = por_nome[ordem[0]]
    comparacoes: list[Comparacao] = []
    escolhida = base.alocacao
    motivo = ""

    for nome in ordem[1:]:
        d = por_nome[nome]
        ganho = d.prob_sucesso - base.prob_sucesso
        variacao_p5 = ((d.cenario_ruim - base.cenario_ruim) / base.cenario_ruim
                       if base.cenario_ruim > 0 else 0.0)

        recusa: str | None = None
        if variacao_p5 < -piora_maxima_do_p5:
            recusa = (
                f"a carteira {nome} piora o cenário ruim desta meta: {_brl(d.cenario_ruim)} "
                f"contra {_brl(base.cenario_ruim)} da {base.alocacao}, "
                f"{_pct(abs(variacao_p5))} abaixo.")
        elif ganho < limiar_materialidade_prob:
            # Ganho NEGATIVO merece frase própria: dizer que "muda pouco" uma carteira que
            # REDUZ a chance de chegar ao alvo esconde o achado mais interessante da
            # simulação em prazo curto — a volatilidade cresce com √t e o prêmio com t, e
            # em 24 meses a dispersão vence. É o resultado que contraria a intuição, e é
            # justamente o que o cliente precisa ver escrito.
            if abs(ganho) < 0.005:
                # Empate. Dizer "REDUZ 0 pontos" é contradição — e quando a base já chega
                # perto de 100%, a informação útil não é a comparação, é que o plano fecha
                # como está. O smoke do `autonomo_volatil` produziu exatamente essa frase
                # contraditória antes desta correção.
                recusa = (
                    f"a carteira {nome} chega à mesma chance da {base.alocacao} nesta meta "
                    f"({_pct(base.prob_sucesso)}): o risco a mais não muda o resultado, só "
                    f"a oscilação do caminho.")
            elif ganho < 0:
                recusa = (
                    f"a carteira {nome} REDUZ a chance de chegar ao alvo nesta meta: "
                    f"{_pontos(abs(ganho))} a menos que a {base.alocacao}. Em {meses} meses "
                    f"a oscilação pesa mais que o retorno a mais, e o risco trabalha contra "
                    f"o prazo.")
            else:
                recusa = (
                    f"a carteira {nome} muda pouco a chance de chegar ao alvo: "
                    f"{_pontos(ganho)} sobre a {base.alocacao}, abaixo dos "
                    f"{_pontos(limiar_materialidade_prob)} que a política trata como "
                    f"diferença material. Em {meses} meses, o risco a mais não compra "
                    f"probabilidade.")

        comparacoes.append(Comparacao(
            alocacao=nome, ganho_de_probabilidade=ganho, variacao_do_p5=variacao_p5,
            p5=d.cenario_ruim, prob_sucesso=d.prob_sucesso,
            elegivel=recusa is None, motivo_da_recusa=recusa))

        if recusa is not None:
            motivo = (f"Nesta simulação, a carteira {escolhida} é a mais exposta a risco que "
                      f"se sustenta para esta meta: {recusa}")
            break

        escolhida = nome
        motivo = (f"Nesta simulação, a carteira {nome} sustenta o risco a mais para esta "
                  f"meta: {_pontos(ganho)} de chance sobre a {base.alocacao}, com o cenário "
                  f"ruim em {_brl(d.cenario_ruim)} contra {_brl(base.cenario_ruim)}.")

    if not motivo:
        motivo = (f"Só a carteira {base.alocacao} foi simulada para esta meta: não há "
                  f"comparação de risco a fazer.")

    # O caso que o primeiro smoke expôs: quando NENHUMA carteira alcança o alvo, falar de
    # risco é responder a pergunta errada. Com R$ 800 por mês e alvo de R$ 200 mil em 24
    # meses, as três chegam a 0% — e discutir qual delas é "a mais exposta que se sustenta"
    # esconde a única alavanca que existe, que é o aporte. Dizer isso primeiro é o que
    # separa um diagnóstico de um relatório.
    if max(d.prob_sucesso for d in distribuicoes) < limiar_materialidade_prob:
        necessario = por_nome[escolhida].aporte_necessario
        quanto = (f" Para chegar lá em 9 de cada 10 cenários, o aporte precisaria ser de "
                  f"{_brl(necessario)} por mês." if necessario else "")
        motivo = (f"Nesta simulação, nenhuma das carteiras alcança o alvo desta meta com o "
                  f"aporte atual — a diferença entre elas não muda esse resultado.{quanto} "
                  f"O que move este plano é o aporte ou o prazo, não o risco.")

    return Veredito(alocacao=escolhida, motivo=motivo, comparacoes=comparacoes)


def _brl(v: float) -> str:
    inteiro = f"{v:,.0f}".replace(",", ".")
    return f"R$ {inteiro}"


def _pct(fracao: float) -> str:
    return f"{fracao * 100:.0f}%"


def _pontos(fracao: float) -> str:
    n = fracao * 100
    unidade = "ponto" if abs(round(n)) == 1 else "pontos"
    return f"{n:.0f} {unidade}"
