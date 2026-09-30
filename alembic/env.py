"""Alembic env — Synapta/Plexo.

Lê DATABASE_URL de plexo-backend/.env (nunca do alembic.ini, nunca impressa),
normaliza para postgresql+psycopg:// com sslmode=require e roda cada revision na
própria transação. Não há metadata/autogenerate: o SQL é a fonte da verdade
(RCVM 19 — inspecionável em forma não compilada); cada revision só executa o
arquivo sql/NN_*.sql correspondente via sqlfile.run_sql_file.
"""
import re
import urllib.parse
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import create_engine

HERE = Path(__file__).resolve().parent   # sqlfile entra no sys.path via prepend_sys_path (alembic.ini)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def database_url() -> str:
    url = dotenv_values(HERE.parent / ".env").get("DATABASE_URL") or ""
    if not url:
        raise SystemExit("DATABASE_URL ausente em plexo-backend/.env")
    url = re.sub(r"^postgres(ql)?(\+[a-z0-9]+)?://", "postgresql+psycopg://", url)
    parts = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(parts.query))
    q.setdefault("sslmode", "require")
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))

def run_migrations_offline() -> None:
    # Modo offline (--sql) gera o script; útil para inspeção, não para aplicar.
    context.configure(url=database_url(), literal_binds=True,
                      transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    engine = create_engine(database_url(), future=True)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
