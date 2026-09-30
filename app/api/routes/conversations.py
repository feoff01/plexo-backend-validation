"""Conversas: leitura das mensagens (RLS decide o que existe) e encerramento explícito."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.agents import conversations as convs
from app.api.deps import Identidade, identidade

router = APIRouter()


@router.get("/conversations")
async def listar(request: Request, limit: int = Query(default=20, ge=1, le=100),
                 status: Literal["aberta", "encerrada", "processada"] | None = Query(default=None),
                 ident: Identidade = Depends(identidade)):
    """Histórico do escopo ativo (lateral da tela). O RLS decide o que existe."""
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        return {"conversas": await convs.listar_conversas(conn, limite=limit, status=status)}


@router.get("/conversations/{conversation_id}/messages")
async def mensagens(conversation_id: str, request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        cabecalho = await convs.cabecalho(conn, conversation_id)
        if cabecalho is None:                 # RLS: conversa de outro escopo não existe para este papel
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        return {"conversa": cabecalho, "mensagens": await convs.listar_mensagens(conn, conversation_id)}


@router.post("/conversations/{conversation_id}/close")
async def encerrar(conversation_id: str, request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        cur = await conn.execute("select status::text from agents.conversations where id = %s", (conversation_id,))
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        encerrou = await convs.encerrar(conn, conversation_id)
    return {"conversation_id": conversation_id, "status": "encerrada",
            "ja_estava_encerrada": not encerrou and row[0] != "aberta"}
