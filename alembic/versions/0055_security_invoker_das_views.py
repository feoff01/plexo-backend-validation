"""55_security_invoker_das_views.sql — restaura security_invoker em duas views reescritas.

Revision ID: 0055_security_invoker_das_views
Revises: 0054_raio_x_da_carteira
Create Date: 2026-08-30
"""
from sqlfile import run_sql_file

revision = "0055_security_invoker_das_views"
down_revision = "0054_raio_x_da_carteira"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("55_security_invoker_das_views.sql")


def downgrade() -> None:
    raise NotImplementedError("0055: base append-only — reverter = reaplicar do zero.")
