"""Extensão tipada de Evidencia para tools inferenciais do Analista.

Fica fora de ``_comum.py`` para não mudar fingerprints/semver de tools descritivas existentes que
fingerprintam aquele helper compartilhado. Futures tools como ``quant.sensibilidade`` devem declarar
este arquivo e ``analytics/estimates.py`` em ``source_dependencies``.
"""
from __future__ import annotations

from pydantic import Field

from app.market.analytics.estimates import MetricEstimate
from app.tools.analista._comum import Evidencia


class EvidenciaEstatistica(Evidencia):
    """Evidência quantitativa com estimativas inferenciais estruturadas."""

    estimativas: dict[str, MetricEstimate] = Field(default_factory=dict)
