"""/onboarding — jornada obrigatória (F21a). Contrato exato em tests/test_f21_onboarding.py.

O corpo de cada PUT /onboarding/passos/{passo} depende do próprio `passo` (path param),
então o corpo chega cru (`request.json()`) e é validado contra o modelo Pydantic certo
aqui dentro — FastAPI não injeta corpo polimórfico por path param sozinho. `extra="forbid"`
em todo modelo (convenção do projeto).

RLS decide o que existe: escopo alheio nunca aparece (404 pela ausência, não por checagem
explícita). O gate C59a do banco é a palavra final sobre a conclusão — as exceções daqui
(DadoInvalido, PassoConflito) só existem para dar uma mensagem melhor que "23514".
"""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.api.deps import Identidade, identidade
from app.onboarding import jornada
from app.onboarding.erros import DadoInvalido, PassoConflito

router = APIRouter()


# ============================================================== corpos — iniciar
class IniciarBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trilha: Literal["a_nao_investe", "b_ja_investe"]


# ============================================================== corpos — passos
class DependenteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relacao: str
    nascimento_ano: int
    dependencia: str


class VidaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nascimento: dt.date
    estado_civil: str | None = None
    profissao: str | None = None
    moradia: str | None = None
    dependentes: list[DependenteBody] = Field(default_factory=list)


class RendaDespesaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    renda_liquida: float
    tipo_vinculo: str | None = None
    decimo_terceiro: bool | None = None
    despesa_total: float
    despesa_essencial: float | None = None
    despesa_fixa: float | None = None
    aporte_mensal: float


class DividaItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: str
    saldo: float
    taxa_aa_percentual: float
    parcela: float
    parcelas_restantes: int | None = None


class DividasBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dividas: list[DividaItemBody] | None = None
    sem_dividas: bool | None = None

    @model_validator(mode="after")
    def _um_ou_outro(self) -> "DividasBody":
        tem_lista, tem_flag = bool(self.dividas), bool(self.sem_dividas)
        if tem_lista and tem_flag:
            raise ValueError("envie 'dividas' OU 'sem_dividas', não os dois")
        if not tem_lista and not tem_flag:
            raise ValueError("envie 'dividas' (lista) ou 'sem_dividas': true")
        return self

    @property
    def dividas_ou_vazio(self) -> list[DividaItemBody]:
        return self.dividas or []


class BemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: str
    rotulo: str
    valor: float
    residencia_principal: bool = False
    onerado: bool = False
    divida_id: str | None = None

    @model_validator(mode="after")
    def _onus_exige_divida(self) -> "BemBody":
        if self.onerado and not self.divida_id:
            raise ValueError(f"bem '{self.rotulo}' está onerado mas não informou divida_id")
        return self


class ContaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instituicao: str
    tipo: str
    saldo: float


class PatrimonioBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bens: list[BemBody] = Field(default_factory=list)
    contas: list[ContaBody] = Field(default_factory=list)


class ObjetivoItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str
    tipo: str
    valor: float
    prazo_meses: int
    prioridade: int


class ObjetivosBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objetivos: list[ObjetivoItemBody] = Field(default_factory=list)
    idade_aposentadoria: int | None = None


class SuitabilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    respostas: dict[str, str]


# `corpo.dividas` some quando só `sem_dividas` foi enviado — jornada.passo_dividas lê
# `corpo.dividas`, então normalizamos aqui para nunca ver None.
def _normalizar_dividas(corpo: DividasBody) -> DividasBody:
    if corpo.dividas is None:
        return DividasBody(dividas=[], sem_dividas=corpo.sem_dividas)
    return corpo


_PASSOS: dict[str, type[BaseModel]] = {
    "vida": VidaBody,
    "renda_despesa": RendaDespesaBody,
    "dividas": DividasBody,
    "patrimonio": PatrimonioBody,
    "objetivos": ObjetivosBody,
    "suitability": SuitabilityBody,
}


# ============================================================== rotas
@router.get("/onboarding")
async def ver_onboarding(request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        return await jornada.estado(conn, user_id=ident.user_id)


@router.post("/onboarding/iniciar")
async def iniciar_onboarding(body: IniciarBody, request: Request,
                             ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        return await jornada.iniciar(conn, scope_id=ident.scope_id, user_id=ident.user_id,
                                     trilha=body.trilha)


@router.put("/onboarding/passos/{passo}")
async def preencher_passo(passo: str, request: Request, ident: Identidade = Depends(identidade)):
    modelo = _PASSOS.get(passo)
    if modelo is None:
        raise HTTPException(status_code=404, detail=f"passo '{passo}' não existe")
    bruto: dict[str, Any] = await request.json()
    try:
        corpo = modelo.model_validate(bruto)
    except ValidationError as e:
        # `include_context=False`: o `ctx.error` de um model_validator que levanta
        # ValueError (ex.: "bem onerado sem divida_id") carrega a EXCEÇÃO crua, que o
        # JSONResponse não sabe serializar — sem isso, o 422 vira 500 no meio da resposta.
        raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False)) from e

    db = request.app.state.db
    try:
        async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
            if passo == "vida":
                resultado = await jornada.passo_vida(conn, scope_id=ident.scope_id,
                                                      user_id=ident.user_id, corpo=corpo, bruto=bruto)
            elif passo == "renda_despesa":
                resultado = await jornada.passo_renda_despesa(conn, scope_id=ident.scope_id,
                                                               user_id=ident.user_id, corpo=corpo, bruto=bruto)
            elif passo == "dividas":
                resultado = await jornada.passo_dividas(conn, scope_id=ident.scope_id,
                                                         user_id=ident.user_id,
                                                         corpo=_normalizar_dividas(corpo), bruto=bruto)
            elif passo == "patrimonio":
                resultado = await jornada.passo_patrimonio(conn, scope_id=ident.scope_id,
                                                            user_id=ident.user_id, corpo=corpo, bruto=bruto)
            elif passo == "objetivos":
                resultado = await jornada.passo_objetivos(conn, scope_id=ident.scope_id,
                                                           user_id=ident.user_id, corpo=corpo, bruto=bruto)
            else:  # suitability
                policies = request.app.state.policies
                payload = await policies.payload("SUITABILITY_QUESTIONARIO")
                resultado = await jornada.passo_suitability(conn, scope_id=ident.scope_id,
                                                             user_id=ident.user_id, corpo=corpo,
                                                             bruto=bruto, payload=payload)
    except DadoInvalido as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except PassoConflito as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return resultado


@router.post("/onboarding/passos/{passo}/pular")
async def pular_passo(passo: str, request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    try:
        async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
            return await jornada.pular(conn, user_id=ident.user_id, passo=passo)
    except PassoConflito as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/onboarding/concluir")
async def concluir_onboarding(request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        faltando = await jornada.faltando_para_concluir(conn, scope_id=ident.scope_id,
                                                         user_id=ident.user_id)
        if faltando:
            raise HTTPException(status_code=409, detail={"faltando": faltando})
        concluiu = await jornada.concluir(conn, user_id=ident.user_id)
        if not concluiu:
            raise HTTPException(status_code=409, detail="onboarding não foi iniciado (chame /onboarding/iniciar antes)")
    await jornada.pos_conclusao_melhor_esforco(db, scope_id=ident.scope_id, user_id=ident.user_id)
    return {"concluido": True}


# ============================================================== intake (F21b)
# Texto é processado INLINE (uma chamada de LLM por requisição — o mesmo precedente do
# turno); arquivo/áudio sem provedor configurado ficam honestamente em
# 'aguardando_provedor' (202) até a F21d plugar o serviço.
class IntakeTextoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passo: str
    texto: str


def _processar(request: Request, submission_id: str):
    from app.intake import provedores
    from app.intake.extrator import processar_submissao

    settings = getattr(request.app.state, "settings", None)
    return processar_submissao(
        request.app.state.db, request.app.state.llm, request.app.state.policies, submission_id,
        transcritor=provedores.transcritor_configurado(settings),
        extrator_arquivo=provedores.extrator_arquivo_configurado(settings))


@router.post("/onboarding/intake")
async def enviar_intake(request: Request, ident: Identidade = Depends(identidade)):
    db = request.app.state.db
    content_type = (request.headers.get("content-type") or "").lower()

    if content_type.startswith("multipart/"):
        form = await request.form()
        passo = str(form.get("passo") or "").strip()
        tipo = str(form.get("tipo") or "").strip()
        midia = form.get("midia")
        if not passo or tipo not in ("arquivo", "audio") or midia is None or isinstance(midia, str):
            raise HTTPException(status_code=422,
                                detail="envie os campos 'passo', 'tipo' (arquivo|audio) e o arquivo 'midia'")
        dados = await midia.read()
        if not dados:
            raise HTTPException(status_code=422, detail="arquivo vazio")
        cfg = await request.app.state.policies.payload("ONBOARDING_EXTRACAO")
        max_bytes = int(cfg.get("max_bytes_media") or 10485760)
        if len(dados) > max_bytes:
            raise HTTPException(status_code=422,
                                detail=f"mídia de {len(dados)} bytes excede o teto de {max_bytes}")
        sha = hashlib.sha256(dados).hexdigest()
        mime = getattr(midia, "content_type", None) or "application/octet-stream"
        try:
            async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
                cur = await conn.execute(
                    "insert into context.intake_submissions "
                    "  (scope_id, user_id, passo, kind, media, media_mime, media_sha256) "
                    "values (%s, %s, %s, %s::context.intake_kind, %s, %s, %s) returning id::text",
                    (ident.scope_id, ident.user_id, passo, tipo, dados, mime, sha))
                submission_id = (await cur.fetchone())[0]
        except psycopg.errors.RaiseException as e:   # C60c (quota/teto) traduzido, não 500
            raise HTTPException(status_code=422, detail=str(e).splitlines()[0]) from e
        resultado = await _processar(request, submission_id)
        return JSONResponse(status_code=202, content={"id": submission_id, "status": resultado.status})

    bruto = await request.json()
    try:
        corpo = IntakeTextoBody.model_validate(bruto)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False)) from e
    texto = corpo.texto.strip()
    if not texto:
        raise HTTPException(status_code=422, detail="texto vazio")
    try:
        async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
            cur = await conn.execute(
                "insert into context.intake_submissions (scope_id, user_id, passo, kind, body_text) "
                "values (%s, %s, %s, 'texto', %s) returning id::text",
                (ident.scope_id, ident.user_id, corpo.passo.strip() or "livre", texto))
            submission_id = (await cur.fetchone())[0]
    except psycopg.errors.RaiseException as e:
        raise HTTPException(status_code=422, detail=str(e).splitlines()[0]) from e
    resultado = await _processar(request, submission_id)
    return {"id": submission_id, "status": resultado.status, "itens": resultado.itens}


@router.get("/onboarding/intake/{submission_id}")
async def ver_intake(submission_id: str, request: Request, ident: Identidade = Depends(identidade)):
    from app.intake.extrator import _itens_de

    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        cur = await conn.execute(
            "select id::text, status::text, passo, kind::text "
            "  from context.intake_submissions where id = %s", (submission_id,))
        row = await cur.fetchone()
        if row is None:                      # a RLS decide o que existe
            raise HTTPException(status_code=404, detail="submissão não encontrada")
        itens = await _itens_de(conn, submission_id)
    return {"id": row[0], "status": row[1], "passo": row[2], "kind": row[3], "itens": itens}


@router.post("/onboarding/intake/itens/{item_id}/confirmar")
async def confirmar_item_intake(item_id: str, request: Request,
                                ident: Identidade = Depends(identidade)):
    from app.intake import aplicar

    db = request.app.state.db
    try:
        async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
            resultado = await aplicar.confirmar_item(conn, item_id=item_id,
                                                     scope_id=ident.scope_id, user_id=ident.user_id)
    except DadoInvalido as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except PassoConflito as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if resultado is None:
        raise HTTPException(status_code=404, detail="item não encontrado")
    return resultado


@router.post("/onboarding/intake/itens/{item_id}/rejeitar")
async def rejeitar_item_intake(item_id: str, request: Request,
                               ident: Identidade = Depends(identidade)):
    from app.intake import aplicar

    db = request.app.state.db
    try:
        async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
            resultado = await aplicar.rejeitar_item(conn, item_id=item_id)
    except PassoConflito as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if resultado is None:
        raise HTTPException(status_code=404, detail="item não encontrado")
    return resultado
