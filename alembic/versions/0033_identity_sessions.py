"""33_identity_sessions.sql — F7: sessões opacas de autenticação, tentativas de login, membership e autenticar_sessao.

Revision ID: 0033_identity_sessions
Revises: 0032_analysis_dag_gates
Create Date: 2026-08-25

Executa sql/33_identity_sessions.sql (fonte da verdade) sem o BEGIN/COMMIT externo.
"""
from sqlfile import run_sql_file

revision = "0033_identity_sessions"
down_revision = "0032_analysis_dag_gates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("33_identity_sessions.sql")


def downgrade() -> None:
    # Append-only por desenho (mesma razão do ledger): não há downgrade parcial
    # testado. Para voltar atrás, derrube os 23 schemas do projeto e reaplique.
    raise NotImplementedError("0033_identity_sessions: base append-only — reverter = reaplicar do zero.")
