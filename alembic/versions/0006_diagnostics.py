"""06_diagnostics.sql — Raio-X: Fundação, score, findings e ações.

Revision ID: 0006_diagnostics
Revises: 0005_wealth
Create Date: 2026-08-22

Executa sql/06_diagnostics.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0006_diagnostics"
down_revision = '0005_wealth'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("06_diagnostics.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0006_diagnostics: base append-only — reverter = reaplicar do zero.")
