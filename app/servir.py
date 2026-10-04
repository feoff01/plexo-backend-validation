"""Sobe a API com um event loop compatível com o psycopg async no Windows.

`uvicorn app.main:app` cria um ProactorEventLoop no Windows e o psycopg recusa ("cannot use the
ProactorEventLoop") — os pools nunca conectam e toda rota devolve 500. Este lançador constrói o loop
Selector à mão e entrega ao uvicorn com loop="none". Em Linux/macOS o comando clássico continua valendo.

Uso (de plexo-backend/): .venv\\Scripts\\python.exe -m app.servir [--host 127.0.0.1] [--port 8000] [--reload]
"""
from __future__ import annotations

import argparse
import asyncio
import selectors
import sys

import uvicorn


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="API Plexo (uvicorn com loop Selector)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="recarrega a cada mudança (só dev; usa o supervisor do uvicorn)")
    args = ap.parse_args(argv)

    if args.reload:
        # o supervisor de reload do uvicorn relança o processo filho, que passa por este mesmo módulo
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=True, loop="asyncio",
                    reload_dirs=["app", "prompts"])
        return

    config = uvicorn.Config("app.main:app", host=args.host, port=args.port, loop="none")
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
