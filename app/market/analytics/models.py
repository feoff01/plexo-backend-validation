"""Modelos internos e imutáveis do Quant Core.

Não são contratos públicos de tool. Eles existem para que engines diferentes compartilhem a mesma
semântica matemática sem acoplar cálculo a ``Evidencia``/``output_payload``.
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReturnMethod(StrEnum):
    """Método de retorno compatível com ``ANALISE_PARAMS.metodo_retorno`` atual."""

    LOG = "log"
    SIMPLE = "simples"


class IndexUnit(StrEnum):
    """Unidades canônicas aceitas por ``market.index_definitions``."""

    ANNUAL_RATE = "taxa_aa"
    MONTHLY_RATE = "taxa_am"
    POINTS = "pontos"
    PERCENTAGE = "percentual"


class ReturnObservation(BaseModel):
    """Retorno entre duas observações consecutivas, datado na observação final."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    value: float = Field(allow_inf_nan=False)


class DistributionSummary(BaseModel):
    """Resumo descritivo sem inferência e sem limiares de negócio escondidos."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    count: int = Field(ge=0)
    mean: float | None = Field(default=None, allow_inf_nan=False)
    median: float | None = Field(default=None, allow_inf_nan=False)
    sample_stddev: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)


class RollingMetricObservation(BaseModel):
    """Métrica rolling datada no fim da janela observada."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    value: float = Field(allow_inf_nan=False)
    window_observations: int = Field(ge=1)


class DrawdownObservation(BaseModel):
    """Drawdown no ponto e pico corrente usado como referência."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    value: float = Field(le=0, allow_inf_nan=False)
    running_peak: float = Field(gt=0, allow_inf_nan=False)


class DrawdownEpisode(BaseModel):
    """Episódio de drawdown máximo, medido em observações e não em dias corridos."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    peak_date: date
    peak_value: float = Field(gt=0, allow_inf_nan=False)
    trough_date: date
    trough_value: float = Field(gt=0, allow_inf_nan=False)
    recovery_date: date | None = None
    recovery_value: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    depth: float = Field(le=0, allow_inf_nan=False)
    time_to_trough_intervals: int = Field(ge=1)
    recovery_intervals: int | None = Field(default=None, ge=1)
    duration_intervals: int = Field(ge=1)
    recovered: bool


class DependenceMethod(StrEnum):
    """Métodos canônicos de dependência linear/monotônica do Quant Core."""

    PEARSON = "pearson"
    SPEARMAN = "spearman"


class DependenceDirection(StrEnum):
    """Regimes condicionais simples definidos pelo retorno da série de mercado."""

    UP = "up"
    DOWN = "down"


class PairedReturnObservation(BaseModel):
    """Par temporal auditável entre retornos de X e Y após alinhamento/lag."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    x_date: date
    y_date: date
    as_of_date: date
    x_value: float = Field(allow_inf_nan=False)
    y_value: float = Field(allow_inf_nan=False)


class DependenceEstimate(BaseModel):
    """Estimativa de dependência sem interpretação causal."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    method: DependenceMethod
    coefficient: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    n_pairs: int = Field(ge=0)
    lag_observations: int = 0
    x_constant: bool = False
    y_constant: bool = False


class RollingDependenceObservation(BaseModel):
    """Estimativa rolling datada quando o último par da janela está integralmente conhecido."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    data: date
    method: DependenceMethod
    coefficient: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    n_pairs: int = Field(ge=2)
    lag_observations: int = 0


class ConditionalDependenceEstimate(BaseModel):
    """Dependência condicionada ao sinal do retorno da série de mercado."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    direction: DependenceDirection
    threshold: float = Field(allow_inf_nan=False)
    method: DependenceMethod
    coefficient: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    n_pairs: int = Field(ge=0)
    lag_observations: int = 0
    x_constant: bool = False
    y_constant: bool = False


class ConditionMeasure(StrEnum):
    """Transformação usada para decidir se a condicionante subiu ou caiu."""

    RETURN = "return"
    LEVEL_CHANGE = "level_change"


class ConditionDirection(StrEnum):
    """Direção histórica selecionada na série condicionante."""

    UP = "up"
    DOWN = "down"


class ConditionChangeObservation(BaseModel):
    """Mudança da condicionante entre dois endpoints consecutivos."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    start_date: date
    end_date: date
    value: float = Field(allow_inf_nan=False)


class ConditionalResponsePair(BaseModel):
    """Resposta do ativo medida no mesmo intervalo definido pela condicionante."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    condition_start_date: date
    condition_end_date: date
    response_start_date: date
    response_end_date: date
    condition_change: float = Field(allow_inf_nan=False)
    response_return: float = Field(ge=-1, allow_inf_nan=False)


class ReturnSampleSummary(BaseModel):
    """Resumo descritivo de retornos simples; nenhuma inferência estatística."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    count: int = Field(ge=0)
    mean: float | None = Field(default=None, allow_inf_nan=False)
    median: float | None = Field(default=None, allow_inf_nan=False)
    sample_stddev: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)
    positive_fraction: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class ConditionalReturnAnalysis(BaseModel):
    """Resultado puro da seleção condicional comparado à amostra-base."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    direction: ConditionDirection
    threshold: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    n_total: int = Field(ge=0)
    n_selected: int = Field(ge=0)
    n_neutral: int = Field(ge=0)
    selected: ReturnSampleSummary
    baseline: ReturnSampleSummary
    selected_condition: DistributionSummary
    mean_difference: float | None = Field(default=None, allow_inf_nan=False)
