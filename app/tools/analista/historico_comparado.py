"""Tool ``dados.historico_comparado``.

Compara o fechamento de um ativo com um benchmark na mesma janela. As duas
séries são alinhadas por pregão e normalizadas para base 100 pela parte pura da
tool. Assim, API, bloco persistido e gráfico usam exatamente o mesmo cálculo
auditável, sem conta no LLM ou no navegador.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.market import series as market_series
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (FORA_DA_COBERTURA, INSTRUMENTO_DESCONHECIDO, SERIE_AMOSTRADA, Evidencia,
                                       Ponto, Serie, amostrar_mensal, avisos_de_qualidade, carregar_serie,
                                       data_referencia, instrumento_por_termo, resolver_cutoff)
from app.tools.executor import ToolContext
from app.tools.registry import tool

PeriodoGrafico = Literal["1m", "3m", "1a", "5a", "tudo"]
PERIODOS_DIAS: dict[str, int] = {"1m": 31, "3m": 93, "1a": 366, "5a": 1827, "tudo": 3653}
BENCHMARK_INDISPONIVEL = "benchmark_indisponivel"
SEM_DATAS_COMUNS = "sem_datas_comuns"


class HistoricoComparadoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="Ticker do ativo principal, por exemplo PETR4.")
    benchmark: str = Field(default="BOVA11", min_length=1, description="Ticker usado como referência; padrão BOVA11.")
    periodo: PeriodoGrafico = Field(default="1a", description="Janela do gráfico: 1m, 3m, 1a, 5a ou tudo.")
    data_referencia: date | None = Field(default=None, description="Point-in-time; nunca usa preço posterior a esta data.")


class HistoricoComparadoResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    benchmark: str
    periodo: PeriodoGrafico
    cutoff_date: date
    de: date
    ate: date
    serie_ativo: Serie
    serie_benchmark: Serie
    instrument_ids: list[str]
    fonte: str
    ingestion_batch_ids: list[str]
    min_observacoes: int
    max_dias_defasagem: int
    max_pontos: int
    avisos_resolucao: list[str]


class PontoNormalizado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: date
    indice: float
    valor_original: float
    variacao_pct: float


class SerieNormalizada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str
    papel: Literal["ativo", "benchmark"]
    pontos: list[PontoNormalizado]


class ResumoHistorico(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ultimo_preco: float | None
    variacao_periodo_pct: float | None
    as_of: date | None


class HistoricoComparadoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    benchmark: str
    periodo: PeriodoGrafico
    de: date
    ate: date
    series: list[SerieNormalizada]
    resumo: ResumoHistorico
    amostrado: bool
    evidencia: Evidencia


async def preparar_historico(params: HistoricoComparadoParams, ctx: ToolContext) -> HistoricoComparadoResolvido:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = cutoff - timedelta(days=PERIODOS_DIAS[params.periodo]), cutoff
    ativo = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    referencia = await instrumento_por_termo(ctx.conn, params.benchmark, cutoff=cutoff)
    avisos: list[str] = []

    serie_ativo, lotes_ativo = Serie(codigo=params.ticker.upper()), []
    if ativo is None:
        avisos.append(INSTRUMENTO_DESCONHECIDO)
    elif not ativo["is_in_universe"]:
        avisos.append(FORA_DA_COBERTURA)
    else:
        serie_ativo, lotes_ativo = await carregar_serie(ctx.conn, ativo["instrument_id"], de=de, ate=ate,
                                                        cutoff=cutoff, codigo=ativo["ticker"] or params.ticker.upper())

    serie_benchmark, lotes_benchmark = Serie(codigo=params.benchmark.upper()), []
    if referencia is None or not referencia["is_in_universe"]:
        avisos.append(BENCHMARK_INDISPONIVEL)
    else:
        serie_benchmark, lotes_benchmark = await carregar_serie(
            ctx.conn, referencia["instrument_id"], de=de, ate=ate, cutoff=cutoff,
            codigo=referencia["ticker"] or params.benchmark.upper())
        if not serie_benchmark.pontos:
            avisos.append(BENCHMARK_INDISPONIVEL)

    ids = [x["instrument_id"] for x in (ativo, referencia) if x is not None and x["is_in_universe"]]
    ctx.registrar_insumo("market.prices", ticker=params.ticker, benchmark=params.benchmark, periodo=params.periodo,
                         cutoff=cutoff.isoformat(), n_ativo=len(serie_ativo.pontos),
                         n_benchmark=len(serie_benchmark.pontos))
    return HistoricoComparadoResolvido(
        ticker=serie_ativo.codigo, benchmark=serie_benchmark.codigo, periodo=params.periodo,
        cutoff_date=cutoff, de=de, ate=ate, serie_ativo=serie_ativo, serie_benchmark=serie_benchmark,
        instrument_ids=ids, fonte="b3", ingestion_batch_ids=sorted(set(lotes_ativo + lotes_benchmark)),
        min_observacoes=int(cfg["min_observacoes"]), max_dias_defasagem=int(cfg["max_dias_defasagem"]),
        max_pontos=int(cfg["max_pontos"]), avisos_resolucao=avisos)


def _normalizar(nome: str, papel: Literal["ativo", "benchmark"], pontos: list[Ponto]) -> SerieNormalizada:
    if not pontos or pontos[0].valor == 0:
        return SerieNormalizada(nome=nome, papel=papel, pontos=[])
    base = pontos[0].valor
    return SerieNormalizada(nome=nome, papel=papel, pontos=[
        PontoNormalizado(data=p.data, indice=(p.valor / base) * 100,
                         valor_original=p.valor, variacao_pct=((p.valor / base) - 1) * 100)
        for p in pontos
    ])


def _amostrar(series: list[SerieNormalizada], max_pontos: int) -> tuple[list[SerieNormalizada], bool]:
    """Um ponto por mês quando a janela é longa demais para caber no payload do modelo.

    `periodo='tudo'` são dez anos: ~2.520 pontos POR SÉRIE, e o output da tool volta INTEIRO ao
    modelo como mensagem `role=tool`. Com os 161 pregões do dev nunca doeu; com o acervo
    carregado, duas séries cheias estouram o `LLM_BUDGETS` do turno sozinhas.

    Amostrar não muda número nenhum: a base 100 e o resumo são calculados sobre a série INTEIRA,
    antes daqui, e `evidencia.n_observacoes` continua contando tudo. E as duas séries seguem
    alinhadas, porque compartilham as mesmas datas — a amostragem mensal escolhe os mesmos meses.
    A série cheia continua indo para o BLOCO, que é desenhado na tela e não passa pelo modelo.
    """
    if not series or len(series[0].pontos) <= max_pontos:
        return series, False
    return [SerieNormalizada(nome=s.nome, papel=s.papel, pontos=amostrar_mensal(s.pontos))
            for s in series], True


@tool(code="dados.historico_comparado", family="dados", semver="1.1.1",
      display_name="Histórico comparado (base 100)",
      description=("Histórico de fechamento de um ativo comparado ao BOVA11 ou a outro ticker, alinhado por pregão e "
                   "normalizado para base 100. Use para mostrar trajetória e comparação nos períodos 1m, 3m, 1a, "
                   "5a ou tudo. Descreve dados passados e não projeta valores futuros."),
      preparar=preparar_historico, source_dependencies=(comum_module.__file__, market_series.__file__), requires_market_data=True)
def montar_historico(r: HistoricoComparadoResolvido) -> HistoricoComparadoOutput:
    avisos = list(dict.fromkeys(r.avisos_resolucao))
    ativo = r.serie_ativo.pontos
    benchmark = r.serie_benchmark.pontos

    if ativo and benchmark:
        comuns = sorted({p.data for p in ativo} & {p.data for p in benchmark})
        if comuns:
            datas = set(comuns)
            ativo = [p for p in ativo if p.data in datas]
            benchmark = [p for p in benchmark if p.data in datas]
        else:
            avisos.append(SEM_DATAS_COMUNS)
            benchmark = []

    as_of = ativo[-1].data if ativo else None
    suficiente, avisos_qualidade = avisos_de_qualidade(
        as_of, r.cutoff_date, len(ativo), min_observacoes=r.min_observacoes,
        max_dias_defasagem=r.max_dias_defasagem)
    avisos = list(dict.fromkeys(avisos + avisos_qualidade))
    series = [_normalizar(r.ticker, "ativo", ativo)] if ativo else []
    if benchmark:
        series.append(_normalizar(r.benchmark, "benchmark", benchmark))
    series, amostrado = _amostrar(series, r.max_pontos)
    if amostrado:
        avisos = list(dict.fromkeys(avisos + [SERIE_AMOSTRADA]))
    primeiro = ativo[0].valor if ativo else None
    ultimo = ativo[-1].valor if ativo else None
    variacao = ((ultimo / primeiro) - 1) * 100 if primeiro not in (None, 0) and ultimo is not None else None
    de_efetivo = ativo[0].data if ativo else r.de
    ate_efetivo = ativo[-1].data if ativo else r.ate
    ev = Evidencia(
        fonte=r.fonte, instrument_ids=r.instrument_ids,
        tickers=[s.nome for s in series], cutoff_date=r.cutoff_date, as_of=as_of,
        n_observacoes=len(ativo), metodo="fechamentos_alinhados_base_100",
        nota_metodo=("Cada série começa em 100 no primeiro pregão comum da janela. A variação mostra desempenho "
                     "histórico relativo, não preço e não previsão."), suficiente=suficiente,
        avisos=avisos, metricas={"ultimo_preco": ultimo, "variacao_periodo_pct": variacao},
        ingestion_batch_ids=r.ingestion_batch_ids)
    return HistoricoComparadoOutput(
        ticker=r.ticker, benchmark=r.benchmark, periodo=r.periodo, de=de_efetivo, ate=ate_efetivo,
        series=series, resumo=ResumoHistorico(ultimo_preco=ultimo, variacao_periodo_pct=variacao, as_of=as_of),
        amostrado=amostrado, evidencia=ev)
