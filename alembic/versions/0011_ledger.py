"""11_ledger.sql — Ledger de Valor Realizado — a prova de que a Synapta se paga.

Revision ID: 0011_ledger
Revises: 0010_copilot
Create Date: 2026-08-22

Executa sql/11_ledger.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0011_ledger"
down_revision = '0010_copilot'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("11_ledger.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0011_ledger: base append-only — reverter = reaplicar do zero.")
