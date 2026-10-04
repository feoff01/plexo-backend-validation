"""58_canario_do_card.sql — canário do card ao vivo + rótulo do extrator [F20].

Revision ID: 0058_canario_do_card
Revises: 0057_isencoes_de_rls
Create Date: 2026-08-31
"""
from sqlfile import run_sql_file

revision = "0058_canario_do_card"
down_revision = "0057_isencoes_de_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("58_canario_do_card.sql")


def downgrade() -> None:
    raise NotImplementedError("0058: base append-only — reverter = reaplicar do zero.")
