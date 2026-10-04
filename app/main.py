"""FastAPI do backend de agentes.

`criar_app(db, llm, policies)` aceita injeção (testes: SingleConnectionDatabase + FakeLLM) — nesse
caso o estado é montado na construção (o ASGITransport de teste não roda lifespan). Sem argumentos,
o lifespan monta o modo produção: PooledDatabase (papéis plexo_app/plexo_service), DeepSeek e
PolicyStore. Rodar: `uvicorn app.main:app --reload` (de plexo-backend/).
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (analyses, auth, carteira, catalogo, charts, conversations, copilot,
                            health, onboarding, perfil, proposals)
from app.config.policies import PolicyStore
from app.config.settings import get_settings
from app.tools import carregar_tools

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def criar_app(db=None, llm=None, policies=None, settings=None) -> FastAPI:
    carregar_tools()
    injetado = db is not None
    settings = settings or get_settings()   # CORS e cookie precisam das settings já na construção

    @asynccontextmanager
    async def lifespan(aplicacao: FastAPI):
        proprio_db = None
        if not injetado:
            from app.db.database import PooledDatabase
            from app.llm.deepseek import DeepSeekClient
            proprio_db = await PooledDatabase(settings).open()
            aplicacao.state.db = proprio_db
            aplicacao.state.llm = DeepSeekClient(settings)
            aplicacao.state.policies = PolicyStore(proprio_db)
            aplicacao.state.enfileirar_analise = None
            if settings.redis_url is not None:      # F6: análise research vai para o worker Arq
                from arq import create_pool

                from app.jobs.worker import redis_settings_de
                pool = await create_pool(redis_settings_de(settings))

                async def enfileirar_analise(analysis_id: str) -> None:
                    await pool.enqueue_job("analisar", analysis_id, _job_id=f"analise:{analysis_id}")
                aplicacao.state.enfileirar_analise = enfileirar_analise
        try:
            yield
        finally:
            if proprio_db is not None:
                await proprio_db.close()

    aplicacao = FastAPI(title="Plexo — Copiloto (agentes)", lifespan=lifespan)
    aplicacao.state.settings = settings
    # F7: o frontend (outra origem) chama a API com cookie → origens explícitas + credenciais.
    # F21c: PUT entrou pelos passos do onboarding (/onboarding/passos/{passo}) — sem ele o
    # preflight devolvia 400 e o wizard morria em silêncio no navegador (o pytest não pega:
    # ASGITransport não faz preflight; foi a captura de tela que acusou).
    aplicacao.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
                             allow_methods=["GET", "POST", "PUT", "OPTIONS"],
                             allow_headers=["Content-Type", "X-Plexo-User-Id", "X-Plexo-Scope-Id"])
    if injetado:
        aplicacao.state.db = db
        aplicacao.state.llm = llm
        aplicacao.state.policies = policies or PolicyStore(db)
        aplicacao.state.enfileirar_analise = None
    aplicacao.include_router(auth.router)
    aplicacao.include_router(copilot.router)
    aplicacao.include_router(conversations.router)
    aplicacao.include_router(catalogo.router)
    aplicacao.include_router(charts.router)
    aplicacao.include_router(proposals.router)
    aplicacao.include_router(onboarding.router)
    aplicacao.include_router(perfil.router)
    aplicacao.include_router(carteira.router)
    aplicacao.include_router(analyses.router)
    aplicacao.include_router(health.router)
    return aplicacao


# instância padrão para `uvicorn app.main:app` (produção)
app = criar_app()
