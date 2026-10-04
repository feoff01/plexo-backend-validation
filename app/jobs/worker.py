"""Worker Arq (Redis gerenciado) — só fiação: cria db/llm/policies no startup e agenda as tasks.

Rodar: `python -m app.cli worker` (exige REDIS_URL no .env; aceita rediss:// TLS). Sem Redis, o mesmo
ciclo roda uma vez com `python -m app.cli context run`. Os horários abaixo são operação (frequência
de varredura), não regra de negócio — os números de negócio estão nas policies lidas pelas tasks.
"""
from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.config.settings import Settings, get_settings
from app.jobs.tasks import (analisar, encerrar_inativas, expirar, extrair_conversa, ingerir_cotahist, ingerir_sgs,
                            processar_intake, varrer_analises_pendentes, varrer_analises_travadas,
                            varrer_encerradas, varrer_execucoes_travadas)


def redis_settings_de(settings: Settings) -> RedisSettings:
    if settings.redis_url is None:
        raise RuntimeError("REDIS_URL ausente no .env — o worker Arq precisa do Redis gerenciado "
                           "(sem ele, use `python -m app.cli context run`)")
    return RedisSettings.from_dsn(settings.redis_url.get_secret_value())


async def startup(ctx: dict[str, Any]) -> None:
    from app.config.policies import PolicyStore
    from app.db.database import PooledDatabase
    from app.llm.deepseek import DeepSeekClient
    from app.tools import carregar_tools

    carregar_tools()
    settings = get_settings()
    ctx["db"] = await PooledDatabase(settings).open()
    ctx["llm"] = DeepSeekClient(settings)
    ctx["policies"] = PolicyStore(ctx["db"])

    async def enfileirar(conversation_id: str) -> None:
        # _job_id = a conversa: enquanto o job estiver na fila/rodando, não duplica
        await ctx["redis"].enqueue_job("extrair_conversa", conversation_id, _job_id=f"extrair:{conversation_id}")

    ctx["enfileirar"] = enfileirar

    async def enfileirar_analise(analysis_id: str) -> None:
        await ctx["redis"].enqueue_job("analisar", analysis_id, _job_id=f"analise:{analysis_id}")

    ctx["enfileirar_analise"] = enfileirar_analise


async def shutdown(ctx: dict[str, Any]) -> None:
    db = ctx.get("db")
    if db is not None:
        await db.close()


class WorkerSettings:
    functions = [extrair_conversa, varrer_encerradas, encerrar_inativas, expirar, varrer_execucoes_travadas,
                 ingerir_sgs, ingerir_cotahist,
                 analisar, varrer_analises_pendentes, varrer_analises_travadas,
                 processar_intake]
    cron_jobs = [
        cron(encerrar_inativas, name="encerrar_inativas", minute={0, 10, 20, 30, 40, 50}, run_at_startup=True),
        cron(varrer_encerradas, name="varrer_encerradas", minute={2, 12, 22, 32, 42, 52}, run_at_startup=True),
        cron(varrer_execucoes_travadas, name="varrer_execucoes_travadas", minute={5, 35}),
        cron(expirar, name="expirar", hour=3, minute=15),
        # mercado (F5): D-1 — o SGS publica de manhã; o COTAHIST diário sai após o pregão
        cron(ingerir_sgs, name="ingerir_sgs", hour=6, minute=30),
        cron(ingerir_cotahist, name="ingerir_cotahist", weekday={0, 1, 2, 3, 4}, hour=7, minute=0),
        # análise research (F6): pega o que o turno enfileirou e não rodou; reabre o que travou
        cron(varrer_analises_pendentes, name="varrer_analises_pendentes", minute={4, 14, 24, 34, 44, 54}, run_at_startup=True),
        cron(varrer_analises_travadas, name="varrer_analises_travadas", minute={8, 38}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = 900       # F6: `analisar` (planner → DAG → relatório) é o job mais longo; as demais tasks levam segundos
