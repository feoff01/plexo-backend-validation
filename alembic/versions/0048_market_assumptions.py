"""48_market_assumptions.sql — F17: premissas de mercado versionadas e a projeção completa.

Revision ID: 0048_market_assumptions
Revises: 0047_renda_comprometivel
Create Date: 2026-08-29
"""
from sqlfile import run_sql_file

revision = "0048_market_assumptions"
down_revision = "0047_renda_comprometivel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("48_market_assumptions.sql")


def downgrade() -> None:
    raise NotImplementedError("0048: base append-only — reverter = reaplicar do zero.")
