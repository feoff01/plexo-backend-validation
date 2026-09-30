"""56_rls_particoes_e_filhas.sql — fecha a RLS das partições, das filhas por FK e das internas.

Revision ID: 0056_rls_particoes_e_filhas
Revises: 0055_security_invoker_das_views
Create Date: 2026-08-30

NOTA: `alembic_version.version_num` é `varchar(32)`. O primeiro nome desta revision
(`0056_rls_das_particoes_e_das_filhas`, 35 caracteres) aplicava o SQL inteiro e só então
estourava no UPDATE da versão — revertendo tudo, com um erro que não menciona o limite.
Nome de revision tem teto de 32.
"""
from sqlfile import run_sql_file

revision = "0056_rls_particoes_e_filhas"
down_revision = "0055_security_invoker_das_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("56_rls_particoes_e_filhas.sql")


def downgrade() -> None:
    raise NotImplementedError("0056: base append-only — reverter = reaplicar do zero.")
