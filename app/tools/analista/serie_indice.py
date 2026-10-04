"""Tool `dados.serie_indice` — série de um índice/taxa (CDI, Selic meta, IPCA…) até o cutoff, com o
acumulado do período. Composição: taxa a.a. → diária na base `dias_uteis_ano` da política; taxa a.m./
percentual → produto; pontos → variação entre extremos."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.market import series as market_series
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (NOTA_RCVM, SERIE_AMOSTRADA, Evidencia, Ponto, Serie, amostrar_mensal,
                                       avisos_de_qualidade, carregar_indice, data_referencia, janela_padrao,
                                       resolver_cutoff)
from app.tools.executor import ToolContext
from app.tools.registry import tool


class SerieIndiceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indice: str = Field(min_length=1, description="Código do índice: cdi, selic_meta, ipca (ver cobertura).")
    de: date | None = Field(default=None, description="Início; padrão: janela padrão da política.")
    ate: date | None = Field(default=None, description="Fim; nunca passa da data de referência.")
    data_referencia: date | None = Field(default=None, description="Point-in-time: só valores até esta data.")


class SerieIndiceResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indice: str
    unidade: str
    cutoff_date: date
    de: date
    ate: date
    serie: Serie
    dias_uteis_ano: int
    max_pontos: int
    min_observacoes: int
    max_dias_defasagem: int
    fonte: str
    ingestion_batch_ids: list[str]


class SerieIndiceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indice: str
    unidade: str
    pontos: list[Ponto]
    acumulado_periodo_pct: float | None
    amostrado: bool
    evidencia: Evidencia


async def preparar_indice(params: SerieIndiceParams, ctx: ToolContext) -> SerieIndiceResolvida:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = janela_padrao(cutoff, params.de, params.ate, janela_dias=int(cfg["janela_padrao_dias"]))
    unidade, fonte, serie, lotes = await carregar_indice(ctx.conn, params.indice.lower(), de=de, ate=ate, cutoff=cutoff)
    ctx.registrar_insumo("market.index_values", indice=params.indice, n=len(serie.pontos), cutoff=cutoff.isoformat())
    return SerieIndiceResolvida(indice=params.indice.lower(), unidade=unidade, cutoff_date=cutoff, de=de, ate=ate,
                                serie=serie, dias_uteis_ano=int(cfg["dias_uteis_ano"]),
                                max_pontos=int(cfg["max_pontos"]),
                                min_observacoes=int(cfg["min_observacoes"]),
                                max_dias_defasagem=int(cfg["max_dias_defasagem"]), fonte=fonte or "bacen_sgs",
                                ingestion_batch_ids=lotes)


def _acumulado(pontos: list[Ponto], unidade: str, dias_uteis_ano: int) -> float | None:
    if not pontos:
        return None
    if unidade == "taxa_aa":
        fator = 1.0
        for p in pontos:
            fator *= (1 + p.valor / 100) ** (1 / dias_uteis_ano)
        return (fator - 1) * 100
    if unidade in ("taxa_am", "percentual"):
        fator = 1.0
        for p in pontos:
            fator *= 1 + p.valor / 100
        return (fator - 1) * 100
    return (pontos[-1].valor / pontos[0].valor - 1) * 100 if pontos[0].valor else None


@tool(code="dados.serie_indice", family="dados", semver="1.1.1",
      display_name="Série de índice / taxa",
      description=("Valores oficiais de um índice ou taxa (CDI, Selic meta, IPCA) em um período, até a data de "
                   "referência, com o acumulado do período. Use para contextualizar juros e inflação ou como "
                   "referência ao lado de um ativo. Não projeta valores futuros."),
      preparar=preparar_indice, source_dependencies=(comum_module.__file__, market_series.__file__), requires_market_data=True)
def montar_indice(r: SerieIndiceResolvida) -> SerieIndiceOutput:
    pontos = r.serie.pontos
    as_of = pontos[-1].data if pontos else None
    suficiente, avisos = avisos_de_qualidade(as_of, r.cutoff_date, len(pontos), min_observacoes=r.min_observacoes,
                                             max_dias_defasagem=r.max_dias_defasagem)
    # O acumulado é da série INTEIRA. Compor sobre a amostra daria outro número, e a amostragem
    # existe para caber no payload do modelo — não pode mudar o que o cliente lê.
    acumulado = _acumulado(pontos, r.unidade, r.dias_uteis_ano) if suficiente else None
    amostrado = len(pontos) > r.max_pontos
    exibidos = amostrar_mensal(pontos) if amostrado else pontos
    if amostrado:
        avisos = list(dict.fromkeys(avisos + [SERIE_AMOSTRADA]))
    ev = Evidencia(fonte=r.fonte, index_codes=[r.indice], cutoff_date=r.cutoff_date, as_of=as_of,
                   n_observacoes=len(pontos),
                   metodo=f"composicao_{r.unidade}_base_{r.dias_uteis_ano}" if r.unidade == "taxa_aa" else f"composicao_{r.unidade}",
                   nota_metodo="Acumulado por composição dos valores oficiais do período. " + NOTA_RCVM,
                   suficiente=suficiente, avisos=avisos, metricas={"acumulado_periodo_pct": acumulado},
                   ingestion_batch_ids=r.ingestion_batch_ids)
    return SerieIndiceOutput(indice=r.indice, unidade=r.unidade, pontos=exibidos,
                             acumulado_periodo_pct=acumulado, amostrado=amostrado, evidencia=ev)
