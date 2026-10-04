"""
F0 — Fundação do backend de agentes.

Cada teste prova um contrato da base: sessão por papel com GUCs (RLS de verdade), registro de
chamadas de LLM com usage/custo (append-only), ciclo de prompts com aprovação de compliance
(gate T15 visto da camada Python) e renderização estrita de templates.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

import pytest

from app.db.errors import PermissionDenied, PromptNotApprovable, PromptNotApproved
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.llm.client import CallMeta, ChatResponse, Usage
from app.llm.fake import FakeLLM
from app.llm.prompts import PromptLoader, content_hash_of, variaveis_do_template
from app.llm.recorder import ModelCallRecorder

ASSESSOR = "agent.assessor.system"

TEMPLATE_OK = (
    "Você é o Assessor da Plexo. Responda com diagnóstico e simulação, nunca com ordem de compra. "
    "Todo número é ILUSTRATIVO.\n\n## Contexto do escopo\n{{ contexto_escopo }}\n"
)


# ---------------------------------------------------------------- sessões e RLS
async def test_sessao_app_seta_gucs_e_isola_escopo(db, escopos):
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        cur = await conn.execute(
            "select current_user, current_setting('app.user_id', true), "
            "current_setting('app.scope_id', true), current_setting('app.role', true)"
        )
        papel, user_id, scope_id, role = await cur.fetchone()
        assert papel == "plexo_app"
        assert (user_id, scope_id, role) == (escopos.u1, escopos.s1, "user")
        cur = await conn.execute("select count(*) from identity.scopes")
        assert (await cur.fetchone())[0] == 1, "plexo_app deve enxergar só o escopo da sessão"


async def test_sessao_service_ve_tudo_mas_app_com_guc_service_nao(db, escopos):
    async with db.service_session() as conn:
        cur = await conn.execute("select current_user, current_setting('app.role', true)")
        assert (await cur.fetchone()) == ("plexo_service", "service")
        cur = await conn.execute(
            "select count(*) from identity.scopes where id in (%s, %s)", (escopos.s1, escopos.s2)
        )
        assert (await cur.fetchone())[0] == 2
    # sabotagem: a API "se declara" service pelo GUC — não pode bastar (core.is_service exige o papel)
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1, role="service") as conn:
        cur = await conn.execute("select count(*) from identity.scopes")
        assert (await cur.fetchone())[0] == 1


# ---------------------------------------------------------------- model_calls + custo
async def test_model_call_gravado_com_usage_e_custo_da_policy(db, escopos):
    async with db.service_session() as conn:
        await policies_repo.set_policy(
            conn, "LLM_PRICING",
            {"deepseek": {"modelo-teste": {"usd_por_m_input": 1.0, "usd_por_m_cache_hit": 0.1,
                                           "usd_por_m_output": 2.0}}},
        )
    fake = FakeLLM(respostas=[ChatResponse(
        text="ok", tool_calls=[], usage=Usage(input_tokens=1000, cached_tokens=200, output_tokens=500),
        finish_reason="stop", model="modelo-teste", provider="deepseek", latency_ms=12,
    )])
    resp = await fake.chat(request=None)
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        recorder = ModelCallRecorder(conn)
        call_id = await recorder.gravar(
            resp, CallMeta(purpose="sintese", agent_code="assessor", scope_id=escopos.s1,
                           prompt_version_id=None, conversation_id=None, message_id=None),
        )
        cur = await conn.execute(
            "select provider, model, input_tokens, cached_tokens, output_tokens, cost_usd, status, purpose::text "
            "from llm.model_calls where id = %s", (call_id,),
        )
        row = await cur.fetchone()
    assert row[:5] == ("deepseek", "modelo-teste", 1000, 200, 500)
    # (1000-200)*1.0/1e6 + 200*0.1/1e6 + 500*2.0/1e6
    assert float(row[5]) == pytest.approx(0.00182, rel=1e-9)
    assert row[6:] == ("succeeded", "sintese")


async def test_model_calls_e_append_only_mesmo_para_o_servico(db, escopos):
    """Padrão T10 (trigger + privilégio): para o serviço a primeira barreira é o privilégio revogado
    em 28_roles_grants (PermissionDenied); o trigger append-only (AppendOnlyViolation, subclasse)
    é a segunda. Qualquer uma das duas prova que o serviço não altera o razão de chamadas."""
    fake = FakeLLM(respostas=[ChatResponse.simples("x", model="m", provider="deepseek")])
    resp = await fake.chat(request=None)
    async with db.service_session() as conn:
        call_id = await ModelCallRecorder(conn).gravar(
            resp, CallMeta(purpose="outro", agent_code=None, scope_id=escopos.s1))
    with pytest.raises(PermissionDenied):
        async with db.service_session() as conn:
            await conn.execute("update llm.model_calls set output_tokens = 1 where id = %s", (call_id,))
    with pytest.raises(PermissionDenied):
        async with db.service_session() as conn:
            await conn.execute("delete from llm.model_calls where id = %s", (call_id,))


# ---------------------------------------------------------------- prompts: push / approve / versões
async def test_approve_recusa_template_pendente(db, escopos, prompt_assessor_draft):
    v = prompt_assessor_draft.version
    async with db.service_session() as conn:
        with pytest.raises(PromptNotApprovable) as exc:
            await prompts_repo.approve(conn, ASSESSOR, version=v, approved_by=escopos.u1)
    assert "PENDENTE" in str(exc.value)


async def test_approve_recusa_vocabulario_proibido(db, escopos, prompt_assessor_draft):
    v = prompt_assessor_draft.version
    async with db.service_session() as conn:
        await prompts_repo.push(conn, ASSESSOR, "Recomendamos sempre o melhor fundo. {{ contexto_escopo }}")
        with pytest.raises(PromptNotApprovable) as exc:
            await prompts_repo.approve(conn, ASSESSOR, version=v, approved_by=escopos.u1)
    assert "recomendamos" in str(exc.value).lower()


async def test_push_atualiza_rascunho_e_depois_versiona_respeitando_one_current(db, escopos, prompt_assessor_draft):
    base = prompt_assessor_draft.version
    async with db.service_session() as conn:
        v = await prompts_repo.push(conn, ASSESSOR, TEMPLATE_OK)
        assert v.version == base and v.compliance_status == "draft", "rascunho vigente é atualizado no lugar"
        assert v.variables == ["contexto_escopo"]
        await prompts_repo.approve(conn, ASSESSOR, version=base, approved_by=escopos.u1)
        # agente passa a apontar para a aprovada
        cur = await conn.execute(
            "select p.version from agents.agent_definitions d join llm.prompt_versions p "
            "on p.id = d.active_prompt_version_id where d.code = 'assessor'")
        assert (await cur.fetchone())[0] == base
        # novo push sobre aprovada = nova versão draft; a aprovada fecha effective_to; ponteiro não muda
        v2 = await prompts_repo.push(conn, ASSESSOR, TEMPLATE_OK + "\nRevisão.")
        assert v2.version == base + 1 and v2.compliance_status == "draft"
        cur = await conn.execute(
            "select count(*) filter (where effective_to is null), "
            "bool_and(effective_to is not null) filter (where version = %s) "
            "from llm.prompt_versions where code = %s", (base, ASSESSOR))
        uma_corrente, aprovada_fechada = await cur.fetchone()
        assert (uma_corrente, aprovada_fechada) == (1, True)
        cur = await conn.execute(
            "select p.version from agents.agent_definitions d join llm.prompt_versions p "
            "on p.id = d.active_prompt_version_id where d.code = 'assessor'")
        assert (await cur.fetchone())[0] == base


async def test_hash_local_do_template_bate_com_content_hash_do_banco(db, escopos, prompt_assessor_draft):
    async with db.service_session() as conn:
        v = await prompts_repo.push(conn, ASSESSOR, TEMPLATE_OK)
        cur = await conn.execute("select content_hash from llm.prompt_versions where id = %s", (v.id,))
        (hash_banco,) = await cur.fetchone()
    assert content_hash_of(TEMPLATE_OK) == hash_banco


async def test_aprovacao_grava_trilha_em_activity_log(db, escopos, prompt_assessor_draft):
    async with db.service_session() as conn:
        await prompts_repo.push(conn, ASSESSOR, TEMPLATE_OK)
        await prompts_repo.approve(conn, ASSESSOR, version=prompt_assessor_draft.version, approved_by=escopos.u1)
        cur = await conn.execute(
            "select actor_kind, actor_user_id::text, object_kind, details->>'code' "
            "from audit.activity_log where action = 'prompt.approved' order by occurred_at desc limit 1")
        assert (await cur.fetchone()) == ("admin", escopos.u1, "prompt_version", ASSESSOR)


# ---------------------------------------------------------------- gate T15 visto do Python
async def test_gate_prompt_draft_bloqueia_conversa_e_aprovado_libera(db, escopos, prompt_assessor_draft):
    insert = ("insert into agents.conversations (scope_id, user_id, agent_code, plan_code_at_start) "
              "values (%s, %s, 'assessor', 'free')")
    with pytest.raises(PromptNotApproved):
        async with db.service_session() as conn:
            await conn.execute(insert, (escopos.s1, escopos.u1))
    async with db.service_session() as conn:
        await prompts_repo.push(conn, ASSESSOR, TEMPLATE_OK)
        await prompts_repo.approve(conn, ASSESSOR, version=prompt_assessor_draft.version, approved_by=escopos.u1)
        await conn.execute(insert, (escopos.s1, escopos.u1))  # agora passa


# ---------------------------------------------------------------- renderização estrita
async def test_loader_renderiza_prompt_aprovado_e_recusa_variavel_faltante(db, escopos, prompt_assessor_draft):
    async with db.service_session() as conn:
        await prompts_repo.push(conn, ASSESSOR, TEMPLATE_OK)
        await prompts_repo.approve(conn, ASSESSOR, version=prompt_assessor_draft.version, approved_by=escopos.u1)
        loader = PromptLoader(conn)
        prompt = await loader.carregar_para_agente("assessor")
    assert prompt.code == ASSESSOR and prompt.version == prompt_assessor_draft.version
    texto = prompt.render(contexto_escopo="renda confirmada: R$ 10.000")
    assert "renda confirmada" in texto and "{{" not in texto
    with pytest.raises(Exception):
        prompt.render()  # contexto_escopo faltando → erro, nunca string vazia silenciosa


def test_variaveis_do_template_sao_detectadas():
    assert variaveis_do_template("a {{ x }} b {{ y }} {{ x }}") == ["x", "y"]


async def test_loader_recusa_prompt_nao_aprovado_quando_exigido(db, escopos, settings, prompt_assessor_draft):
    assert settings.require_approved_prompts is True
    async with db.service_session() as conn:
        with pytest.raises(PromptNotApproved):
            await PromptLoader(conn).carregar_para_agente("assessor")  # o fixture deixou o agente em rascunho


# ---------------------------------------------------------------- settings
def test_settings_nao_expoe_segredos_na_repr(settings):
    texto = repr(settings) + str(settings.model_dump())
    assert "@" not in texto or "***" in texto
    # nunca colocar o valor do segredo numa expressão de assert: o pytest imprimiria o valor na falha
    conninfo = settings.pg_conninfo("admin")
    esquema_ok = conninfo.startswith("postgresql://")
    assert esquema_ok
    # TLS é invariante para banco REMOTO — é o gerenciado da Aiven que trafega pela internet. Um
    # Postgres em loopback dentro do próprio runner (CI) não tem rede para grampear, e a imagem
    # oficial não sobe com TLS sem certificado. Apontar para host remoto sem TLS segue vermelho.
    local = "@localhost" in conninfo or "@127.0.0.1" in conninfo
    ssl_ok = local or "sslmode=require" in conninfo
    assert ssl_ok


# ---------------------------------------------------------------- provedor real (só com chave)
def _tem_chave_llm() -> bool:
    from app.config.settings import Settings
    try:
        return Settings().llm_api_key is not None
    except Exception:
        return False


@pytest.mark.skipif(not _tem_chave_llm(), reason="sem chave do DeepSeek no .env/ambiente")
async def test_deepseek_live_responde_json_estrito(settings):
    from app.llm.deepseek import DeepSeekClient
    from app.llm.client import ChatRequest, Message
    client = DeepSeekClient(settings)
    resp = await client.chat(ChatRequest(
        messages=[Message(role="user", content="Responda apenas JSON: {\"ok\": true}")],
        response_format={"type": "json_object"}, max_output_tokens=50,
        metadata=CallMeta(purpose="outro", agent_code=None, scope_id=None)))
    assert json.loads(resp.text)["ok"] is True
    assert resp.usage.input_tokens > 0 and resp.provider == "deepseek"

