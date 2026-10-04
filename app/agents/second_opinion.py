"""2ª opinião do Assessor (C27): a indicação de terceiro vira ASSERÇÃO (recomendacao_externa,
nasce 'declarado') e o veredito vira decisions.records kind='segunda_opiniao' com ≥1 motivo
material (C27a) e insumos não-materiais (a asserção ainda não é fato confirmado — C27c).
Tudo na MESMA transação da mensagem do agente: o registro nasce junto do que o cliente leu.
"""
from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


async def registrar(conn: AsyncConnection, *, scope_id: str, user_id: str, agent_message_id: str,
                    user_message_id: str, tool_execution_id: str, produto: dict) -> str:
    """`produto` = output de produto.custo_fundo (model_dump). Devolve o id do record."""
    cur = await conn.execute(
        """insert into context.assertions
             (scope_id, user_id, subject_kind, attribute, value, modality, status, source,
              evidence_message_ids)
           values (%s, %s, 'recomendacao_externa', 'produto_indicado', %s, 'fato', 'declarado',
                   'conversa', %s)
           returning id::text""",
        (scope_id, user_id,
         Jsonb({"descricao": produto.get("descricao"), "taxa_adm_aa": produto.get("taxa_adm_aa"),
                "classe": produto.get("classe")}),
         [user_message_id]))
    assertion_id = (await cur.fetchone())[0]

    descricao = produto.get("descricao") or "produto indicado"
    cur = await conn.execute(
        """insert into decisions.records
             (scope_id, user_id, kind, headline, target_ref, agent_message_id)
           values (%s, %s, 'segunda_opiniao', %s, %s, %s)
           returning id::text""",
        (scope_id, user_id, f"Segunda opinião sobre o custo de {descricao}",
         Jsonb({"tool_execution_id": tool_execution_id}), agent_message_id))
    record_id = (await cur.fetchone())[0]

    claim = (f"Custo de administração estimado de R$ {produto.get('custo_adm_total_estimado_brl')} "
             f"no horizonte (taxa {produto.get('taxa_adm_aa')} a.a.; método {produto.get('metodo')}; "
             f"referência da classe: {produto.get('referencia_classe_aa')})")
    await conn.execute(
        "insert into decisions.rationale_items (record_id, seq, driver, claim, is_material) "
        "values (%s, 1, 'custo', %s, true)", (record_id, claim))
    await conn.execute(
        "insert into decisions.inputs (record_id, input_kind, ref, assertion_id, is_material) "
        "values (%s, 'assertion', %s, %s, false)",
        (record_id, Jsonb({"origem": "conversa"}), assertion_id))
    await conn.execute(
        "insert into decisions.inputs (record_id, input_kind, ref, is_material) "
        "values (%s, 'outro', %s, false)",
        (record_id, Jsonb({"tool_execution_id": tool_execution_id})))
    return record_id
