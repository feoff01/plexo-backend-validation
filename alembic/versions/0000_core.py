"""00_core.sql — Fundação: extensões, schemas, domains financeiros e funções transversais.

Revision ID: 0000_core
Revises: None
Create Date: 2026-08-22

Executa sql/00_core.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0000_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("00_core.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0000_core: base append-only — reverter = reaplicar do zero.")
