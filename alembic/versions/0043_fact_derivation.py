"""43_fact_derivation.sql — F15: janela operável do motor + pergunta no catálogo.

Revision ID: 0043_fact_derivation
Revises: 0042_supersede_on_user_confirm
Create Date: 2026-08-29

Executa sql/43_fact_derivation.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0043_fact_derivation"
down_revision = "0042_supersede_on_user_confirm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("43_fact_derivation.sql")


def downgrade() -> None:
    raise NotImplementedError("0043_fact_derivation: base append-only — reverter = reaplicar do zero.")
