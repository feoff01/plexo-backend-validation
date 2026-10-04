"""60_intake_do_onboarding.sql — intake do onboarding: texto/arquivo/áudio → IA → confirmação [F21b].

Revision ID: 0060_intake_do_onboarding
Revises: 0059_onboarding_fundacoes
Create Date: 2026-08-31
"""
from sqlfile import run_sql_file

revision = "0060_intake_do_onboarding"
down_revision = "0059_onboarding_fundacoes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("60_intake_do_onboarding.sql")


def downgrade() -> None:
    raise NotImplementedError("0060: base append-only — reverter = reaplicar do zero.")
