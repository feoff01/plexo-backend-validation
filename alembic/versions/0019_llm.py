"""19_llm.sql — A camada de LLM como objeto de domínio: prompts versionados, cada chamada

Revision ID: 0019_llm
Revises: 0018_tools
Create Date: 2026-08-22

Executa sql/19_llm.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0019_llm"
down_revision = '0018_tools'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("19_llm.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0019_llm: base append-only — reverter = reaplicar do zero.")
