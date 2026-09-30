"""09_content.sql — Sinais (5 partes), Cartas, notificações e aprovações de compliance.

Revision ID: 0009_content
Revises: 0008_budget
Create Date: 2026-08-22

Executa sql/09_content.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0009_content"
down_revision = '0008_budget'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("09_content.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0009_content: base append-only — reverter = reaplicar do zero.")
