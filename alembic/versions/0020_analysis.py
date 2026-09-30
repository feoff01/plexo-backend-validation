"""20_analysis.sql — A profundidade exclusiva do Analista IA (Blueprint v2.1 §4, §8, §13.4, §23).

Revision ID: 0020_analysis
Revises: 0019_llm
Create Date: 2026-08-22

Executa sql/20_analysis.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0020_analysis"
down_revision = '0019_llm'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("20_analysis.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0020_analysis: base append-only — reverter = reaplicar do zero.")
