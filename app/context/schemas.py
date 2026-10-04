"""Saída estruturada do extrator de contexto — Pydantic estrito + parse tolerante do JSON do LLM.

Primeira barreira (a segunda é o banco: gates de 21/22). Item individual inválido é DESCARTADO com
motivo, nunca derruba a extração inteira; o que sobra segue para o banco, que confere de novo.

Regras espelhadas do schema (não inventadas aqui):
- `status` de asserção só nasce 'declarado' | 'inferido' (C22a);
- `likelihood` é obrigatória em intencao/hipotese e proibida nas demais (CHECK hypothesis_needs_likelihood);
- `evidence_seqs` não vazio (signal_needs_evidence / conversation_needs_evidence);
- `value` é objeto JSON (CHECK value_is_object); `attribute` é slug.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SIGNAL_KINDS = ("mudanca_tolerancia_risco", "novo_objetivo", "mudanca_horizonte", "evento_de_vida",
                "mudanca_renda", "mudanca_despesa", "nova_divida", "mencao_aposentadoria",
                "mudanca_dependentes", "outro")
PROPOSAL_KINDS = ("suitability_risk_profile", "goal_create", "goal_update", "profile_field", "budget_field",
                  "outro", "assertion_confirm", "household_member", "income_source", "estate_asset",
                  "investment_constraint")
SUBJECT_KINDS = ("titular", "membro", "renda", "despesa", "patrimonio", "divida", "objetivo", "preferencia",
                 "contexto_vida", "mercado", "recomendacao_externa", "outro")
MODALITIES = ("fato", "intencao", "hipotese", "preferencia", "opiniao")
MODALIDADES_COM_LIKELIHOOD = {"intencao", "hipotese"}

_SLUG = r"^[a-z0-9][a-z0-9._-]*$"


class SignalOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: Literal[SIGNAL_KINDS]
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_seqs: list[int] = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class AssertionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # F15: chave do catálogo (migration 38). Sem ela a asserção fica fora de v_fact_operavel,
    # não vira indicador e o aplicador recusa a proposta correspondente — ou seja, o trabalho
    # do extrator se perde. A existência da chave é conferida contra o banco em `validar_itens`.
    fact_key: str | None = Field(default=None, pattern=_SLUG, max_length=120)
    subject_kind: Literal[SUBJECT_KINDS]
    attribute: str = Field(pattern=_SLUG, max_length=120)
    value: dict[str, Any]
    unit: str | None = None
    modality: Literal[MODALITIES]
    status: Literal["declarado", "inferido"]          # C22a — 'confirmado' aqui é item recusado
    likelihood: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_seqs: list[int] = Field(min_length=1)
    signal_index: int | None = None

    @model_validator(mode="after")
    def _likelihood_bicondicional(self) -> "AssertionOut":
        exige = self.modality in MODALIDADES_COM_LIKELIHOOD
        if exige and self.likelihood is None:
            raise ValueError(f"modality '{self.modality}' exige likelihood")
        if not exige and self.likelihood is not None:
            raise ValueError(f"modality '{self.modality}' não admite likelihood")
        return self


NATUREZAS = ("pontual", "recorrente", "incerto")


class ProposalOut(BaseModel):
    model_config = ConfigDict(extra="ignore")                 # 'status', 'applied_at' etc. do LLM são ignorados
    fact_key: str | None = Field(default=None, pattern=_SLUG, max_length=120)
    nature: Literal[NATUREZAS] | None = None
    signal_index: int
    kind: Literal[PROPOSAL_KINDS]
    target_ref: dict[str, Any]
    current_value: dict[str, Any] | None = None
    proposed_value: dict[str, Any]
    rationale: str = Field(min_length=1)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    signals: list[SignalOut] = Field(default_factory=list)
    assertions: list[AssertionOut] = Field(default_factory=list)
    proposals: list[ProposalOut] = Field(default_factory=list)


def parse_json_tolerante(texto: str) -> dict[str, Any] | None:
    """Objeto JSON do output do LLM, tolerante a texto/cerca de código ao redor. None se não houver."""
    bruto = (texto or "").strip()
    m = re.search(r"\{.*\}", bruto, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _motivo(err: ValidationError) -> str:
    partes = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e.get("loc", ()))
        recebido = e.get("input")
        sufixo = f" (recebido: {recebido!r})" if isinstance(recebido, (str, int, float, bool)) or recebido is None else ""
        partes.append((f"{loc}: {e.get('msg')}" if loc else str(e.get("msg"))) + sufixo)
    return "; ".join(partes)


def validar_itens(obj: dict[str, Any], chaves_validas: set[str] | None = None) -> tuple[ExtractionResult, list[dict[str, Any]]]:
    """Valida item a item. Devolve (resultado com os válidos, descartados=[{secao, indice, motivo, item}]).

    Os índices ORIGINAIS são preservados em `signal_index` via remapeamento: um sinal descartado faz
    as asserções/propostas que apontavam para ele serem descartadas também (evidência sem dono).

    `chaves_validas` é o catálogo vigente (migration 38). Quando informado, item com `fact_key` fora
    dele é DESCARTADO com motivo — vocabulário fechado é fechado também para o extrator, senão o
    catálogo vira sugestão e as juntas voltam a não fechar.
    """
    descartados: list[dict[str, Any]] = []
    sinais: list[SignalOut] = []
    mapa_sinal: dict[int, int] = {}                 # índice original → índice válido
    for i, bruto in enumerate(obj.get("signals") or []):
        try:
            mapa_sinal[i] = len(sinais)
            sinais.append(SignalOut.model_validate(bruto))
        except ValidationError as err:
            mapa_sinal.pop(i, None)
            descartados.append({"secao": "signals", "indice": i, "motivo": _motivo(err), "item": bruto})

    assercoes: list[AssertionOut] = []
    for i, bruto in enumerate(obj.get("assertions") or []):
        try:
            item = AssertionOut.model_validate(bruto)
        except ValidationError as err:
            descartados.append({"secao": "assertions", "indice": i, "motivo": _motivo(err), "item": bruto})
            continue
        if chaves_validas is not None and item.fact_key and item.fact_key not in chaves_validas:
            descartados.append({"secao": "assertions", "indice": i, "item": bruto,
                                "motivo": f"fact_key '{item.fact_key}' não existe no catálogo"})
            continue
        if item.signal_index is not None:
            if item.signal_index not in mapa_sinal:
                descartados.append({"secao": "assertions", "indice": i, "item": bruto,
                                    "motivo": f"signal_index {item.signal_index} aponta para sinal inexistente ou descartado"})
                continue
            item = item.model_copy(update={"signal_index": mapa_sinal[item.signal_index]})
        assercoes.append(item)

    propostas: list[ProposalOut] = []
    for i, bruto in enumerate(obj.get("proposals") or []):
        try:
            item = ProposalOut.model_validate(bruto)
        except ValidationError as err:
            descartados.append({"secao": "proposals", "indice": i, "motivo": _motivo(err), "item": bruto})
            continue
        if chaves_validas is not None and item.fact_key and item.fact_key not in chaves_validas:
            descartados.append({"secao": "proposals", "indice": i, "item": bruto,
                                "motivo": f"fact_key '{item.fact_key}' não existe no catálogo"})
            continue
        if item.signal_index not in mapa_sinal:
            descartados.append({"secao": "proposals", "indice": i, "item": bruto,
                                "motivo": f"signal_index {item.signal_index} aponta para sinal inexistente ou descartado"})
            continue
        propostas.append(item.model_copy(update={"signal_index": mapa_sinal[item.signal_index]}))

    return ExtractionResult(signals=sinais, assertions=assercoes, proposals=propostas), descartados
