"""Replay congelado da matemática/output de `quant.event_study` 1.0.1.

Não registra tool e não acessa banco. Existe para reproduzir `resolved_params` históricos da 1.0.1
mesmo depois do cutover da implementação canônica. Não deve receber novas features.
"""
from __future__ import annotations

import math
import statistics
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LEGACY_SEMVER = "1.0.1"
MetodoRetorno = Literal["log", "simples"]
MetodoES = Literal["market_model", "market_adjusted"]

EVENTO_AJUSTADO = "evento_ajustado"
INSTRUMENTO_DESCONHECIDO = "instrumento_desconhecido"
JANELA_POS_TRUNCADA = "janela_pos_truncada"
SEM_DADOS = "sem_dados"
SERIE_CURTA = "serie_curta"
NOTA_RCVM = ("Métrica descritiva sobre preços oficiais passados; retorno passado não indica retorno futuro. "
             "Não é tese, previsão nem indicação de compra ou venda.")


class Ponto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: date
    valor: float


class Serie(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str
    pontos: list[Ponto] = Field(default_factory=list)


class Janela(BaseModel):
    model_config = ConfigDict(extra="forbid")
    de: date | None
    ate: date | None
    n: int


class Evidencia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fonte: str
    instrument_ids: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    index_codes: list[str] = Field(default_factory=list)
    cutoff_date: date
    as_of: date | None
    n_observacoes: int
    lacunas: list[date] = Field(default_factory=list)
    metodo: str
    nota_metodo: str
    suficiente: bool
    avisos: list[str] = Field(default_factory=list)
    metricas: dict[str, float | None] = Field(default_factory=dict)
    ingestion_batch_ids: list[str] = Field(default_factory=list)


class EventStudyResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    benchmark: str
    instrument_ids: list[str]
    cutoff_date: date
    data_evento: date
    data_evento_efetiva: date | None
    serie_ativo: Serie
    serie_benchmark: Serie
    metodo: MetodoES
    metodo_retorno: MetodoRetorno
    janela_estimacao_dias: int
    pre_dias: int
    pos_dias: int
    min_observacoes: int
    max_dias_defasagem: int
    fonte: str
    ingestion_batch_ids: list[str]


class RetornoAnormal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: date
    ar_pct: float


class EventStudyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    benchmark: str
    data_evento: date
    data_evento_efetiva: date | None
    metodo: MetodoES
    alpha: float | None
    beta: float | None
    ar: list[RetornoAnormal]
    car_pct: float | None
    desvio_residuos_pct: float | None
    janela_estimacao: Janela
    janela_evento: Janela
    truncada: bool
    evidencia: Evidencia


def _retornos(pontos: list[Ponto], metodo: MetodoRetorno) -> list[tuple[date, float]]:
    return [
        (b.data, math.log(b.valor / a.valor) if metodo == "log" else b.valor / a.valor - 1)
        for a, b in zip(pontos, pontos[1:])
    ]


def _alinhar(ra: list[tuple[date, float]], rb: list[tuple[date, float]]) -> list[tuple[date, float, float]]:
    comuns = sorted(set(d for d, _ in ra) & set(d for d, _ in rb))
    va, vb = dict(ra), dict(rb)
    return [(d, va[d], vb[d]) for d in comuns]


def calcular_event_study_1_0_1(r: EventStudyResolvido) -> EventStudyOutput:
    """Implementação pura congelada da 1.0.1; não corrigir/refatorar."""
    ra = _retornos(r.serie_ativo.pontos, r.metodo_retorno)
    rb = _retornos(r.serie_benchmark.pontos, r.metodo_retorno)
    pares = _alinhar(ra, rb)
    datas = [d for d, _, _ in pares]
    avisos: list[str] = []
    if len(r.instrument_ids) < 2:
        avisos.append(INSTRUMENTO_DESCONHECIDO)
    if r.data_evento_efetiva is not None and r.data_evento_efetiva != r.data_evento:
        avisos.append(EVENTO_AJUSTADO)
    idx = datas.index(r.data_evento_efetiva) if r.data_evento_efetiva in datas else None
    alpha = beta = car = sd = None
    ars: list[RetornoAnormal] = []
    est = Janela(de=None, ate=None, n=0)
    evt = Janela(de=None, ate=None, n=0)
    truncada = False
    suficiente = False
    if idx is None:
        avisos.append(SEM_DADOS)
    else:
        fim_est = idx - r.pre_dias
        ini_est = max(0, fim_est - r.janela_estimacao_dias)
        estimacao = pares[ini_est:fim_est]
        ini_evt = max(0, idx - r.pre_dias)
        fim_evt = idx + r.pos_dias + 1
        truncada = fim_evt > len(pares)
        evento = pares[ini_evt:fim_evt]
        if truncada:
            avisos.append(JANELA_POS_TRUNCADA)
        est = Janela(de=estimacao[0][0] if estimacao else None, ate=estimacao[-1][0] if estimacao else None, n=len(estimacao))
        evt = Janela(de=evento[0][0] if evento else None, ate=evento[-1][0] if evento else None, n=len(evento))
        suficiente = len(estimacao) >= max(2, r.min_observacoes) and bool(evento)
        if not suficiente:
            avisos.append(SERIE_CURTA)
        else:
            if r.metodo == "market_model":
                reg = statistics.linear_regression([b for _, _, b in estimacao], [a for _, a, _ in estimacao])
                alpha, beta = reg.intercept, reg.slope
            else:
                alpha, beta = 0.0, 1.0
            residuos = [a - (alpha + beta * b) for _, a, b in estimacao]
            sd = statistics.stdev(residuos) if len(residuos) >= 2 else None
            sd = sd * 100 if sd is not None else None
            ars = [RetornoAnormal(data=d, ar_pct=(a - (alpha + beta * b)) * 100) for d, a, b in evento]
            car = sum(x.ar_pct for x in ars)
    as_of = datas[-1] if datas else None
    ev = Evidencia(
        fonte=r.fonte,
        instrument_ids=r.instrument_ids,
        tickers=[r.serie_ativo.codigo, r.serie_benchmark.codigo],
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=len(pares),
        metodo=f"event_study_{r.metodo}_{r.metodo_retorno}",
        nota_metodo=("Retorno anormal = retorno do ativo − retorno esperado pelo benchmark (alpha/beta da janela de "
                     "estimação); CAR = soma na janela do evento. Sem teste de significância nem inferência "
                     "estatística: o CAR comparado ao desvio dos resíduos é só ordem de grandeza. " + NOTA_RCVM),
        suficiente=suficiente,
        avisos=avisos,
        metricas={"alpha": alpha, "beta": beta, "car_pct": car, "desvio_residuos_pct": sd},
        ingestion_batch_ids=r.ingestion_batch_ids,
    )
    return EventStudyOutput(
        ticker=r.serie_ativo.codigo,
        benchmark=r.serie_benchmark.codigo,
        data_evento=r.data_evento,
        data_evento_efetiva=r.data_evento_efetiva,
        metodo=r.metodo,
        alpha=alpha,
        beta=beta,
        ar=ars,
        car_pct=car,
        desvio_residuos_pct=sd,
        janela_estimacao=est,
        janela_evento=evt,
        truncada=truncada,
        evidencia=ev,
    )
