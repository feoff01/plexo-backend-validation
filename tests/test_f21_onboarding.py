"""F21a — onboarding obrigatório: jornada em identity.user_profiles, escrita estruturada
(fatos `formulario`, budget.debts, estate/wealth, planning.goals, household), suitability
config-first (policy SUITABILITY_QUESTIONARIO) e funil em analytics.onboarding_steps.

Vermelho antes da implementação: nenhuma rota /onboarding/* existe (404), o cadastro não
cria a linha de jornada e /auth/me não expõe o bloco `onboarding`.

Contratos congelados aqui (a implementação segue o teste, nunca o contrário):
- fatos declarados no formulário gravam source='formulario' e nascem 'declarado' com
  confirmação no segundo ato (C22a), pelo próprio usuário;
- taxa de dívida chega em % a.a. no formulário e vive como FRAÇÃO em budget.debts
  (14 -> 0.14 — a mesma armadilha que já mordeu fundacao.py);
- suitability grava identity.suitability_assessments COM scope_id, supersede a anterior
  e materializa o fato vida.tolerancia_risco_declarada;
- concluir só passa com o núcleo (gate C59a no banco); resposta de falta é 409, não 500.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid

import httpx
import pytest
import pytest_asyncio

from app.config.policies import PolicyStore
from app.llm.fake import FakeLLM

HEADERS = lambda u, s: {"X-Plexo-User-Id": u, "X-Plexo-Scope-Id": s}  # noqa: E731

# Payload do questionário v1 — o teste cria a policy DENTRO da transação (nunca depende
# do estado do dev). Pontuação: soma dos pontos; limiares <=4 conservador, <=9 moderado.
QUESTIONARIO_V1 = {
    "versao_questionario": "suit-plexo-v1",
    "validade_meses": 24,
    "limiares": {"conservador_max": 4, "moderado_max": 9},
    "perguntas": [
        {"id": "reacao_queda", "opcoes": {"vender_tudo": 0, "esperar_preocupado": 1, "manter": 2, "aportar_mais": 3}},
        {"id": "experiencia", "opcoes": {"nenhuma": 0, "iniciante": 1, "intermediaria": 2, "avancada": 3}},
        {"id": "parcela_oscilacao", "opcoes": {"ate_10": 0, "ate_30": 1, "ate_60": 2, "acima_60": 3}},
        {"id": "horizonte", "opcoes": {"ate_2_anos": 0, "de_2_a_8": 1, "acima_8": 2}},
        {"id": "liquidez_12m", "opcoes": {"mais_da_metade": 0, "ate_metade": 1, "pouco": 2}},
    ],
}
# manter(2) + iniciante(1) + ate_30(1) + de_2_a_8(1) + ate_metade(1) = 6 -> moderado
RESPOSTAS_MODERADO = {
    "reacao_queda": "manter",
    "experiencia": "iniciante",
    "parcela_oscilacao": "ate_30",
    "horizonte": "de_2_a_8",
    "liquidez_12m": "ate_metade",
}


@pytest_asyncio.fixture
async def api(db):
    from app.main import criar_app

    aplicacao = criar_app(db=db, llm=FakeLLM([]), policies=PolicyStore(db, ttl_s=0))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=aplicacao), base_url="http://teste") as c:
        yield c


async def _publicar_questionario(db) -> None:
    async with db.service_session() as conn:
        await conn.execute(
            "update engine.policy_versions set effective_to = clock_timestamp() "
            "where code = 'SUITABILITY_QUESTIONARIO' and effective_to is null")
        await conn.execute(
            "insert into engine.policy_versions (code, version, payload, compliance_status, effective_from) "
            "select 'SUITABILITY_QUESTIONARIO', coalesce(max(version), 0) + 1, %s::jsonb, 'draft', clock_timestamp() "
            "  from engine.policy_versions where code = 'SUITABILITY_QUESTIONARIO'",
            (json.dumps(QUESTIONARIO_V1),))


async def _iniciar(api, escopos, trilha: str = "b_ja_investe"):
    r = await api.post("/onboarding/iniciar", json={"trilha": trilha},
                       headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    return r.json()


async def _renda_despesa(api, escopos):
    r = await api.put("/onboarding/passos/renda_despesa", json={
        "renda_liquida": 12000, "tipo_vinculo": "clt", "decimo_terceiro": True,
        "despesa_total": 8000, "despesa_essencial": 5500, "despesa_fixa": 4200,
        "aporte_mensal": 2500,
    }, headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    return r.json()


async def _suitability(api, escopos):
    r = await api.put("/onboarding/passos/suitability", json={"respostas": RESPOSTAS_MODERADO},
                      headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    return r.json()


async def _fatos_confirmados(db, scope_id: str) -> dict[str, float | str]:
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select fact_key, value from context.assertions "
            "where scope_id = %s and status = 'confirmado' and superseded_at is null", (scope_id,))
        linhas = await cur.fetchall()
    saida: dict[str, float | str] = {}
    for chave, valor in linhas:
        saida[chave] = valor.get("amount", valor.get("text"))
    return saida


# ---------------------------------------------------------------- jornada

async def test_rotas_exigem_autenticacao(api):
    assert (await api.get("/onboarding")).status_code == 401


async def test_conta_legado_sem_jornada_nao_e_obrigada(api, escopos):
    r = await api.get("/onboarding", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["obrigatorio"] is False and corpo["concluido"] is False


async def test_iniciar_cria_jornada_e_funil(api, db, escopos):
    corpo = await _iniciar(api, escopos)
    assert corpo["trilha"] == "b_ja_investe" and corpo["concluido"] is False
    r = await api.get("/onboarding", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.json()["obrigatorio"] is True
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select onboarding_track::text, onboarding_started_at from identity.user_profiles "
            "where user_id = %s", (escopos.u1,))
        linha = await cur.fetchone()
        assert linha is not None and linha[0] == "b_ja_investe" and linha[1] is not None
        cur = await conn.execute(
            "select count(*) from analytics.onboarding_steps where user_id = %s", (escopos.u1,))
        assert (await cur.fetchone())[0] >= 1


async def test_cadastro_cria_jornada_e_me_expoe_onboarding(api, db):
    email = f"f21-{uuid.uuid4().hex[:10]}@teste.local"
    r = await api.post("/auth/cadastro", json={
        "email": email, "senha": "senha-muito-longa-1", "nome": "Nova Conta", "aceite_termos": True})
    assert r.status_code == 201, r.text
    r = await api.get("/auth/me")
    assert r.status_code == 200
    bloco = r.json().get("onboarding")
    assert bloco is not None and bloco["obrigatorio"] is True and bloco["concluido"] is False
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select 1 from identity.user_profiles p join identity.users u on u.id = p.user_id "
            "where u.email = %s", (email,))
        assert await cur.fetchone() is not None


# ---------------------------------------------------------------- passos estruturados

async def test_passo_vida_grava_fatos_e_familia(api, db, escopos):
    await _iniciar(api, escopos)
    r = await api.put("/onboarding/passos/vida", json={
        "nascimento": "1985-04-12", "estado_civil": "casado", "profissao": "engenheira",
        "moradia": "alugado",
        "dependentes": [{"relacao": "filho", "nascimento_ano": 2015, "dependencia": "total"}],
    }, headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    fatos = await _fatos_confirmados(db, escopos.s1)
    assert fatos.get("vida.estado_civil") == "casado"
    assert fatos.get("vida.data_nascimento") is None  # data vai em {"date": ...}, não amount/text
    async with db.service_session() as conn:
        cur = await conn.execute("select birth_date from identity.users where id = %s", (escopos.u1,))
        assert (await cur.fetchone())[0] == dt.date(1985, 4, 12)
        cur = await conn.execute(
            "select value->>'date' from context.assertions where scope_id = %s "
            "and fact_key = 'vida.data_nascimento' and status = 'confirmado'", (escopos.s1,))
        assert (await cur.fetchone())[0] == "1985-04-12"
        cur = await conn.execute(
            "select count(*) from household.members where scope_id = %s and ended_at is null", (escopos.s1,))
        assert (await cur.fetchone())[0] == 2  # titular + 1 dependente


async def test_passo_renda_despesa_confirma_fatos_formulario(api, db, escopos):
    await _iniciar(api, escopos)
    await _renda_despesa(api, escopos)
    fatos = await _fatos_confirmados(db, escopos.s1)
    assert fatos.get("renda.mensal_liquida") == 12000
    assert fatos.get("despesa.total_mensal") == 8000
    assert fatos.get("fluxo.aporte_mensal") == 2500
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select source::text, confirmed_by::text from context.assertions "
            "where scope_id = %s and fact_key = 'renda.mensal_liquida' and status = 'confirmado'",
            (escopos.s1,))
        origem, confirmador = await cur.fetchone()
    assert origem == "formulario" and confirmador == escopos.u1


async def test_faixa_do_catalogo_vira_422_e_nao_500(api, escopos):
    await _iniciar(api, escopos)
    r = await api.put("/onboarding/passos/renda_despesa", json={
        "renda_liquida": 20_000_000, "despesa_total": 8000, "aporte_mensal": 0,
    }, headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 422, r.text


async def test_passo_dividas_grava_taxa_em_fracao(api, db, escopos):
    await _iniciar(api, escopos)
    r = await api.put("/onboarding/passos/dividas", json={"dividas": [
        {"tipo": "financiamento_veiculo", "saldo": 38000, "taxa_aa_percentual": 14,
         "parcela": 1450, "parcelas_restantes": 30},
    ]}, headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    assert len(r.json()["dividas"]) == 1 and r.json()["dividas"][0]["id"]
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select kind::text, outstanding_brl, annual_rate, monthly_payment_brl "
            "from budget.debts where scope_id = %s and settled_at is null", (escopos.s1,))
        linhas = await cur.fetchall()
    assert len(linhas) == 1
    kind, saldo, taxa, parcela = linhas[0]
    assert kind == "financiamento_veiculo" and float(saldo) == 38000
    assert float(taxa) == pytest.approx(0.14), "taxa entra em % a.a. e vive como fração"
    assert float(parcela) == 1450


async def test_passo_dividas_nao_se_regrava(api, escopos):
    await _iniciar(api, escopos)
    corpo = {"dividas": [{"tipo": "emprestimo_pessoal", "saldo": 1000, "taxa_aa_percentual": 30, "parcela": 100}]}
    h = HEADERS(escopos.u1, escopos.s1)
    assert (await api.put("/onboarding/passos/dividas", json=corpo, headers=h)).status_code == 200
    r = await api.put("/onboarding/passos/dividas", json=corpo, headers=h)
    assert r.status_code == 409, "reeditar estrutura é a conversa/produto, não o wizard v1"


async def test_passo_dividas_sem_dividas(api, db, escopos):
    await _iniciar(api, escopos)
    r = await api.put("/onboarding/passos/dividas", json={"sem_dividas": True},
                      headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from budget.debts where scope_id = %s", (escopos.s1,))
        assert (await cur.fetchone())[0] == 0


async def test_passo_patrimonio_onus_exige_divida(api, db, escopos):
    await _iniciar(api, escopos)
    h = HEADERS(escopos.u1, escopos.s1)
    r = await api.put("/onboarding/passos/patrimonio", json={
        "bens": [{"tipo": "imovel_residencial", "rotulo": "Apto", "valor": 900000,
                  "residencia_principal": True, "onerado": True}],
        "contas": [],
    }, headers=h)
    assert r.status_code == 422, "bem onerado sem dívida vinculada não entra (gate da 25)"
    divida = (await api.put("/onboarding/passos/dividas", json={"dividas": [
        {"tipo": "financiamento_imovel", "saldo": 420000, "taxa_aa_percentual": 9.5, "parcela": 4300},
    ]}, headers=h)).json()["dividas"][0]["id"]
    r = await api.put("/onboarding/passos/patrimonio", json={
        "bens": [{"tipo": "imovel_residencial", "rotulo": "Apto", "valor": 900000,
                  "residencia_principal": True, "onerado": True, "divida_id": divida}],
        "contas": [{"instituicao": "Corretora X", "tipo": "investimento", "saldo": 150000}],
    }, headers=h)
    assert r.status_code == 200, r.text
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select linked_debt_id::text from estate.assets where scope_id = %s", (escopos.s1,))
        assert (await cur.fetchone())[0] == divida
        cur = await conn.execute(
            "select count(*) from wealth.accounts where scope_id = %s", (escopos.s1,))
        assert (await cur.fetchone())[0] == 1
        cur = await conn.execute(
            "select count(*) from estate.valuations v join estate.assets a on a.id = v.asset_id "
            "where a.scope_id = %s", (escopos.s1,))
        assert (await cur.fetchone())[0] == 1


async def test_passo_objetivos_cria_goals_e_idade(api, db, escopos):
    await _iniciar(api, escopos)
    r = await api.put("/onboarding/passos/objetivos", json={
        "objetivos": [
            {"nome": "Aposentadoria", "tipo": "aposentadoria", "valor": 3_000_000,
             "prazo_meses": 300, "prioridade": 1},
            {"nome": "Faculdade", "tipo": "educacao", "valor": 600_000, "prazo_meses": 120, "prioridade": 2},
        ],
        "idade_aposentadoria": 65,
    }, headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select name, target_amount_brl, target_date, priority from planning.goals "
            "where scope_id = %s order by priority", (escopos.s1,))
        linhas = await cur.fetchall()
    assert [l[0] for l in linhas] == ["Aposentadoria", "Faculdade"]
    esperado = dt.date.today() + dt.timedelta(days=300 * 30)
    assert abs((linhas[0][2] - esperado).days) <= 62, "prazo_meses vira target_date"
    fatos = await _fatos_confirmados(db, escopos.s1)
    assert fatos.get("destino.idade_aposentadoria") == 65


# ---------------------------------------------------------------- suitability

async def test_suitability_pontuacao_golden(api, db, escopos):
    await _publicar_questionario(db)
    await _iniciar(api, escopos)
    corpo = await _suitability(api, escopos)
    assert corpo["resultado"] == "moderado" and corpo["pontuacao"] == 6
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select scope_id::text, questionnaire_version, result::text, score, valid_until "
            "from identity.suitability_assessments where user_id = %s and superseded_at is null",
            (escopos.u1,))
        linha = await cur.fetchone()
    assert linha is not None and linha[0] == escopos.s1, "suitability nasce COM scope_id (RLS)"
    assert linha[1] == "suit-plexo-v1" and linha[2] == "moderado" and float(linha[3]) == 6
    assert linha[4] >= dt.date.today() + dt.timedelta(days=700), "validade vem da policy (24 meses)"
    fatos = await _fatos_confirmados(db, escopos.s1)
    assert fatos.get("vida.tolerancia_risco_declarada") == "moderado"


async def test_suitability_refeita_supersede_a_anterior(api, db, escopos):
    await _publicar_questionario(db)
    await _iniciar(api, escopos)
    await _suitability(api, escopos)
    respostas = dict(RESPOSTAS_MODERADO, reacao_queda="vender_tudo", parcela_oscilacao="ate_10",
                     experiencia="nenhuma", horizonte="ate_2_anos", liquidez_12m="mais_da_metade")
    r = await api.put("/onboarding/passos/suitability", json={"respostas": respostas},
                      headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200 and r.json()["resultado"] == "conservador"
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select count(*) filter (where superseded_at is null), count(*) "
            "from identity.suitability_assessments where user_id = %s", (escopos.u1,))
        vigentes, total = await cur.fetchone()
    assert vigentes == 1 and total == 2, "refazer = nova linha; a anterior ganha superseded_at"


async def test_suitability_resposta_desconhecida_e_422(api, db, escopos):
    await _publicar_questionario(db)
    await _iniciar(api, escopos)
    r = await api.put("/onboarding/passos/suitability",
                      json={"respostas": dict(RESPOSTAS_MODERADO, reacao_queda="tanto_faz")},
                      headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 422


# ---------------------------------------------------------------- pular e concluir

async def test_pular_opcional_marca_funil_e_nucleo_nao_pula(api, db, escopos):
    await _iniciar(api, escopos)
    h = HEADERS(escopos.u1, escopos.s1)
    r = await api.post("/onboarding/passos/patrimonio/pular", headers=h)
    assert r.status_code == 200, r.text
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select skipped from analytics.onboarding_steps "
            "where user_id = %s and step_code = 'patrimonio' order by entered_at desc limit 1",
            (escopos.u1,))
        assert (await cur.fetchone())[0] is True
    assert (await api.post("/onboarding/passos/suitability/pular", headers=h)).status_code == 409
    assert (await api.post("/onboarding/passos/renda_despesa/pular", headers=h)).status_code == 409


async def test_concluir_sem_nucleo_e_409_com_o_que_falta(api, db, escopos):
    await _publicar_questionario(db)
    await _iniciar(api, escopos)
    r = await api.post("/onboarding/concluir", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 409, r.text
    faltando = r.json()["detail"]["faltando"]
    assert "suitability" in faltando and "renda.mensal_liquida" in faltando


async def test_concluir_com_nucleo_completa_e_expoe_estado(api, db, escopos):
    await _publicar_questionario(db)
    await _iniciar(api, escopos)
    await _renda_despesa(api, escopos)
    await _suitability(api, escopos)
    r = await api.post("/onboarding/concluir", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.status_code == 200, r.text
    r = await api.get("/onboarding", headers=HEADERS(escopos.u1, escopos.s1))
    assert r.json()["concluido"] is True
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select onboarding_completed_at from identity.user_profiles where user_id = %s",
            (escopos.u1,))
        assert (await cur.fetchone())[0] is not None


async def test_jornada_e_isolada_por_usuario(api, escopos):
    await _iniciar(api, escopos)
    r = await api.get("/onboarding", headers=HEADERS(escopos.u2, escopos.s2))
    assert r.status_code == 200
    assert r.json()["obrigatorio"] is False, "a jornada de u1 não vaza para u2"
