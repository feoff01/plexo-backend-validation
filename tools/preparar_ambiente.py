#!/usr/bin/env python3
"""Deixa um banco RECÉM-CRIADO pronto para os testes — o checklist do ESTADO §5, automatizado.

Para quando existe schema mas não existe estado: o Postgres do CI (`services: postgres`) e o dev
logo depois de `db_runner.py reset`. Faz, nesta ordem:

  1. `seed dev` e `seed persona`            — usuários, escopos, orçamento, conteúdo, persona
  2. `tools sync`                            — catálogo de tools espelhado no banco
  3. aprova a lista EXPLÍCITA de policies client-facing — os gates 29a recusam execução com
     policy `draft`; o resto continua em rascunho (ver POLICIES_CLIENT_FACING abaixo)
  4. `prompts push` + `approve` de cada .j2  — o gate de 19 recusa conversa com prompt não aprovado

Não é caminho de produção: aprovar prompt e policy é ato de compliance com revisor identificado, e
aqui o revisor é o usuário de operação do seed. Em produção isso se faz na mão, um a um, olhando o
diff — é essa a diferença entre um banco descartável e o banco que atende cliente.

Uso (de plexo-backend/):  python tools/preparar_ambiente.py [--por <uuid|e-mail>]
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":                                  # psycopg async exige SelectorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config.settings import Settings                      # noqa: E402
from app.db.database import PooledDatabase                    # noqa: E402
from app.db.repos import identity as identity_repo            # noqa: E402
from app.db.repos import policies as policies_repo            # noqa: E402
from app.db.repos import prompts as prompts_repo              # noqa: E402

OPERACAO_PADRAO = "synaptainvest@gmail.com"
PROMPTS_DIR = ROOT / "prompts"
SEEDS = ("dev.sql", "persona.sql")


async def _aplicar_seeds(db) -> None:
    for nome in SEEDS:
        sql = (ROOT / "seeds" / nome).read_text(encoding="utf-8")
        async with db.service_session() as conn:
            await conn.execute(sql)
        print(f"  seed aplicado: {nome}")


async def _sincronizar_tools(db, git_sha: str) -> None:
    from app.tools import carregar_tools
    from app.tools.registry import specs_registradas
    from app.tools.sync import sincronizar

    carregar_tools()
    async with db.service_session() as conn:
        rel = await sincronizar(conn, specs_registradas(), git_sha=git_sha, desativar_ausentes=True)
    print(f"  tools: {len(rel.criadas)} criadas, {len(rel.inalteradas)} inalteradas, "
          f"{len(rel.versionadas)} versionadas")


# Lista EXPLÍCITA, do ESTADO §5: as premissas client-facing que os gates 29a exigem aprovadas para
# as tools executarem. NÃO se aprova tudo — aprovação é ato de compliance, e "aprovar todo rascunho"
# desliga gate em silêncio: `DRIFT_BANDS` precisa continuar em draft, senão o T1 (run client-facing
# com política não aprovada) passa a ser aceito e a suíte SQL fica verde sem provar nada.
POLICIES_CLIENT_FACING = (
    "FOUNDATION_THRESHOLDS", "INCOME_HAIRCUT", "PREMISSAS_FALLBACK", "PLANEJAMENTO_PREMISSAS",
    "PRODUTO_REFERENCIAS", "EDUCACAO_PARAMS", "EDUCACAO_EXEMPLOS", "ANALISE_PARAMS",
    "ANALISE_RESEARCH", "AGENT_CONVERSATIONS", "LLM_BUDGETS", "AGENT_QUOTAS",
    "CONTEXTO_DOCUMENTAL", "EXPECTATIVAS_PARAMS",
    # [F19] Sem ela aprovada, o gate 29a derruba `planejamento.pontos_de_atencao` em toda
    # conversa: a tool declara a política porque os limiares SÃO a premissa do que ela
    # afirma. O invariante "rascunho não vira número do cliente" continua provado pelo
    # T125b, que usa uma política própria da fixture justamente para não depender do
    # estado desta aqui.
    "RAIOX_LIMIARES",
)


async def _aprovar_policies(db, uid: str) -> None:
    aprovadas = []
    async with db.service_session() as conn:
        for code in POLICIES_CLIENT_FACING:
            cur = await conn.execute(
                "select 1 from engine.policy_versions "
                " where code = %s and effective_to is null and compliance_status = 'draft'", (code,))
            if await cur.fetchone():
                await policies_repo.approve_current(conn, code, approved_by=uid)
                aprovadas.append(code)
    print(f"  policies aprovadas: {len(aprovadas)} de {len(POLICIES_CLIENT_FACING)} previstas "
          f"(o resto segue em rascunho, de propósito)")


async def _aprovar_prompts(db, uid: str) -> None:
    aprovados = 0
    for caminho in sorted(PROMPTS_DIR.glob("*.j2")):
        code = caminho.stem
        template = caminho.read_text(encoding="utf-8")
        async with db.service_session() as conn:
            row = await prompts_repo.push(conn, code, template, created_by=uid)
            await prompts_repo.approve(conn, code, version=row.version, approved_by=uid)
        aprovados += 1
    print(f"  prompts aprovados: {aprovados}")


async def principal(por: str) -> None:
    import subprocess

    git_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
    db = await PooledDatabase(Settings()).open()
    try:
        await _aplicar_seeds(db)
        async with db.service_session() as conn:
            uid = await identity_repo.resolver_user_id(conn, por)
        if uid is None:
            raise SystemExit(f"usuário de operação {por!r} não existe — o seed dev deveria tê-lo criado")
        await _sincronizar_tools(db, git_sha)
        await _aprovar_policies(db, uid)
        await _aprovar_prompts(db, uid)
    finally:
        await db.close()
    print("ambiente pronto.")


if __name__ == "__main__":
    argv = sys.argv[1:]
    por = argv[argv.index("--por") + 1] if "--por" in argv else OPERACAO_PADRAO
    asyncio.run(principal(por))
