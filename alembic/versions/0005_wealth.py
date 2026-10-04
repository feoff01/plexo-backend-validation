"""05_wealth.sql — Patrimônio: contas, Open Finance, SNAPSHOTS APPEND-ONLY, transações.

Revision ID: 0005_wealth
Revises: 0004_market
Create Date: 2026-08-22

Executa sql/05_wealth.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0005_wealth"
down_revision = '0004_market'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("05_wealth.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0005_wealth: base append-only — reverter = reaplicar do zero.")
