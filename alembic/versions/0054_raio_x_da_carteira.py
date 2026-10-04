"""54_raio_x_da_carteira.sql — F19: a taxonomia de findings ganha produtor, e o banco cobra.

Revision ID: 0054_raio_x_da_carteira
Revises: 0053_reconciliacao_da_carteira
Create Date: 2026-08-30
"""
from sqlfile import run_sql_file

revision = "0054_raio_x_da_carteira"
down_revision = "0053_reconciliacao_da_carteira"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("54_raio_x_da_carteira.sql")


def downgrade() -> None:
    raise NotImplementedError("0054: base append-only — reverter = reaplicar do zero.")
