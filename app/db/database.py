"""Acesso ao banco por PAPEL, com o contrato de sessão de 14_rls_partitions.sql.

Duas implementações com a mesma interface:
- PooledDatabase — produção/CLI: um pool por papel; cada sessão é uma transação real.
- SingleConnectionDatabase — testes: uma conexão, transação externa nunca comitada; cada sessão
  é um SAVEPOINT (psycopg aninha `transaction()` automaticamente). Zero resíduo.

Em ambas, dentro da transação: `SET LOCAL ROLE <papel>` (quando o login é administrador — dev)
e `set_config('app.user_id'|'app.scope_id'|'app.role', ..., true)`. Assim RLS e
core.is_service() valem em dev exatamente como em produção (avnadmin tem BYPASSRLS; sem
SET ROLE nada seria provado). Erros do banco saem traduzidos (app.db.errors).

Nunca `SET` de sessão: a conexão volta ao pool limpa.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol

import psycopg
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from app.config.settings import Settings
from app.db.errors import translate


class Database(Protocol):
    def app_session(self, user_id: str, scope_id: str, role: str = "user"): ...
    def service_session(self): ...


async def _configurar(conn: AsyncConnection, settings: Settings, papel: str,
                      user_id: str | None, scope_id: str | None, role: str) -> None:
    if settings.db_set_role:
        await conn.execute("RESET ROLE")
        # nome validado por regex em settings.papel_sql — não vem de input de usuário
        await conn.execute(f"SET LOCAL ROLE {settings.papel_sql(papel)}")
    await conn.execute(
        "select set_config('app.user_id', %s, true), set_config('app.scope_id', %s, true), "
        "set_config('app.role', %s, true)",
        (user_id or "", scope_id or "", role),
    )


class PooledDatabase:
    def __init__(self, settings: Settings):
        self._settings = settings
        # F9: o Aiven derruba conexões ociosas ("server closed the connection unexpectedly") e a API ficava
        # servindo conexões mortas até reiniciar. `check` testa a conexão antes de entregá-la; `max_idle`
        # recicla as paradas antes de o servidor as fechar.
        opcoes = dict(open=False, min_size=settings.db_pool_min, max_size=settings.db_pool_max,
                      kwargs={"autocommit": False}, check=AsyncConnectionPool.check_connection,
                      max_idle=settings.db_pool_max_idle_s, reconnect_timeout=30)
        self._pool_app = AsyncConnectionPool(settings.pg_conninfo("app"), **opcoes)
        self._pool_service = AsyncConnectionPool(settings.pg_conninfo("service"), **opcoes)

    async def open(self) -> "PooledDatabase":
        await self._pool_app.open()
        await self._pool_service.open()
        return self

    async def close(self) -> None:
        await self._pool_app.close()
        await self._pool_service.close()

    async def __aenter__(self):
        return await self.open()

    async def __aexit__(self, *exc):
        await self.close()

    @asynccontextmanager
    async def _sessao(self, pool: AsyncConnectionPool, papel: str, user_id, scope_id, role) -> AsyncIterator[AsyncConnection]:
        async with pool.connection() as conn:
            try:
                async with conn.transaction():
                    await _configurar(conn, self._settings, papel, user_id, scope_id, role)
                    yield conn
            except psycopg.Error as e:
                raise translate(e) from e

    def app_session(self, user_id: str, scope_id: str, role: str = "user"):
        return self._sessao(self._pool_app, "app", user_id, scope_id, role)

    def service_session(self):
        return self._sessao(self._pool_service, "service", None, None, "service")


class SingleConnectionDatabase:
    """Banco de teste: tudo numa conexão de administrador, dentro de uma transação que nunca comita."""

    def __init__(self, conn: AsyncConnection, settings: Settings):
        self._conn = conn
        self._settings = settings

    @classmethod
    @asynccontextmanager
    async def open(cls, settings: Settings) -> AsyncIterator["SingleConnectionDatabase"]:
        async with await AsyncConnection.connect(settings.pg_conninfo("admin"), autocommit=False) as conn:
            db = cls(conn, settings)
            async with conn.transaction():
                yield db
                raise psycopg.Rollback()  # nunca comita: o banco de dev fica como estava

    @asynccontextmanager
    async def _sessao(self, papel: str, user_id, scope_id, role) -> AsyncIterator[AsyncConnection]:
        try:
            async with self._conn.transaction():  # aninhado → SAVEPOINT
                await _configurar(self._conn, self._settings, papel, user_id, scope_id, role)
                yield self._conn
        except psycopg.Error as e:
            raise translate(e) from e

    def app_session(self, user_id: str, scope_id: str, role: str = "user"):
        return self._sessao("app", user_id, scope_id, role)

    def service_session(self):
        return self._sessao("service", None, None, "service")

    @property
    def conexao_admin(self) -> AsyncConnection:
        """Para fixtures que precisam de BYPASSRLS (limpeza/arranjo). Nunca em código de produção."""
        return self._conn
