"""Tools da família `planejamento` — projeção de objetivo e aposentadoria antecipada.

Método: projeção DETERMINÍSTICA composta, em termos reais, com os retornos de
PREMISSAS_FALLBACK e a taxa de retirada de PLANEJAMENTO_PREMISSAS — sem distribuição.
Percentis/probabilidade (formulação B) são do motor com Monte Carlo e semente registrada
(META_PROBABILIDADE_DE_SUCESSO.md); esta tool declara isso em `nota_metodo`.
Aporte de referência quando o cliente não informa: o COMMITTABLE (piso da renda variável).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.tools.context_pack import sobra_mensal, ultimo_income_summary
from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.hashing import arred2
from app.tools.registry import tool

# Esta frase é exibida ao CLIENTE, na proveniência do bloco. A versão anterior dizia
# "projecao_deterministica_sem_distribuicao" e mandava o cliente ver um arquivo .md do
# repositório. Método é informação legítima; nome interno de arquivo e de função não é.
NOTA_METODO = ("Dois cenários fixos, um de renda fixa e outro de renda variável, com retornos "
               "reais definidos em premissa aprovada. Não há distribuição de probabilidade "
               "aqui: a chance de atingir o objetivo vem da simulação de mercado.")


def _cenario(saldo: float, aporte: float, alvo: float, n_meses: int, retorno_aa: float) -> dict:
    i = (1 + retorno_aa) ** (1 / 12) - 1
    cresc = (1 + i) ** n_meses
    fator = ((cresc - 1) / i) if i > 0 else float(n_meses)
    projetado = saldo * cresc + aporte * fator
    faltante = alvo - saldo * cresc
    necessario = max(faltante / fator, float(0)) if fator > 0 else float(0)
    return {
        "retorno_real_aa": retorno_aa,
        "valor_projetado_brl": arred2(projetado),
        "atingivel": projetado >= alvo,
        "aporte_necessario_brl": arred2(necessario),
    }


async def _aporte_de_referencia(params_aporte: float | None, ctx: ToolContext) -> tuple[float, str, float | None]:
    """Quanto assumir de aporte quando o cliente não disse.

    Era a renda COMPROMETÍVEL — o mesmo erro da capacidade de aporte, e com efeito pior aqui:
    a projeção do carro comparou "aporte necessário R$ 28.645" contra uma capacidade de
    R$ 26.000 que ignorava R$ 16.800 de despesa mensal. As duas pontas da comparação estavam
    infladas, e o cliente saiu achando que faltava pouco.

    A referência passa a ser a SOBRA. Sem despesa registrada não há sobra que se saiba, e aí
    vale a renda comprometível — com o aviso de que a despesa não entrou na conta.
    """
    resumo = await ultimo_income_summary(ctx.conn, ctx.scope_id)
    ctx.registrar_insumo("budget.income_summaries", presente=resumo is not None)
    if resumo is None:
        if params_aporte is not None:
            return params_aporte, "parametro", None
        raise ToolInsumoFaltante(
            "não sei quanto você consegue guardar por mês, e não há renda registrada para eu "
            "derivar isso. Quanto você pretende aportar mensalmente?")

    committable = resumo["committable_brl"]
    sobra = await sobra_mensal(ctx.conn, ctx.scope_id, committable)
    ctx.registrar_insumo("budget.monthly_summaries", meses=sobra["meses_observados"])
    capacidade = sobra["sobra_brl"] if sobra["sobra_brl"] is not None else committable
    if params_aporte is not None:
        return params_aporte, "parametro", capacidade
    return capacidade, "sobra_mensal" if sobra["sobra_brl"] is not None else "committable", capacidade


# =============================================================================
# planejamento.projecao_objetivo
# =============================================================================
class ProjecaoObjetivoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_alvo_brl: float = Field(gt=0, description="Valor-alvo do objetivo, em reais de hoje.")
    prazo_meses: int = Field(gt=0, description="Prazo até o objetivo, em meses.")
    saldo_inicial_brl: float | None = Field(default=None, ge=0, description="Quanto já existe destinado ao objetivo.")
    aporte_mensal_brl: float | None = Field(default=None, gt=0, description="Aporte mensal; se ausente, uso o comprometível do orçamento (piso da renda variável).")


class ProjecaoResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_alvo_brl: float
    prazo_meses: int
    saldo_inicial_brl: float
    aporte_mensal_brl: float
    fonte_aporte: str                     # parametro | committable
    capacidade_mensal_brl: float | None
    retorno_real_rf_aa: float
    retorno_real_rv_aa: float
    premissas: dict


class ProjecaoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_alvo_brl: float
    prazo_meses: int
    aporte_considerado_brl: float
    fonte_aporte: str
    cenarios: dict
    capacidade_mensal_brl: float | None
    avisos: list[str]
    premissas_usadas: dict
    nota_metodo: str


async def preparar_projecao(params: ProjecaoObjetivoParams, ctx: ToolContext) -> ProjecaoResolvida:
    fallback = await ctx.policy("PREMISSAS_FALLBACK")
    aporte, fonte, capacidade = await _aporte_de_referencia(params.aporte_mensal_brl, ctx)
    return ProjecaoResolvida(
        valor_alvo_brl=params.valor_alvo_brl, prazo_meses=params.prazo_meses,
        saldo_inicial_brl=params.saldo_inicial_brl or float(0),
        aporte_mensal_brl=arred2(aporte), fonte_aporte=fonte, capacidade_mensal_brl=capacidade,
        retorno_real_rf_aa=float(fallback["retorno_real_rf"]),
        retorno_real_rv_aa=float(fallback["retorno_real_rv"]),
        premissas={"PREMISSAS_FALLBACK": fallback},
    )


@tool(code="planejamento.projecao_objetivo", family="planejamento", semver="1.1.1",
      display_name="Projeção de objetivo",
      description=("Projeta um objetivo HIPOTÉTICO (valor-alvo e prazo digitados) em dois cenários "
                   "determinísticos — renda fixa e renda variável — e calcula o aporte necessário em "
                   "cada um. NÃO responde 'qual a chance de eu conseguir': não há probabilidade aqui. "
                   "Para chance, use `planejamento.simulacao_objetivo`, que lê os objetivos já "
                   "cadastrados do cliente e simula dez mil cenários."),
      preparar=preparar_projecao)
def calcular_projecao(r: ProjecaoResolvida) -> ProjecaoOutput:
    cenarios = {
        "renda_fixa": _cenario(r.saldo_inicial_brl, r.aporte_mensal_brl, r.valor_alvo_brl,
                               r.prazo_meses, r.retorno_real_rf_aa),
        "renda_variavel": _cenario(r.saldo_inicial_brl, r.aporte_mensal_brl, r.valor_alvo_brl,
                                   r.prazo_meses, r.retorno_real_rv_aa),
    }
    avisos: list[str] = []
    if r.capacidade_mensal_brl is not None and cenarios["renda_variavel"]["aporte_necessario_brl"] > r.capacidade_mensal_brl:
        avisos.append("aporte_necessario_acima_da_capacidade")
    return ProjecaoOutput(
        valor_alvo_brl=r.valor_alvo_brl, prazo_meses=r.prazo_meses,
        aporte_considerado_brl=r.aporte_mensal_brl, fonte_aporte=r.fonte_aporte,
        cenarios=cenarios, capacidade_mensal_brl=r.capacidade_mensal_brl, avisos=avisos,
        premissas_usadas={"retorno_real_rf_aa": r.retorno_real_rf_aa,
                          "retorno_real_rv_aa": r.retorno_real_rv_aa},
        nota_metodo=NOTA_METODO,
    )


# =============================================================================
# planejamento.aposentadoria_antecipada
# =============================================================================
class AposentadoriaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idade_alvo: int = Field(gt=0, description="Idade em que o cliente quer parar de trabalhar.")
    renda_desejada_mensal_brl: float = Field(gt=0, description="Renda mensal desejada na aposentadoria, em reais de hoje.")
    idade_atual: int | None = Field(default=None, gt=0, description="Idade atual do cliente; obrigatória se não estiver no contexto.")
    patrimonio_atual_brl: float | None = Field(default=None, ge=0, description="Patrimônio investível atual destinado à independência.")
    aporte_mensal_brl: float | None = Field(default=None, gt=0, description="Aporte mensal; se ausente, uso o comprometível do orçamento.")


class AposentadoriaResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idade_alvo: int
    idade_atual: int
    renda_desejada_mensal_brl: float
    patrimonio_atual_brl: float
    patrimonio_informado: bool
    aporte_mensal_brl: float
    fonte_aporte: str
    capacidade_mensal_brl: float | None
    taxa_retirada_anual: float
    retorno_real_rf_aa: float
    retorno_real_rv_aa: float
    premissas: dict


class AposentadoriaOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patrimonio_necessario_brl: float
    anos_ate_alvo: int
    cenarios: dict
    aporte_considerado_brl: float
    fonte_aporte: str
    avisos: list[str]
    premissas_usadas: dict
    nota_metodo: str


async def preparar_aposentadoria(params: AposentadoriaParams, ctx: ToolContext) -> AposentadoriaResolvida:
    fallback = await ctx.policy("PREMISSAS_FALLBACK")
    plano = await ctx.policy("PLANEJAMENTO_PREMISSAS")
    if params.idade_atual is None:
        raise ToolInsumoFaltante(
            "idade atual do cliente desconhecida — pergunte a idade (idade_atual) antes de projetar")
    aporte, fonte, capacidade = await _aporte_de_referencia(params.aporte_mensal_brl, ctx)
    return AposentadoriaResolvida(
        idade_alvo=params.idade_alvo, idade_atual=params.idade_atual,
        renda_desejada_mensal_brl=params.renda_desejada_mensal_brl,
        patrimonio_atual_brl=params.patrimonio_atual_brl or float(0),
        patrimonio_informado=params.patrimonio_atual_brl is not None,
        aporte_mensal_brl=arred2(aporte), fonte_aporte=fonte, capacidade_mensal_brl=capacidade,
        taxa_retirada_anual=float(plano["taxa_retirada_anual"]),
        retorno_real_rf_aa=float(fallback["retorno_real_rf"]),
        retorno_real_rv_aa=float(fallback["retorno_real_rv"]),
        premissas={"PREMISSAS_FALLBACK": fallback, "PLANEJAMENTO_PREMISSAS": plano},
    )


@tool(code="planejamento.aposentadoria_antecipada", family="planejamento", semver="1.1.1",
      display_name="Aposentadoria antecipada",
      description=("Diagnóstico de independência financeira: patrimônio necessário para sustentar a "
                   "renda desejada (taxa de retirada de política), projeção do patrimônio até a idade-"
                   "alvo em cenários renda fixa e renda variável, e aporte necessário em cada um."),
      preparar=preparar_aposentadoria)
def calcular_aposentadoria(r: AposentadoriaResolvida) -> AposentadoriaOutput:
    necessario = arred2(r.renda_desejada_mensal_brl * 12 / r.taxa_retirada_anual)
    anos = r.idade_alvo - r.idade_atual
    avisos: list[str] = []
    if anos <= 0:
        avisos.append("idade_alvo_nao_esta_no_futuro")
        anos = 0
    if not r.patrimonio_informado:
        avisos.append("patrimonio_atual_nao_informado_assumido_zero")
    n = anos * 12
    cenarios = {
        "renda_fixa": _cenario(r.patrimonio_atual_brl, r.aporte_mensal_brl, necessario, n, r.retorno_real_rf_aa),
        "renda_variavel": _cenario(r.patrimonio_atual_brl, r.aporte_mensal_brl, necessario, n, r.retorno_real_rv_aa),
    }
    return AposentadoriaOutput(
        patrimonio_necessario_brl=necessario, anos_ate_alvo=anos, cenarios=cenarios,
        aporte_considerado_brl=r.aporte_mensal_brl, fonte_aporte=r.fonte_aporte, avisos=avisos,
        premissas_usadas={"taxa_retirada_anual": r.taxa_retirada_anual,
                          "retorno_real_rf_aa": r.retorno_real_rf_aa,
                          "retorno_real_rv_aa": r.retorno_real_rv_aa},
        nota_metodo=NOTA_METODO,
    )
