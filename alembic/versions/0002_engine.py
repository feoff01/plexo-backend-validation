"""02_engine.sql — A espinha dorsal de auditabilidade. Nada derivado existe sem um run.

Revision ID: 0002_engine
Revises: 0001_identity
Create Date: 2026-08-22

Executa sql/02_engine.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0002_engine"
down_revision = '0001_identity'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("02_engine.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0002_engine: base append-only — reverter = reaplicar do zero.")
