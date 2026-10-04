"""42_supersede_on_user_confirm.sql — F14: confirmação do cliente aposenta as irmãs.

Revision ID: 0042_supersede_on_user_confirm
Revises: 0041_score_premises
Create Date: 2026-08-29

Executa sql/42_supersede_on_user_confirm.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0042_supersede_on_user_confirm"
down_revision = "0041_score_premises"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("42_supersede_on_user_confirm.sql")


def downgrade() -> None:
    raise NotImplementedError("0042: base append-only — reverter = reaplicar do zero.")
