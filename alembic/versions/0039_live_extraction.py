"""39_live_extraction.sql — F14b: proposta de contexto durante a conversa.

Revision ID: 0039_live_extraction
Revises: 0038_fact_catalog
Create Date: 2026-08-29

Executa sql/39_live_extraction.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0039_live_extraction"
down_revision = "0038_fact_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("39_live_extraction.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 24 schemas do projeto e reaplique.
    raise NotImplementedError("0039_live_extraction: base append-only — reverter = reaplicar do zero.")
