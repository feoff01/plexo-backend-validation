"""14_rls_partitions.sql — (a) RLS habilitada e FORÇADA em toda tabela com scope_id.

Revision ID: 0014_rls_partitions
Revises: 0013_audit
Create Date: 2026-08-22

Executa sql/14_rls_partitions.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0014_rls_partitions"
down_revision = '0013_audit'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("14_rls_partitions.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0014_rls_partitions: base append-only — reverter = reaplicar do zero.")
