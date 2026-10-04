"""50_probabilidade_no_destino.sql — F17: a chance de alcançar o objetivo entra no Destino.

Revision ID: 0050_probabilidade_no_destino
Revises: 0049_elegibilidade_calibrada
Create Date: 2026-08-29
"""
from sqlfile import run_sql_file

revision = "0050_probabilidade_no_destino"
down_revision = "0049_elegibilidade_calibrada"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("50_probabilidade_no_destino.sql")


def downgrade() -> None:
    raise NotImplementedError("0050: base append-only — reverter = reaplicar do zero.")
