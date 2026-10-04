"""53_reconciliacao_da_carteira.sql — F19: o agregado não pode mentir sobre o detalhe.

Revision ID: 0053_reconciliacao_da_carteira
Revises: 0052_extracao_incremental
Create Date: 2026-08-30
"""
from sqlfile import run_sql_file

revision = "0053_reconciliacao_da_carteira"
down_revision = "0052_extracao_incremental"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("53_reconciliacao_da_carteira.sql")


def downgrade() -> None:
    raise NotImplementedError("0053: base append-only — reverter = reaplicar do zero.")
