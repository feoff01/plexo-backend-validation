"""07_planning.sql — Objetivos, Portfolio Builder, Carteiras Modelo, drift 5/25 e roteamento de aporte.

Revision ID: 0007_planning
Revises: 0006_diagnostics
Create Date: 2026-08-22

Executa sql/07_planning.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0007_planning"
down_revision = '0006_diagnostics'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("07_planning.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0007_planning: base append-only — reverter = reaplicar do zero.")
