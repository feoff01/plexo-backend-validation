"""Tool `quant.correlacao` — correlação de Pearson entre os retornos de dois ativos, ou de um ativo e um
índice/taxa, alinhados por data, com defasagem opcional (d > 0: A antecede B em d pregões). Correlação
não é causalidade — a nota de método diz isso e o prompt repete."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import series as market_series
from app.market.analytics import dependence as quant_dependence
from app.market.analytics import models as quant_models
from app.market.analytics import returns as quant_returns
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (INSTRUMENTO_DESCONHECIDO, NOTA_RCVM, SERIE_CONSTANTE, Evidencia, MetodoRetorno,
                                       Serie, avisos_de_qualidade, carregar_indice, carregar_serie, data_referencia,
                                       instrumento_por_termo, janela_padrao, resolver_cutoff)
from app.tools.executor import ToolContext
from app.tools.registry import tool


class CorrelacaoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker_a: str = Field(min_length=1, description="Ticker do primeiro ativo.")
    ticker_b: str | None = Field(default=None, description="Ticker do segundo ativo (ou use indice_b).")
    indice_b: str | None = Field(default=None, description="Índice/taxa como segunda série: cdi, selic_meta, ipca.")
    janela_dias: int | None = Field(default=None, ge=1, description="Janela em dias corridos; padrão da política.")
    defasagem_dias: int = Field(default=0, ge=0, description="d > 0 compara o retorno de A com o de B d pregões depois.")
    data_referencia: date | None = Field(default=None, description="Point-in-time: só dados até esta data.")

    @model_validator(mode="after")
    def _um_segundo(self):
        if (self.ticker_b is None) == (self.indice_b is None):
            raise ValueError("informe exatamente um: ticker_b ou indice_b")
        return self


class CorrelacaoResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker_a: str
    codigo_b: str
    instrument_ids: list[str]
    index_codes: list[str]
    cutoff_date: date
    serie_a: Serie
    serie_b: Serie
    unidade_b: str = "pontos"          # unidade do índice quando B é índice; 'pontos' para ativo
    dias_uteis_ano: int                # base de conversão de taxa a.a. (policy)
    defasagem_dias: int
    metodo_retorno: MetodoRetorno
    min_observacoes: int
    max_dias_defasagem: int
    fonte: str
    ingestion_batch_ids: list[str]


class CorrelacaoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    par: str
    correlacao: float | None
    n_pares: int
    defasagem_dias: int
    evidencia: Evidencia


async def preparar_correlacao(params: CorrelacaoParams, ctx: ToolContext) -> CorrelacaoResolvida:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = janela_padrao(cutoff, None, None, janela_dias=int(params.janela_dias or cfg["janela_padrao_dias"]))
    ids, codes, lotes = [], [], []
    serie_a, serie_b, unidade_b, fonte = Serie(codigo=params.ticker_a), Serie(codigo=params.ticker_b or params.indice_b), "pontos", "b3"
    inst_a = await instrumento_por_termo(ctx.conn, params.ticker_a, cutoff=cutoff)
    if inst_a is not None and inst_a["is_in_universe"]:
        serie_a, la = await carregar_serie(ctx.conn, inst_a["instrument_id"], de=de, ate=ate, cutoff=cutoff, codigo=inst_a["ticker"])
        ids.append(inst_a["instrument_id"]); lotes += la
    if params.ticker_b is not None:
        inst_b = await instrumento_por_termo(ctx.conn, params.ticker_b, cutoff=cutoff)
        if inst_b is not None and inst_b["is_in_universe"]:
            serie_b, lb = await carregar_serie(ctx.conn, inst_b["instrument_id"], de=de, ate=ate, cutoff=cutoff, codigo=inst_b["ticker"])
            ids.append(inst_b["instrument_id"]); lotes += lb
    else:
        unidade_b, fonte_b, serie_b, lb = await carregar_indice(ctx.conn, params.indice_b.lower(), de=de, ate=ate, cutoff=cutoff)
        codes.append(params.indice_b.lower()); lotes += lb
        fonte = f"b3+{fonte_b or 'bacen_sgs'}"
    ctx.registrar_insumo("market.prices", tickers=[params.ticker_a, params.ticker_b], indice=params.indice_b,
                         n_a=len(serie_a.pontos), n_b=len(serie_b.pontos), cutoff=cutoff.isoformat())
    return CorrelacaoResolvida(ticker_a=params.ticker_a, codigo_b=params.ticker_b or params.indice_b.lower(),
                               instrument_ids=ids, index_codes=codes, cutoff_date=cutoff, serie_a=serie_a, serie_b=serie_b,
                               unidade_b=unidade_b, dias_uteis_ano=int(cfg["dias_uteis_ano"]),
                               defasagem_dias=params.defasagem_dias, metodo_retorno=cfg["metodo_retorno"],
                               min_observacoes=int(cfg["min_observacoes"]), max_dias_defasagem=int(cfg["max_dias_defasagem"]),
                               fonte=fonte, ingestion_batch_ids=sorted(set(lotes)))


@tool(code="quant.correlacao", family="quant", semver="1.0.3",
      display_name="Correlação entre séries",
      description=("Correlação de Pearson entre os retornos de dois ativos, ou de um ativo e um índice/taxa (CDI, "
                   "Selic, IPCA), alinhados por data, com defasagem opcional. Use para perguntas do tipo 'X e Y "
                   "andam juntos?' ou 'juros sobe, X sobe?'. Correlação não é causalidade nem previsão."),
      preparar=preparar_correlacao,
      source_dependencies=(comum_module.__file__, market_series.__file__, quant_models.__file__,
                           quant_returns.__file__, quant_dependence.__file__),
      requires_market_data=True, exposed_to_llm=False)
def calcular_correlacao(r: CorrelacaoResolvida) -> CorrelacaoOutput:
    pontos_a = [market_series.MarketPoint(data=p.data, valor=p.valor) for p in r.serie_a.pontos]
    pontos_b = [market_series.MarketPoint(data=p.data, valor=p.valor) for p in r.serie_b.pontos]
    ra = quant_returns.calculate_returns(pontos_a, r.metodo_retorno)
    rb = (quant_returns.calculate_index_returns(
              pontos_b, r.unidade_b, periods_per_year=r.dias_uteis_ano, method=r.metodo_retorno
          ) if r.index_codes else quant_returns.calculate_returns(pontos_b, r.metodo_retorno))
    pares = quant_dependence.align_returns(ra, rb, lag_observations=r.defasagem_dias)
    n = len(pares)
    as_of = min(r.serie_a.pontos[-1].data if r.serie_a.pontos else r.cutoff_date,
                r.serie_b.pontos[-1].data if r.serie_b.pontos else r.cutoff_date) if pares else None
    suficiente, avisos = avisos_de_qualidade(as_of, r.cutoff_date, n, min_observacoes=r.min_observacoes,
                                             max_dias_defasagem=r.max_dias_defasagem)
    if len(r.instrument_ids) + len(r.index_codes) < 2:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
    estimate = (quant_dependence.dependence_estimate(
        pares, method=quant_models.DependenceMethod.PEARSON, lag_observations=r.defasagem_dias
    ) if suficiente else None)
    rho = estimate.coefficient if estimate is not None else None
    if suficiente and rho is None:
        avisos.append(SERIE_CONSTANTE)
    ev = Evidencia(fonte=r.fonte, instrument_ids=r.instrument_ids, tickers=[r.serie_a.codigo] + ([r.serie_b.codigo] if not r.index_codes else []),
                   index_codes=r.index_codes, cutoff_date=r.cutoff_date, as_of=as_of, n_observacoes=n,
                   metodo=f"pearson_retornos_{r.metodo_retorno}_defasagem_{r.defasagem_dias}",
                   nota_metodo=("Pearson sobre retornos alinhados por data (interseção de pregões); índice em taxa é "
                                "convertido ao retorno do período. Correlação não é causalidade. " + NOTA_RCVM),
                   suficiente=suficiente, avisos=avisos, metricas={"correlacao": rho, "n_pares": float(n)},
                   ingestion_batch_ids=r.ingestion_batch_ids)
    return CorrelacaoOutput(par=f"{r.serie_a.codigo} × {r.codigo_b}", correlacao=rho, n_pares=n,
                            defasagem_dias=r.defasagem_dias, evidencia=ev)
