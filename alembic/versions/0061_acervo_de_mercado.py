"""61_acervo_de_mercado.sql — calendário, setor, índices, curva, fundamentos e preço ajustado [F22].

Revision ID: 0061_acervo_de_mercado
Revises: 0060_intake_do_onboarding
Create Date: 2026-09-09
"""
from sqlfile import run_sql_file

revision = "0061_acervo_de_mercado"
down_revision = "0060_intake_do_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("61_acervo_de_mercado.sql")


def downgrade() -> None:
    raise NotImplementedError("0061: base append-only — reverter = reaplicar do zero.")
