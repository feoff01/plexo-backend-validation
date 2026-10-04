"""30_content_education_gate.sql — Conteúdo educativo: view do aprovado+publicado, trilha obrigatória e texto imutável.

Revision ID: 0030_content_education_gate
Revises: 0029_tool_gates
Create Date: 2026-08-24

Executa sql/30_content_education_gate.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0030_content_education_gate"
down_revision = "0029_tool_gates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("30_content_education_gate.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0030_content_education_gate: base append-only — reverter = reaplicar do zero.")
