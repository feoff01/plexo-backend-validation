"""22_assertions.sql — A CAMADA EPISTÊMICA. Estende o schema `context` (21) com a memória do que

Revision ID: 0022_assertions
Revises: 0021_context
Create Date: 2026-08-22

Executa sql/22_assertions.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0022_assertions"
down_revision = '0021_context'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("22_assertions.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0022_assertions: base append-only — reverter = reaplicar do zero.")
