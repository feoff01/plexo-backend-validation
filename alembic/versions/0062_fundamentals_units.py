"""62_fundamentals_units.sql — unidade explícita para fundamentos [FQ5].

Revision ID: 0062_fundamentals_units
Revises: 0061_acervo_de_mercado
Create Date: 2026-09-30
"""
from sqlfile import run_sql_file

revision = "0062_fundamentals_units"
down_revision = "0061_acervo_de_mercado"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("62_fundamentals_units.sql")


def downgrade() -> None:
    raise NotImplementedError("0062: contrato de unidade de fundamentos — reverter = reaplicar do zero.")
