"""
Fixtures dos testes Python do backend.

Estratégia (decidida em 2026-08-23): banco de DEV real da Aiven, UMA conexão de administrador por
teste com transação externa aberta; cada "sessão" do app (app_session / service_session) vira um
SAVEPOINT com SET LOCAL ROLE plexo_app|plexo_service + GUCs — exatamente o que a produção faz, só
que aninhado. No fim do teste, ROLLBACK total: zero resíduo, inclusive nas tabelas append-only
(messages, model_calls, tool_executions) que nem o serviço consegue limpar.

O administrador (avnadmin) tem BYPASSRLS — por isso NENHUM teste de isolamento roda sem SET ROLE.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

if sys.platform == "win32":  # psycopg async exige o SelectorEventLoop no Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# F7: os testes das fases anteriores autenticam por header X-Plexo-*; em produção o default é
# desligado (auth_headers_dev=False). A variável de ambiente vence o .env no pydantic-settings.
os.environ.setdefault("AUTH_HEADERS_DEV", "true")

from app.config.settings import Settings  # noqa: E402
from app.db.database import SingleConnectionDatabase  # noqa: E402
from app.db.repos import prompts as prompts_repo  # noqa: E402

ASSESSOR_PROMPT = "agent.assessor.system"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest_asyncio.fixture
async def db(settings):
    """Banco de teste: uma conexão, transação externa, rollback no fim."""
    async with SingleConnectionDatabase.open(settings) as database:
        yield database


class HistoricalIngestionConnection:
    """Setup opt-in: datas explícitas na criação e única finalização real do lote.

    Não congela o relógio, altera loaders, atualiza lote terminal ou substitui ingestão/audit.
    SQL temporal diferente do contrato conhecido falha, exigindo revisão desta fixture.
    """

    _OPEN = (
        "insert into market.ingestion_batches (source_code, dataset, reference_date, file_hash) "
        "values (%s, %s, %s, %s) returning id::text"
    )
    _CLOSE = (
        "update market.ingestion_batches set status = %s, finished_at = clock_timestamp(), rows_ingested = %s, "
        "error_detail = %s, reference_date = coalesce(%s, reference_date) where id = %s"
    )

    def __init__(self, conn, *, started_at: datetime, finished_at: datetime):
        for stamp in (started_at, finished_at):
            if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
                raise ValueError("fixture de ingestão exige timestamps UTC explícitos")
        if started_at > finished_at:
            raise ValueError("fixture: started_at deve ser <= finished_at")
        self._conn = conn
        self.started_at = started_at
        self.finished_at = finished_at

    def __getattr__(self, name):
        return getattr(self._conn, name)

    async def execute(self, query, params=None, **kwargs):
        if isinstance(query, str) and query.startswith("insert into market.ingestion_batches "):
            if query != self._OPEN:
                raise AssertionError("SQL de abertura mudou; revisar fixture temporal")
            query = query.replace("reference_date, file_hash)", "reference_date, file_hash, started_at)")
            query = query.replace("values (%s, %s, %s, %s)", "values (%s, %s, %s, %s, %s)")
            params = (*params, self.started_at)
        elif isinstance(query, str) and query.startswith("update market.ingestion_batches set status = "):
            if query != self._CLOSE:
                raise AssertionError("SQL de finalização mudou; revisar fixture temporal")
            query = query.replace("finished_at = clock_timestamp()", "finished_at = %s")
            params = (params[0], self.finished_at, *params[1:])
        return await self._conn.execute(query, params, **kwargs)


@pytest.fixture
def historical_ingestion_connection():
    """Factory restrita aos testes que declaram disponibilidade histórica; sem autouse."""
    return HistoricalIngestionConnection


@pytest_asyncio.fixture
async def prompt_assessor_draft(db):
    """Estado conhecido, independente do banco de dev: o Assessor aponta para um rascunho [PENDENTE]
    vigente (versão devolvida). Tudo dentro da transação do teste — o banco não muda."""
    async with db.service_session() as conn:
        return await prompts_repo.reabrir_rascunho(conn, ASSESSOR_PROMPT, "[PENDENTE — rascunho de teste] {{ contexto_escopo }}")


@dataclass(frozen=True)
class Escopos:
    u1: str
    s1: str
    u2: str
    s2: str


TEMPLATE_MINIMO = "Prompt de teste aprovado. Contexto: {{ contexto_escopo }}"


async def _tornar_escopo_canario(conn, scope_id: str) -> None:
    """F20 (gate C58, migration 58): card ao vivo só nasce para escopo na allowlist
    `escopos_canario_card_ao_vivo` de `CONTEXT_FACT_CATALOG` — chave ausente ou escopo
    fora dela é fail-closed. A allowlist semeada pela migration 58 só tem os escopos
    fixos de dev/personas/demonstração; a fixture `escopos` cria um `scope_id` novo
    (uuid4) a cada teste, então nenhuma allowlist estática cobre os testes daqui.

    `abrir_conversa` simula abrir uma conversa real, e o contrato da F14 (anterior ao
    F20) é que ela pode gerar card ao vivo — por isso o próprio setup do teste garante
    o canário, no mesmo padrão de versionamento que `test_f20_canario.py` usa
    explicitamente em `_nova_versao_da_policy`: encerra a versão vigente e publica uma
    nova com o payload herdado + o escopo na allowlist. `clock_timestamp()` (não
    `now()`) evita colidir com o CHECK effective_to > effective_from quando mais de uma
    versão nasce na mesma transação do teste."""
    cur = await conn.execute(
        "select payload from engine.policy_versions "
        "where code = 'CONTEXT_FACT_CATALOG' and effective_to is null")
    linha = await cur.fetchone()
    payload = dict(linha[0]) if linha and linha[0] else {}
    allowlist = list(payload.get("escopos_canario_card_ao_vivo") or [])
    if scope_id in allowlist:
        return
    payload["escopos_canario_card_ao_vivo"] = allowlist + [scope_id]
    await conn.execute(
        "update engine.policy_versions set effective_to = clock_timestamp() "
        "where code = 'CONTEXT_FACT_CATALOG' and effective_to is null")
    await conn.execute(
        "insert into engine.policy_versions "
        "  (code, version, payload, compliance_status, effective_from) "
        "select 'CONTEXT_FACT_CATALOG', coalesce(max(version), 0) + 1, "
        "       %s::jsonb, 'draft', clock_timestamp() "
        "  from engine.policy_versions where code = 'CONTEXT_FACT_CATALOG'",
        (json.dumps(payload),))


async def abrir_conversa(db, escopos: "Escopos", *, agente: str = "assessor", plano: str = "free") -> str:
    """Aprova (dentro da transação) o prompt do agente e abre uma conversa no plano dado."""
    code = f"agent.{agente}.system"
    async with db.service_session() as conn:
        await prompts_repo.reabrir_rascunho(conn, code, TEMPLATE_MINIMO)
        atual = await prompts_repo.get_current(conn, code)
        await prompts_repo.approve(conn, code, version=atual.version, approved_by=escopos.u1)
        await _tornar_escopo_canario(conn, escopos.s1)
        cur = await conn.execute(
            "insert into agents.conversations (scope_id, user_id, agent_code, plan_code_at_start) "
            "values (%s, %s, %s::agents.agent_code, %s::billing.plan_code) returning id::text",
            (escopos.s1, escopos.u1, agente, plano))
        return (await cur.fetchone())[0]


@pytest_asyncio.fixture
async def escopos(db) -> Escopos:
    """Dois usuários, dois escopos pessoais — criados como serviço dentro da transação do teste."""
    u1, u2, s1, s2 = (str(uuid.uuid4()) for _ in range(4))
    async with db.service_session() as conn:
        await conn.execute(
            """INSERT INTO identity.users (id, email, full_name, status)
               VALUES (%s, %s, 'Teste Um', 'active'), (%s, %s, 'Teste Dois', 'active')""",
            (u1, f"t1-{u1[:8]}@teste.local", u2, f"t2-{u2[:8]}@teste.local"),
        )
        await conn.execute(
            """INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
               VALUES (%s, 'personal', 'S1', %s), (%s, 'personal', 'S2', %s)""",
            (s1, u1, s2, u2),
        )
    return Escopos(u1=u1, s1=s1, u2=u2, s2=s2)
