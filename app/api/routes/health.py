from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    db = request.app.state.db
    async with db.service_session() as conn:
        cur = await conn.execute("select current_user, core.is_service()")
        papel, servico = await cur.fetchone()
    return {"ok": True, "papel_servico": papel, "is_service": servico}
