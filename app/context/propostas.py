"""Escrita da proposta nascida DENTRO da conversa (migration 39).

O laço completo, e onde cada peça vive:

    modelo nota "passei a ganhar 10 mil"
      └ tool contexto.verificar_mudanca      (read-only, cacheável, golden)
      └ ESTE MÓDULO grava run 'turno' → sinal → proposta   (Tx B do turno)
      └ evento SSE `proposta` → card na tela
      └ /proposals/{id}/confirm → aplicador → contexto atualizado

Por que a escrita não está na tool: o executor devolve output de cache sem executar a
função, então uma tool que escrevesse seria pulada na segunda vez. Aqui a idempotência é
explícita e do banco (índice único `proposals_idempotent_idx`, C38e).

A cadeia de proveniência continua inteira: o run ao vivo aponta a mensagem exata do turno,
e proposta sem sinal continua impossível. Nada aqui contorna gate — tudo o que este módulo
tenta ainda passa por C38b/C38d/C38f/C38g/C39c/C39d.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

# `kind` de context.proposal_kind por família do fato. O enum vem da 21/22 e não muda aqui.
KIND_POR_FAMILIA = {
    "fluxo": "budget_field",
    "protecao": "profile_field",
    "estoque": "estate_asset",
    "destino": "goal_update",
    "comportamento": "profile_field",
    "vida": "profile_field",
}


@dataclass(frozen=True)
class PropostaCriada:
    id: str
    fact_key: str
    rotulo: str
    valor_atual: float | None
    valor_proposto: float
    unidade: str | None
    natureza: str | None
    precisa_classificar_natureza: bool
    rationale: str
    expires_at: str | None

    def para_evento(self) -> dict[str, Any]:
        return {
            "id": self.id, "fact_key": self.fact_key, "rotulo": self.rotulo,
            "valor_atual": self.valor_atual, "valor_proposto": self.valor_proposto,
            "unidade": self.unidade, "natureza": self.natureza,
            "precisa_classificar_natureza": self.precisa_classificar_natureza,
            "rationale": self.rationale, "expires_at": self.expires_at,
        }


class PropostaRecusada(RuntimeError):
    """O banco recusou — e o motivo é informação, não erro a esconder.

    Recusa esperada e frequente: variação abaixo do limiar (C38d), teto semanal de cards
    (C39c), teto de pendentes do escopo (C38g), fato governado por outra fonte (C38b).
    Nenhuma delas derruba o turno: o agente segue a conversa sem o card.
    """


async def _run_de_turno(conn: AsyncConnection, *, conversation_id: str, scope_id: str) -> str:
    cur = await conn.execute(
        "insert into context.extraction_runs (conversation_id, scope_id, kind, status) "
        "values (%s, %s, 'turno', 'running') returning id::text",
        (conversation_id, scope_id))
    return (await cur.fetchone())[0]


async def _sinal(conn: AsyncConnection, *, run_id: str, scope_id: str, user_id: str,
                 kind: str, resumo: str, confianca: float, message_ids: list[str]) -> str:
    cur = await conn.execute(
        "insert into context.signals (extraction_run_id, scope_id, user_id, kind, summary, "
        "                             confidence, evidence_message_ids, payload) "
        "values (%s, %s, %s, %s::context.signal_kind, %s, %s, %s::uuid[], %s) returning id::text",
        (run_id, scope_id, user_id, kind, resumo, confianca, message_ids,
         Jsonb({"origem": "tool contexto.verificar_mudanca"})))
    return (await cur.fetchone())[0]


SIGNAL_KIND_POR_FAMILIA = {
    "fluxo": "mudanca_renda",
    "protecao": "evento_de_vida",
    "estoque": "nova_divida",
    "destino": "novo_objetivo",
    "comportamento": "outro",
    "vida": "evento_de_vida",
}


async def propor_do_turno(
    conn: AsyncConnection,
    *,
    scope_id: str,
    user_id: str,
    conversation_id: str,
    message_ids: list[str],
    saida_tool: dict[str, Any],
    confianca: float = 0.9,
) -> PropostaCriada | None:
    """Grava a proposta a partir do output de `contexto.verificar_mudanca`.

    Devolve None quando não há o que propor (mudança imaterial, fato governado por outra
    fonte, natureza ainda indefinida) — o caso mais comum e o mais importante de acertar,
    porque é ele que impede o produto de virar cutucão.

    Levanta PropostaRecusada quando o banco recusou por governança; o turno segue.
    """
    if not saida_tool.get("pode_virar_proposta"):
        return None
    if not message_ids:
        return None   # sinal sem evidência não existe (gate da 21)

    fact_key = saida_tool["fact_key"]
    rotulo = saida_tool["rotulo"]
    natureza = saida_tool.get("natureza")
    valor_atual = saida_tool.get("valor_atual")
    valor_novo = saida_tool["valor_informado"]

    # já existe pendente idêntica? A pergunta antes do INSERT evita gastar um SAVEPOINT
    # no caminho mais provável — o cliente repetir o mesmo número na mesma conversa.
    cur = await conn.execute(
        "select id::text from context.change_proposals "
        "where scope_id = %s and fact_key = %s and status = 'proposta' "
        "  and proposal_hash = core.canonical_hash(%s)",
        (scope_id, fact_key, Jsonb({"amount": valor_novo})))
    if await cur.fetchone():
        return None

    # A família sai do catálogo, não do chamador: é ela que escolhe o `proposal_kind` e o
    # `signal_kind` do enum da 21, e deixar isso na mão de quem chama abriria espaço para
    # uma proposta de renda nascer classificada como objetivo.
    cur = await conn.execute(
        "select family::text from context.fact_definitions where fact_key = %s", (fact_key,))
    linha = await cur.fetchone()
    familia = linha[0] if linha else "vida"

    rationale = _rationale(rotulo, valor_atual, valor_novo, saida_tool.get("unidade"))
    kind = KIND_POR_FAMILIA.get(familia, "profile_field")
    signal_kind = SIGNAL_KIND_POR_FAMILIA.get(familia, "outro")

    try:
        async with conn.transaction():
            run_id = await _run_de_turno(conn, conversation_id=conversation_id, scope_id=scope_id)
            signal_id = await _sinal(
                conn, run_id=run_id, scope_id=scope_id, user_id=user_id, kind=signal_kind,
                resumo=f"{rotulo}: {valor_atual} → {valor_novo}", confianca=confianca,
                message_ids=message_ids)
            cur = await conn.execute(
                """insert into context.change_proposals
                     (signal_id, scope_id, user_id, kind, fact_key, nature, target_ref,
                      current_value, proposed_value, rationale)
                   values (%s, %s, %s, %s::context.proposal_kind, %s, %s::context.fact_nature, %s,
                           %s, %s, %s)
                   returning id::text, expires_at::text""",
                (signal_id, scope_id, user_id, kind, fact_key, natureza,
                 Jsonb({"table": "context.assertions", "fact_key": fact_key}),
                 Jsonb({"amount": valor_atual}) if valor_atual is not None else None,
                 Jsonb({"amount": valor_novo}), rationale))
            proposta_id, expires = await cur.fetchone()
            await conn.execute(
                "update context.extraction_runs set status = 'succeeded', signals_found = 1, "
                "finished_at = now() where id = %s", (run_id,))
    except psycopg.errors.UniqueViolation:
        return None                      # corrida com outro turno: a proposta já existe
    except psycopg.Error as e:
        raise PropostaRecusada(str(e).strip().splitlines()[0]) from e

    return PropostaCriada(
        id=proposta_id, fact_key=fact_key, rotulo=rotulo, valor_atual=valor_atual,
        valor_proposto=valor_novo, unidade=saida_tool.get("unidade"), natureza=natureza,
        precisa_classificar_natureza=bool(saida_tool.get("precisa_classificar_natureza")),
        rationale=rationale, expires_at=expires)


def _rationale(rotulo: str, atual: float | None, novo: float, unidade: str | None) -> str:
    """O texto que o cliente lê no card. Diagnóstico, nunca ordem (RCVM 19)."""
    sufixo = f" {unidade}" if unidade and unidade not in ("BRL", "fracao") else ""
    fmt = (lambda v: f"R$ {v:,.2f}".replace(",", "·").replace(".", ",").replace("·", ".")) \
        if unidade == "BRL" else (lambda v: f"{v:g}{sufixo}")
    if atual is None:
        return f"{rotulo} apareceu como {fmt(novo)} e ainda não constava no seu contexto."
    return f"{rotulo} apareceu como {fmt(novo)}, contra {fmt(atual)} registrado no seu contexto."
