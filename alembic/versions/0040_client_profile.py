"""40_client_profile.sql — F14c: indicadores e scores do cliente (gates + famílias).

Revision ID: 0040_client_profile
Revises: 0039_live_extraction
Create Date: 2026-08-29

Executa sql/40_client_profile.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0040_client_profile"
down_revision = "0039_live_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("40_client_profile.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 24 schemas do projeto e reaplique.
    raise NotImplementedError("0040_client_profile: base append-only — reverter = reaplicar do zero.")
