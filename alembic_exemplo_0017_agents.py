"""Camada de agentes: núcleo conversacional (agents).

Revision ID: 0017_agents
Revises: 0016_ROOT_ANTERIOR  # ajustar para a última revision do conjunto 00-16
Create Date: 2026-08-19

Convenção: o SQL vive em migrations/sql/ e a revision só o executa.
Uma revision por arquivo SQL, na ordem 17 -> 21.
"""
from pathlib import Path

from alembic import op

revision = "0017_agents"
down_revision = "0016_ROOT_ANTERIOR"  # <-- AJUSTAR
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "17_agents.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    # Downgrade destrutivo e explícito — sem meias-medidas silenciosas.
    op.execute("DROP SCHEMA IF EXISTS agents CASCADE;")
    op.execute("DELETE FROM engine.policy_versions WHERE code = 'AGENT_QUOTAS';")
