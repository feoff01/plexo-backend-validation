"""Guardrails do turno — pré-LLM (determinísticos) e pós-LLM (vocabulário RCVM, ILUSTRATIVO).

Cada intervenção vira linha em agents.guardrail_events (registro, não log perdido).
A lista de termos vive em config/vocabulario_proibido.yaml — nunca no código.
"""
from __future__ import annotations

from typing import Any

import re
from dataclasses import dataclass

from app.db.repos.prompts import encontrar_vocabulario_proibido, termos_proibidos

RODAPE_ILUSTRATIVO = ("\n\nSimulação ILUSTRATIVA sob as premissas indicadas; não é projeção de "
                      "rentabilidade nem indicação de compra ou venda. A decisão é sua.")

TEXTO_SEGURO_VOCABULARIO = ("Os números da simulação estão registrados, mas não consegui redigir a "
                            "resposta dentro do vocabulário adequado. Reformule a pergunta ou tente "
                            "novamente — a conta continua valendo, e a decisão é sua.")

# Texto seguro quando a síntese não pôde ser entregue: neutro por agente (o antigo falava em "aporte
# mensal, taxa e prazo" — vocabulário do simulador do Educador — e aparecia até em resposta do Analista).
TEXTO_SEGURO_TOOL = ("Não consegui redigir a leitura desta resposta. Reformule a pergunta — de preferência uma "
                     "medição por vez — ou peça uma análise aprofundada.")
_BLOCO_TOOL = re.compile(r"<[^<>]{0,8}DSML[^<>]{0,8}tool_calls>.*?</[^<>]{0,8}DSML[^<>]{0,8}tool_calls>", re.S)
_TAG_TOOL = re.compile(r"</?[^<>]{0,8}DSML[^<>]*>")
# Qualquer tag com DSML que sobrou (bloco truncado, barras fullwidth duplas "<｜｜DSML｜｜…"): dali em diante
# só há chamada de ferramenta — inclusive os VALORES dos parâmetros, que não são texto para o cliente.
_INICIO_TOOL = re.compile(r"<[^<>]{0,8}DSML")

# O texto vazado nunca volta ao modelo (ele continuaria o padrão): entra este marcador no lugar.
RESPOSTA_DESCARTADA = "(resposta anterior descartada: saiu como chamada de ferramenta, não como texto)"
INSTRUCAO_SEM_TOOL = ("Sua resposta anterior saiu como chamada de ferramenta, não como texto. Não chame ferramentas "
                      "agora. Escreva a leitura APENAS com os resultados já obtidos nesta conversa (número, data, fonte "
                      "e método), diga o que não foi medido e mantenha o vocabulário de diagnóstico.")


_INICIO_MARCACAO = re.compile(r"<[｜|]|DSML")


def parece_marcacao_de_tool(texto: str) -> bool:
    """F9 (stream): o texto acumulado começou a mostrar marcação interna do provedor? Vale para retenção
    ao vivo — a limpeza definitiva continua em `limpar_marcacao_de_tool` sobre o texto completo."""
    return bool(_INICIO_MARCACAO.search(texto))


def limpar_marcacao_de_tool(texto: str) -> tuple[str, bool]:
    """Provedor em modo thinking pode vazar a marcação interna de tool-call como texto quando não há
    tool disponível. Nunca chega ao cliente: remove blocos completos; se ainda sobrar qualquer tag DSML
    (bloco truncado), corta o texto dali em diante. Sinaliza (guardrail 'outro')."""
    if "DSML" not in texto:
        return texto, False
    limpo = _BLOCO_TOOL.sub("", texto)
    m = _INICIO_TOOL.search(limpo)
    if m:
        limpo = limpo[:m.start()]
    limpo = _TAG_TOOL.sub("", limpo)
    return " ".join(limpo.split()), True


def texto_seguro_tool(executadas: list[str]) -> str:
    """Quando nem o reparo rende texto.

    A versão anterior interpolava os CÓDIGOS das tools — o cliente lia "Medi o que coube
    neste turno (planejamento.projecao_objetivo, contexto.verificar_mudanca)". Nome de
    função não é informação para quem perguntou sobre a própria aposentadoria: é o sistema
    falando de si mesmo num momento em que já falhou.

    Quantas medições foram feitas é informação útil (elas estão logo abaixo, na
    proveniência, com rótulo em português). Quais funções rodaram, não.
    """
    if not executadas:
        return TEXTO_SEGURO_TOOL
    n = len(dict.fromkeys(executadas))
    quantas = "uma medição" if n == 1 else f"{n} medições"
    return (f"Fiz {quantas} para responder isso — os números estão logo abaixo —, mas não "
            "consegui escrever a leitura deles. Pode refazer a pergunta? Se puder, uma coisa "
            "de cada vez; ou peça uma análise mais aprofundada.")


TEXTO_SEGURO_RELATORIO = ("Não consegui redigir o relatório desta análise dentro do limite de resposta configurado. "
                          "As medições ficaram registradas com proveniência; peça uma nova análise aprofundada para "
                          "gerar o relatório novamente.")

TEXTO_SEGURO_ORCAMENTO = ("Não consegui concluir este turno dentro do orçamento de processamento "
                          "configurado. Tente novamente em instantes; nada foi perdido.")

_PADROES_INJECTION = (
    r"ignore (as|suas|todas as) instru", r"finja que", r"aja como se", r"revele (o|seu) (prompt|sistema)",
    r"system prompt", r"jailbreak", r"desconsidere (as|suas) regras",
)
_PADROES_PEDIDO_RECOMENDACAO = (
    r"\bo que (eu )?devo (comprar|vender|fazer com)\b", r"\bqual (o |a )?melhor (fundo|investimento|op[çc][ãa]o)\b",
    r"\bme recomenda\b", r"\bvale a pena comprar\b",
)


@dataclass(frozen=True)
class Intervencao:
    kind: str            # agents.guardrail_events.kind
    action: str          # bloqueado | reescrito | avisado | registrado
    detalhe: str


def pre_llm(texto: str) -> list[Intervencao]:
    """Heurísticas baratas ANTES de gastar token. Nada aqui bloqueia o turno em v1 — registra."""
    baixo = texto.lower()
    achadas: list[Intervencao] = []
    for padrao in _PADROES_INJECTION:
        if re.search(padrao, baixo):
            achadas.append(Intervencao("prompt_injection_suspeita", "registrado", padrao))
            break
    for padrao in _PADROES_PEDIDO_RECOMENDACAO:
        if re.search(padrao, baixo):
            achadas.append(Intervencao("pedido_recomendacao", "avisado", padrao))
            break
    return achadas


def vocabulario(texto: str) -> list[str]:
    return encontrar_vocabulario_proibido(texto, termos_proibidos())


def vocabulario_em_tool(payload: Any) -> list[str]:
    """Termos vetados (RCVM 19) dentro do OUTPUT de uma tool — texto que não passou pelo LLM.

    Existe porque, até a F13b, `vocabulario()` só via texto do modelo: saída de tool, blocos e
    cited_refs chegavam ao cliente sem checagem nenhuma. Com documento de terceiro na tela isso
    virou risco real. Aqui a checagem REGISTRA e devolve os achados — quem bloqueia é a aprovação
    no banco (34), que impede documento com termo vetado de virar citável.

    Varre recursivamente só as strings; número, booleano e chave não são texto client-facing."""
    achados: list[str] = []

    def visitar(no: Any) -> None:
        if isinstance(no, str):
            achados.extend(t for t in vocabulario(no) if t not in achados)
        elif isinstance(no, dict):
            for valor in no.values():
                visitar(valor)
        elif isinstance(no, (list, tuple)):
            for item in no:
                visitar(item)

    visitar(payload)
    return achados


def garantir_ilustrativo(texto: str, houve_calculo: bool) -> str:
    if houve_calculo and "ilustrativ" not in texto.lower():
        return texto + RODAPE_ILUSTRATIVO
    return texto


def instrucao_de_reescrita(achados: list[str]) -> str:
    return ("Reescreva a resposta anterior preservando os números e as fontes, mas SEM usar os "
            f"termos vetados ({', '.join(achados)}). Enquadre como diagnóstico/comparação e feche "
            "com 'a decisão é sua'. Devolva apenas o texto final.")
