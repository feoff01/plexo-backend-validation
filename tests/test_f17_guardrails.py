"""F17 — o §8 do documento como teste, não como intenção.

`META_PROBABILIDADE_DE_SUCESSO.md` §8 lista o que a tela NÃO pode fazer com uma
probabilidade. Cada item vira asserção aqui, porque guardrail que vive só em documento é
guardrail que alguém remove sem perceber num refactor de três linhas.

O RISCO CONCRETO QUE ISTO EVITA
    Uma probabilidade de sucesso é o número mais persuasivo que a plataforma emite, e o mais
    fácil de ler como promessa. "Você chega a R$ 1,18 milhão" é uma frase que um cliente
    guarda; que ela veio de uma mediana, sob premissa arbitrada e distribuição que subestima
    a cauda, é o que ele esquece. Sob a RCVM 19 a diferença entre simulação e promessa não é
    de estilo — é o que separa diagnóstico de oferta.

    Daí as três regras: o cenário ruim nunca é omitido quando a mediana aparece; todo bloco
    de número carrega o rodapé de simulação e a limitação do método; e nenhum texto usa
    vocabulário de recomendação.
"""
from __future__ import annotations

import inspect

import pytest

from app.engine import elegibilidade, projecao, simulacao
from app.tools.assessor import simulacao_objetivo as tool_mod

PROIBIDO = ("recomend", "melhor", "compre", "venda", "oportunidade",
            "garantid", "vai render", "certeza")


def _campos(modelo) -> set[str]:
    return set(modelo.model_fields)


def test_a_saida_da_tool_nunca_traz_mediana_sem_cenario_ruim():
    """O guardrail central do §8: um fan chart lido de cima para baixo vira promessa de
    retorno; lido a partir do p5, vira planejamento.

    A checagem é ESTRUTURAL, no schema — não no texto de um prompt. Prompt se reescreve; o
    modelo de saída é contrato, e o agente não consegue receber a mediana sem receber o
    cenário ruim junto.
    """
    campos = _campos(tool_mod.Projecao)
    assert "mediana_p50" in campos
    assert "cenario_ruim_p5" in campos, (
        "a tool não pode devolver mediana sem o cenário ruim: quem lê só a mediana lê uma "
        "promessa")
    ordem = list(tool_mod.Projecao.model_fields)
    assert ordem.index("cenario_ruim_p5") < ordem.index("mediana_p50"), (
        "o cenário ruim vem ANTES da mediana na estrutura: o agente escreve na ordem em que "
        "recebe, e essa ordem é o guardrail")


def test_a_saida_da_tool_traz_o_arrependimento():
    """A chance de terminar com menos do que foi depositado é o risco que o cliente sente e
    que percentil nenhum comunica. Sem ela, "a arrojada tem mediana maior" parece um
    argumento."""
    assert "chance_de_ficar_abaixo_do_depositado" in _campos(tool_mod.Projecao)


def test_a_tool_emite_numero_e_por_isso_carrega_rodape_de_simulacao():
    """`emite_numero=True` é o que faz o executor exigir o rodapé ILUSTRATIVO. Uma tool que
    projeta futuro e se declara sem número passaria por baixo do rodapé."""
    import app.tools.registry as R
    from app.tools import carregar_tools

    carregar_tools()
    spec = R._REG["planejamento.simulacao_objetivo"]
    assert spec.emite_numero, (
        "projeção de futuro sem `emite_numero` não recebe o rodapé de simulação")
    assert tool_mod.NOTA and tool_mod.LIMITACAO
    assert "não previsão" in tool_mod.NOTA or "não é previsão" in tool_mod.NOTA
    assert "cauda" in tool_mod.LIMITACAO, (
        "a limitação declarada precisa dizer que a normal subestima a cauda — é a premissa "
        "que mais aperta o resultado, e escondê-la é o erro grave, não a normal em si")


@pytest.mark.parametrize("modulo", [simulacao, elegibilidade, projecao, tool_mod],
                         ids=lambda m: m.__name__)
def test_nenhum_texto_do_motor_usa_vocabulario_de_recomendacao(modulo):
    """RCVM 19 aplicada ao que o cliente pode ler.

    Varre as constantes de texto e as f-strings do módulo. Comentário e docstring ficam de
    fora — o vocabulário proibido aparece neles justamente para EXPLICAR a proibição, e
    barrá-los ali tornaria o código mudo sobre a própria regra.
    """
    fonte = inspect.getsource(modulo)
    codigo = compile(fonte, modulo.__name__, "exec")
    literais: list[str] = []

    def coletar(c):
        for const in c.co_consts:
            if isinstance(const, str):
                literais.append(const)
            elif hasattr(const, "co_consts"):
                coletar(const)

    coletar(codigo)
    # a docstring de módulo e as de função entram em co_consts; excluí-las por conteúdo é
    # frágil, então excluem-se pelo tamanho: texto de tela é curto, docstring é longa.
    for texto in (t for t in literais if len(t) < 400):
        baixo = texto.lower()
        for termo in PROIBIDO:
            assert termo not in baixo, f"'{termo}' em literal de {modulo.__name__}: {texto!r}"


def test_percentis_da_tool_cobrem_a_faixa_inteira():
    """p5, p25, p50, p75, p95: sem os quartis o fan chart vira três linhas e a distribuição
    parece mais estreita do que é."""
    campos = _campos(tool_mod.Projecao)
    for c in ("cenario_ruim_p5", "p25", "mediana_p50", "p75", "cenario_bom_p95"):
        assert c in campos, f"falta {c} na saída da tool"


def test_o_aporte_necessario_esta_na_saida():
    """Quando o plano não fecha, o número acionável é o aporte — não o risco. Ele precisa
    estar na saída, senão o agente responde "não dá" sem dizer quanto daria."""
    assert "aporte_para_90_por_cento" in _campos(tool_mod.Projecao)
