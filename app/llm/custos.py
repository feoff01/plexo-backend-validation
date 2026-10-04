"""llm.cost_ledger — razão de custo agregado por referência (conversa, análise ou job), upsert diário.

Uma função só, usada pelo turno do Copiloto (ref_kind='conversation') e pelo agente de Contexto
(ref_kind='job', ref_id=extraction_run). O custo em USD é a soma de llm.model_calls.cost_usd das
chamadas informadas — o que o provedor cobrou, nunca estimativa local.
"""
from __future__ import annotations

from psycopg import AsyncConnection


async def upsert_cost_ledger(conn: AsyncConnection, *, scope_id: str | None, ref_kind: str, ref_id: str,
                             call_ids: list[str], input_tokens: int, cached_tokens: int, output_tokens: int,
                             tool_executions: int = 0) -> None:
    cur = await conn.execute(
        "select coalesce(sum(cost_usd), 0) from llm.model_calls where id = any(%s)", (call_ids,))
    custo = (await cur.fetchone())[0]
    await conn.execute(
        """insert into llm.cost_ledger
             (scope_id, ref_kind, ref_id, model_calls, input_tokens, cached_tokens, output_tokens,
              tool_executions, estimated_usd)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (ref_kind, ref_id, as_of_date) do update set
             model_calls = llm.cost_ledger.model_calls + excluded.model_calls,
             input_tokens = llm.cost_ledger.input_tokens + excluded.input_tokens,
             cached_tokens = llm.cost_ledger.cached_tokens + excluded.cached_tokens,
             output_tokens = llm.cost_ledger.output_tokens + excluded.output_tokens,
             tool_executions = llm.cost_ledger.tool_executions + excluded.tool_executions,
             estimated_usd = coalesce(llm.cost_ledger.estimated_usd, 0) + coalesce(excluded.estimated_usd, 0)""",
        (scope_id, ref_kind, ref_id, len(call_ids), input_tokens, cached_tokens, output_tokens,
         tool_executions, custo))
