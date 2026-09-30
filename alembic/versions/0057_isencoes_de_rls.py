"""57_isencoes_de_rls_declaradas.sql — a isenção de RLS vira dado declarado, não silêncio.

Revision ID: 0057_isencoes_de_rls
Revises: 0056_rls_particoes_e_filhas
Create Date: 2026-08-30
"""
from sqlfile import run_sql_file

revision = "0057_isencoes_de_rls"
down_revision = "0056_rls_particoes_e_filhas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("57_isencoes_de_rls_declaradas.sql")


def downgrade() -> None:
    raise NotImplementedError("0057: base append-only — reverter = reaplicar do zero.")
