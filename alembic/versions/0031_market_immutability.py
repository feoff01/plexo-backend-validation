"""31_market_immutability.sql — Séries de mercado append-only e válidas; lotes de ingestão imutáveis e idempotentes; 10 anos de partições.

Revision ID: 0031_market_immutability
Revises: 0030_content_education_gate
Create Date: 2026-08-24

Executa sql/31_market_immutability.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0031_market_immutability"
down_revision = "0030_content_education_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("31_market_immutability.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0031_market_immutability: base append-only — reverter = reaplicar do zero.")
