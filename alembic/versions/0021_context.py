"""21_context.sql — O quarto agente: Contexto Pessoal. Lê conversas ENCERRADAS, extrai sinais

Revision ID: 0021_context
Revises: 0020_analysis
Create Date: 2026-08-22

Executa sql/21_context.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0021_context"
down_revision = '0020_analysis'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("21_context.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0021_context: base append-only — reverter = reaplicar do zero.")
