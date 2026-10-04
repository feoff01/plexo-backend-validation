"""Orquestração da jornada de onboarding: passos, funil e conclusão.

O gate de verdade é do BANCO (C59a, sql/59_onboarding_fundacoes.sql) — o que está aqui
é: (1) escrever nas tabelas estruturadas certas, lendo enum/coluna real, nunca inventando
vocabulário; (2) registrar o funil (analytics.onboarding_steps) e o progresso cru
(identity.user_profiles.answers); (3) uma pré-checagem de `concluir()` para devolver uma
mensagem better que "23514, sem suitability vigente".
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.onboarding import escrita, estrutura
from app.onboarding.erros import DadoInvalido, PassoConflito
from app.onboarding.suitability import pontuar

# Ordem do wizard e índice do funil. 'intro' nasce em iniciar(); 'output' é o destino
# final, gravado só por concluir() (não é um PUT).
PASSOS_WIZARD = ["vida", "renda_despesa", "dividas", "patrimonio", "objetivos", "suitability"]
_STEP_INDEX = {"intro": 0, **{p: i + 1 for i, p in enumerate(PASSOS_WIZARD)}, "output": len(PASSOS_WIZARD) + 1}
PASSOS_PULAVEIS = {"dividas", "patrimonio", "objetivos"}

_ROTULO_RELACAO = {
    "titular": "Titular", "conjuge": "Cônjuge", "filho": "Filho(a)",
    "enteado": "Enteado(a)", "pai_mae": "Pai/Mãe", "irmao": "Irmão/Irmã",
    "outro_dependente": "Dependente", "outro": "Outro",
}
_CONTA_KIND = {
    "investimento": "corretora", "corretora": "corretora",
    "banco": "banco", "corrente": "banco", "poupanca": "banco",
    "previdencia": "previdencia", "exterior": "exterior", "cripto": "cripto_exchange",
}
_CAMPOS_RENDA_DESPESA = [
    ("renda_liquida", "renda.mensal_liquida"),
    ("tipo_vinculo", "renda.tipo_vinculo"),
    ("decimo_terceiro", "renda.tem_decimo_terceiro"),
    ("despesa_total", "despesa.total_mensal"),
    ("despesa_essencial", "despesa.essencial_mensal"),
    ("despesa_fixa", "despesa.fixa_contratada"),
    ("aporte_mensal", "fluxo.aporte_mensal"),
]


# A conversão prazo→data mora em estrutura.py (compartilhada com o intake da F21b).
_daqui_a_meses = estrutura.daqui_a_meses


def _proximo_passo(passo: str) -> str:
    if passo not in PASSOS_WIZARD:
        return passo
    i = PASSOS_WIZARD.index(passo)
    return PASSOS_WIZARD[i + 1] if i + 1 < len(PASSOS_WIZARD) else "output"


# ---------------------------------------------------------------- estado / funil
async def estado(conn: AsyncConnection, *, user_id: str) -> dict[str, Any]:
    cur = await conn.execute(
        "select onboarding_track::text, onboarding_step, onboarding_completed_at "
        "  from identity.user_profiles where user_id = %s", (user_id,))
    row = await cur.fetchone()
    if row is None:
        # Conta legado (ou nunca chegou a /iniciar): não obrigamos ninguém que o banco
        # não sabe estar em jornada nenhuma.
        return {"obrigatorio": False, "concluido": False, "trilha": None,
                "passo_atual": None, "passos": PASSOS_WIZARD}
    trilha, passo_atual, completed_at = row
    concluido = completed_at is not None
    return {"obrigatorio": not concluido, "concluido": concluido, "trilha": trilha,
            "passo_atual": passo_atual, "passos": PASSOS_WIZARD}


async def _garantir_membro(conn: AsyncConnection, *, scope_id: str, user_id: str) -> None:
    """Contas antigas de teste (fixture `escopos`) não têm a linha de scope_members —
    e o gate `members_titular_gate` (household, 23) exige membro ativo antes de aceitar
    o titular. Idempotente: ON CONFLICT DO NOTHING."""
    await conn.execute(
        "insert into identity.scope_members (scope_id, user_id, role, accepted_at) "
        "values (%s, %s, 'owner', now()) on conflict (scope_id, user_id) do nothing",
        (scope_id, user_id))


async def _registrar_funil(conn: AsyncConnection, *, user_id: str, trilha: str | None,
                           passo: str, skipped: bool = False) -> None:
    await conn.execute(
        "insert into analytics.onboarding_steps "
        "  (user_id, track, step_code, step_index, completed_at, skipped) "
        "values (%s, %s::identity.onboard_track, %s, %s, now(), %s)",
        (user_id, trilha, passo, _STEP_INDEX.get(passo, 99), skipped))


async def _avancar(conn: AsyncConnection, *, user_id: str, passo: str, bruto: dict[str, Any]) -> None:
    """Todo PUT de passo: uma linha no funil + merge do payload CRU em answers[passo] +
    avanço de onboarding_step para o próximo passo do wizard."""
    cur = await conn.execute(
        "select onboarding_track::text from identity.user_profiles where user_id = %s", (user_id,))
    row = await cur.fetchone()
    trilha = row[0] if row else None
    await _registrar_funil(conn, user_id=user_id, trilha=trilha, passo=passo)
    await conn.execute(
        "update identity.user_profiles "
        "   set answers = jsonb_set(answers, array[%s]::text[], %s::jsonb, true), "
        "       onboarding_step = %s "
        " where user_id = %s",
        (passo, Jsonb(bruto), _proximo_passo(passo), user_id))


# ---------------------------------------------------------------- iniciar / pular
async def iniciar(conn: AsyncConnection, *, scope_id: str, user_id: str, trilha: str) -> dict[str, Any]:
    await _garantir_membro(conn, scope_id=scope_id, user_id=user_id)
    await conn.execute(
        "insert into identity.user_profiles "
        "  (user_id, onboarding_track, onboarding_started_at, onboarding_step) "
        "values (%s, %s::identity.onboard_track, now(), %s) "
        "on conflict (user_id) do update set "
        "  onboarding_track = excluded.onboarding_track, "
        "  onboarding_started_at = coalesce(identity.user_profiles.onboarding_started_at, "
        "                                    excluded.onboarding_started_at)",
        (user_id, trilha, PASSOS_WIZARD[0]))
    await _registrar_funil(conn, user_id=user_id, trilha=trilha, passo="intro")
    return await estado(conn, user_id=user_id)


async def pular(conn: AsyncConnection, *, user_id: str, passo: str) -> dict[str, Any]:
    if passo not in PASSOS_PULAVEIS:
        raise PassoConflito(f"o passo '{passo}' é do núcleo obrigatório e não pode ser pulado")
    cur = await conn.execute(
        "select onboarding_track::text from identity.user_profiles where user_id = %s", (user_id,))
    row = await cur.fetchone()
    trilha = row[0] if row else None
    await _registrar_funil(conn, user_id=user_id, trilha=trilha, passo=passo, skipped=True)
    await conn.execute(
        "update identity.user_profiles set onboarding_step = %s where user_id = %s",
        (_proximo_passo(passo), user_id))
    return {"passo": passo, "pulado": True}


# ---------------------------------------------------------------- passo: vida
async def passo_vida(conn: AsyncConnection, *, scope_id: str, user_id: str, corpo, bruto: dict[str, Any]) -> dict[str, Any]:
    await conn.execute("update identity.users set birth_date = %s where id = %s",
                       (corpo.nascimento, user_id))
    await escrita.confirmar_fato(conn, scope_id=scope_id, user_id=user_id,
                                 fact_key="vida.data_nascimento", valor=corpo.nascimento)
    if corpo.estado_civil is not None:
        await escrita.confirmar_fato(conn, scope_id=scope_id, user_id=user_id,
                                     fact_key="vida.estado_civil", valor=corpo.estado_civil)
    if corpo.profissao is not None:
        await escrita.confirmar_fato(conn, scope_id=scope_id, user_id=user_id,
                                     fact_key="vida.profissao", valor=corpo.profissao)
    if corpo.moradia is not None:
        await escrita.confirmar_fato(conn, scope_id=scope_id, user_id=user_id,
                                     fact_key="vida.moradia", valor=corpo.moradia)

    await _garantir_membro(conn, scope_id=scope_id, user_id=user_id)
    cur = await conn.execute(
        "select 1 from household.members where scope_id = %s and relation = 'titular' "
        "and ended_at is null", (scope_id,))
    if await cur.fetchone() is None:
        cur2 = await conn.execute("select full_name from identity.users where id = %s", (user_id,))
        linha = await cur2.fetchone()
        nome = (linha[0] if linha else None) or "Titular"
        await conn.execute(
            "insert into household.members (scope_id, user_id, relation, display_name, origin) "
            "values (%s, %s, 'titular', %s, 'onboarding')",
            (scope_id, user_id, nome))

    for dep in corpo.dependentes:
        rotulo = _ROTULO_RELACAO.get(dep.relacao, "Dependente")
        await conn.execute(
            "insert into household.members "
            "  (scope_id, relation, display_name, birth_year, dependency, origin) "
            "values (%s, %s::household.relation, %s, %s, %s::household.dependency, 'onboarding')",
            (scope_id, dep.relacao, rotulo, dep.nascimento_ano, dep.dependencia))

    await _avancar(conn, user_id=user_id, passo="vida", bruto=bruto)
    return {"passo": "vida", "ok": True}


# ---------------------------------------------------------------- passo: renda_despesa
async def passo_renda_despesa(conn: AsyncConnection, *, scope_id: str, user_id: str, corpo, bruto: dict[str, Any]) -> dict[str, Any]:
    dados = corpo.model_dump(exclude_unset=True)
    for campo, fact_key in _CAMPOS_RENDA_DESPESA:
        if campo in dados and dados[campo] is not None:
            await escrita.confirmar_fato(conn, scope_id=scope_id, user_id=user_id,
                                         fact_key=fact_key, valor=dados[campo])
    await _avancar(conn, user_id=user_id, passo="renda_despesa", bruto=bruto)
    return {"passo": "renda_despesa", "ok": True}


# ---------------------------------------------------------------- passo: dividas
async def passo_dividas(conn: AsyncConnection, *, scope_id: str, user_id: str, corpo, bruto: dict[str, Any]) -> dict[str, Any]:
    cur = await conn.execute(
        "select answers ? 'dividas' from identity.user_profiles where user_id = %s", (user_id,))
    row = await cur.fetchone()
    if row and row[0]:
        raise PassoConflito("o passo de dívidas já foi preenchido — reeditar é conversa/produto, não o wizard")

    ids: list[str] = []
    for d in corpo.dividas:
        ids.append(await estrutura.criar_divida(
            conn, scope_id=scope_id, tipo=d.tipo, saldo=d.saldo,
            taxa_aa_percentual=d.taxa_aa_percentual, parcela=d.parcela,
            parcelas_restantes=d.parcelas_restantes))

    await _avancar(conn, user_id=user_id, passo="dividas", bruto=bruto)
    return {"passo": "dividas", "dividas": [{"id": i} for i in ids]}


# ---------------------------------------------------------------- passo: patrimonio
async def passo_patrimonio(conn: AsyncConnection, *, scope_id: str, user_id: str, corpo, bruto: dict[str, Any]) -> dict[str, Any]:
    ids_bens: list[str] = []
    for bem in corpo.bens:
        ids_bens.append(await estrutura.criar_bem(
            conn, scope_id=scope_id, tipo=bem.tipo, rotulo=bem.rotulo, valor=bem.valor,
            residencia_principal=bem.residencia_principal, onerado=bem.onerado,
            divida_id=bem.divida_id))

    ids_contas: list[str] = []
    for conta in corpo.contas:
        kind = _CONTA_KIND.get(conta.tipo, "outro")
        cur = await conn.execute(
            "insert into wealth.accounts (scope_id, kind, label, institution_name) "
            "values (%s, %s::wealth.account_kind, %s, %s) returning id::text",
            (scope_id, kind, conta.instituicao, conta.instituicao))
        account_id = (await cur.fetchone())[0]
        ids_contas.append(account_id)
        await conn.execute(
            "insert into wealth.account_balances "
            "  (account_id, scope_id, as_of_date, balance, balance_brl, origin) "
            "values (%s, %s, current_date, %s, %s, 'manual')",
            (account_id, scope_id, conta.saldo, conta.saldo))

    await _avancar(conn, user_id=user_id, passo="patrimonio", bruto=bruto)
    return {"passo": "patrimonio", "bens": [{"id": i} for i in ids_bens],
            "contas": [{"id": i} for i in ids_contas]}


# ---------------------------------------------------------------- passo: objetivos
async def passo_objetivos(conn: AsyncConnection, *, scope_id: str, user_id: str, corpo, bruto: dict[str, Any]) -> dict[str, Any]:
    ids: list[str] = []
    for obj in corpo.objetivos:
        ids.append(await estrutura.criar_objetivo(
            conn, scope_id=scope_id, user_id=user_id, nome=obj.nome, tipo=obj.tipo,
            valor=obj.valor, prazo_meses=obj.prazo_meses, prioridade=obj.prioridade))

    if corpo.idade_aposentadoria is not None:
        await escrita.confirmar_fato(conn, scope_id=scope_id, user_id=user_id,
                                     fact_key="destino.idade_aposentadoria",
                                     valor=corpo.idade_aposentadoria)

    await _avancar(conn, user_id=user_id, passo="objetivos", bruto=bruto)
    return {"passo": "objetivos", "objetivos": [{"id": i} for i in ids]}


# ---------------------------------------------------------------- passo: suitability
async def passo_suitability(conn: AsyncConnection, *, scope_id: str, user_id: str, corpo,
                            bruto: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    resultado = pontuar(corpo.respostas, payload)

    # A regra-estrela (C59b/21): refazer é linha nova. Encerra a vigente ANTES de inserir
    # a nova — a nova também nasceria com superseded_at NULL e o índice
    # suitability_one_current recusaria as duas vigentes ao mesmo tempo.
    await conn.execute(
        "update identity.suitability_assessments set superseded_at = now() "
        "where user_id = %s and superseded_at is null", (user_id,))

    validade_meses = int(payload.get("validade_meses") or 24)
    valid_until = _daqui_a_meses(dt.date.today(), validade_meses)

    cur = await conn.execute(
        "insert into identity.suitability_assessments "
        "  (user_id, scope_id, questionnaire_version, answers, result, score, valid_until) "
        "values (%s, %s, %s, %s, %s::identity.risk_profile, %s, %s) returning id::text",
        (user_id, scope_id, payload.get("versao_questionario"), Jsonb(corpo.respostas),
         resultado.resultado, resultado.pontuacao, valid_until))
    assessment_id = (await cur.fetchone())[0]

    # Fato regulatório (C38b: allows_conversation_update=false) — 'formulario' é fonte
    # que MANDA para este fato (topo de source_precedence), então confirmar por aqui é
    # exatamente o caminho que o catálogo autoriza.
    await escrita.confirmar_fato(conn, scope_id=scope_id, user_id=user_id,
                                 fact_key="vida.tolerancia_risco_declarada",
                                 valor=resultado.resultado)

    await _avancar(conn, user_id=user_id, passo="suitability", bruto=bruto)
    return {"passo": "suitability", "resultado": resultado.resultado,
            "pontuacao": resultado.pontuacao, "id": assessment_id}


# ---------------------------------------------------------------- concluir
async def _fatos_nucleo(conn: AsyncConnection) -> list[str]:
    cur = await conn.execute(
        "select payload -> 'fatos_nucleo' from engine.policy_versions "
        "where code = 'ONBOARDING_NUCLEO' and effective_to is null")
    row = await cur.fetchone()
    payload = row[0] if row else None
    if isinstance(payload, list) and payload:
        return [str(x) for x in payload]
    return ["renda.mensal_liquida", "despesa.total_mensal"]  # mesmo fallback do gate C59a


async def faltando_para_concluir(conn: AsyncConnection, *, scope_id: str, user_id: str) -> list[str]:
    """Pré-checagem — o veredito final é sempre o gate C59a do banco."""
    faltando: list[str] = []
    cur = await conn.execute(
        "select 1 from identity.suitability_assessments "
        "where user_id = %s and superseded_at is null and valid_until >= current_date", (user_id,))
    if await cur.fetchone() is None:
        faltando.append("suitability")

    nucleo = await _fatos_nucleo(conn)
    cur = await conn.execute(
        "select fact_key from context.v_fact_current where scope_id = %s and fact_key = any(%s)",
        (scope_id, nucleo))
    presentes = {r[0] for r in await cur.fetchall()}
    faltando.extend(f for f in nucleo if f not in presentes)
    return faltando


async def concluir(conn: AsyncConnection, *, user_id: str) -> bool:
    """UPDATE que dispara o gate C59a. Devolve False se o usuário nunca chamou iniciar()
    (nenhuma linha em identity.user_profiles para o UPDATE atingir)."""
    cur = await conn.execute(
        "update identity.user_profiles set onboarding_completed_at = now(), "
        "  onboarding_step = 'output' where user_id = %s", (user_id,))
    return (cur.rowcount or 0) > 0


async def pos_conclusao_melhor_esforco(db, *, scope_id: str, user_id: str) -> None:
    """Deriva, projeta e recalcula o perfil depois da conclusão — MELHOR ESFORÇO.

    O gate C59a do banco já é a palavra final sobre a conclusão em si: nada aqui pode
    derrubá-la. Sessão PRÓPRIA (separada da que gravou onboarding_completed_at, que já
    fechou/comitou antes desta função ser chamada) e cada etapa num SAVEPOINT individual —
    erro numa não contamina as seguintes nem a jornada concluída. Falha vira auditoria sob
    serviço, nunca 500 nem rollback da conclusão.
    """
    from app.context.derivacao import derivar_escopo
    from app.db.repos import audit
    from app.engine.perfil import calcular_perfil
    from app.engine.projecao import projetar_escopo

    etapas = (
        ("context.derivar_escopo", lambda conn: derivar_escopo(conn, scope_id, user_id)),
        ("engine.projetar_escopo", lambda conn: projetar_escopo(conn, scope_id)),
        ("engine.calcular_perfil", lambda conn: calcular_perfil(conn, scope_id)),
    )
    async with db.app_session(user_id=user_id, scope_id=scope_id) as conn:
        for nome, chamada in etapas:
            try:
                async with conn.transaction():
                    await chamada(conn)
            except Exception as e:  # noqa: BLE001 — best-effort: o motivo é o dado, nunca 500
                async with db.service_session() as sconn:
                    await audit.registrar(
                        sconn, actor_kind="job", actor_user_id=user_id, scope_id=scope_id,
                        action="onboarding.concluir.pos_processamento_falhou",
                        object_kind="scope", object_id=scope_id,
                        details={"etapa": nome, "erro": str(e).strip().splitlines()[0]})
