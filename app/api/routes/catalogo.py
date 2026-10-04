"""Catálogo que a tela do Copiloto precisa antes do primeiro turno: agentes visíveis e chips.

Chips são CONFIG (app/config/chips.yaml) — aqui só se filtra pelos agentes ativos e visíveis no
banco, para que desativar um agente apague os atalhos dele sem tocar no YAML.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.agents import conversations as convs
from app.agents.perguntas import proximas
from app.agents.router import chips_lista
from app.api.deps import Identidade, identidade

router = APIRouter()


async def _visiveis(request: Request, ident: Identidade) -> list[dict]:
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        return await convs.agentes_visiveis(conn)


@router.get("/agents")
async def agentes(request: Request, ident: Identidade = Depends(identidade)):
    return {"agentes": await _visiveis(request, ident)}


@router.get("/chips")
async def chips(request: Request, agente: str | None = Query(default=None),
                ident: Identidade = Depends(identidade)):
    visiveis = {a["code"] for a in await _visiveis(request, ident)}
    if agente is not None and agente not in visiveis:
        raise HTTPException(status_code=422, detail="agente desconhecido ou indisponível")
    itens = [c for c in chips_lista() if c.agente in visiveis and (agente is None or c.agente == agente)]
    saida = [{"id": c.id, "rotulo": c.rotulo, "agente": c.agente, "texto": c.texto, "modo": c.modo}
             for c in itens]

    # F15: os chips do YAML são a base EDITORIAL; na frente deles entram as perguntas que mais
    # destravam diagnóstico para ESTE escopo. O dado que falta vira a próxima conversa — é a
    # mecânica de onboarding que a D29 pede (progresso mensurável, sem formulário).
    if "assessor" in visiveis and agente in (None, "assessor"):
        db = request.app.state.db
        try:
            async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
                perguntas = await proximas(conn, ident.scope_id)
            # `modo` é o modo do TURNO (standard | research), não a origem do chip:
            # pergunta de contexto é sempre uma conversa normal com o Assessor.
            saida = [{**p.para_chip(), "modo": "standard"} for p in perguntas] + saida
        except Exception:  # pragma: no cover — sem perfil calculado, a tela cai nos chips fixos
            pass
    return {"chips": saida}
