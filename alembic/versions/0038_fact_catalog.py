"""38_fact_catalog.sql — F14a: catálogo de fatos do Contexto Pessoal.

Revision ID: 0038_fact_catalog
Revises: 0037_focus_base_calculo
Create Date: 2026-08-29

Executa sql/38_fact_catalog.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0038_fact_catalog"
down_revision = "0037_focus_base_calculo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("38_fact_catalog.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 24 schemas do projeto e reaplique.
    raise NotImplementedError("0038_fact_catalog: base append-only — reverter = reaplicar do zero.")
