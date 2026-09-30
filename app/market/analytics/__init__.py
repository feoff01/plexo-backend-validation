"""Quant Core do Analista de Mercado.

Esta package contém somente matemática/modelos determinísticos. Não acessa banco, LLM, policies,
SSE ou registry de tools. I/O pertence a ``app.market.series`` / ``preparar()`` das tools.
"""

from app.market.analytics.estimates import ConfidenceInterval, MetricEstimate
from app.market.analytics.models import (
    DependenceMethod,
    DistributionSummary,
    IndexUnit,
    ReturnMethod,
    ReturnObservation,
)

__all__ = ["ConfidenceInterval", "MetricEstimate", "DependenceMethod", "DistributionSummary", "IndexUnit", "ReturnMethod", "ReturnObservation"]
