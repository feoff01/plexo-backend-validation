"""Perfil financeiro do cliente — o que a tela lê depois que o motor roda.

Devolve o perfil COMO ELE DEVE SER LIDO, e não como um número só: o gate da Fundação acima
de tudo, um score por família, o elo mais fraco entre as críticas, e — o que quase todo
produto esconde — a lista do que NÃO foi possível medir, com o nome do dado que falta.

Não há endpoint de "score geral" de propósito. Média ponderada permitiria que uma falha
crítica fosse escondida por força em outra família.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import Identidade, identidade
from app.context.catalogo import catalogo, cobertura
from app.engine.perfil import perfil_atual

router = APIRouter()


@router.get("/perfil")
async def ler_perfil(request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        perfil = await perfil_atual(conn, ident.scope_id)
        cob = await cobertura(conn, ident.scope_id)
    return {**perfil, "cobertura": cob}


@router.get("/perfil/catalogo")
async def ler_catalogo(request: Request, familia: str | None = None,
                       ident: Identidade = Depends(identidade)):
    """O vocabulário fechado do que a plataforma sabe registrar sobre o cliente."""
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        definicoes = await catalogo(conn, family=familia)
        cob = await cobertura(conn, ident.scope_id)
    return {
        "fatos": [{"fact_key": d.fact_key, "rotulo": d.display_name, "familia": d.family,
                   "unidade": d.unit, "tipo": d.value_type,
                   "fonte_que_manda": d.fonte_que_manda,
                   "atualizavel_por_conversa": d.allows_conversation_update,
                   "meia_vida_dias": d.half_life_days}
                  for d in definicoes],
        "cobertura": cob,
    }
