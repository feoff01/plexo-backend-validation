"""36_focus_source.sql — F13b: registra a fonte `bacen_focus` (omissão da 0035).

Revision ID: 0036_focus_source
Revises: 0035_market_expectations
Create Date: 2026-08-27

Executa sql/36_focus_source.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0036_focus_source"
down_revision = "0035_market_expectations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("36_focus_source.sql")


def downgrade() -> None:
    raise NotImplementedError("0036_focus_source: base append-only — reverter = reaplicar do zero.")
