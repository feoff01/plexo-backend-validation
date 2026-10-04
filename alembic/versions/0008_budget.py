"""08_budget.sql — Orçamento: fluxos de caixa, taxa de poupança, dívidas, reserva.

Revision ID: 0008_budget
Revises: 0007_planning
Create Date: 2026-08-22

Executa sql/08_budget.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0008_budget"
down_revision = '0007_planning'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("08_budget.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0008_budget: base append-only — reverter = reaplicar do zero.")
