"""04_market.sql — Dados de mercado: instrumentos, preços D-1 (particionado), índices, FX,

Revision ID: 0004_market
Revises: 0003_billing
Create Date: 2026-08-22

Executa sql/04_market.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0004_market"
down_revision = '0003_billing'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("04_market.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0004_market: base append-only — reverter = reaplicar do zero.")
