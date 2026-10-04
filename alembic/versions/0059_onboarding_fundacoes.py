"""59_onboarding_fundacoes.sql — fundações do onboarding obrigatório [F21a].

Revision ID: 0059_onboarding_fundacoes
Revises: 0058_canario_do_card
Create Date: 2026-08-31
"""
from sqlfile import run_sql_file

revision = "0059_onboarding_fundacoes"
down_revision = "0058_canario_do_card"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("59_onboarding_fundacoes.sql")


def downgrade() -> None:
    raise NotImplementedError("0059: base append-only — reverter = reaplicar do zero.")
