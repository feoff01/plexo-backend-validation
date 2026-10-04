"""Confirmação/rejeição de item do intake — sob app_session do próprio usuário.

Confirmar é o ato epistêmico: só aqui o que a IA propôs vira fato (asserção
source='onboarding', C22a em dois atos) ou estrutura (planning.goals, budget.debts,
estate.assets — pelos MESMOS escritores do wizard, app/onboarding/estrutura.py).
A RLS decide o que existe (item invisível → None → 404 na rota); os gates C60a/C60b
do banco são a palavra final sobre a transição.
"""
from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

from app.onboarding import escrita, estrutura
from app.onboarding.erros import PassoConflito


async def _carregar(conn: AsyncConnection, item_id: str):
    cur = await conn.execute(
        "select id::text, kind::text, fact_key, payload, status::text "
        "  from context.intake_items where id = %s", (item_id,))
    return await cur.fetchone()


async def confirmar_item(conn: AsyncConnection, *, item_id: str, scope_id: str,
                         user_id: str) -> dict[str, Any] | None:
    row = await _carregar(conn, item_id)
    if row is None:
        return None
    _, kind, fact_key, payload, status = row
    if status != "proposto":
        raise PassoConflito(f"item já está '{status}' — a decisão sobre um item é única")

    extra: dict[str, Any] = {}
    if kind == "fato":
        extra["assertion_id"] = await escrita.confirmar_fato(
            conn, scope_id=scope_id, user_id=user_id, fact_key=fact_key,
            valor=payload.get("valor"), source="onboarding",
            confianca=escrita.CONFIANCA_ONBOARDING)
    elif kind == "objetivo":
        extra["goal_id"] = await estrutura.criar_objetivo(
            conn, scope_id=scope_id, user_id=user_id, nome=payload["nome"],
            tipo=payload.get("tipo", "outro"), valor=payload["valor"],
            prazo_meses=payload["prazo_meses"], prioridade=payload.get("prioridade", 3))
    elif kind == "divida":
        extra["debt_id"] = await estrutura.criar_divida(
            conn, scope_id=scope_id, tipo=payload.get("tipo", "outro"), saldo=payload["saldo"],
            taxa_aa_percentual=payload.get("taxa_aa_percentual", 0),
            parcela=payload.get("parcela", 0),
            parcelas_restantes=payload.get("parcelas_restantes"))
    else:  # bem
        extra["asset_id"] = await estrutura.criar_bem(
            conn, scope_id=scope_id, tipo=payload.get("tipo", "outro"),
            rotulo=payload["rotulo"], valor=payload["valor"])

    await conn.execute(
        "update context.intake_items set status = 'confirmado', confirmed_at = now(), "
        "confirmed_by = %s where id = %s", (user_id, item_id))
    return {"id": item_id, "status": "confirmado", **extra}


async def rejeitar_item(conn: AsyncConnection, *, item_id: str) -> dict[str, Any] | None:
    row = await _carregar(conn, item_id)
    if row is None:
        return None
    status = row[4]
    if status != "proposto":
        raise PassoConflito(f"item já está '{status}' — a decisão sobre um item é única")
    await conn.execute(
        "update context.intake_items set status = 'rejeitado', rejected_at = now() "
        " where id = %s", (item_id,))
    return {"id": item_id, "status": "rejeitado"}
