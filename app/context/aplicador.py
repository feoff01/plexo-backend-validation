"""Aplicação da proposta confirmada — o passo que faltava para o contexto realmente mudar.

Até aqui, `/proposals/{id}/confirm` marcava a proposta como `confirmada` e **nada acontecia**:
a F3 deixou explícito que "nada é aplicado nesta fase". O cliente dizia "sim, pode atualizar"
e o contexto continuava igual. Este módulo fecha esse buraco.

O CAMINHO, e por que ele é longo de propósito:

    proposta confirmada
      └ nova asserção nasce 'declarado'            (C22a — nunca nasce confirmada)
      └ é confirmada pelo PRÓPRIO usuário          (C21/C22 — confirmed_by = user_id)
           └ supersessão respeita precedência      (C38c — upload não derruba open_finance)
      └ proposta → 'aplicada'                      (C39d — pontual não vira recorrente)
      └ audit.activity_log com a proveniência      (proposta → sinal → mensagens)
      └ indicadores e scores do dia são invalidados

Nenhum atalho: a asserção passa pelos mesmos gates de qualquer outra. O que a confirmação do
cliente compra não é bypass — é o direito de existir como fato confirmado.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)


class AplicacaoRecusada(RuntimeError):
    """O banco recusou a aplicação. A mensagem é a do gate — ela é a explicação ao cliente."""


class AplicacaoImpossivel(RuntimeError):
    """A proposta não é aplicável por desenho (perfil de risco exige refazer o suitability)."""


@dataclass(frozen=True)
class Aplicacao:
    proposta_id: str
    assertion_id: str
    fact_key: str
    valor_anterior: float | None
    valor_novo: float
    indicadores_invalidados: int


_SQL_PROPOSTA = """
select p.id::text, p.scope_id::text, p.user_id::text, p.status::text, p.kind::text,
       p.fact_key, p.nature::text, p.current_value, p.proposed_value, p.signal_id::text,
       s.evidence_message_ids, d.subject_kind::text, d.attribute, d.unit,
       d.is_recurring_by_nature, d.requires_nature_check
  from context.change_proposals p
  join context.signals s on s.id = p.signal_id
  left join context.fact_definitions d on d.fact_key = p.fact_key
 where p.id = %s
"""


async def aplicar(conn: AsyncConnection, proposta_id: str, *, user_id: str) -> Aplicacao:
    """Aplica uma proposta CONFIRMADA. Idempotente: já aplicada devolve o estado atual."""
    cur = await conn.execute(_SQL_PROPOSTA, (proposta_id,))
    row = await cur.fetchone()
    if row is None:
        raise AplicacaoRecusada(f"proposta {proposta_id} não existe")

    (pid, scope_id, dono_id, status, kind, fact_key, natureza, atual, proposto,
     signal_id, evidencias, subject_kind, attribute, unidade,
     recorrente_por_natureza, exige_natureza) = row

    if dono_id != user_id:
        # mesma regra do endpoint: quem confirma o próprio contexto é o próprio usuário
        raise AplicacaoRecusada("só o próprio usuário aplica mudança no contexto dele")
    if status == "aplicada":
        raise AplicacaoRecusada("proposta já aplicada")
    if status != "confirmada":
        raise AplicacaoRecusada(
            f"proposta está em '{status}': só proposta confirmada pelo cliente é aplicada")
    if kind == "suitability_risk_profile":
        # A regra-estrela da 21: perfil de risco é registro regulatório point-in-time.
        raise AplicacaoImpossivel(
            "mudança de perfil de risco exige refazer o questionário de suitability — "
            "inferência de conversa não altera perfil regulatório")
    if fact_key is None:
        raise AplicacaoImpossivel(
            "proposta sem fato catalogado: a aplicação automática só existe para o catálogo "
            "(migration 38). Esta precisa ser tratada na tela do contexto.")
    if exige_natureza and natureza is None:
        raise AplicacaoRecusada(
            "falta classificar se a mudança passou a valer ou foi de uma vez só")
    if recorrente_por_natureza and natureza == "pontual":
        raise AplicacaoRecusada(
            "a observação foi pontual e este fato é recorrente: um bônus não vira salário")

    valor_novo = _numero(proposto)
    if valor_novo is None:
        raise AplicacaoRecusada("proposta sem valor numérico legível")

    try:
        async with conn.transaction():
            cur = await conn.execute(
                """insert into context.assertions
                     (scope_id, user_id, fact_key, subject_kind, attribute, value, unit,
                      modality, status, confidence, source, source_ref, signal_id,
                      evidence_message_ids)
                   values (%s, %s, %s, %s::context.subject_kind, %s, %s, %s,
                           'fato', 'declarado', %s, 'conversa', %s, %s, %s::uuid[])
                   returning id::text""",
                (scope_id, user_id, fact_key, subject_kind, attribute, Jsonb(proposto), unidade,
                 1.0, Jsonb({"proposal_id": pid, "aplicada_por": "confirmacao_do_usuario"}),
                 signal_id, list(evidencias or [])))
            assertion_id = (await cur.fetchone())[0]

            # Confirmar é um SEGUNDO ato, com ator — e é ele que dispara a supersessão
            # consciente de precedência (C38c) e o gate de fonte (C38b).
            await conn.execute(
                "update context.assertions set status = 'confirmado', confirmed_at = now(), "
                "confirmed_by = %s, confirmed_via_proposal_id = %s where id = %s",
                (user_id, pid, assertion_id))

            await conn.execute(
                "update context.change_proposals set status = 'aplicada', applied_at = now() "
                "where id = %s", (pid,))

            await conn.execute(
                """insert into audit.activity_log
                     (actor_kind, actor_user_id, scope_id, action, object_kind, object_id, details)
                   values ('user', %s, %s, 'context.proposal.applied', 'proposal', %s, %s)""",
                (user_id, scope_id, pid,
                 Jsonb({"fact_key": fact_key, "assertion_id": assertion_id,
                        "signal_id": signal_id, "natureza": natureza,
                        "valor_anterior": _numero(atual), "valor_novo": valor_novo,
                        "evidence_message_ids": [str(e) for e in (evidencias or [])]})))

            invalidados = await invalidar_perfil(conn, scope_id, motivo=f"fato {fact_key} mudou")
    except psycopg.Error as e:
        raise AplicacaoRecusada(str(e).strip().splitlines()[0]) from e

    return Aplicacao(proposta_id=pid, assertion_id=assertion_id, fact_key=fact_key,
                     valor_anterior=_numero(atual), valor_novo=valor_novo,
                     indicadores_invalidados=invalidados)


async def registrar_recusa(conn: AsyncConnection, proposta_id: str, *, user_id: str,
                           motivo_codigo: str | None, nota: str | None) -> None:
    """Recusa também é informação: "não, foi bônus" diz que existe renda variável não recorrente.

    Guardar só `false` joga fora o fato que a recusa revelou — por isso o código do motivo
    entra em `rejection_reason_code` e o texto livre em `rejection_note`.
    """
    await conn.execute(
        "update context.change_proposals set status = 'rejeitada', rejected_at = now(), "
        "rejection_reason_code = %s, rejection_note = %s "
        "where id = %s and user_id = %s and status in ('proposta','confirmada')",
        (motivo_codigo, nota, proposta_id, user_id))
    await conn.execute(
        """insert into audit.activity_log
             (actor_kind, actor_user_id, scope_id, action, object_kind, object_id, details)
           select 'user', %s, scope_id, 'context.proposal.rejected', 'proposal', id,
                  %s from context.change_proposals where id = %s""",
        (user_id, Jsonb({"motivo": motivo_codigo, "nota": nota}), proposta_id))


async def classificar_natureza(conn: AsyncConnection, proposta_id: str, *, user_id: str,
                               natureza: str) -> None:
    """A resposta do card: "passou a ser recorrente" / "foi pontual" / "ainda não sei".

    A resposta é o rótulo de medição do canário (F20): trocar a natureza sem deixar
    trilha apagaria a comparação com `nature_do_extrator` (context.v_precisao_extrator).
    Por isso reclassificar audita, como a recusa já faz em `registrar_recusa`.
    """
    if natureza not in ("pontual", "recorrente", "incerto"):
        raise AplicacaoRecusada(f"natureza inválida: {natureza}")
    cur = await conn.execute(
        "select nature::text from context.change_proposals where id = %s", (proposta_id,))
    row = await cur.fetchone()
    natureza_anterior = row[0] if row else None

    await conn.execute(
        "update context.change_proposals set nature = %s::context.fact_nature "
        "where id = %s and user_id = %s and status = 'proposta'",
        (natureza, proposta_id, user_id))

    await conn.execute(
        """insert into audit.activity_log
             (actor_kind, actor_user_id, scope_id, action, object_kind, object_id, details)
           select 'user', %s, scope_id, 'context.proposal.nature_classified', 'proposal', id,
                  %s from context.change_proposals where id = %s""",
        (user_id, Jsonb({"natureza_anterior": natureza_anterior, "natureza_nova": natureza}),
         proposta_id))


async def invalidar_perfil(conn: AsyncConnection, scope_id: str, *, motivo: str) -> int:
    """Um fato mudou: indicador e score do dia deixam de valer.

    Apagar em vez de recalcular na hora é deliberado — o motor roda no job, com run
    próprio e proveniência. O que não pode acontecer é a tela mostrar um score de
    ontem como se fosse de hoje depois que o cliente corrigiu a renda.
    """
    cur = await conn.execute(
        "delete from diagnostics.client_indicators where scope_id = %s and as_of_date = current_date",
        (scope_id,))
    n = cur.rowcount or 0
    await conn.execute(
        "delete from diagnostics.client_scores where scope_id = %s and as_of_date = current_date",
        (scope_id,))
    log.info("perfil invalidado (scope=%s, motivo=%s, indicadores=%s)", scope_id, motivo, n)
    return n


def _numero(value: dict[str, Any] | None) -> float | None:
    from app.context.catalogo import numero_do_valor
    return numero_do_valor(value)
