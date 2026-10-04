"""Contratos internos para estimativas estatísticas do Quant Core.

Este módulo não calcula regressões nem testes de hipótese. Ele define o envelope auditável que
futuras análises inferenciais podem usar sem transformar ``Evidencia.metricas`` em um dicionário
sem tipo. Fica separado de ``analytics.models`` de propósito: várias tools atuais fingerprintam
``models.py`` e não devem mudar de identidade só porque um contrato futuro foi acrescentado.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfidenceInterval(BaseModel):
    """Intervalo de confiança bilateral, sem inferir significância por conta própria."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    lower: float = Field(allow_inf_nan=False)
    upper: float = Field(allow_inf_nan=False)
    level: float = Field(gt=0, lt=1, allow_inf_nan=False)
    method: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _ordered(self) -> "ConfidenceInterval":
        if self.lower > self.upper:
            raise ValueError("confidence interval requires lower <= upper")
        return self


class MetricEstimate(BaseModel):
    """Estimativa pontual com incerteza e método explícitos.

    ``estimate=None`` representa uma estimativa matematicamente indisponível, nunca zero. Nesse
    estado erro-padrão/intervalo também precisam ser ausentes e pelo menos um warning deve explicar
    a indisponibilidade.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    estimate: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=128)
    n: int = Field(ge=0)
    standard_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    confidence_interval: ConfidenceInterval | None = None
    method: str = Field(min_length=1, max_length=128)
    warnings: tuple[str, ...] = ()

    @field_validator("warnings")
    @classmethod
    def _warnings_validos(cls, warnings: tuple[str, ...]) -> tuple[str, ...]:
        limpos = tuple(w.strip() for w in warnings)
        if any(not w for w in limpos):
            raise ValueError("warnings must be non-empty strings")
        if len(set(limpos)) != len(limpos):
            raise ValueError("warnings must be unique")
        return limpos

    @model_validator(mode="after")
    def _coerencia(self) -> "MetricEstimate":
        if self.estimate is None:
            if self.standard_error is not None or self.confidence_interval is not None:
                raise ValueError("undefined estimate cannot carry standard error or confidence interval")
            if not self.warnings:
                raise ValueError("undefined estimate requires at least one warning")
        elif self.n == 0:
            raise ValueError("defined estimate requires n >= 1")
        return self
