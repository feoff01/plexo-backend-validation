"""46_insumos_da_lacuna.sql — F16: a correção da 44, agora também na fórmula.

Revision ID: 0046_insumos_da_lacuna
Revises: 0045_perfil_client_facing
Create Date: 2026-08-29

Executa sql/46_insumos_da_lacuna.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0046_insumos_da_lacuna"
down_revision = "0045_perfil_client_facing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("46_insumos_da_lacuna.sql")


def downgrade() -> None:
    raise NotImplementedError("0046: base append-only — reverter = reaplicar do zero.")
