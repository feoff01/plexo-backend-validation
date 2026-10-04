"""F7 — autenticação real: sessão opaca em identity.sessions + cookie httpOnly.

Cada teste prova um caminho de entrada que a API aceita e, principalmente, os que ela recusa:
senha errada, sessão revogada/expirada, escopo alheio, Origin estranho, headers de dev desligados.
Banco real sob papel (conftest): nada sobra.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio

from tests.conftest import abrir_conversa

from app.config.policies import PolicyStore
from app.llm.fake import FakeLLM

ORIGEM = "http://localhost:3000"
SENHA = "senha-forte-1234"


def _app(db, settings, **override):
    from app.main import criar_app
    base = {"auth_headers_dev": False, "cookie_secure": False, "cors_origins": [ORIGEM],
            "login_max_falhas_email": 3, "login_janela_min": 15}
    base.update(override)
    s = settings.model_copy(update=base)
    return criar_app(db=db, llm=FakeLLM([]), policies=PolicyStore(db, ttl_s=0), settings=s)


@pytest_asyncio.fixture
async def api(db, settings):
    transport = httpx.ASGITransport(app=_app(db, settings))
    async with httpx.AsyncClient(transport=transport, base_url=ORIGEM) as cliente:
        yield cliente


@pytest_asyncio.fixture
async def contas(db, escopos):
    """u1 com senha; u1 também membro aceito de s2 (para a troca de escopo)."""
    from app.auth import senha as senha_mod
    async with db.service_session() as conn:
        await conn.execute("update identity.users set password_hash = %s where id = %s",
                           (senha_mod.gerar(SENHA), escopos.u1))
        await conn.execute(
            "insert into identity.scope_members (scope_id, user_id, role, accepted_at) values (%s, %s, 'adult', now())",
            (escopos.s2, escopos.u1))
        cur = await conn.execute("select email from identity.users where id = %s", (escopos.u1,))
        email = (await cur.fetchone())[0]
    return {"email": email, "u1": escopos.u1, "s1": escopos.s1, "s2": escopos.s2}


async def _login(api, contas, **extra):
    return await api.post("/auth/login", json={"email": contas["email"], "senha": SENHA, **extra})


# ------------------------------------------------------------------ senha
def test_senha_round_trip_e_prefixo_desconhecido():
    from app.auth import senha
    h = senha.gerar("abc-def-ghi-1")
    assert h.startswith("$scrypt$")
    assert senha.verificar("abc-def-ghi-1", h)
    assert not senha.verificar("abc-def-ghi-2", h)
    assert not senha.verificar("qualquer", "$argon2id$v=19$m=1$x$y")
    assert not senha.verificar("qualquer", None)


# ------------------------------------------------------------------ cadastro
async def test_cadastro_cria_usuario_escopo_e_sessao(api, db):
    email = f"novo-{uuid.uuid4().hex[:8]}@teste.local"
    r = await api.post("/auth/cadastro", json={"email": email, "senha": SENHA, "nome": "Pessoa Nova", "aceite_termos": True})
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["user"]["email"] == email
    assert corpo["escopos"][0]["role"] == "owner" and corpo["escopo_ativo"] == corpo["escopos"][0]["id"]
    cookie = r.headers["set-cookie"]
    assert "plx_sessao=" in cookie and "httponly" in cookie.lower() and "samesite=lax" in cookie.lower() and "path=/" in cookie.lower()
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from identity.consents where user_id = %s and granted", (corpo["user"]["id"],))
        assert (await cur.fetchone())[0] == 2
        cur = await conn.execute("select provider from identity.auth_identities where user_id = %s", (corpo["user"]["id"],))
        assert (await cur.fetchone())[0] == "password"
    r2 = await api.post("/auth/cadastro", json={"email": email, "senha": SENHA, "nome": "Outra", "aceite_termos": True})
    assert r2.status_code == 409
    r3 = await api.post("/auth/cadastro", json={"email": "x@teste.local", "senha": "curta", "nome": "A B", "aceite_termos": True})
    assert r3.status_code == 422
    r4 = await api.post("/auth/cadastro", json={"email": "y@teste.local", "senha": SENHA, "nome": "A B", "aceite_termos": False})
    assert r4.status_code == 422


async def test_cadastro_fechado_devolve_403(db, settings):
    transport = httpx.ASGITransport(app=_app(db, settings, cadastro_aberto=False))
    async with httpx.AsyncClient(transport=transport, base_url=ORIGEM) as api:
        r = await api.post("/auth/cadastro", json={"email": "z@teste.local", "senha": SENHA, "nome": "A B", "aceite_termos": True})
        assert r.status_code == 403


# ------------------------------------------------------------------ login
async def test_login_ok_emite_cookie_e_audita(api, db, contas):
    r = await _login(api, contas)
    assert r.status_code == 200, r.text
    assert r.json()["escopo_ativo"] == contas["s1"]
    assert "plx_sessao=" in r.headers["set-cookie"]
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select ip_address::text, user_agent from audit.activity_log where action = 'auth.login' and actor_user_id = %s",
            (contas["u1"],))
        row = await cur.fetchone()
    assert row is not None and row[0] is not None


async def test_login_senha_errada_401_e_registra_tentativa(api, db, contas):
    r = await api.post("/auth/login", json={"email": contas["email"], "senha": "errada-errada"})
    assert r.status_code == 401
    r2 = await api.post("/auth/login", json={"email": "ninguem@teste.local", "senha": "errada-errada"})
    assert r2.status_code == 401 and r2.json()["detail"] == r.json()["detail"]
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from identity.login_attempts where ok = false")
        assert (await cur.fetchone())[0] >= 2


async def test_login_bloqueia_apos_falhas(api, contas):
    for _ in range(3):
        await api.post("/auth/login", json={"email": contas["email"], "senha": "errada-errada"})
    r = await _login(api, contas)
    assert r.status_code == 429 and "retry-after" in r.headers


async def test_usuario_suspenso_nao_entra(api, db, contas):
    async with db.service_session() as conn:
        await conn.execute("update identity.users set status = 'suspended' where id = %s", (contas["u1"],))
    r = await _login(api, contas)
    assert r.status_code == 403


# ------------------------------------------------------------------ sessão
async def test_me_exige_sessao_valida(api, db, contas):
    assert (await api.get("/auth/me")).status_code == 401
    await _login(api, contas)
    r = await api.get("/auth/me")
    assert r.status_code == 200 and r.json()["user"]["id"] == contas["u1"]
    assert {e["id"] for e in r.json()["escopos"]} == {contas["s1"], contas["s2"]}
    async with db.service_session() as conn:
        await conn.execute("update identity.sessions set revoked_at = now() where user_id = %s", (contas["u1"],))
    assert (await api.get("/auth/me")).status_code == 401


async def test_expiracao_deslizante(api, db, contas):
    await _login(api, contas)
    async with db.service_session() as conn:
        await conn.execute(
            "update identity.sessions set last_seen_at = now() - interval '1 hour', expires_at = now() + interval '1 hour' "
            "where user_id = %s", (contas["u1"],))
    assert (await api.get("/auth/me")).status_code == 200
    async with db.service_session() as conn:
        cur = await conn.execute("select expires_at > now() + interval '2 hours' from identity.sessions where user_id = %s", (contas["u1"],))
        assert (await cur.fetchone())[0] is True
        # o menor expires_at que o CHECK aceita — já no passado quando o próximo request chega
        await conn.execute("update identity.sessions set expires_at = created_at + interval '1 millisecond' where user_id = %s", (contas["u1"],))
    assert (await api.get("/auth/me")).status_code == 401


async def test_logout_revoga_e_apaga_cookie(api, db, contas):
    await _login(api, contas)
    r = await api.post("/auth/logout")
    assert r.status_code == 204 and "max-age=0" in r.headers["set-cookie"].lower()
    assert (await api.get("/auth/me")).status_code == 401
    assert (await api.post("/auth/logout")).status_code == 204     # idempotente


async def test_troca_de_escopo_valida_membership_e_muda_o_rls(api, db, escopos, contas):
    conversa_s1 = await abrir_conversa(db, escopos)
    await _login(api, contas)
    assert (await api.get(f"/conversations/{conversa_s1}/messages")).status_code == 200
    alheio = str(uuid.uuid4())
    assert (await api.post("/auth/escopo", json={"scope_id": alheio})).status_code == 403
    r = await api.post("/auth/escopo", json={"scope_id": contas["s2"]})
    assert r.status_code == 200 and r.json()["escopo_ativo"] == contas["s2"]
    assert (await api.get("/auth/me")).json()["escopo_ativo"] == contas["s2"]
    assert (await api.get(f"/conversations/{conversa_s1}/messages")).status_code == 404   # RLS: agora em s2


# ------------------------------------------------------------------ headers dev / CSRF / CORS
async def test_headers_dev_so_valem_com_a_flag(db, settings, escopos):
    h = {"X-Plexo-User-Id": escopos.u1, "X-Plexo-Scope-Id": escopos.s1}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, settings)), base_url=ORIGEM) as api:
        assert (await api.get("/proposals", headers=h)).status_code == 401
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(db, settings, auth_headers_dev=True)), base_url=ORIGEM) as api:
        assert (await api.get("/proposals", headers=h)).status_code == 200


async def test_csrf_origin_estranho_em_mutacao_com_cookie(api, contas):
    await _login(api, contas)
    r = await api.post("/auth/escopo", json={"scope_id": contas["s2"]}, headers={"Origin": "https://mal.example"})
    assert r.status_code == 403
    r = await api.post("/auth/escopo", json={"scope_id": contas["s2"]}, headers={"Origin": ORIGEM})
    assert r.status_code == 200


async def test_cors_preflight_ecoa_origem_com_credenciais(api):
    r = await api.options("/auth/login", headers={"Origin": ORIGEM, "Access-Control-Request-Method": "POST",
                                                   "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGEM
    assert r.headers["access-control-allow-credentials"] == "true"
