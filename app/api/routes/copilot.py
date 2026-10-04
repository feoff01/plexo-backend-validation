"""POST /copilot/turns — o turno do Copiloto, em SSE (padrão) ou JSON (?stream=false)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agents import eventos as ev
from app.agents.turn import TurnoCopiloto, TurnoInput
from app.api import sse
from app.api.deps import Identidade, identidade

router = APIRouter()


class TurnoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: str = ""
    agent_code: str | None = None
    chip_id: str | None = None
    conversation_id: str | None = None
    mode: Literal["standard", "research"] = "standard"


def _turno(request: Request) -> TurnoCopiloto:
    estado = request.app.state
    return TurnoCopiloto(db=estado.db, llm=estado.llm, policies=estado.policies,
                         enfileirar_analise=getattr(estado, "enfileirar_analise", None),
                         streaming=getattr(getattr(estado, "settings", None), "llm_stream", True))


@router.post("/copilot/turns")
async def copilot_turns(body: TurnoBody, request: Request,
                        stream: bool = Query(default=True),
                        ident: Identidade = Depends(identidade)):
    turno = _turno(request)
    entrada = TurnoInput(texto=body.texto, user_id=ident.user_id, scope_id=ident.scope_id,
                         agent_code=body.agent_code, chip_id=body.chip_id,
                         conversation_id=body.conversation_id, mode=body.mode)
    if stream:
        async def gerar():
            async for evento in turno.executar(entrada):
                yield sse.formatar(evento)
        return StreamingResponse(gerar(), media_type=sse.MEDIA_TYPE, headers=sse.HEADERS)

    eventos = [e async for e in turno.executar(entrada)]
    ultimo = eventos[-1] if eventos else None
    corpo = {"eventos": [{"nome": e.nome, **e.to_dict()} for e in eventos]}
    status = 200
    if isinstance(ultimo, ev.Done):
        corpo.update(conversation_id=ultimo.conversation_id, message_id=ultimo.message_id)
    elif isinstance(ultimo, ev.Paywall):
        status = 402
    elif isinstance(ultimo, ev.Erro):
        status = 503 if ultimo.tipo == "prompt_nao_aprovado" else 422
    return JSONResponse(corpo, status_code=status)
