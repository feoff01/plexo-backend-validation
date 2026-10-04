"""Extrator de contexto — conversa ENCERRADA → extraction_run → signals → assertions → change_proposals.

Sequência (PLANO_AGENTES_IA §7.3):
  Tx 1  INSERT extraction_runs 'running' (o gate T22 do banco recusa conversa aberta — sobe traduzido);
  leitura  transcrição (seq, id, role, content) + perfil atual (v_current_facts / v_open_questions);
  LLM   purpose='extracao_contexto', json_object, 1 reparo; cada chamada gravada em llm.model_calls;
  Tx 2  UMA transação de serviço: sinais (cada item em SAVEPOINT — gate de evidência descarta só ele) →
        asserções (nascem declarado/inferido; dedup contra fato vigente; valid_until por policy) →
        propostas (limiar de confiança, teto de pendentes, expires_at; status='proposta' SEMPRE) →
        UPDATE run 'succeeded' (o trigger marca a conversa 'processada') → cost_ledger (ref_kind='job');
  falha → UPDATE run 'failed' + audit (extraction_one_success permite reprocessar).

O LLM referencia mensagens por seq; a tradução seq→message_id é daqui e o banco confere de novo.
Nada é aplicado em tabela estruturada: proposta é o produto final do agente.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.config.policies import PolicyStore
from app.context.schemas import ExtractionResult, parse_json_tolerante, validar_itens
from app.db.errors import translate
from app.db.repos import audit
from app.llm.budget import BudgetExceeded, TurnBudget
from app.llm.client import CallMeta, ChatRequest, ChatResponse, LLMClient, Message, ProviderUnavailable
from app.llm.custos import upsert_cost_ledger
from app.llm.prompts import PromptLoader
from app.llm.recorder import ModelCallRecorder

PROMPT_CODE = "context.extractor"
PURPOSE = "extracao_contexto"
AGENT_CODE = "contexto"
ACAO_DESCARTE = "context.extraction.item_descartado"
ACAO_FALHA = "context.extraction.falhou"
ACAO_SUCESSO = "context.extraction.concluida"

INSTRUCAO_REPARO = ("Sua resposta anterior não era um objeto JSON válido no formato pedido "
                    "({\"signals\": [...], \"assertions\": [...], \"proposals\": [...]}). "
                    "Responda APENAS o objeto JSON, sem texto fora dele.")


class ConversaNaoEncontrada(LookupError):
    """Conversa inexistente para o serviço."""


class ConversaJaProcessada(RuntimeError):
    """Já existe extraction_run 'succeeded' para a conversa (extraction_one_success) — nada a fazer."""


class SaidaInvalida(RuntimeError):
    """O LLM não devolveu JSON utilizável nem após o reparo."""


@dataclass
class ResultadoExtracao:
    run_id: str
    conversation_id: str
    status: str                                   # succeeded | failed
    signals: int = 0
    assertions: int = 0
    proposals: int = 0
    descartados: list[dict[str, Any]] = field(default_factory=list)
    model_call_id: str | None = None
    erro: str | None = None

    def resumo(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "conversation_id": self.conversation_id, "status": self.status,
                "signals": self.signals, "assertions": self.assertions, "proposals": self.proposals,
                "descartados": len(self.descartados), "model_call_id": self.model_call_id, "erro": self.erro}


@dataclass(frozen=True)
class _Conversa:
    id: str
    scope_id: str
    user_id: str
    status: str


@dataclass(frozen=True)
class _Mensagem:
    seq: int
    id: str
    role: str
    content: str


# ---------------------------------------------------------------- leituras
async def ler_transcricao(conn: AsyncConnection, conversation_id: str) -> list[_Mensagem]:
    cur = await conn.execute(
        "select seq, id::text, role::text, coalesce(content, content_json::text, '') from agents.messages "
        "where conversation_id = %s and role in ('user', 'agent') order by seq", (conversation_id,))
    return [_Mensagem(*r) for r in await cur.fetchall()]


def formatar_transcricao(mensagens: list[_Mensagem]) -> str:
    """Uma linha por mensagem, '#seq papel: texto' — o LLM só vê o seq, nunca o id."""
    if not mensagens:
        return "(conversa sem mensagens)"
    return "\n".join(f"#{m.seq} {m.role}: {m.content.strip()}" for m in mensagens)


async def catalogo_para_prompt(conn: AsyncConnection) -> tuple[str, set[str]]:
    """O catálogo como o extrator o lê, e o conjunto de chaves para validar a saída dele.

    Vocabulário fechado só funciona se o extrator souber qual é o vocabulário. Antes da F15 ele
    inventava `attribute` livremente, e o que ele escrevia ficava fora de `v_fact_operavel` e do
    aplicador — trabalho perdido em silêncio.
    """
    cur = await conn.execute(
        "select fact_key, display_name, subject_kind::text, attribute, unit, value_type::text "
        "from context.fact_definitions where is_active order by family, fact_key")
    linhas, chaves = [], set()
    for fact_key, rotulo, subject_kind, attribute, unit, tipo in await cur.fetchall():
        chaves.add(fact_key)
        medida = f" · {unit}" if unit else ""
        linhas.append(f"- `{fact_key}` — {rotulo} · subject_kind={subject_kind} · "
                      f"attribute={attribute} · {tipo}{medida}")
    return "\n".join(linhas), chaves


async def perfil_atual(conn: AsyncConnection, scope_id: str) -> str:
    """Fatos vigentes e perguntas abertas do escopo, sem PII (só atributo/valor/modalidade)."""
    cur = await conn.execute(
        "select subject_kind::text, attribute, value, unit from context.v_current_facts "
        "where scope_id = %s order by observed_at desc", (scope_id,))
    fatos = [f"- {r[0]}.{r[1]} = {json.dumps(r[2], ensure_ascii=False)}" + (f" {r[3]}" if r[3] else "")
             for r in await cur.fetchall()]
    cur = await conn.execute(
        "select subject_kind::text, attribute, value, modality::text, reason from context.v_open_questions "
        "where scope_id = %s order by observed_at desc", (scope_id,))
    abertas = [f"- {r[0]}.{r[1]} = {json.dumps(r[2], ensure_ascii=False)} ({r[3]}, {r[4]})"
               for r in await cur.fetchall()]
    partes = ["Fatos confirmados:"] + (fatos or ["(nenhum)"]) + ["Pendências/perguntas abertas:"] + (abertas or ["(nenhuma)"])
    return "\n".join(partes)


async def _fatos_vigentes(conn: AsyncConnection, scope_id: str) -> set[tuple[str, str, str]]:
    cur = await conn.execute(
        "select subject_kind::text, attribute, value from context.v_current_facts where scope_id = %s", (scope_id,))
    return {(r[0], r[1], json.dumps(r[2], sort_keys=True, ensure_ascii=False)) for r in await cur.fetchall()}


def _chave(subject_kind: str, attribute: str, value: dict[str, Any]) -> tuple[str, str, str]:
    return subject_kind, attribute, json.dumps(value, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------- o processamento
async def processar_conversa(db, llm: LLMClient, policies: PolicyStore, conversation_id: str) -> ResultadoExtracao:
    # Tx 1 — a conversa e o run (gate T22 é do banco)
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select id::text, scope_id::text, user_id::text, status::text from agents.conversations where id = %s",
            (conversation_id,))
        row = await cur.fetchone()
        if row is None:
            raise ConversaNaoEncontrada(conversation_id)
        conversa = _Conversa(*row)
        # Até onde a conversa vai HOJE, e até onde já foi lida. A pergunta deixou de ser
        # "já processei esta conversa?" e passou a ser "já processei ATÉ AQUI?" — porque
        # escrever numa conversa encerrada agora a reabre (F18), e o que for dito depois
        # precisa ser lido. Sem isto, tudo o que viesse após uma reabertura ficava invisível
        # para a extração, em silêncio.
        cur = await conn.execute(
            "select coalesce(max(seq), 0) from agents.messages where conversation_id = %s",
            (conversation_id,))
        ate_seq = int((await cur.fetchone())[0])
        cur = await conn.execute(
            "select coalesce(max(coalesce(ate_seq, %s)), -1) from context.extraction_runs "
            "where conversation_id = %s and status = 'succeeded' and kind = 'pos_conversa'",
            (ate_seq, conversation_id))
        ja_lido = int((await cur.fetchone())[0])
        if ja_lido >= ate_seq:
            raise ConversaJaProcessada(conversation_id)
        cur = await conn.execute(
            "insert into context.extraction_runs (conversation_id, scope_id, ate_seq) "
            "values (%s, %s, %s) returning id::text",
            (conversation_id, conversa.scope_id, ate_seq))
        run_id = (await cur.fetchone())[0]

    resultado = ResultadoExtracao(run_id=run_id, conversation_id=conversation_id, status="failed")
    call_ids: list[str] = []
    tokens = [0, 0, 0]

    async def chamar(req: ChatRequest, budget: TurnBudget) -> ChatResponse:
        budget.reservar_chamada(PURPOSE)
        resp = await llm.chat(req)
        async with db.service_session() as conn:
            call_id = await ModelCallRecorder(conn).gravar(resp, req.metadata)
        call_ids.append(call_id)
        resultado.model_call_id = call_id
        tokens[0] += resp.usage.input_tokens
        tokens[1] += resp.usage.cached_tokens
        tokens[2] += resp.usage.output_tokens
        budget.registrar(resp)
        return resp

    try:
        # leitura + prompt
        async with db.service_session() as conn:
            prompt = await PromptLoader(conn).carregar_por_code(PROMPT_CODE)
            mensagens = await ler_transcricao(conn, conversation_id)
            perfil = await perfil_atual(conn, conversa.scope_id)
            catalogo_txt, chaves_validas = await catalogo_para_prompt(conn)
        sistema = prompt.render(conversa=formatar_transcricao(mensagens), perfil_atual=perfil,
                                catalogo=catalogo_txt)
        budget = TurnBudget.from_policy(await policies.payload("LLM_BUDGETS"))
        meta = CallMeta(purpose=PURPOSE, agent_code=AGENT_CODE, scope_id=conversa.scope_id,
                        conversation_id=conversation_id, prompt_version_id=prompt.id)
        historico = [Message(role="system", content=sistema),
                     Message(role="user", content="Extraia agora. Responda apenas o objeto JSON.")]

        # LLM + 1 reparo
        obj: dict[str, Any] | None = None
        for tentativa in range(2):
            resp = await chamar(ChatRequest(messages=list(historico), metadata=meta,
                                            response_format={"type": "json_object"},
                                            max_output_tokens=budget.tokens_restantes(), temperature=0.0), budget)
            obj = parse_json_tolerante(resp.text)
            if obj is not None:
                break
            historico += [Message(role="assistant", content=resp.text), Message(role="user", content=INSTRUCAO_REPARO)]
        if obj is None:
            raise SaidaInvalida("o LLM não devolveu JSON válido após o reparo")

        validado, descartados = validar_itens(obj, chaves_validas)
        resultado.descartados.extend(descartados)

        # Tx 2 — gravação
        async with db.service_session() as conn:
            await _gravar(conn, conversa, run_id, mensagens, validado, resultado, policies)
            for d in resultado.descartados:
                await audit.registrar(conn, actor_kind="job", action=ACAO_DESCARTE, object_kind="extraction_run",
                                      object_id=run_id, scope_id=conversa.scope_id,
                                      details={"secao": d["secao"], "indice": d.get("indice"), "motivo": d["motivo"]})
            await conn.execute(
                "update context.extraction_runs set status = 'succeeded', signals_found = %s, finished_at = now(), "
                "model_call_id = %s where id = %s", (resultado.signals, resultado.model_call_id, run_id))
            await upsert_cost_ledger(conn, scope_id=conversa.scope_id, ref_kind="job", ref_id=run_id,
                                     call_ids=call_ids, input_tokens=tokens[0], cached_tokens=tokens[1],
                                     output_tokens=tokens[2])
            await audit.registrar(conn, actor_kind="job", action=ACAO_SUCESSO, object_kind="extraction_run",
                                  object_id=run_id, scope_id=conversa.scope_id,
                                  details={"signals": resultado.signals, "assertions": resultado.assertions,
                                           "proposals": resultado.proposals, "descartados": len(resultado.descartados)})
        resultado.status = "succeeded"
        return resultado

    except BaseException as exc:
        resultado.erro = f"{type(exc).__name__}: {exc}"
        async with db.service_session() as conn:
            await conn.execute(
                "update context.extraction_runs set status = 'failed', finished_at = now(), model_call_id = %s "
                "where id = %s", (resultado.model_call_id, run_id))
            if call_ids:
                await upsert_cost_ledger(conn, scope_id=conversa.scope_id, ref_kind="job", ref_id=run_id,
                                         call_ids=call_ids, input_tokens=tokens[0], cached_tokens=tokens[1],
                                         output_tokens=tokens[2])
            await audit.registrar(conn, actor_kind="job", action=ACAO_FALHA, object_kind="extraction_run",
                                  object_id=run_id, scope_id=conversa.scope_id, details={"erro": resultado.erro})
        if isinstance(exc, (SaidaInvalida, ProviderUnavailable, BudgetExceeded)):
            return resultado          # falha esperada: fica registrada, reprocesso permitido
        raise


async def _gravar(conn: AsyncConnection, conversa: _Conversa, run_id: str, mensagens: list[_Mensagem],
                  validado: ExtractionResult, resultado: ResultadoExtracao, policies: PolicyStore) -> None:
    extracao = await policies.payload("CONTEXT_EXTRACTION")
    assercoes_cfg = await policies.payload("CONTEXT_ASSERTIONS")
    min_conf = float(extracao["min_confidence_para_proposta"])
    validade_dias = int(extracao["validade_proposta_dias"])
    max_pendentes = int(extracao["max_propostas_pendentes_por_escopo"])
    validade_por_atributo: dict[str, Any] = assercoes_cfg.get("validade_dias") or {}
    seq_para_id = {m.seq: m.id for m in mensagens}

    def traduzir(seqs: list[int]) -> list[str] | None:
        ids = [seq_para_id.get(s) for s in seqs]
        return None if any(i is None for i in ids) else ids

    # sinais — índice alinhado com validado.signals; None = descartado
    signal_ids: list[str | None] = []
    for i, s in enumerate(validado.signals):
        ids = traduzir(s.evidence_seqs)
        if ids is None:
            resultado.descartados.append({"secao": "signals", "indice": i, "motivo": f"evidence_seqs {s.evidence_seqs}: seq inexistente nesta conversa"})
            signal_ids.append(None)
            continue
        try:
            async with conn.transaction():
                cur = await conn.execute(
                    "insert into context.signals (extraction_run_id, scope_id, user_id, kind, summary, confidence, evidence_message_ids, payload) "
                    "values (%s, %s, %s, %s::context.signal_kind, %s, %s, %s::uuid[], %s) returning id::text",
                    (run_id, conversa.scope_id, conversa.user_id, s.kind, s.summary, s.confidence, ids, Jsonb(s.payload)))
                signal_ids.append((await cur.fetchone())[0])
        except psycopg.Error as e:
            resultado.descartados.append({"secao": "signals", "indice": i, "motivo": f"banco recusou: {translate(e)}"})
            signal_ids.append(None)
    resultado.signals = sum(1 for x in signal_ids if x)

    # asserções
    vigentes = await _fatos_vigentes(conn, conversa.scope_id)
    for i, a in enumerate(validado.assertions):
        if _chave(a.subject_kind, a.attribute, a.value) in vigentes:
            resultado.descartados.append({"secao": "assertions", "indice": i, "motivo": "duplicada: já é fato vigente em v_current_facts"})
            continue
        ids = traduzir(a.evidence_seqs)
        if ids is None:
            resultado.descartados.append({"secao": "assertions", "indice": i, "motivo": f"evidence_seqs {a.evidence_seqs}: seq inexistente nesta conversa"})
            continue
        signal_id = signal_ids[a.signal_index] if a.signal_index is not None else None
        if a.signal_index is not None and signal_id is None:
            resultado.descartados.append({"secao": "assertions", "indice": i, "motivo": f"signal_index {a.signal_index}: sinal descartado"})
            continue
        dias = validade_por_atributo.get(a.attribute)
        try:
            async with conn.transaction():
                await conn.execute(
                    """insert into context.assertions
                         (scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, status, confidence, likelihood,
                          source, source_ref, signal_id, evidence_message_ids, valid_until)
                       values (%s, %s, %s, %s::context.subject_kind, %s, %s, %s, %s::context.assertion_modality,
                               %s::context.assertion_status, %s, %s, 'conversa', %s, %s, %s::uuid[],
                               case when %s::int is null then null else current_date + %s::int end)""",
                    (conversa.scope_id, conversa.user_id, a.fact_key, a.subject_kind, a.attribute, Jsonb(a.value), a.unit, a.modality,
                     a.status, a.confidence, a.likelihood,
                     Jsonb({"conversation_id": conversa.id, "extraction_run_id": run_id}), signal_id, ids, dias, dias))
                resultado.assertions += 1
        except psycopg.Error as e:
            resultado.descartados.append({"secao": "assertions", "indice": i, "motivo": f"banco recusou: {translate(e)}"})

    # propostas
    cur = await conn.execute(
        "select count(*) from context.change_proposals where scope_id = %s and status = 'proposta'", (conversa.scope_id,))
    pendentes = (await cur.fetchone())[0]
    for i, p in enumerate(validado.proposals):
        signal_id = signal_ids[p.signal_index]
        if signal_id is None:
            resultado.descartados.append({"secao": "proposals", "indice": i, "motivo": f"signal_index {p.signal_index}: sinal descartado"})
            continue
        conf = validado.signals[p.signal_index].confidence
        if conf < min_conf:
            resultado.descartados.append({"secao": "proposals", "indice": i, "motivo": f"confiança {conf} abaixo de min_confidence_para_proposta={min_conf}"})
            continue
        if pendentes >= max_pendentes:
            resultado.descartados.append({"secao": "proposals", "indice": i, "motivo": f"teto de propostas pendentes do escopo atingido ({max_pendentes})"})
            continue
        try:
            async with conn.transaction():
                await conn.execute(
                    """insert into context.change_proposals
                         (signal_id, scope_id, user_id, kind, fact_key, nature, target_ref, current_value, proposed_value, rationale, status, expires_at)
                       values (%s, %s, %s, %s::context.proposal_kind, %s, %s::context.fact_nature, %s, %s, %s, %s, 'proposta', current_date + %s::int)""",
                    (signal_id, conversa.scope_id, conversa.user_id, p.kind, p.fact_key, p.nature, Jsonb(p.target_ref),
                     Jsonb(p.current_value) if p.current_value is not None else None, Jsonb(p.proposed_value),
                     p.rationale, validade_dias))
                resultado.proposals += 1
                pendentes += 1
        except psycopg.Error as e:
            resultado.descartados.append({"secao": "proposals", "indice": i, "motivo": f"banco recusou: {translate(e)}"})
