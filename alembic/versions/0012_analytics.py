"""12_analytics.sql — Este schema não é "nice to have". É o instrumento da prioridade nº 1 do negócio.

Revision ID: 0012_analytics
Revises: 0011_ledger
Create Date: 2026-08-22

Executa sql/12_analytics.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0012_analytics"
down_revision = '0011_ledger'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("12_analytics.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0012_analytics: base append-only — reverter = reaplicar do zero.")
