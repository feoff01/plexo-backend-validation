"""27_decisions.sql — O que foi apresentado ao cliente, QUANDO, POR QUÊ e COM BASE EM QUÊ.

Revision ID: 0027_decisions
Revises: 0026_preferences
Create Date: 2026-08-22

Executa sql/27_decisions.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0027_decisions"
down_revision = '0026_preferences'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("27_decisions.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0027_decisions: base append-only — reverter = reaplicar do zero.")
