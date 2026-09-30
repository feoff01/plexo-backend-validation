"""Tradução dos erros que o BANCO levanta (ele é o executor das regras) para exceções de domínio.

O app nunca engole 23514 genericamente: cada regra conhecida vira um tipo, o resto sobe intacto.
As mensagens casadas aqui são as dos triggers em sql/17–28 (não alterar lá sem alterar aqui).
"""
from __future__ import annotations

import psycopg


class DbError(Exception):
    """Erro de banco já traduzido; `sqlstate` e `mensagem` preservados."""

    def __init__(self, mensagem: str, sqlstate: str | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.sqlstate = sqlstate


class QuotaExceeded(DbError):
    """AGENT_QUOTAS — pergunta excedente rejeitada na escrita (17_agents). Vira paywall (402)."""


class PromptNotApproved(DbError):
    """Gate de 19_llm: agente client-facing com prompt não aprovado por compliance (T15)."""


class FamilyNotAllowed(DbError):
    """Gate de 18_tools: agente invocando tool de família não permitida (T18)."""


class PermissionDenied(DbError):
    """42501 por privilégio — inclui as tabelas append-only, cujo UPDATE/DELETE foi REVOGADO dos papéis
    de aplicação em 28_roles_grants (padrão T10: trigger + privilégio)."""


class AppendOnlyViolation(PermissionDenied):
    """42501 levantado pelos TRIGGERS de imutabilidade (core.forbid_update_delete, freeze_*): a linha é
    append-only/finalizada. Subclasse de PermissionDenied — quem só precisa saber 'não pode mutar'
    captura a base."""


class PolicyGateViolation(DbError):
    """Gate de compliance (engine.runs_policy_gate / tools 29a): saída client-facing referenciando
    política não aprovada. O conserto é aprovar a política, nunca contornar o gate."""


class PlanGateViolation(DbError):
    """Gate de plano mínimo da tool (29b) — paywall, mesma família do erro de cota."""


class ConversationNotEnded(DbError):
    """Gate de 21_context (T22): o Contexto não processa conversa aberta — extraction_run recusado."""


class EvidenceInvalid(DbError):
    """Gates de evidência (21/22, T23): sinal/asserção apontando mensagem inexistente, de outra conversa
    ou de outro escopo. O LLM referencia por seq; a tradução seq→id é do extrator, o banco confere."""


class AssertionBornConfirmed(DbError):
    """C22a (22_assertions): asserção nasce 'declarado' ou 'inferido' — confirmação é ato posterior do usuário."""


class LikelihoodRule(DbError):
    """CHECK hypothesis_needs_likelihood: intenção/hipótese exigem likelihood; fato/preferência/opinião a proíbem."""


class SelfConfirmationOnly(DbError):
    """CHECK self_confirmation_only (T24b): só o próprio usuário confirma proposta/asserção do seu contexto."""


class SuitabilityRequired(DbError):
    """Regra-estrela (T24c/d): mudança de perfil de risco só é aplicada com suitability NOVO, do próprio usuário."""


class PolicyNotFound(LookupError):
    """engine.policy_versions sem versão vigente para o código pedido."""


class PromptNotApprovable(ValueError):
    """Aprovação recusada pela checagem da aplicação (PENDENTE, vocabulário, variáveis) — antes de tocar o banco."""


_MARCAS_APPEND_ONLY = ("append-only", "imutável", "imutavel", "é imutável", "já finalizad", "já finalizada")


def translate(exc: BaseException) -> BaseException:
    """Devolve a exceção de domínio correspondente, ou a original se não for um caso conhecido."""
    if not isinstance(exc, psycopg.Error):
        return exc
    code = exc.sqlstate or ""
    msg = (exc.diag.message_primary if exc.diag and exc.diag.message_primary else str(exc)) or ""
    low = msg.lower()
    constraint = (exc.diag.constraint_name if exc.diag else None) or ""
    if code == "23514":
        if constraint == "self_confirmation_only":
            return SelfConfirmationOnly(msg, code)
        if constraint == "hypothesis_needs_likelihood":
            return LikelihoodRule(msg, code)
        if constraint == "risk_apply_requires_suitability" or "suitability" in low:
            return SuitabilityRequired(msg, code)
        if "não processa conversa aberta" in low or "nao processa conversa aberta" in low:
            return ConversationNotEnded(msg, code)
        if "referencia mensagens inexistentes" in low:
            return EvidenceInvalid(msg, code)
        if low.startswith("asserção nasce") or low.startswith("assercao nasce"):
            return AssertionBornConfirmed(msg, code)
        if msg.startswith("Cota mensal"):
            return QuotaExceeded(msg, code)
        if "prompt não aprovado" in low or "prompt nao aprovado" in low:
            return PromptNotApproved(msg, code)
        if "não pode invocar tool da família" in low or "nao pode invocar tool da familia" in low:
            return FamilyNotAllowed(msg, code)
        if "por compliance" in low and ("não aprovada" in low or "nao aprovada" in low):
            return PolicyGateViolation(msg, code)
        if "exige plano mínimo" in low or "exige plano minimo" in low:
            return PlanGateViolation(msg, code)
        return exc
    if code == "42501":
        if any(m in low for m in _MARCAS_APPEND_ONLY):
            return AppendOnlyViolation(msg, code)
        return PermissionDenied(msg, code)
    return exc
