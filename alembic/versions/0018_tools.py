"""18_tools.sql — Registro dos "códigos prontos" — o coração do fluxo desenhado:

Revision ID: 0018_tools
Revises: 0017_agents
Create Date: 2026-08-22

Executa sql/18_tools.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0018_tools"
down_revision = '0017_agents'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("18_tools.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0018_tools: base append-only — reverter = reaplicar do zero.")
