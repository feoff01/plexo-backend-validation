"""64_ibra_index_definition.sql — registra IBrA para universo auditável [FQ5.6].

Revision ID: 0064_ibra_index_definition
Revises: 0063_economatica_source
Create Date: 2026-10-02
"""
from sqlfile import run_sql_file

revision = "0064_ibra_index_definition"
down_revision = "0063_economatica_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("64_ibra_index_definition.sql")


def downgrade() -> None:
    raise NotImplementedError("0064: definição de índice de mercado; reaplicar banco do zero.")
