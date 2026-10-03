"""Shadow interno de rolling volatility para a evolução futura de quant.risco_retorno.

Não registra tool, não altera policy/planner/bloco e não participa do fingerprint da 1.1.0.
O cálculo-base é delegado integralmente à implementação pública 1.1.0; este módulo compõe
somente a evolução de volatilidade já disponível no Quant Core.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.market.analytics import returns as quant_returns
from app.market.analytics import risk as quant_risk
from app.tools.analista import risco_retorno
from app.tools.analista._comum import amostrar_mensal

JANELA_VOLATILIDADE_INSUFICIENTE = "janela_volatilidade_insuficiente"
SERIE_RISCO_AMOSTRADA = "serie_risco_amostrada"
MAX_PONTOS_ROLLING_SHADOW = 60


class PontoVolatilidadeRolling(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    vol_anualizada_pct: float = Field(ge=0, allow_inf_nan=False)


class EvolucaoVolatilidadeShadow(BaseModel):
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


class RiscoRetornoRollingShadowOutput(risco_retorno.RiscoRetornoOutput):
    """Candidata aditiva: todos os campos 1.1.0 + evolução rolling shadow."""

    evolucao_volatilidade: EvolucaoVolatilidadeShadow | None = None
    avisos_candidato: list[str] = Field(default_factory=list)


def _selecionar_equidistante(items: list, *, limite: int) -> list:
    if limite < 2:
        raise ValueError("limite deve ser >= 2")
    if len(items) <= limite:
        return list(items)
    ultimo = len(items) - 1
    return [items[(i * ultimo) // (limite - 1)] for i in range(limite)]


def calcular_risco_retorno_rolling_shadow(
    r: risco_retorno.RiscoRetornoResolvido,
    *,
    janela_observacoes: int,
) -> RiscoRetornoRollingShadowOutput:
    """Compõe rolling volatility sobre o contrato público 1.1.0 sem registrá-la como tool."""
    if janela_observacoes < 2:
        raise ValueError("janela_observacoes deve ser >= 2")

    base = risco_retorno.calcular_risco_retorno(r)
    base_payload = base.model_dump()

    serie = r.serie
    pontos = serie.points if serie is not None else []
    if len(pontos) < 2:
        return RiscoRetornoRollingShadowOutput(
            **base_payload,
            evolucao_volatilidade=None,
            avisos_candidato=[JANELA_VOLATILIDADE_INSUFICIENTE],
        )

    retornos = quant_returns.calculate_returns(pontos, r.metodo_retorno)
    rolling = quant_risk.rolling_volatility(
        retornos,
        window=janela_observacoes,
        periods_per_year=r.dias_uteis_ano,
    )
    if not rolling:
        return RiscoRetornoRollingShadowOutput(
            **base_payload,
            evolucao_volatilidade=None,
            avisos_candidato=[JANELA_VOLATILIDADE_INSUFICIENTE],
        )

    minimo = min(rolling, key=lambda item: item.value)
    maximo = max(rolling, key=lambda item: item.value)

    mensal = amostrar_mensal(rolling)
    exibidos = _selecionar_equidistante(mensal, limite=MAX_PONTOS_ROLLING_SHADOW)
    amostrado = len(exibidos) < len(rolling)
    avisos = [SERIE_RISCO_AMOSTRADA] if amostrado else []

    evolucao = EvolucaoVolatilidadeShadow(
        janela_observacoes=janela_observacoes,
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
    )
    return RiscoRetornoRollingShadowOutput(
        **base_payload,
        evolucao_volatilidade=evolucao,
        avisos_candidato=avisos,
    )
