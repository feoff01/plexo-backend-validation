"""01_identity.sql — Usuários, ESCOPOS (decisão estrutural §4.12), perfil, suitability, LGPD.

Revision ID: 0001_identity
Revises: 0000_core
Create Date: 2026-08-22

Executa sql/01_identity.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0001_identity"
down_revision = '0000_core'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("01_identity.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0001_identity: base append-only — reverter = reaplicar do zero.")
