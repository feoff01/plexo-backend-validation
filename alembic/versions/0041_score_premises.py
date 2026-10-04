"""41_score_premises.sql — F14c: premissas dos indicadores em CLIENT_SCORES v2.

Revision ID: 0041_score_premises
Revises: 0040_client_profile
Create Date: 2026-08-29

Executa sql/41_score_premises.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0041_score_premises"
down_revision = "0040_client_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("41_score_premises.sql")


def downgrade() -> None:
    raise NotImplementedError("0041_score_premises: base append-only — reverter = reaplicar do zero.")
