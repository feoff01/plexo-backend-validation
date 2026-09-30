"""49_elegibilidade_calibrada.sql — F17: tolerância do p5, sem a qual a regra vetava sempre.

Revision ID: 0049_elegibilidade_calibrada
Revises: 0048_market_assumptions
Create Date: 2026-08-29
"""
from sqlfile import run_sql_file

revision = "0049_elegibilidade_calibrada"
down_revision = "0048_market_assumptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("49_elegibilidade_calibrada.sql")


def downgrade() -> None:
    raise NotImplementedError("0049: base append-only — reverter = reaplicar do zero.")
