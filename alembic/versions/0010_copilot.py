"""10_copilot.sql — Copiloto contextual: a interface de linguagem natural SOBRE os números do app.

Revision ID: 0010_copilot
Revises: 0009_content
Create Date: 2026-08-22

Executa sql/10_copilot.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0010_copilot"
down_revision = '0009_content'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("10_copilot.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0010_copilot: base append-only — reverter = reaplicar do zero.")
