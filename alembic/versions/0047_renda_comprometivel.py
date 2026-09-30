"""47_renda_comprometivel.sql — F16: o piso da renda, e margem para o elo mais fraco.

Revision ID: 0047_renda_comprometivel
Revises: 0046_insumos_da_lacuna
Create Date: 2026-08-29
"""
from sqlfile import run_sql_file

revision = "0047_renda_comprometivel"
down_revision = "0046_insumos_da_lacuna"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("47_renda_comprometivel.sql")


def downgrade() -> None:
    raise NotImplementedError("0047: base append-only — reverter = reaplicar do zero.")
