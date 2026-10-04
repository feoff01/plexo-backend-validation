"""25_estate.sql — Patrimônio ALÉM da carteira: imóvel, empresa, veículo, previdência fechada.

Revision ID: 0025_estate
Revises: 0024_income
Create Date: 2026-08-22

Executa sql/25_estate.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0025_estate"
down_revision = '0024_income'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("25_estate.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0025_estate: base append-only — reverter = reaplicar do zero.")
