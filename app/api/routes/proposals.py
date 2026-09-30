"""Propostas de mudança de contexto — a saída do agente de Contexto, confirmada só pelo PRÓPRIO usuário.

RLS decide o que existe (escopo alheio → 404). O CHECK self_confirmation_only do banco recusa terceiro
do mesmo escopo (→ 403).

**Mudança da F14:** até aqui, confirmar parava em 'confirmada' e NADA acontecia — o cliente dizia
"sim, pode atualizar" e o contexto continuava igual. Agora `confirm` aplica de fato, pelo caminho
longo de `app.context.aplicador` (asserção nasce declarada → é confirmada pelo próprio usuário →
supersessão consciente de precedência → proposta 'aplicada' → auditoria → perfil invalidado).

Perfil de risco continua sendo a exceção que prova a regra: ele exige refazer o suitability, e a
API diz isso em vez de aplicar (regra-estrela da 21, T24).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Identidade, identidade
from app.context.aplicador import (
    AplicacaoImpossivel, AplicacaoRecusada, aplicar, classificar_natureza, registrar_recusa,
)
from app.db.errors import SelfConfirmationOnly
from app.db.repos import audit

router = APIRouter()

ORIENTACAO_SUITABILITY = ("Perfil de risco não muda por conversa: para esta mudança valer, refaça o questionário "
                          "de suitability. Nada foi alterado no seu cadastro.")
ORIENTACAO_APLICADA = "Contexto atualizado. O diagnóstico será recalculado com o dado novo."
ORIENTACAO_NATUREZA = ("Falta uma informação para aplicar: isso passou a valer daqui em diante ou foi de "
                       "uma vez só? Responda em /proposals/{id}/nature.")

_COLS = ("id::text, signal_id::text, kind::text, fact_key, nature::text, origin::text, target_ref, "
         "current_value, proposed_value, rationale, status::text, proposed_at, expires_at")

# As três saídas do card. "Ainda não sei" é uma resposta legítima e precisa existir: forçar
# sim/não numa dúvida real é como um bônus vira salário no plano do cliente.
NATUREZAS = ("recorrente", "pontual", "incerto")


def _dict(r) -> dict:
    return {"id": r[0], "signal_id": r[1], "kind": r[2], "fact_key": r[3], "nature": r[4],
            "origin": r[5], "target_ref": r[6], "current_value": r[7], "proposed_value": r[8],
            "rationale": r[9], "status": r[10], "proposed_at": r[11].isoformat(),
            "expires_at": r[12].isoformat() if r[12] else None}


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = None
    # Recusa é informação: "não, foi bônus" diz que existe renda variável não recorrente.
    reason_code: str | None = Field(
        default=None, max_length=120,
        description="Motivo em código: 'foi_pontual', 'valor_errado', 'nao_quero_registrar', 'ja_mudou_de_novo'.")


class NatureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nature: str = Field(description="recorrente | pontual | incerto")


@router.get("/proposals")
async def listar(request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        cur = await conn.execute(
            f"select {_COLS} from context.change_proposals where status = 'proposta' "
            "and (expires_at is null or expires_at >= current_date) order by proposed_at desc")
        return {"propostas": [_dict(r) for r in await cur.fetchall()]}


async def _carregar(conn, proposal_id: str) -> tuple[str, str]:
    cur = await conn.execute(
        "select status::text, kind::text from context.change_proposals where id = %s", (proposal_id,))
    row = await cur.fetchone()
    if row is None:                          # RLS: proposta de outro escopo não existe para este papel
        raise HTTPException(status_code=404, detail="proposta não encontrada")
    if row[0] != "proposta":
        raise HTTPException(status_code=409, detail=f"proposta já está '{row[0]}'")
    return row[0], row[1]


@router.post("/proposals/{proposal_id}/nature")
async def classificar(proposal_id: str, body: NatureBody, request: Request,
                      ident: Identidade = Depends(identidade)):
    """A resposta do card: passou a valer, foi de uma vez, ou ainda não sei."""
    if body.nature not in NATUREZAS:
        raise HTTPException(status_code=422, detail=f"natureza deve ser uma de {NATUREZAS}")
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        await _carregar(conn, proposal_id)
        await classificar_natureza(conn, proposal_id, user_id=ident.user_id, natureza=body.nature)
    return {"id": proposal_id, "nature": body.nature}


@router.post("/proposals/{proposal_id}/confirm")
async def confirmar(proposal_id: str, request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    try:
        async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
            _, kind = await _carregar(conn, proposal_id)
            await conn.execute(
                "update context.change_proposals set status = 'confirmada', confirmed_at = now(), confirmed_by = %s "
                "where id = %s and status = 'proposta'", (ident.user_id, proposal_id))
            await audit.registrar(conn, actor_kind="user", actor_user_id=ident.user_id, scope_id=ident.scope_id,
                                  action="proposal.confirmed", object_kind="proposal", object_id=proposal_id,
                                  details={"kind": kind})

            if kind == "suitability_risk_profile":
                return {"id": proposal_id, "status": "confirmada", "kind": kind,
                        "aplicada": False, "orientacao": ORIENTACAO_SUITABILITY}
            try:
                resultado = await aplicar(conn, proposal_id, user_id=ident.user_id)
            except AplicacaoImpossivel as e:
                # Não é erro: é uma proposta que exige outro caminho (suitability, tela própria).
                return {"id": proposal_id, "status": "confirmada", "kind": kind,
                        "aplicada": False, "orientacao": str(e)}
            except AplicacaoRecusada as e:
                # A confirmação vale; a aplicação não pôde acontecer agora. O cliente precisa
                # saber POR QUÊ — normalmente falta classificar a natureza.
                raise HTTPException(status_code=409, detail=str(e)) from e
    except SelfConfirmationOnly:
        raise HTTPException(status_code=403, detail="só o próprio usuário confirma uma proposta do seu contexto")

    return {"id": proposal_id, "status": "aplicada", "kind": kind, "aplicada": True,
            "fact_key": resultado.fact_key, "valor_anterior": resultado.valor_anterior,
            "valor_novo": resultado.valor_novo, "assertion_id": resultado.assertion_id,
            "orientacao": ORIENTACAO_APLICADA}


@router.post("/proposals/{proposal_id}/reject")
async def rejeitar(proposal_id: str, request: Request, body: RejectBody | None = None,
                   ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    nota = body.note if body else None
    motivo = body.reason_code if body else None
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        _, kind = await _carregar(conn, proposal_id)
        await registrar_recusa(conn, proposal_id, user_id=ident.user_id,
                               motivo_codigo=motivo, nota=nota)
    return {"id": proposal_id, "status": "rejeitada", "kind": kind, "reason_code": motivo}
