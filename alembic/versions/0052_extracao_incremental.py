"""52_extracao_incremental.sql — F18: conversa reaberta volta a ser lida pela extração.

Revision ID: 0052_extracao_incremental
Revises: 0051_orcamento_da_sintese
Create Date: 2026-08-30
"""
from sqlfile import run_sql_file

revision = "0052_extracao_incremental"
down_revision = "0051_orcamento_da_sintese"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("52_extracao_incremental.sql")


def downgrade() -> None:
    raise NotImplementedError("0052: base append-only — reverter = reaplicar do zero.")
