"""35_market_expectations.sql — F13b: pesquisa Focus (BCB) como série de expectativas.

Revision ID: 0035_market_expectations
Revises: 0034_docs
Create Date: 2026-08-27

Executa sql/35_market_expectations.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0035_market_expectations"
down_revision = "0034_docs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("35_market_expectations.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial testado.
    raise NotImplementedError("0035_market_expectations: base append-only — reverter = reaplicar do zero.")
