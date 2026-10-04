"""F21b — intake do onboarding: texto/arquivo/áudio → IA → itens propostos → confirmação.

Vermelho antes da implementação: rotas /onboarding/intake* não existem (404) e `app.intake`
não importa.

Contratos congelados aqui (a implementação segue o teste):
- texto é processado INLINE na rota (mesmo precedente do turno: uma chamada de LLM por
  requisição) e devolve os itens já propostos;
- arquivo/áudio sem provedor configurado ficam HONESTAMENTE em 'aguardando_provedor' (202);
  a interface do provedor é plugável (`app.intake.provedores.FakeTranscritor` nos testes);
- item confirmado escreve: fato → asserção `source='onboarding'` (declarado→confirmado,
  C22a); objetivo → `planning.goals`; dívida → `budget.debts` com taxa em FRAÇÃO;
- item com fact_key fora do catálogo ou fora da faixa é DESCARTADO na extração (com motivo),
  nunca vira proposto; teto de itens por submissão vem da policy ONBOARDING_EXTRACAO.
"""
from __future__ import annotations

import io
import json
import uuid

import httpx
import pytest
import pytest_asyncio

from app.config.policies import PolicyStore
from app.llm.client import ChatResponse, Usage
from app.llm.fake import FakeLLM

HEADERS = lambda u, s: {"X-Plexo-User-Id": u, "X-Plexo-Scope-Id": s}  # noqa: E731

ITENS_PADRAO = {
    "itens": [
        {"kind": "objetivo", "nome": "Comprar carro", "tipo": "outro", "valor": 80000,
         "prazo_meses": 24, "prioridade": 2},
        {"kind": "divida", "tipo": "emprestimo_pessoal", "saldo": 12000,
         "taxa_aa_percentual": 32, "parcela": 600},
        {"kind": "fato", "fact_key": "fluxo.aporte_mensal", "valor": 1500},
        {"kind": "fato", "fact_key": "fato.inexistente", "valor": 1},        # descartado: catálogo
        {"kind": "fato", "fact_key": "renda.mensal_liquida", "valor": 20_000_000},  # descartado: faixa
    ]
}


def _json(obj) -> ChatResponse:
    return ChatResponse(text=json.dumps(obj, ensure_ascii=False), tool_calls=[],
                        usage=Usage(input_tokens=200, cached_tokens=0, output_tokens=80),
                        finish_reason="stop", model="fake-m", provider="fake", latency_ms=5)


def _api_com(db, respostas: list[ChatResponse]):
    from app.main import criar_app
    return criar_app(db=db, llm=FakeLLM(respostas), policies=PolicyStore(db, ttl_s=0))


@pytest_asyncio.fixture
async def api(db):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_api_com(db, [_json(ITENS_PADRAO)])),
                                 base_url="http://teste") as c:
        yield c


async def _iniciar(api, escopos):
    r = await api.post("/onboarding/iniciar", json={"trilha": "b_ja_investe"},
                       headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text


async def _enviar_texto(api, escopos, texto="Quero comprar um carro de 80 mil em 2 anos."):
    r = await api.post("/onboarding/intake", json={"passo": "objetivos", "texto": texto},
                       headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    return r.json()


def _item_por_kind(corpo, kind):
    return next(i for i in corpo["itens"] if i["kind"] == kind)


# ---------------------------------------------------------------- rotas e extração

async def test_rotas_exigem_autenticacao(api):
    assert (await api.post("/onboarding/intake", json={"passo": "objetivos", "texto": "x"})).status_code == 401


async def test_texto_extrai_itens_propostos_e_descarta_invalidos(api, db, escopos):
    await _iniciar(api, escopos)
    corpo = await _enviar_texto(api, escopos)
    assert corpo["status"] == "extraido"
    # 5 itens roteirizados; 2 descartados (catálogo e faixa) → 3 propostos
    assert len(corpo["itens"]) == 3
    assert {i["kind"] for i in corpo["itens"]} == {"objetivo", "divida", "fato"}
    assert all(i["status"] == "proposto" for i in corpo["itens"])
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select status::text, body_text from context.intake_submissions where id = %s",
            (corpo["id"],))
        status, body = await cur.fetchone()
        assert status == "extraido" and "carro" in body
        cur = await conn.execute(
            "select count(*) from context.intake_items where submission_id = %s", (corpo["id"],))
        assert (await cur.fetchone())[0] == 3


async def test_texto_vazio_e_422(api, escopos):
    await _iniciar(api, escopos)
    r = await api.post("/onboarding/intake", json={"passo": "objetivos", "texto": "   "},
                       headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 422


async def test_teto_de_itens_por_submissao_vem_da_policy(db, escopos):
    muitos = {"itens": [
        {"kind": "fato", "fact_key": "fluxo.aporte_mensal", "valor": 100 + n} for n in range(15)
    ]}
    app = _api_com(db, [_json(muitos)])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://teste") as api2:
        r = await api2.post("/onboarding/iniciar", json={"trilha": "b_ja_investe"},
                            headers=HEADERS(escopos.u1, escopos.s1))
        assert r.status_code == 200
        corpo = (await api2.post("/onboarding/intake", json={"passo": "renda_despesa", "texto": "aportes"},
                                 headers=HEADERS(escopos.u1, escopos.s1))).json()
    assert len(corpo["itens"]) == 12, "acima do teto da policy, o excedente é descartado com motivo"


# ---------------------------------------------------------------- confirmação → estrutura/fatos

async def test_confirmar_fato_grava_assercao_source_onboarding(api, db, escopos):
    await _iniciar(api, escopos)
    corpo = await _enviar_texto(api, escopos)
    item = _item_por_kind(corpo, "fato")
    r = await api.post(f"/onboarding/intake/itens/{item['id']}/confirmar",
                       headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmado" and r.json().get("assertion_id")
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select source::text, status::text, value->>'amount', confirmed_by::text "
            "  from context.assertions "
            " where scope_id = %s and fact_key = 'fluxo.aporte_mensal' and superseded_at is null "
            " order by created_at desc limit 1", (escopos.s1,))
        source, status, valor, confirmador = await cur.fetchone()
    assert source == "onboarding" and status == "confirmado"
    assert float(valor) == 1500 and confirmador == escopos.u1


async def test_confirmar_objetivo_cria_goal(api, db, escopos):
    await _iniciar(api, escopos)
    corpo = await _enviar_texto(api, escopos)
    item = _item_por_kind(corpo, "objetivo")
    r = await api.post(f"/onboarding/intake/itens/{item['id']}/confirmar",
                       headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200 and r.json().get("goal_id")
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select name, target_amount_brl, priority from planning.goals where scope_id = %s",
            (escopos.s1,))
        linhas = await cur.fetchall()
    assert len(linhas) == 1 and linhas[0][0] == "Comprar carro"
    assert float(linhas[0][1]) == 80000 and linhas[0][2] == 2


async def test_confirmar_divida_cria_debt_em_fracao(api, db, escopos):
    await _iniciar(api, escopos)
    corpo = await _enviar_texto(api, escopos)
    item = _item_por_kind(corpo, "divida")
    r = await api.post(f"/onboarding/intake/itens/{item['id']}/confirmar",
                       headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200 and r.json().get("debt_id")
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select kind::text, outstanding_brl, annual_rate from budget.debts where scope_id = %s",
            (escopos.s1,))
        kind, saldo, taxa = await cur.fetchone()
    assert kind == "emprestimo_pessoal" and float(saldo) == 12000
    assert float(taxa) == pytest.approx(0.32)


async def test_confirmar_duas_vezes_e_409_e_rejeitado_nao_confirma(api, db, escopos):
    await _iniciar(api, escopos)
    corpo = await _enviar_texto(api, escopos)
    h = HEADERS(escopos.u1, escopos.s1)
    fato = _item_por_kind(corpo, "fato")
    assert (await api.post(f"/onboarding/intake/itens/{fato['id']}/confirmar", headers=h)).status_code == 200
    assert (await api.post(f"/onboarding/intake/itens/{fato['id']}/confirmar", headers=h)).status_code == 409
    divida = _item_por_kind(corpo, "divida")
    assert (await api.post(f"/onboarding/intake/itens/{divida['id']}/rejeitar", headers=h)).status_code == 200
    assert (await api.post(f"/onboarding/intake/itens/{divida['id']}/confirmar", headers=h)).status_code == 409


async def test_item_alheio_e_404(api, db, escopos):
    await _iniciar(api, escopos)
    corpo = await _enviar_texto(api, escopos)
    item = corpo["itens"][0]
    r = await api.post(f"/onboarding/intake/itens/{item['id']}/confirmar",
                       headers=HEADERS(escopos.u2, escopos.s2))
    assert r.status_code == 404, "RLS decide o que existe"


# ---------------------------------------------------------------- arquivo / áudio (provedor plugável)

async def test_audio_sem_provedor_fica_aguardando(api, db, escopos):
    await _iniciar(api, escopos)
    r = await api.post(
        "/onboarding/intake",
        data={"passo": "objetivos", "tipo": "audio"},
        files={"midia": ("gravacao.webm", io.BytesIO(b"\x1a\x45audio-fake"), "audio/webm")},
        headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 202, r.text
    corpo = r.json()
    assert corpo["status"] == "aguardando_provedor"
    r = await api.get(f"/onboarding/intake/{corpo['id']}", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200 and r.json()["status"] == "aguardando_provedor"
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select kind::text, media_mime, media_sha256, body_text "
            "  from context.intake_submissions where id = %s", (corpo["id"],))
        kind, mime, sha, body = await cur.fetchone()
    assert kind == "audio" and mime == "audio/webm" and len(sha) == 64 and body is None


async def test_arquivo_sem_provedor_fica_aguardando(api, escopos):
    await _iniciar(api, escopos)
    r = await api.post(
        "/onboarding/intake",
        data={"passo": "patrimonio", "tipo": "arquivo"},
        files={"midia": ("extrato.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
        headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 202 and r.json()["status"] == "aguardando_provedor"


async def test_processar_com_transcritor_plugado_extrai(db, escopos):
    """O provedor é injetável: com um FakeTranscritor plugado, a submissão de áudio vira
    texto e passa pela MESMA extração do caminho de texto."""
    from app.intake.extrator import processar_submissao
    from app.intake.provedores import FakeTranscritor

    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into context.intake_submissions "
            "  (scope_id, user_id, passo, kind, media, media_mime, media_sha256) "
            "values (%s, %s, 'objetivos', 'audio', %s, 'audio/webm', %s) returning id::text",
            (escopos.s1, escopos.u1, b"\x01\x02", "a" * 64))
        submission_id = (await cur.fetchone())[0]

    llm = FakeLLM([_json(ITENS_PADRAO)])
    resultado = await processar_submissao(
        db, llm, PolicyStore(db, ttl_s=0), submission_id,
        transcritor=FakeTranscritor("quero comprar um carro de 80 mil em dois anos"))
    assert resultado.status == "extraido" and len(resultado.itens) == 3
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select body_text, status::text from context.intake_submissions where id = %s",
            (submission_id,))
        body, status = await cur.fetchone()
    assert status == "extraido" and "carro" in body
