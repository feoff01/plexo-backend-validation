"""34_docs.sql — F13a: camada documental (comunicados oficiais como evidência `documentary`).

Revision ID: 0034_docs
Revises: 0033_identity_sessions
Create Date: 2026-08-27

Executa sql/34_docs.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0034_docs"
down_revision = "0033_identity_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("34_docs.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 24 schemas do projeto e reaplique.
    raise NotImplementedError("0034_docs: base append-only — reverter = reaplicar do zero.")
