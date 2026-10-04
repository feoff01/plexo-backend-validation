"""63_economatica_source.sql — registra fonte auxiliar Economatica [FQ5.6A].

Revision ID: 0063_economatica_source
Revises: 0062_fundamentals_units
Create Date: 2026-10-01
"""
from sqlfile import run_sql_file

revision = "0063_economatica_source"
down_revision = "0062_fundamentals_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("63_economatica_source.sql")


def downgrade() -> None:
    raise NotImplementedError("0063: source provenance auxiliar; reaplicar banco do zero.")
