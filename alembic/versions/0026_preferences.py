"""26_preferences.sql — Restrições e preferências — o que NÃO pode ser sugerido a este cliente.

Revision ID: 0026_preferences
Revises: 0025_estate
Create Date: 2026-08-22

Executa sql/26_preferences.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0026_preferences"
down_revision = '0025_estate'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("26_preferences.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0026_preferences: base append-only — reverter = reaplicar do zero.")
