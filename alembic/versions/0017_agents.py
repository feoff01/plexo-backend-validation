"""17_agents.sql — Núcleo conversacional dos agentes: Analista IA, Assessor IA, Educador

Revision ID: 0017_agents
Revises: 0015_taxonomia
Create Date: 2026-08-22

Executa sql/17_agents.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0017_agents"
down_revision = '0015_taxonomia'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("17_agents.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0017_agents: base append-only — reverter = reaplicar do zero.")
