"""/auth — cadastro, login, logout, me, escopo. Tudo roda como SERVIÇO (identity.sessions é fechada
para plexo_app); o que a rota devolve ao cliente é o mínimo: usuário, escopos e escopo ativo.

Regras que o banco garante (33): sessão revogada não volta, token imutável, membership no escopo ativo.
Regras daqui: rate limit por e-mail/ip (login_attempts), mensagem única para credencial inválida,
cookie httpOnly, CSRF por origem em mutação.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import Identidade, identidade, verificar_origem
from app.auth import senha as senha_mod
from app.auth import sessoes
from app.db.repos import audit
from app.db.repos import identity as identity_repo
from app.db.repos import sessoes as sessoes_repo

router = APIRouter(prefix="/auth")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MSG_CREDENCIAL = "e-mail ou senha inválidos"
# Hash "fantasma" verificado quando o e-mail não existe: mesmo custo de tempo, sem revelar existência.
_HASH_FANTASMA = senha_mod.gerar("fantasma-sem-uso")


def _email_normalizado(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL_RE.match(v) or len(v) > 254:
        raise ValueError("e-mail inválido")
    return v


class CadastroBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    senha: str = Field(min_length=10, max_length=128)
    nome: str = Field(min_length=2, max_length=120)
    aceite_termos: bool

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _email_normalizado(v)

    @field_validator("aceite_termos")
    @classmethod
    def _aceite(cls, v: bool) -> bool:
        if not v:
            raise ValueError("o aceite dos termos e da política de privacidade é obrigatório")
        return v


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    senha: str = Field(max_length=128)
    scope_id: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _email_normalizado(v)


class EscopoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: str


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _ua(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:512] if ua else None


def _set_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(value=token, **sessoes.cookie_params(request.app.state.settings))


def _apagar_cookie(response: Response, request: Request) -> None:
    p = sessoes.cookie_params(request.app.state.settings)
    response.delete_cookie(key=p["key"], path=p["path"], domain=p["domain"],
                           httponly=True, secure=p["secure"], samesite=p["samesite"])


async def _corpo_me(db, user_id: str, scope_id: str, expires_at=None) -> dict:
    async with db.service_session() as conn:
        user = await identity_repo.usuario_basico(conn, user_id)
        escopos = await identity_repo.escopos_do_usuario(conn, user_id)
        cur = await conn.execute(
            "select onboarding_completed_at from identity.user_profiles where user_id = %s", (user_id,))
        linha_onboarding = await cur.fetchone()
    # F21a: sem linha (conta legado) não é obrigada; com linha, obrigatorio = ainda não concluiu.
    if linha_onboarding is None:
        onboarding = {"obrigatorio": False, "concluido": False}
    else:
        concluido = linha_onboarding[0] is not None
        onboarding = {"obrigatorio": not concluido, "concluido": concluido}
    corpo = {"user": user, "escopos": escopos, "escopo_ativo": scope_id, "onboarding": onboarding}
    if expires_at is not None:
        corpo["sessao"] = {"expires_at": expires_at.isoformat()}
    return corpo


@router.post("/cadastro", status_code=201)
async def cadastro(body: CadastroBody, request: Request, response: Response):
    settings = request.app.state.settings
    db = request.app.state.db
    if not settings.cadastro_aberto:
        raise HTTPException(status_code=403, detail="cadastro fechado")
    verificar_origem(request)
    token = sessoes.novo_token()
    ip, ua = _ip(request), _ua(request)
    async with db.service_session() as conn:
        if await identity_repo.usuario_por_email(conn, body.email) is not None:
            raise HTTPException(status_code=409, detail="e-mail já cadastrado")
        user_id, scope_id = await identity_repo.criar_usuario_com_escopo(
            conn, email=body.email, nome=body.nome.strip(), password_hash=senha_mod.gerar(body.senha),
            ip=ip, user_agent=ua, termos_versao=settings.termos_versao, privacidade_versao=settings.privacidade_versao)
        # F21a: onboarding é obrigatório desde o nascimento da conta — a linha da jornada
        # nasce na MESMA transação do cadastro, nunca depois (senão haveria uma janela de
        # conta sem jornada nenhuma, e /onboarding a trataria como legado).
        await conn.execute(
            "insert into identity.user_profiles (user_id) values (%s) "
            "on conflict (user_id) do nothing", (user_id,))
        await sessoes_repo.criar(conn, user_id=user_id, scope_id=scope_id, token_hash=sessoes.hash_token(token),
                                 ttl_h=settings.sessao_ttl_h, ip=ip, user_agent=ua)
        await audit.registrar(conn, actor_kind="user", actor_user_id=user_id, scope_id=scope_id,
                              action="auth.cadastro", object_kind="user", object_id=user_id,
                              ip_address=ip, user_agent=ua)
    _set_cookie(response, request, token)
    return await _corpo_me(db, user_id, scope_id)


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    settings = request.app.state.settings
    db = request.app.state.db
    verificar_origem(request)
    ip, ua = _ip(request), _ua(request)
    email_hash = sessoes.hash_email(body.email)

    # A tentativa falha precisa ficar GRAVADA: por isso a recusa é decidida dentro da sessão de
    # serviço e levantada só depois dela (levantar dentro desfaria a transação, e o rate limit
    # nunca contaria). `recusa` = (status, detail, reason) ou None.
    recusa = None
    async with db.service_session() as conn:
        por_email, por_ip = await sessoes_repo.falhas_recentes(conn, email_hash=email_hash, ip=ip,
                                                              janela_min=settings.login_janela_min)
        if por_email >= settings.login_max_falhas_email or por_ip >= settings.login_max_falhas_ip:
            raise HTTPException(status_code=429, detail="muitas tentativas; aguarde para tentar de novo",
                                headers={"Retry-After": str(settings.login_janela_min * 60)})
        usuario = await identity_repo.usuario_por_email(conn, body.email)
        hash_ = usuario["password_hash"] if usuario else _HASH_FANTASMA
        ok = senha_mod.verificar(body.senha, hash_) and usuario is not None
        escopo = None
        if not ok:
            recusa = (401, _MSG_CREDENCIAL, "credencial")
        elif usuario["status"] != "active":
            recusa = (403, "conta não está ativa", usuario["status"])
        else:
            escopo = _escolher_escopo(await identity_repo.escopos_do_usuario(conn, usuario["id"]), body.scope_id)
            if escopo is None:
                recusa = (403, "sem escopo disponível para esta conta", "sem_escopo")
        if recusa is not None:
            await sessoes_repo.registrar_tentativa(conn, email_hash=email_hash, ip=ip, ok=False, reason=recusa[2])
    if recusa is not None:
        raise HTTPException(status_code=recusa[0], detail=recusa[1])

    async with db.service_session() as conn:
        if senha_mod.precisa_rehash(hash_):
            await identity_repo.atualizar_password_hash(conn, usuario["id"], senha_mod.gerar(body.senha))
        token = sessoes.novo_token()
        await sessoes_repo.criar(conn, user_id=usuario["id"], scope_id=escopo, token_hash=sessoes.hash_token(token),
                                 ttl_h=settings.sessao_ttl_h, ip=ip, user_agent=ua)
        await sessoes_repo.registrar_tentativa(conn, email_hash=email_hash, ip=ip, ok=True, reason=None)
        await identity_repo.marcar_visto(conn, usuario["id"])
        await audit.registrar(conn, actor_kind="user", actor_user_id=usuario["id"], scope_id=escopo,
                              action="auth.login", object_kind="user", object_id=usuario["id"],
                              ip_address=ip, user_agent=ua)
    _set_cookie(response, request, token)
    return await _corpo_me(db, usuario["id"], escopo)


def _escolher_escopo(escopos: list[dict], pedido: str | None) -> str | None:
    ids = [e["id"] for e in escopos]
    if pedido is not None:
        return pedido if pedido in ids else None
    for e in escopos:
        if e["role"] == "owner" and e["kind"] == "personal":
            return e["id"]
    return ids[0] if ids else None


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    settings = request.app.state.settings
    token = request.cookies.get(settings.cookie_nome)
    if token:
        verificar_origem(request)
        await sessoes.revogar(request.app.state.db, token, "logout")
    _apagar_cookie(response, request)
    return Response(status_code=204, headers=dict(response.headers))


@router.get("/me")
async def me(request: Request, ident: Identidade = Depends(identidade)):
    expires_at = None
    if ident.session_id is not None:
        async with request.app.state.db.service_session() as conn:
            cur = await conn.execute("select expires_at from identity.sessions where id = %s", (ident.session_id,))
            row = await cur.fetchone()
            expires_at = row[0] if row else None
    return await _corpo_me(request.app.state.db, ident.user_id, ident.scope_id, expires_at)


@router.post("/escopo")
async def trocar_escopo(body: EscopoBody, request: Request, ident: Identidade = Depends(identidade)):
    if ident.session_id is None:
        raise HTTPException(status_code=400, detail="troca de escopo exige sessão por cookie")
    ok = await sessoes.trocar_escopo(request.app.state.db, ident.session_id, ident.user_id, body.scope_id)
    if not ok:
        raise HTTPException(status_code=403, detail="sem acesso a este escopo")
    return {"escopo_ativo": body.scope_id}
