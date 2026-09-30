"""Atualização interativa dos gráficos persistidos na conversa."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.agents.blocos import blocos_de
from app.api.deps import Identidade, identidade
from app.tools.executor import ToolParamsInvalid, executar_tool

router = APIRouter()


class HistoricoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1, max_length=24)
    benchmark: str = Field(default="BOVA11", min_length=1, max_length=24)
    periodo: Literal["1m", "3m", "1a", "5a", "tudo"] = "1a"
    data_referencia: date | None = None


@router.post("/charts/history")
async def historico(body: HistoricoBody, request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        cur = await conn.execute("select id::text from agents.conversations where id = %s", (body.conversation_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        try:
            resultado = await executar_tool(
                conn, "dados.historico_comparado",
                {"ticker": body.ticker, "benchmark": body.benchmark, "periodo": body.periodo,
                 "data_referencia": body.data_referencia},
                scope_id=ident.scope_id, conversation_id=body.conversation_id,
                cutoff_date=body.data_referencia)
        except ToolParamsInvalid as exc:
            raise HTTPException(status_code=422, detail=exc.erros) from exc
        payload = resultado.output.model_dump(mode="json")
        blocos = blocos_de("dados.historico_comparado", payload, execution_id=resultado.execution_id)
        return {"bloco": blocos[0] if blocos else None, "execution_id": resultado.execution_id,
                "cache_hit": resultado.cache_hit, "avisos": payload["evidencia"]["avisos"]}
