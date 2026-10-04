"""13_audit.sql — Log de auditoria — QUEM fez O QUÊ. (Não confundir com engine.runs, que

Revision ID: 0013_audit
Revises: 0012_analytics
Create Date: 2026-08-22

Executa sql/13_audit.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0013_audit"
down_revision = '0012_analytics'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("13_audit.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0013_audit: base append-only — reverter = reaplicar do zero.")
