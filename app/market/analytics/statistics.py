"""Estatística descritiva compartilhada pelo Quant Core.

Convenções:
- amostras vazias produzem ``None`` onde a estatística não existe;
- desvio-padrão é AMOSTRAL (n-1), preservando a semântica das tools atuais;
- NaN/inf nunca atravessam silenciosamente o engine.
"""
from __future__ import annotations

import math
import statistics as _statistics
from collections.abc import Iterable

from app.market.analytics.models import DistributionSummary


class NonFiniteSample(ValueError):
    """A amostra contém NaN ou infinito."""


def finite_values(values: Iterable[float]) -> list[float]:
    out = [float(v) for v in values]
    for value in out:
        if not math.isfinite(value):
            raise NonFiniteSample("amostra contém valor não finito")
    return out


def sample_stddev(values: Iterable[float]) -> float | None:
    """Desvio-padrão amostral; indefinido para menos de duas observações."""
    sample = finite_values(values)
    return _statistics.stdev(sample) if len(sample) >= 2 else None


def describe(values: Iterable[float]) -> DistributionSummary:
    """Resumo descritivo determinístico da amostra."""
    sample = finite_values(values)
    if not sample:
        return DistributionSummary(count=0)
    return DistributionSummary(
        count=len(sample),
        mean=_statistics.fmean(sample),
        median=_statistics.median(sample),
        sample_stddev=_statistics.stdev(sample) if len(sample) >= 2 else None,
        minimum=min(sample),
        maximum=max(sample),
    )
