"""51_orcamento_da_sintese.sql — F18: reserva de tokens para o turno conseguir redigir.

Revision ID: 0051_orcamento_da_sintese
Revises: 0050_probabilidade_no_destino
Create Date: 2026-08-30
"""
from sqlfile import run_sql_file

revision = "0051_orcamento_da_sintese"
down_revision = "0050_probabilidade_no_destino"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("51_orcamento_da_sintese.sql")


def downgrade() -> None:
    raise NotImplementedError("0051: base append-only — reverter = reaplicar do zero.")
