"""15_taxonomia.sql — (a) Seed das POLÍTICAS versionadas — todas nascem DRAFT (C6: o primeiro

Revision ID: 0015_taxonomia
Revises: 0014_rls_partitions
Create Date: 2026-08-22

Executa sql/15_taxonomia.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0015_taxonomia"
down_revision = '0014_rls_partitions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("15_taxonomia.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0015_taxonomia: base append-only — reverter = reaplicar do zero.")
