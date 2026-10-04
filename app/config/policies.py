"""PolicyStore — leitura tipada de engine.policy_versions (config-first).

A regra do projeto: nenhuma premissa numérica vive em código. Este módulo lê a versão VIGENTE
(effective_to IS NULL) de cada policy e entrega dicionários; acessores tipados ficam em
`Policies`. Cache curto em memória (TTL) — policy muda sem deploy, mas não a cada requisição.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.db.errors import PolicyNotFound
from app.db.repos import policies as repo


@dataclass(frozen=True)
class LlmPricing:
    usd_por_m_input: float
    usd_por_m_cache_hit: float
    usd_por_m_output: float

    def custo(self, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
        nao_cacheado = max(input_tokens - cached_tokens, 0)
        return (nao_cacheado * self.usd_por_m_input
                + cached_tokens * self.usd_por_m_cache_hit
                + output_tokens * self.usd_por_m_output) / 1_000_000


def pricing_de(payload: dict[str, Any] | None, provider: str, model: str) -> LlmPricing | None:
    """LLM_PRICING: {"<provider>": {"<model>": {usd_por_m_input, usd_por_m_cache_hit, usd_por_m_output}}}."""
    if not payload:
        return None
    p = (payload.get(provider) or {}).get(model)
    if not p:
        return None
    return LlmPricing(float(p["usd_por_m_input"]), float(p["usd_por_m_cache_hit"]), float(p["usd_por_m_output"]))


class PolicyStore:
    """Cache TTL sobre o repositório; `db` precisa oferecer service_session()."""

    def __init__(self, db, ttl_s: float = 60.0):
        self._db = db
        self._ttl = ttl_s
        self._cache: dict[str, tuple[float, repo.PolicyRow]] = {}

    async def get(self, code: str) -> repo.PolicyRow:
        hit = self._cache.get(code)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        async with self._db.service_session() as conn:
            row = await repo.get_current(conn, code)
        if row is None:
            raise PolicyNotFound(code)
        self._cache[code] = (time.monotonic() + self._ttl, row)
        return row

    async def payload(self, code: str) -> dict[str, Any]:
        return (await self.get(code)).payload

    def invalidar(self, code: str | None = None) -> None:
        if code is None:
            self._cache.clear()
        else:
            self._cache.pop(code, None)
