"""44_fidelidade_do_perfil.sql — F15: duas correções de fidelidade achadas ao rodar o motor.

Revision ID: 0044_fidelidade_do_perfil
Revises: 0043_fact_derivation
Create Date: 2026-08-29

Executa sql/44_fidelidade_do_perfil.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0044_fidelidade_do_perfil"
down_revision = "0043_fact_derivation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("44_fidelidade_do_perfil.sql")


def downgrade() -> None:
    raise NotImplementedError("0044: base append-only — reverter = reaplicar do zero.")
