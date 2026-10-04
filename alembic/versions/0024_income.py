"""24_income.sql — Renda destrinchada. Estende o schema `budget` (08).

Revision ID: 0024_income
Revises: 0023_household
Create Date: 2026-08-22

Executa sql/24_income.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0024_income"
down_revision = '0023_household'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("24_income.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0024_income: base append-only — reverter = reaplicar do zero.")
