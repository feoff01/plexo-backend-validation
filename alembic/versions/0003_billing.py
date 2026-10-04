"""03_billing.sql — Planos, entitlements (TIER_CONFIG como DADO — §16.8.2), assinaturas.

Revision ID: 0003_billing
Revises: 0002_engine
Create Date: 2026-08-22

Executa sql/03_billing.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0003_billing"
down_revision = '0002_engine'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("03_billing.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0003_billing: base append-only — reverter = reaplicar do zero.")
