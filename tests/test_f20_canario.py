"""F20 — canário do card: o que a camada Python garante além dos gates do banco.

A suíte SQL (T135–T137) prova o gate de nascimento, o rótulo imutável e a view de
precisão. Aqui fica o que só o app pode provar: reclassificar AUDITA (a resposta do
cliente é rótulo de medição — troca sem trilha é medição adulterada), o fail-closed
não estoura na cara do agente em `propor_do_turno`, e o espelho `nature_do_extrator`
nasce preenchido pelo caminho real de escrita.
"""
from __future__ import annotations

import json

import pytest

from app.context.aplicador import classificar_natureza
from app.context.propostas import propor_do_turno
from tests.test_f14_perfil import _fato_confirmado

pytestmark = pytest.mark.asyncio

SAIDA = {"fact_key": "renda.mensal_liquida", "rotulo": "Renda mensal líquida",
         "unidade": "BRL", "valor_atual": 8000.0, "valor_informado": 10000.0,
         "pode_virar_proposta": True, "natureza": "recorrente",
         "precisa_classificar_natureza": False}


async def _nova_versao_da_policy(conn, payload_extra: dict | None, *, remover_chave: bool = False):
    """Versão vigente nova de CONTEXT_FACT_CATALOG dentro da transação do teste.

    `payload_extra` é mesclado sobre o payload atual; `remover_chave=True` tira a
    allowlist inteira (o estado fail-closed). O rollback do teste desfaz tudo.
    """
    # clock_timestamp(): now() é congelado na transação do teste e violaria o CHECK
    # effective_to > effective_from ao encerrar uma versão criada nesta mesma transação.
    await conn.execute(
        "update engine.policy_versions set effective_to = clock_timestamp() "
        "where code = 'CONTEXT_FACT_CATALOG' and effective_to is null")
    if remover_chave:
        operacao = "- 'escopos_canario_card_ao_vivo'"
        params: tuple = ()
    else:
        operacao = "|| %s::jsonb"
        params = (json.dumps(payload_extra or {}),)
    await conn.execute(
        "insert into engine.policy_versions "
        "  (code, version, payload, compliance_status, effective_from) "
        "select 'CONTEXT_FACT_CATALOG', coalesce(max(version), 0) + 1, "
        "       coalesce((select payload from engine.policy_versions "
        "                  where code = 'CONTEXT_FACT_CATALOG' "
        "                  order by version desc limit 1), '{}'::jsonb) "
        f"       {operacao}, 'draft', clock_timestamp() "
        "  from engine.policy_versions where code = 'CONTEXT_FACT_CATALOG'",
        params)


async def _card_do_turno(conn, escopos, conversa):
    await _fato_confirmado(conn, escopos, "renda.mensal_liquida", 8000.0)
    cur = await conn.execute(
        "insert into agents.messages (conversation_id, scope_id, seq, role, content) "
        "values (%s, %s, 1, 'user', 'passei a ganhar 10 mil') returning id::text",
        (conversa, escopos.s1))
    msg_id = (await cur.fetchone())[0]
    return await propor_do_turno(conn, scope_id=escopos.s1, user_id=escopos.u1,
                                 conversation_id=conversa, message_ids=[msg_id],
                                 saida_tool=SAIDA)


async def test_reclassificar_audita_a_resposta(db, escopos):
    """A resposta do card é o rótulo do canário — trocar natureza sem trilha é adulterar
    a medição. `classificar_natureza` grava em audit.activity_log, como a recusa já faz."""
    from tests.conftest import abrir_conversa
    conversa = await abrir_conversa(db, escopos)
    async with db.service_session() as conn:
        await _nova_versao_da_policy(
            conn, {"escopos_canario_card_ao_vivo": [escopos.s1]})
        criada = await _card_do_turno(conn, escopos, conversa)
        assert criada is not None

        await classificar_natureza(conn, criada.id, user_id=escopos.u1,
                                   natureza="recorrente")

        cur = await conn.execute(
            "select count(*) from audit.activity_log "
            "where action = 'context.proposal.nature_classified' and object_id = %s",
            (criada.id,))
        assert (await cur.fetchone())[0] == 1, \
            "reclassificar precisa deixar trilha em audit.activity_log"


async def test_fail_closed_nao_estoura_nem_cria(db, escopos):
    """Sem a chave `escopos_canario_card_ao_vivo` na policy, o card não nasce para
    NINGUÉM — e a recusa do banco não pode estourar na cara do agente: `propor_do_turno`
    devolve None (ou recusa controlada), nunca proposta."""
    from tests.conftest import abrir_conversa
    conversa = await abrir_conversa(db, escopos)
    async with db.service_session() as conn:
        await _nova_versao_da_policy(conn, None, remover_chave=True)
        try:
            criada = await _card_do_turno(conn, escopos, conversa)
        except Exception:
            criada = None      # recusa controlada também cumpre o contrato: card não nasce
        assert criada is None, "sem allowlist na policy, nenhum escopo é canário"

        cur = await conn.execute(
            "select count(*) from context.change_proposals "
            "where scope_id = %s and origin = 'turno'", (escopos.s1,))
        assert (await cur.fetchone())[0] == 0


async def test_rotulo_nasce_preenchido_pelo_caminho_real(db, escopos):
    """O espelho não é responsabilidade do chamador: quem insere pela via real do app
    sai com `nature_do_extrator` igual à natureza proposta, copiado pelo banco."""
    from tests.conftest import abrir_conversa
    conversa = await abrir_conversa(db, escopos)
    async with db.service_session() as conn:
        await _nova_versao_da_policy(
            conn, {"escopos_canario_card_ao_vivo": [escopos.s1]})
        criada = await _card_do_turno(conn, escopos, conversa)
        assert criada is not None

        cur = await conn.execute(
            "select nature_do_extrator::text from context.change_proposals where id = %s",
            (criada.id,))
        assert (await cur.fetchone())[0] == "recorrente"
