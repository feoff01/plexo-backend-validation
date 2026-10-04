"""32_analysis_dag_gates.sql — Pipeline do Analista research: gates por análise, DAG/replan limitados pelo banco, relatório fundamentado, RLS nas filhas.

Revision ID: 0032_analysis_dag_gates
Revises: 0031_market_immutability
Create Date: 2026-08-25

Executa sql/32_analysis_dag_gates.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0032_analysis_dag_gates"
down_revision = "0031_market_immutability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("32_analysis_dag_gates.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0032_analysis_dag_gates: base append-only — reverter = reaplicar do zero.")
