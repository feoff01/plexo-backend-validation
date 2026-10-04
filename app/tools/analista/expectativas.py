"""Tool `dados.expectativas_mercado` — o que o mercado PROJETA (pesquisa Focus do BCB).

Fecha a terceira perna do contexto: o agente já sabia o que a taxa É (série do SGS) e o que o Copom
DISSE (camada documental, 34). Faltava o que o mercado espera. Nada aqui é projeção da Plexo — é a
estatística que o Banco Central publica, com data de coleta e número de respondentes.

`base_calculo` é PREMISSA, não detalhe: o Focus publica duas janelas para a mesma data e horizonte
(30 dias e 5 dias úteis), com número de respondentes diferente. Qual delas se cita vem da policy
`EXPECTATIVAS_PARAMS` — foi por não separá-las que a primeira ingestão guardou número errado (37).
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.tools.analista._comum import Evidencia
from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.registry import tool

FONTE = "bacen_focus"
METODO = "mediana das projeções informadas ao Banco Central na coleta mais recente"
NOTA_METODO = ("Estatística descritiva das projeções de terceiros publicada pelo Banco Central. "
               "Não é projeção da Plexo e não indica resultado futuro.")


class ExpectativasParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indicador: str = Field(description="Indicador projetado: 'Selic', 'IPCA', 'Câmbio', 'PIB Total'.")


class Horizonte(BaseModel):
    model_config = ConfigDict(extra="forbid")
    referencia: str
    mediana: float | None
    media: float | None
    desvio_padrao: float | None
    minimo: float | None
    maximo: float | None
    respondentes: int | None


class ExpectativasResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indicador: str
    data_coleta: str
    base_calculo: int
    janela_dias: str
    horizontes: list[Horizonte]
    cutoff_date: date
    lotes: list[str]


class ExpectativasOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indicador: str
    data_coleta: str
    janela: str
    horizontes: list[Horizonte]
    evidencia: Evidencia
    nota: str


async def preparar_expectativas(params: ExpectativasParams, ctx: ToolContext) -> ExpectativasResolvida:
    cfg = await ctx.policy("EXPECTATIVAS_PARAMS")
    base = int(cfg["base_calculo"])
    max_horizontes = int(cfg["max_horizontes"])
    janela = str(cfg["janela_descricao"])
    cutoff = ctx.cutoff_date or date.today()

    cur = await ctx.conn.execute(
        "select max(data_coleta)::text from market.market_expectations "
        " where indicador = %s and base_calculo = %s and data_coleta <= %s",
        (params.indicador, base, cutoff))
    linha = await cur.fetchone()
    coleta = linha[0] if linha else None
    ctx.registrar_insumo("market.market_expectations", indicador=params.indicador, coleta=coleta)
    if coleta is None:
        raise ToolInsumoFaltante(
            f"não há expectativa de mercado ingerida para {params.indicador!r} — diga ao cliente que "
            f"este indicador está fora da cobertura, sem substituir por conhecimento próprio")

    cur = await ctx.conn.execute(
        "select referencia, mediana::float, media::float, desvio_padrao::float, minimo::float, "
        "       maximo::float, respondentes, ingestion_batch_id::text "
        "  from market.market_expectations "
        " where indicador = %s and base_calculo = %s and data_coleta = %s "
        " order by referencia limit %s",
        (params.indicador, base, coleta, max_horizontes))
    linhas = await cur.fetchall()
    horizontes = [Horizonte(referencia=r, mediana=mn, media=md, desvio_padrao=dp,
                            minimo=mi, maximo=ma, respondentes=n)
                  for r, mn, md, dp, mi, ma, n, _ in linhas]
    lotes = sorted({lote for *_, lote in linhas if lote})
    return ExpectativasResolvida(indicador=params.indicador, data_coleta=coleta, base_calculo=base,
                                 janela_dias=janela, horizontes=horizontes, cutoff_date=cutoff, lotes=lotes)


@tool(code="dados.expectativas_mercado", family="dados", semver="1.0.0",
      display_name="Expectativas de mercado (Focus)",
      description=("O que o mercado projeta para um indicador (Selic, IPCA, Câmbio, PIB), segundo a pesquisa "
                   "Focus do Banco Central: mediana, dispersão e número de respondentes por ano de referência, "
                   "na coleta mais recente. Descreve projeção de TERCEIROS com data e fonte; não é projeção "
                   "da Plexo nem indicação de investimento."),
      requires_market_data=True, preparar=preparar_expectativas)
def calcular_expectativas(r: ExpectativasResolvida) -> ExpectativasOutput:
    avisos: list[str] = []
    if not r.horizontes:
        avisos.append("sem_horizonte_na_coleta")
    if any(h.mediana is None for h in r.horizontes):
        avisos.append("horizonte_sem_mediana")

    metricas: dict[str, float | None] = {f"mediana_{h.referencia}": h.mediana for h in r.horizontes}
    evidencia = Evidencia(
        fonte=FONTE, cutoff_date=r.cutoff_date, as_of=date.fromisoformat(r.data_coleta),
        n_observacoes=len(r.horizontes), metodo=METODO, nota_metodo=NOTA_METODO,
        suficiente=bool(r.horizontes), avisos=avisos, metricas=metricas, ingestion_batch_ids=r.lotes)
    return ExpectativasOutput(indicador=r.indicador, data_coleta=r.data_coleta, janela=r.janela_dias,
                              horizontes=r.horizontes, evidencia=evidencia, nota=NOTA_METODO)
