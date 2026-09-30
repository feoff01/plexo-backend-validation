"""Tools da família `orcamento` — reserva de emergência e capacidade de aporte.

Config-first: TODA premissa numérica vem de engine.policy_versions (FOUNDATION_THRESHOLDS,
INCOME_HAIRCUT) via ctx.policy() — o teste de varredura recusa literal numérico neste arquivo
(exceção: 0/1 identidade e 12 meses/ano). A parte `calcular_*` é pura e travada por golden master.
Linguagem de saída: diagnóstico/estimativa — nunca ordem, nunca promessa.
"""
from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from app.tools.context_pack import (
    dividas_ativas, income_breakdown, media_custo_mensal, reserve_settings,
    savings_rate_recente, sobra_mensal, ultimo_income_summary,
)
from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.hashing import arred2
from app.tools.registry import tool


# =============================================================================
# orcamento.reserva_emergencia
# =============================================================================
class ReservaEmergenciaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    custo_mensal_brl: float | None = Field(default=None, gt=0, description="Custo de vida mensal; se ausente, uso a média dos meses registrados no orçamento.")
    meses_alvo: float | None = Field(default=None, gt=0, description="Meses de reserva desejados; se ausente, uso a configuração do escopo ou a referência da política.")
    saldo_reserva_brl: float | None = Field(default=None, ge=0, description="Saldo atual reservado para emergência, se o cliente informar.")
    aporte_mensal_brl: float | None = Field(default=None, gt=0, description="Aporte mensal que o cliente pretende destinar à reserva.")


class ReservaResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    custo_mensal_brl: float
    fonte_custo: str                      # parametro | override | media_monthly_summaries
    meses_media_custo: int
    meses_alvo: float
    fonte_meses_alvo: str                 # parametro | reserve_settings | policy
    meses_minimos: float
    saldo_reserva_brl: float
    fonte_saldo: str                      # parametro | desconhecido
    aporte_mensal_brl: float | None
    variable_share: float | None
    premissas: dict


class ReservaOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    custo_mensal_brl: float
    meses_cobertos: float
    alvo_meses: float
    alvo_brl: float
    minimo_meses: float
    minimo_brl: float
    gap_para_alvo_brl: float
    gap_para_minimo_brl: float
    meses_para_fechar_alvo: int | None
    acima_do_minimo: bool
    no_alvo: bool
    variable_share: float | None
    avisos: list[str]
    premissas_usadas: dict
    fontes: dict


async def preparar_reserva(params: ReservaEmergenciaParams, ctx: ToolContext) -> ReservaResolvida:
    fundacao = await ctx.policy("FOUNDATION_THRESHOLDS")
    ajustes = await reserve_settings(ctx.conn, ctx.scope_id)
    ctx.registrar_insumo("budget.reserve_settings", presente=ajustes is not None)

    if params.custo_mensal_brl is not None:
        custo, fonte_custo, meses_media = params.custo_mensal_brl, "parametro", 0
    elif ajustes and ajustes.get("monthly_cost_override_brl"):
        custo, fonte_custo, meses_media = ajustes["monthly_cost_override_brl"], "override", 0
    else:
        media, n = await media_custo_mensal(ctx.conn, ctx.scope_id)
        ctx.registrar_insumo("budget.monthly_summaries", meses=n)
        if media is None:
            raise ToolInsumoFaltante(
                "custo de vida mensal desconhecido: não há meses registrados no orçamento — "
                "pergunte ao cliente o custo mensal aproximado (custo_mensal_brl)")
        custo, fonte_custo, meses_media = media, "media_monthly_summaries", n

    if params.meses_alvo is not None:
        alvo, fonte_alvo = params.meses_alvo, "parametro"
    elif ajustes and ajustes.get("target_months"):
        alvo, fonte_alvo = ajustes["target_months"], "reserve_settings"
    else:
        alvo, fonte_alvo = float(fundacao["reserva_meses_alvo"]), "policy"

    if params.saldo_reserva_brl is not None:
        saldo, fonte_saldo = params.saldo_reserva_brl, "parametro"
    else:
        saldo, fonte_saldo = float(0), "desconhecido"

    renda = await income_breakdown(ctx.conn, ctx.scope_id)
    return ReservaResolvida(
        custo_mensal_brl=arred2(custo), fonte_custo=fonte_custo, meses_media_custo=meses_media,
        meses_alvo=float(alvo), fonte_meses_alvo=fonte_alvo,
        meses_minimos=float(fundacao["reserva_meses_min"]),
        saldo_reserva_brl=arred2(saldo), fonte_saldo=fonte_saldo,
        aporte_mensal_brl=params.aporte_mensal_brl,
        variable_share=(renda or {}).get("variable_share"),
        premissas={"FOUNDATION_THRESHOLDS": fundacao},
    )


@tool(code="orcamento.reserva_emergencia", family="orcamento", semver="1.0.1",
      display_name="Reserva de emergência",
      description=("Diagnóstico da reserva de emergência do cliente: meses cobertos hoje, alvo e mínimo "
                   "(config do escopo ou referência da política), gap em R$ e meses para fechar com o "
                   "aporte informado. Não indica produto; devolve números e fontes."),
      preparar=preparar_reserva)
def calcular_reserva(r: ReservaResolvida) -> ReservaOutput:
    alvo_brl = arred2(r.custo_mensal_brl * r.meses_alvo)
    minimo_brl = arred2(r.custo_mensal_brl * r.meses_minimos)
    gap_alvo = arred2(max(alvo_brl - r.saldo_reserva_brl, 0))
    gap_minimo = arred2(max(minimo_brl - r.saldo_reserva_brl, 0))
    meses_fechar = (math.ceil(gap_alvo / r.aporte_mensal_brl)
                    if r.aporte_mensal_brl and gap_alvo > 0 else None)
    avisos: list[str] = []
    if r.fonte_saldo == "desconhecido":
        avisos.append("saldo_reserva_desconhecido")
    return ReservaOutput(
        custo_mensal_brl=r.custo_mensal_brl,
        meses_cobertos=arred2(r.saldo_reserva_brl / r.custo_mensal_brl),
        alvo_meses=r.meses_alvo, alvo_brl=alvo_brl,
        minimo_meses=r.meses_minimos, minimo_brl=minimo_brl,
        gap_para_alvo_brl=gap_alvo, gap_para_minimo_brl=gap_minimo,
        meses_para_fechar_alvo=meses_fechar,
        acima_do_minimo=r.saldo_reserva_brl >= minimo_brl,
        no_alvo=r.saldo_reserva_brl >= alvo_brl,
        variable_share=r.variable_share, avisos=avisos,
        premissas_usadas={"reserva_meses_min": r.meses_minimos, "reserva_meses_alvo": r.meses_alvo}
        if r.fonte_meses_alvo == "policy" else
        {"reserva_meses_min": r.meses_minimos, "reserva_meses_alvo": float(r.premissas["FOUNDATION_THRESHOLDS"]["reserva_meses_alvo"])},
        fontes={"custo": r.fonte_custo, "meses_alvo": r.fonte_meses_alvo, "saldo": r.fonte_saldo},
    )


# =============================================================================
# orcamento.capacidade_aporte
# =============================================================================
class CapacidadeAporteParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aporte_desejado_brl: float | None = Field(default=None, gt=0, description="Aporte mensal que o cliente quer testar contra a capacidade.")


class DividaInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descricao: str
    outstanding_brl: float
    annual_rate: float | None
    monthly_payment_brl: float | None
    is_expensive: bool | None


class CapacidadeResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fonte: str                                 # income_summaries | renda_fixa_breakdown
    fixed_brl: float
    variable_brl: float
    variable_p10_brl: float
    committable_brl: float
    months_observed: int
    savings_rate_referencia: float | None
    dividas: list[DividaInfo]
    aporte_desejado_brl: float | None
    sobra: dict                                # sobra_brl, teto_brl, despesas, meses
    premissas: dict


class DividaCara(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descricao: str
    outstanding_brl: float
    annual_rate: float | None
    custo_anual_estimado_brl: float | None


class CapacidadeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # A RESPOSTA é a sobra, não a renda comprometível. A versão anterior devolvia R$ 26.000
    # para uma cliente que gasta R$ 16.800 por mês — número certo para "renda com que dá para
    # contar" e falso para "quanto dá para aportar", que é o que a pergunta quer dizer.
    capacidade_mensal_brl: float               # renda comprometível − despesa total
    teto_se_cortar_o_supérfluo_brl: float | None   # renda comprometível − despesa essencial
    renda_com_que_da_para_contar_brl: float    # o antigo número, agora com o nome certo
    fonte: str
    decomposicao: dict
    regra: str
    aporte_desejado_brl: float | None
    aporte_desejado_cabe: bool | None
    excedente_sobre_capacidade_brl: float
    dividas_caras: list[DividaCara]
    pagamentos_mensais_dividas_brl: float
    savings_rate_referencia: float | None
    avisos: list[str]
    premissas_usadas: dict


async def preparar_capacidade(params: CapacidadeAporteParams, ctx: ToolContext) -> CapacidadeResolvida:
    haircut = await ctx.policy("INCOME_HAIRCUT")
    resumo = await ultimo_income_summary(ctx.conn, ctx.scope_id)
    ctx.registrar_insumo("budget.income_summaries", presente=resumo is not None)

    if resumo is not None:
        fonte = "income_summaries"
        fixed, variable = resumo["fixed_brl"], resumo["variable_brl"]
        p10, committable = resumo["variable_p10_brl"], resumo["committable_brl"]
        meses = resumo["months_observed"]
    else:
        renda = await income_breakdown(ctx.conn, ctx.scope_id)
        ctx.registrar_insumo("budget.v_income_breakdown", presente=renda is not None)
        if renda is None:
            raise ToolInsumoFaltante(
                "renda do escopo desconhecida: sem income_summaries nem fontes de renda ativas — "
                "pergunte ao cliente a renda mensal (fixa e variável)")
        # sem histórico não há piso observado: só a parte FIXA conta (a regra é piso, nunca média)
        fonte = "renda_fixa_breakdown"
        fixed, variable = renda["fixed_brl"], renda["variable_brl"]
        p10, committable, meses = float(0), renda["fixed_brl"], 0

    dividas = [DividaInfo(**d) for d in await dividas_ativas(ctx.conn, ctx.scope_id)]
    ctx.registrar_insumo("budget.debts", ativas=len(dividas))
    sobra = await sobra_mensal(ctx.conn, ctx.scope_id, arred2(committable))
    ctx.registrar_insumo("budget.monthly_summaries", meses=sobra["meses_observados"])
    return CapacidadeResolvida(
        fonte=fonte, fixed_brl=arred2(fixed), variable_brl=arred2(variable),
        variable_p10_brl=arred2(p10), committable_brl=arred2(committable),
        months_observed=meses,
        savings_rate_referencia=await savings_rate_recente(ctx.conn, ctx.scope_id),
        dividas=dividas, aporte_desejado_brl=params.aporte_desejado_brl, sobra=sobra,
        premissas={"INCOME_HAIRCUT": haircut},
    )


@tool(code="orcamento.capacidade_aporte", family="orcamento", semver="2.0.0",
      display_name="Capacidade de aporte",
      description=("Quanto SOBRA por mês para aportar, depois das despesas: renda com que dá para "
                   "contar (piso da variável, nunca a média) menos o custo de vida. Devolve também o "
                   "teto se o não essencial for cortado, a decomposição das duas contas, as dívidas "
                   "caras ativas e a conferência de um aporte desejado."),
      preparar=preparar_capacidade)
def calcular_capacidade(r: CapacidadeResolvida) -> CapacidadeOutput:
    caras = [DividaCara(descricao=d.descricao, outstanding_brl=d.outstanding_brl, annual_rate=d.annual_rate,
                        custo_anual_estimado_brl=(arred2(d.outstanding_brl * d.annual_rate)
                                                  if d.annual_rate is not None else None))
             for d in r.dividas if d.is_expensive]
    avisos: list[str] = []
    if caras:
        avisos.append("ha_divida_cara_ativa")
    if r.months_observed < int(r.premissas["INCOME_HAIRCUT"]["meses_minimos_para_p10"]):
        avisos.append("historico_curto_para_p10")
    if r.fonte != "income_summaries":
        avisos.append("sem_income_summaries_usando_so_renda_fixa")
    # A capacidade É a sobra. Quando não há despesa registrada não dá para saber quanto sobra,
    # e a resposta honesta é cair na renda comprometível DIZENDO que a despesa não entrou —
    # nunca apresentar renda comprometível como se fosse dinheiro livre.
    sobra = r.sobra["sobra_brl"]
    if sobra is None:
        avisos.append("sem_despesa_registrada_capacidade_e_renda_bruta")
        capacidade = r.committable_brl
    else:
        capacidade = sobra
    cabe = (r.aporte_desejado_brl <= capacidade) if r.aporte_desejado_brl is not None else None
    return CapacidadeOutput(
        capacidade_mensal_brl=capacidade,
        teto_se_cortar_o_supérfluo_brl=r.sobra["teto_brl"],
        renda_com_que_da_para_contar_brl=r.committable_brl,
        fonte=r.fonte,
        decomposicao={"fixa_brl": r.fixed_brl, "piso_variavel_brl": r.variable_p10_brl,
                      "media_variavel_brl": r.variable_brl,
                      "despesa_total_brl": r.sobra["despesa_total_brl"],
                      "despesa_essencial_brl": r.sobra["despesa_essencial_brl"]},
        regra="sobra_sobre_o_piso_da_renda",
        aporte_desejado_brl=r.aporte_desejado_brl, aporte_desejado_cabe=cabe,
        excedente_sobre_capacidade_brl=arred2(max((r.aporte_desejado_brl or float(0)) - capacidade, 0)),
        dividas_caras=caras,
        pagamentos_mensais_dividas_brl=arred2(sum(d.monthly_payment_brl or float(0) for d in r.dividas)),
        savings_rate_referencia=r.savings_rate_referencia,
        avisos=avisos,
        premissas_usadas={"meses_minimos_para_p10": int(r.premissas["INCOME_HAIRCUT"]["meses_minimos_para_p10"])},
    )
