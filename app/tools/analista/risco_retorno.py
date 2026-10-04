"""Tool canônica `quant.risco_retorno` (FQ3.1/FQ3.3).

Orquestra MarketSeriesLoader + Returns/Risk Core sem duplicar matemática. Após o cutover FQ3.3,
é a interface exposta para novos turnos/planos; `quant.retorno_volatilidade` permanece registrada
apenas para replay/auditoria legacy.

A base de preço é parte do contrato:
- adjusted_close (default) -> retrospective_as_known_now;
- raw_close -> observation_date_cutoff.

A semântica temporal é derivada da base e não é parâmetro livre, evitando combinações inválidas.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import series as market_series
from app.market.analytics import models as quant_models
from app.market.analytics import returns as quant_returns
from app.market.analytics import risk as quant_risk
from app.market.analytics import statistics as quant_statistics
from app.market.series import PriceBasis, ResolvedMarketSeries, TemporalSemantics
from app.tools.analista import _comum as comum_module
from app.tools.analista._comum import (
    FORA_DA_COBERTURA,
    INSTRUMENTO_DESCONHECIDO,
    NOTA_RCVM,
    Evidencia,
    Janela,
    avisos_de_qualidade,
    amostrar_mensal,
    carregar_serie_resolvida,
    data_referencia,
    instrumento_por_termo,
    janela_padrao,
    resolver_cutoff,
)
from app.tools.executor import ToolContext
from app.tools.registry import tool


def temporal_semantics_for_basis(basis: PriceBasis) -> TemporalSemantics:
    """Alias compatível; a regra canônica vive na fundação de séries."""
    return market_series.temporal_semantics_for_price_basis(basis)


class RiscoRetornoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(min_length=1, description="Ticker do ativo (ex.: PETR4).")
    janela_dias: int | None = Field(
        default=None,
        ge=1,
        description="Janela em dias corridos até a referência; quando omitida usa a policy ANALISE_PARAMS.",
    )
    de: date | None = Field(default=None, description="Início explícito; substitui a janela padrão.")
    ate: date | None = Field(default=None, description="Fim explícito; nunca passa da data de referência.")
    data_referencia: date | None = Field(
        default=None,
        description=("Cutoff pela data da observação. Não usa observações com data posterior, mas não garante "
                     "vintage histórico contra backfills/revisões posteriores."),
    )
    price_basis: PriceBasis = Field(
        default=PriceBasis.ADJUSTED_CLOSE,
        description=("Base dos preços. adjusted_close é o default para retorno/risco econômico e usa ajuste "
                     "retrospectivo com corporate actions conhecidas hoje; raw_close usa a cotação de fechamento "
                     "publicada e cutoff apenas pela data da observação."),
    )
    incluir_evolucao_volatilidade: bool = Field(
        default=False,
        description=("Inclui evolução histórica da volatilidade anualizada em janela móvel. "
                     "Use somente quando a pergunta pedir evolução ao longo do tempo."),
    )
    janela_volatilidade_observacoes: int | None = Field(
        default=None,
        ge=2,
        description=("Janela móvel em observações de retorno, não dias corridos. Quando a evolução é pedida e "
                     "a janela é omitida, usa ANALISE_PARAMS.risco_janela_movel_observacoes."),
    )

    @model_validator(mode="after")
    def _coerencia_rolling(self) -> "RiscoRetornoParams":
        if not self.incluir_evolucao_volatilidade and self.janela_volatilidade_observacoes is not None:
            raise ValueError(
                "janela_volatilidade_observacoes exige incluir_evolucao_volatilidade=true"
            )
        return self


class DrawdownDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    peak_date: date
    trough_date: date
    recovery_date: date | None = None
    depth_pct: float = Field(le=0, allow_inf_nan=False)
    time_to_trough_intervals: int = Field(ge=1)
    recovery_intervals: int | None = Field(default=None, ge=1)
    duration_intervals: int = Field(ge=1)
    recovered: bool


class RiscoRetornoResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    instrument_id: str | None
    in_universe: bool
    cutoff_date: date
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    serie: ResolvedMarketSeries | None
    metodo_retorno: quant_models.ReturnMethod
    dias_uteis_ano: int = Field(ge=1)
    min_observacoes: int = Field(ge=1)
    max_dias_defasagem: int = Field(ge=0)
    incluir_evolucao_volatilidade: bool = False
    janela_volatilidade_observacoes: int | None = Field(default=None, ge=2)

    @model_validator(mode="after")
    def _coerencia_da_serie(self) -> "RiscoRetornoResolvido":
        esperado = temporal_semantics_for_basis(self.price_basis)
        if self.temporal_semantics != esperado:
            raise ValueError("temporal_semantics incompatível com price_basis")
        if self.serie is not None:
            prov = self.serie.provenance
            if prov.price_basis != self.price_basis:
                raise ValueError("price_basis resolvido diverge da provenance da série")
            if prov.temporal_semantics != self.temporal_semantics:
                raise ValueError("temporal_semantics resolvida diverge da provenance da série")
            if self.instrument_id is not None and self.serie.instrument_id != self.instrument_id:
                raise ValueError("instrument_id resolvido diverge da série")
        if self.incluir_evolucao_volatilidade and self.janela_volatilidade_observacoes is None:
            raise ValueError("evolução rolling resolvida exige janela_volatilidade_observacoes")
        if not self.incluir_evolucao_volatilidade and self.janela_volatilidade_observacoes is not None:
            raise ValueError("janela rolling resolvida exige incluir_evolucao_volatilidade=true")
        return self


class PontoVolatilidadeRolling(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    vol_anualizada_pct: float = Field(ge=0, allow_inf_nan=False)


class EvolucaoVolatilidade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    janela_observacoes: int = Field(ge=2)
    n_janelas_total: int = Field(ge=1)
    primeira_data: date
    ultima_data: date
    vol_inicio_pct: float = Field(ge=0, allow_inf_nan=False)
    vol_fim_pct: float = Field(ge=0, allow_inf_nan=False)
    vol_min_pct: float = Field(ge=0, allow_inf_nan=False)
    vol_min_data: date
    vol_max_pct: float = Field(ge=0, allow_inf_nan=False)
    vol_max_data: date
    pontos: list[PontoVolatilidadeRolling]
    amostrado: bool


class RiscoRetornoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    periodo: Janela
    price_basis: PriceBasis
    temporal_semantics: TemporalSemantics
    retorno_acumulado_pct: float | None
    retorno_anualizado_pct: float | None
    vol_anualizada_pct: float | None
    downside_deviation_anualizada_pct: float | None
    downside_target_periodic_pct: float = Field(default=0.0, allow_inf_nan=False)
    max_drawdown_pct: float | None
    drawdown: DrawdownDetail | None = None
    evolucao_volatilidade: EvolucaoVolatilidade | None = None
    evidencia: Evidencia


async def preparar_risco_retorno(params: RiscoRetornoParams, ctx: ToolContext) -> RiscoRetornoResolvido:
    cfg = await ctx.policy("ANALISE_PARAMS")
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    de, ate = janela_padrao(
        cutoff,
        params.de,
        params.ate,
        janela_dias=int(params.janela_dias or cfg["janela_padrao_dias"]),
    )
    inst = await instrumento_por_termo(ctx.conn, params.ticker, cutoff=cutoff)
    basis = params.price_basis
    semantics = temporal_semantics_for_basis(basis)
    janela_rolling: int | None = None
    if params.incluir_evolucao_volatilidade:
        janela_rolling = (
            params.janela_volatilidade_observacoes
            if params.janela_volatilidade_observacoes is not None
            else int(cfg["risco_janela_movel_observacoes"])
        )

    serie: ResolvedMarketSeries | None = None
    in_universe = bool(inst is not None and inst["is_in_universe"])
    if in_universe and inst is not None:
        serie = await carregar_serie_resolvida(
            ctx.conn,
            inst["instrument_id"],
            de=de,
            ate=ate,
            cutoff=cutoff,
            codigo=inst["ticker"] or params.ticker,
            basis=basis,
            temporal_semantics=semantics,
            include_calendar=True,
        )

    ctx.registrar_insumo(
        "market.prices",
        ticker=params.ticker,
        encontrado=inst is not None,
        in_universe=in_universe,
        n=serie.quality.observations if serie is not None else 0,
        cutoff=cutoff.isoformat(),
        price_basis=basis.value,
        temporal_semantics=semantics.value,
        dataset=serie.provenance.dataset if serie is not None else None,
        incluir_evolucao_volatilidade=params.incluir_evolucao_volatilidade,
        janela_volatilidade_observacoes=janela_rolling,
    )
    return RiscoRetornoResolvido(
        ticker=params.ticker,
        instrument_id=inst["instrument_id"] if inst else None,
        in_universe=in_universe,
        cutoff_date=cutoff,
        price_basis=basis,
        temporal_semantics=semantics,
        serie=serie,
        metodo_retorno=quant_models.ReturnMethod(cfg["metodo_retorno"]),
        dias_uteis_ano=int(cfg["dias_uteis_ano"]),
        min_observacoes=int(cfg["min_observacoes"]),
        max_dias_defasagem=int(cfg["max_dias_defasagem"]),
        incluir_evolucao_volatilidade=params.incluir_evolucao_volatilidade,
        janela_volatilidade_observacoes=janela_rolling,
    )


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _nota_metodo(r: RiscoRetornoResolvido) -> str:
    base = (
        "Preços ajustados retrospectivamente com corporate actions disponíveis hoje; essa série não representa "
        "um vintage histórico reproduzível no cutoff."
        if r.price_basis == PriceBasis.ADJUSTED_CLOSE
        else "Fechamentos brutos publicados; o cutoff limita a data da observação, mas não garante vintage histórico."
    )
    rolling = (
        f" Evolução de volatilidade usa janela móvel de {r.janela_volatilidade_observacoes} observações de retorno; "
        "o resumo usa a série rolling completa e os pontos exibidos podem ser compactados sem recalcular métricas."
        if r.incluir_evolucao_volatilidade
        else ""
    )
    return (
        f"{base} Retorno {r.metodo_retorno.value} entre observações consecutivas; anualização geométrica; "
        f"volatilidade = desvio-padrão amostral × raiz({r.dias_uteis_ano}); downside deviation anualizada "
        f"usa target periódico 0% e raiz({r.dias_uteis_ano}); drawdown é medido contra o pico corrente, "
        f"com duração/recuperação em intervalos observados.{rolling} " + NOTA_RCVM
    )


JANELA_VOLATILIDADE_INSUFICIENTE = "janela_volatilidade_insuficiente"
SERIE_RISCO_AMOSTRADA = "serie_risco_amostrada"
MAX_PONTOS_ROLLING = 60


def _selecionar_equidistante(items: list, *, limite: int) -> list:
    if limite < 2:
        raise ValueError("limite deve ser >= 2")
    if len(items) <= limite:
        return list(items)
    ultimo = len(items) - 1
    return [items[(i * ultimo) // (limite - 1)] for i in range(limite)]


def _evolucao_volatilidade(
    r: RiscoRetornoResolvido,
    pontos: list,
    *,
    suficiente: bool,
) -> tuple[EvolucaoVolatilidade | None, list[str]]:
    if not r.incluir_evolucao_volatilidade:
        return None, []
    janela = r.janela_volatilidade_observacoes
    if janela is None:
        raise ValueError("janela_volatilidade_observacoes ausente no resolvido")
    if not suficiente or len(pontos) < 2:
        return None, [JANELA_VOLATILIDADE_INSUFICIENTE]

    retornos = quant_returns.calculate_returns(pontos, r.metodo_retorno)
    rolling = quant_risk.rolling_volatility(
        retornos,
        window=janela,
        periods_per_year=r.dias_uteis_ano,
    )
    if not rolling:
        return None, [JANELA_VOLATILIDADE_INSUFICIENTE]

    minimo = min(rolling, key=lambda item: item.value)
    maximo = max(rolling, key=lambda item: item.value)
    mensal = amostrar_mensal(rolling)
    exibidos = _selecionar_equidistante(mensal, limite=MAX_PONTOS_ROLLING)
    amostrado = len(exibidos) < len(rolling)
    avisos = [SERIE_RISCO_AMOSTRADA] if amostrado else []
    return EvolucaoVolatilidade(
        janela_observacoes=janela,
        n_janelas_total=len(rolling),
        primeira_data=rolling[0].data,
        ultima_data=rolling[-1].data,
        vol_inicio_pct=rolling[0].value * 100,
        vol_fim_pct=rolling[-1].value * 100,
        vol_min_pct=minimo.value * 100,
        vol_min_data=minimo.data,
        vol_max_pct=maximo.value * 100,
        vol_max_data=maximo.data,
        pontos=[
            PontoVolatilidadeRolling(data=item.data, vol_anualizada_pct=item.value * 100)
            for item in exibidos
        ],
        amostrado=amostrado,
    ), avisos


@tool(
    code="quant.risco_retorno",
    family="quant",
    semver="1.2.0",
    display_name="Risco e retorno histórico",
    description=("Analisa retorno acumulado/anualizado, volatilidade anualizada, downside deviation, máximo drawdown "
                 "e, quando solicitado, a evolução histórica da volatilidade em janela móvel governada ou explícita. "
                 "Por padrão usa adjusted_close retrospectivo; raw_close pode ser pedido explicitamente. "
                 "A evolução rolling é histórica e descritiva, não forecast, sinal ou recomendação."),
    preparar=preparar_risco_retorno,
    source_dependencies=(
        comum_module.__file__,
        market_series.__file__,
        quant_models.__file__,
        quant_returns.__file__,
        quant_risk.__file__,
        quant_statistics.__file__,
    ),
    requires_market_data=True,
    exposed_to_llm=True,
)
def calcular_risco_retorno(r: RiscoRetornoResolvido) -> RiscoRetornoOutput:
    serie = r.serie
    pontos = serie.points if serie is not None else []
    n = len(pontos)
    as_of = pontos[-1].data if pontos else None

    suficiente, avisos = avisos_de_qualidade(
        as_of,
        r.cutoff_date,
        n,
        min_observacoes=r.min_observacoes,
        max_dias_defasagem=r.max_dias_defasagem,
    )
    if r.instrument_id is None:
        avisos = [INSTRUMENTO_DESCONHECIDO] + [a for a in avisos if a != "sem_dados"]
    elif not r.in_universe:
        avisos = [FORA_DA_COBERTURA] + [a for a in avisos if a != "sem_dados"]
    if serie is not None:
        avisos = _unique(avisos + serie.provenance.warnings)

    acumulado = anualizado = vol = downside = dd = None
    drawdown: DrawdownDetail | None = None
    if suficiente and n >= 2:
        rets = [x.value for x in quant_returns.calculate_returns(pontos, r.metodo_retorno)]
        acumulado_raw = quant_returns.cumulative_price_return(pontos)
        anualizado_raw = quant_returns.annualized_price_return(pontos, periods_per_year=r.dias_uteis_ano)
        vol_raw = quant_risk.annualized_volatility(rets, periods_per_year=r.dias_uteis_ano)
        downside_raw = quant_risk.annualized_downside_deviation(
            rets,
            target_return=0.0,
            periods_per_year=r.dias_uteis_ano,
        )
        dd_raw = quant_risk.maximum_drawdown(pontos)
        episodio = quant_risk.maximum_drawdown_episode(pontos)

        acumulado = acumulado_raw * 100 if acumulado_raw is not None else None
        anualizado = anualizado_raw * 100 if anualizado_raw is not None else None
        vol = vol_raw * 100 if vol_raw is not None else None
        downside = downside_raw * 100 if downside_raw is not None else None
        dd = dd_raw * 100 if dd_raw is not None else None
        if episodio is not None:
            drawdown = DrawdownDetail(
                peak_date=episodio.peak_date,
                trough_date=episodio.trough_date,
                recovery_date=episodio.recovery_date,
                depth_pct=episodio.depth * 100,
                time_to_trough_intervals=episodio.time_to_trough_intervals,
                recovery_intervals=episodio.recovery_intervals,
                duration_intervals=episodio.duration_intervals,
                recovered=episodio.recovered,
            )

    evolucao_volatilidade, avisos_rolling = _evolucao_volatilidade(
        r,
        pontos,
        suficiente=suficiente,
    )
    avisos = _unique(avisos + avisos_rolling)

    quality = serie.quality if serie is not None else None
    prov = serie.provenance if serie is not None else None
    fonte = ",".join(prov.source_codes) if prov is not None and prov.source_codes else "b3"
    codigo = serie.code if serie is not None else r.ticker
    ev = Evidencia(
        fonte=fonte,
        instrument_ids=[r.instrument_id] if r.instrument_id else [],
        tickers=[codigo] if r.instrument_id and r.in_universe else [],
        cutoff_date=r.cutoff_date,
        as_of=as_of,
        n_observacoes=n,
        lacunas=quality.missing_dates if quality is not None else [],
        metodo=(f"risco_retorno:{r.price_basis.value}:{r.temporal_semantics.value}:"
                f"{r.metodo_retorno.value}:base_{r.dias_uteis_ano}"),
        nota_metodo=_nota_metodo(r),
        suficiente=suficiente,
        avisos=avisos,
        metricas={
            "retorno_acumulado_pct": acumulado,
            "retorno_anualizado_pct": anualizado,
            "vol_anualizada_pct": vol,
            "downside_deviation_anualizada_pct": downside,
            "max_drawdown_pct": dd,
        },
        ingestion_batch_ids=prov.ingestion_batch_ids if prov is not None else [],
    )
    return RiscoRetornoOutput(
        ticker=codigo,
        periodo=Janela(de=pontos[0].data if pontos else None, ate=as_of, n=n),
        price_basis=r.price_basis,
        temporal_semantics=r.temporal_semantics,
        retorno_acumulado_pct=acumulado,
        retorno_anualizado_pct=anualizado,
        vol_anualizada_pct=vol,
        downside_deviation_anualizada_pct=downside,
        downside_target_periodic_pct=0.0,
        max_drawdown_pct=dd,
        drawdown=drawdown,
        evolucao_volatilidade=evolucao_volatilidade,
        evidencia=ev,
    )
