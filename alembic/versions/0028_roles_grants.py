"""28_roles_grants.sql — Papéis de aplicação (NOLOGIN) e privilégios.

Revision ID: 0028_roles_grants
Revises: 0027_decisions
Create Date: 2026-08-22

Executa sql/28_roles_grants.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0028_roles_grants"
down_revision = '0027_decisions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("28_roles_grants.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0028_roles_grants: base append-only — reverter = reaplicar do zero.")
