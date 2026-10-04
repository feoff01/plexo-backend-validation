"""Server-Sent Events: um evento do turno = um bloco `event:`/`data:`."""
from __future__ import annotations

import json

from app.agents.eventos import Evento

HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
MEDIA_TYPE = "text/event-stream"


def formatar(evento: Evento) -> str:
    payload = json.dumps(evento.to_dict(), ensure_ascii=False, default=str)
    return f"event: {evento.nome}\ndata: {payload}\n\n"
