"""29_tool_gates.sql — Gates de execução de tools: políticas aprovadas (client-facing) e plano mínimo.

Revision ID: 0029_tool_gates
Revises: 0028_roles_grants
Create Date: 2026-08-23

Executa sql/29_tool_gates.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0029_tool_gates"
down_revision = "0028_roles_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("29_tool_gates.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0029_tool_gates: base append-only — reverter = reaplicar do zero.")
