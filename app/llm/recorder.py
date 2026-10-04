"""Registro de chamadas em llm.model_calls (append-only, uma linha por chamada, ao concluir).

cost_usd = usage × LLM_PRICING vigente (policy operacional; payload por provedor/modelo).
Sem pricing cadastrado, cost_usd fica NULL — visível, nunca inventado.
"""
from __future__ import annotations

from psycopg import AsyncConnection

from app.config.policies import LlmPricing, pricing_de
from app.db.repos import policies as policies_repo
from app.llm.client import CallMeta, ChatResponse


class ModelCallRecorder:
    def __init__(self, conn: AsyncConnection, pricing: LlmPricing | None = None):
        self._conn = conn
        self._pricing = pricing

    async def _pricing_para(self, provider: str, model: str) -> LlmPricing | None:
        if self._pricing is not None:
            return self._pricing
        row = await policies_repo.get_current(self._conn, "LLM_PRICING")
        return pricing_de(row.payload if row else None, provider, model)

    async def gravar(self, resp: ChatResponse, meta: CallMeta, request_hash: str | None = None) -> str:
        pricing = await self._pricing_para(resp.provider, resp.model)
        custo = pricing.custo(resp.usage.input_tokens, resp.usage.cached_tokens, resp.usage.output_tokens) if pricing else None
        cur = await self._conn.execute(
            """insert into llm.model_calls
                 (purpose, provider, model, prompt_version_id, agent_code, scope_id, conversation_id, message_id,
                  analysis_id, request_hash, input_tokens, cached_tokens, output_tokens, cost_usd, latency_ms,
                  status, error_code)
               values (%s::llm.call_purpose, %s, %s, %s, %s::agents.agent_code, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               returning id::text""",
            (meta.purpose, resp.provider, resp.model, meta.prompt_version_id, meta.agent_code, meta.scope_id,
             meta.conversation_id, meta.message_id, meta.analysis_id, request_hash,
             resp.usage.input_tokens, resp.usage.cached_tokens, resp.usage.output_tokens, custo,
             resp.latency_ms, resp.status, resp.error_code))
        return (await cur.fetchone())[0]
