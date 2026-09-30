"""Exceções de domínio do onboarding. Sem FastAPI aqui — a rota (app/api/routes/onboarding.py)
é quem traduz cada uma para o HTTPException certo."""
from __future__ import annotations


class DadoInvalido(ValueError):
    """422 — pré-validação (catálogo, resposta desconhecida, ônus sem dívida) recusou
    ANTES de bater no banco. O gate do banco (C38a/C59a) continua sendo o backstop."""


class PassoConflito(RuntimeError):
    """409 — o passo já foi preenchido (dívidas não se regravam) ou não pode ser pulado
    no estado atual da jornada."""
