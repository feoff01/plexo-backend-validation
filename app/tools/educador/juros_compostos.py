"""Tool `educacao.simulador_juros_compostos` — simulação didática de capitalização mensal.

Não é projeção de rentabilidade: a taxa é a que o CLIENTE informou (didática), o aporte é mensal ao
fim de cada mês e a capitalização é mensal (taxa mensal equivalente à anual informada). Limites de
sanidade (prazo/taxa máximos) vêm de `EDUCACAO_PARAMS`. `calcular_juros` é pura (golden).
Literais no código: 1 (identidade), 12 (meses/ano), 100 (percentual).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.tools.executor import ToolContext, ToolParamsInvalid
from app.tools.hashing import arred2
from app.tools.registry import tool

MESES_POR_ANO = 12
PERCENTUAL = 100


class JurosParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_inicial_brl: float = Field(default=0, ge=0, description="Valor aplicado no início (pode ser zero).")
    aporte_mensal_brl: float = Field(default=0, ge=0, description="Aporte ao fim de cada mês (pode ser zero).")
    taxa_anual_pct: float = Field(gt=0, description="Taxa de juros anual, em % (ex.: 10 para 10% a.a.). É didática, informada pelo cliente.")
    prazo_anos: int = Field(gt=0, description="Prazo em anos inteiros.")


class JurosResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_inicial_brl: float
    aporte_mensal_brl: float
    taxa_anual_pct: float
    prazo_anos: int
    premissas: dict


class PontoAnual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ano: int
    aportado_acumulado_brl: float
    montante_brl: float
    juros_acumulados_brl: float


class JurosOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_inicial_brl: float
    aporte_mensal_brl: float
    taxa_anual_pct: float
    taxa_mensal_equivalente_pct: float
    prazo_anos: int
    total_aportado_brl: float
    montante_final_brl: float
    juros_totais_brl: float
    serie_anual: list[PontoAnual]
    metodo: str
    premissas_usadas: dict


async def preparar_juros(params: JurosParams, ctx: ToolContext) -> JurosResolvida:
    cfg = await ctx.policy("EDUCACAO_PARAMS")
    erros = []
    if params.prazo_anos > int(cfg["prazo_max_anos"]):
        erros.append({"loc": ["prazo_anos"], "msg": f"prazo acima do máximo didático ({cfg['prazo_max_anos']} anos)"})
    if params.taxa_anual_pct > float(cfg["taxa_max_aa_pct"]):
        erros.append({"loc": ["taxa_anual_pct"], "msg": f"taxa acima do máximo didático ({cfg['taxa_max_aa_pct']}% a.a.)"})
    if params.valor_inicial_brl == 0 and params.aporte_mensal_brl == 0:
        erros.append({"loc": ["aporte_mensal_brl"], "msg": "informe valor inicial ou aporte mensal"})
    if erros:
        raise ToolParamsInvalid("educacao.simulador_juros_compostos", erros)
    return JurosResolvida(valor_inicial_brl=params.valor_inicial_brl, aporte_mensal_brl=params.aporte_mensal_brl,
                          taxa_anual_pct=params.taxa_anual_pct, prazo_anos=params.prazo_anos,
                          premissas={"EDUCACAO_PARAMS": {"prazo_max_anos": cfg["prazo_max_anos"],
                                                         "taxa_max_aa_pct": cfg["taxa_max_aa_pct"]}})


@tool(code="educacao.simulador_juros_compostos", family="educacao", semver="1.0.0",
      display_name="Simulador didático de juros compostos",
      description=("Simulação DIDÁTICA de juros compostos com a taxa que o cliente informar: valor inicial, "
                   "aporte mensal, taxa anual (%) e prazo (anos) → montante, total aportado, juros e série "
                   "ano a ano. Serve para explicar o conceito; não é projeção de rentabilidade de nenhum produto."),
      preparar=preparar_juros)
def calcular_juros(r: JurosResolvida) -> JurosOutput:
    taxa_mensal = (1 + r.taxa_anual_pct / PERCENTUAL) ** (1 / MESES_POR_ANO) - 1
    montante = r.valor_inicial_brl
    aportado = r.valor_inicial_brl
    serie: list[PontoAnual] = []
    for ano in range(1, r.prazo_anos + 1):
        for _ in range(MESES_POR_ANO):
            montante = montante * (1 + taxa_mensal) + r.aporte_mensal_brl
            aportado += r.aporte_mensal_brl
        serie.append(PontoAnual(ano=ano, aportado_acumulado_brl=arred2(aportado), montante_brl=arred2(montante),
                                juros_acumulados_brl=arred2(montante - aportado)))
    return JurosOutput(
        valor_inicial_brl=r.valor_inicial_brl, aporte_mensal_brl=r.aporte_mensal_brl,
        taxa_anual_pct=r.taxa_anual_pct, taxa_mensal_equivalente_pct=arred2(taxa_mensal * PERCENTUAL),
        prazo_anos=r.prazo_anos, total_aportado_brl=arred2(aportado), montante_final_brl=arred2(montante),
        juros_totais_brl=arred2(montante - aportado), serie_anual=serie,
        metodo="capitalizacao_mensal_aporte_fim_do_mes", premissas_usadas=r.premissas)
