"""45_perfil_client_facing.sql — F15: o gate C40d também na leitura do perfil.

Revision ID: 0045_perfil_client_facing
Revises: 0044_fidelidade_do_perfil
Create Date: 2026-08-29

Executa sql/45_perfil_client_facing.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0045_perfil_client_facing"
down_revision = "0044_fidelidade_do_perfil"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("45_perfil_client_facing.sql")


def downgrade() -> None:
    raise NotImplementedError("0045: base append-only — reverter = reaplicar do zero.")
