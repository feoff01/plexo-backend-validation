"""37_focus_base_calculo.sql — F13b: `baseCalculo` entra na chave natural do Focus.

Revision ID: 0037_focus_base_calculo
Revises: 0036_focus_source
Create Date: 2026-08-27

Executa sql/37_focus_base_calculo.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0037_focus_base_calculo"
down_revision = "0036_focus_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("37_focus_base_calculo.sql")


def downgrade() -> None:
    raise NotImplementedError("0037_focus_base_calculo: base append-only — reverter = reaplicar do zero.")
