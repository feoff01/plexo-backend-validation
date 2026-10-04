"""Extração do intake — submissão (texto pronto ou transcrito) → itens PROPOSTOS.

Espelha o desenho de app/context/extractor.py (LLM json_object + 1 reparo, cada chamada
gravada em llm.model_calls, custo em cost_ledger ref_kind='job', descartes auditados item
a item, falha esperada vira status — nunca exceção para cima), mas escreve nas tabelas
próprias do intake (migration 60): os gates C60a–d são do banco.

Sem provedor de transcrição/leitura configurado, a submissão binária fica HONESTAMENTE em
'aguardando_provedor' — "dado insuficiente não é exceção" (mesmo contrato das tools).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from psycopg.types.json import Jsonb

from app.config.policies import PolicyStore
from app.context.extractor import catalogo_para_prompt
from app.context.schemas import parse_json_tolerante
from app.db.repos import audit
from app.intake.itens import MODELO_POR_KIND
from app.intake.provedores import ExtratorDeArquivo, Transcritor
from app.llm.client import CallMeta, ChatRequest, ChatResponse, LLMClient, Message, ProviderUnavailable
from app.llm.custos import upsert_cost_ledger
from app.llm.prompts import PromptLoader
from app.llm.recorder import ModelCallRecorder
from app.onboarding import escrita

PROMPT_CODE = "context.onboarding_extractor"
PURPOSE = "extracao_contexto"
AGENT_CODE = "contexto"
ACAO_DESCARTES = "onboarding.intake.descartes"
ACAO_FALHA = "onboarding.intake.falhou"
ACAO_SUCESSO = "onboarding.intake.extraida"

INSTRUCAO_REPARO = ('Sua resposta anterior não era um objeto JSON válido no formato pedido '
                    '({"itens": [...]}). Responda APENAS o objeto JSON, sem texto fora dele.')


class SubmissaoNaoEncontrada(LookupError):
    """Submissão inexistente para o serviço."""


@dataclass
class ResultadoIntake:
    submission_id: str
    status: str                                   # extraido | aguardando_provedor | falhou
    itens: list[dict[str, Any]] = field(default_factory=list)
    descartados: list[dict[str, Any]] = field(default_factory=list)
    erro: str | None = None

    def resumo(self) -> dict[str, Any]:
        return {"submission_id": self.submission_id, "status": self.status,
                "itens": len(self.itens), "descartados": len(self.descartados), "erro": self.erro}


async def _itens_de(conn, submission_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select id::text, seq, kind::text, fact_key, payload, status::text "
        "  from context.intake_items where submission_id = %s order by seq", (submission_id,))
    return [{"id": r[0], "seq": r[1], "kind": r[2], "fact_key": r[3], "payload": r[4],
             "status": r[5]} for r in await cur.fetchall()]


async def processar_submissao(db, llm: LLMClient, policies: PolicyStore, submission_id: str, *,
                              transcritor: Transcritor | None = None,
                              extrator_arquivo: ExtratorDeArquivo | None = None) -> ResultadoIntake:
    # a submissão, como o serviço a vê
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select scope_id::text, user_id::text, passo, kind::text, body_text, media, "
            "       media_mime, status::text "
            "  from context.intake_submissions where id = %s", (submission_id,))
        row = await cur.fetchone()
        if row is None:
            raise SubmissaoNaoEncontrada(submission_id)
        scope_id, user_id, passo, kind, body, media, mime, status = row
        if status == "extraido":                       # idempotente: já processada
            return ResultadoIntake(submission_id, "extraido", await _itens_de(conn, submission_id))

    # binário sem texto: transcreve se houver provedor; senão, estado honesto
    if body is None:
        provedor = transcritor if kind == "audio" else extrator_arquivo
        if provedor is None:
            async with db.service_session() as conn:
                await conn.execute(
                    "update context.intake_submissions set status = 'aguardando_provedor' "
                    " where id = %s and status = 'recebido'", (submission_id,))
            return ResultadoIntake(submission_id, "aguardando_provedor")
        try:
            if kind == "audio":
                body = await provedor.transcrever(bytes(media), mime or "")
            else:
                body = await provedor.extrair_texto(bytes(media), mime or "")
        except Exception as exc:  # provedor externo: falha é estado, não 500
            erro = f"{type(exc).__name__}: {exc}"
            async with db.service_session() as conn:
                await conn.execute(
                    "update context.intake_submissions set status = 'falhou', error_detail = %s "
                    " where id = %s", (erro, submission_id))
                await audit.registrar(conn, actor_kind="job", action=ACAO_FALHA,
                                      object_kind="intake_submission", object_id=submission_id,
                                      scope_id=scope_id, details={"erro": erro})
            return ResultadoIntake(submission_id, "falhou", erro=erro)
        async with db.service_session() as conn:   # C60d: preenche body_text NULL, nunca troca
            await conn.execute(
                "update context.intake_submissions set body_text = %s where id = %s",
                (body, submission_id))

    # prompt aprovado + catálogo + orçamento da policy
    async with db.service_session() as conn:
        prompt = await PromptLoader(conn).carregar_por_code(PROMPT_CODE)
        catalogo_txt, _ = await catalogo_para_prompt(conn)
    cfg = await policies.payload("ONBOARDING_EXTRACAO")
    max_itens = int(cfg.get("max_itens_por_submissao") or 12)
    max_tokens = int(cfg.get("max_output_tokens") or 6000)
    temperatura = float(cfg.get("temperatura") or 0.0)

    sistema = prompt.render(passo=passo, catalogo=catalogo_txt, max_itens=max_itens)
    meta = CallMeta(purpose=PURPOSE, agent_code=AGENT_CODE, scope_id=scope_id,
                    prompt_version_id=prompt.id)
    historico = [Message(role="system", content=sistema), Message(role="user", content=body)]

    call_ids: list[str] = []
    tokens = [0, 0, 0]

    async def chamar(req: ChatRequest) -> ChatResponse:
        resp = await llm.chat(req)
        async with db.service_session() as conn:
            call_ids.append(await ModelCallRecorder(conn).gravar(resp, req.metadata))
        tokens[0] += resp.usage.input_tokens
        tokens[1] += resp.usage.cached_tokens
        tokens[2] += resp.usage.output_tokens
        return resp

    async def falhar(erro: str) -> ResultadoIntake:
        async with db.service_session() as conn:
            await conn.execute(
                "update context.intake_submissions set status = 'falhou', error_detail = %s "
                " where id = %s", (erro, submission_id))
            if call_ids:
                await upsert_cost_ledger(conn, scope_id=scope_id, ref_kind="job", ref_id=submission_id,
                                         call_ids=call_ids, input_tokens=tokens[0],
                                         cached_tokens=tokens[1], output_tokens=tokens[2])
            await audit.registrar(conn, actor_kind="job", action=ACAO_FALHA,
                                  object_kind="intake_submission", object_id=submission_id,
                                  scope_id=scope_id, details={"erro": erro})
        return ResultadoIntake(submission_id, "falhou", erro=erro)

    try:
        obj: dict[str, Any] | None = None
        for _ in range(2):                                   # 1 reparo, como o extrator
            resp = await chamar(ChatRequest(messages=list(historico), metadata=meta,
                                            response_format={"type": "json_object"},
                                            max_output_tokens=max_tokens, temperature=temperatura))
            obj = parse_json_tolerante(resp.text)
            if obj is not None:
                break
            historico += [Message(role="assistant", content=resp.text),
                          Message(role="user", content=INSTRUCAO_REPARO)]
    except ProviderUnavailable as exc:
        return await falhar(f"provedor_indisponivel: {exc}")
    if obj is None:
        return await falhar("saida_invalida: o LLM não devolveu JSON válido após o reparo")

    # validação item a item — descarte com motivo, nunca derruba o lote
    validos: list[tuple[str, str | None, dict[str, Any]]] = []
    descartados: list[dict[str, Any]] = []
    brutos = obj.get("itens") if isinstance(obj.get("itens"), list) else []
    async with db.service_session() as conn:
        for idx, bruto in enumerate(brutos):
            if not isinstance(bruto, dict):
                descartados.append({"indice": idx, "motivo": "item_nao_e_objeto"}); continue
            if len(validos) >= max_itens:
                descartados.append({"indice": idx, "motivo": "teto"}); continue
            kind_item = bruto.get("kind")
            modelo = MODELO_POR_KIND.get(kind_item)
            if modelo is None:
                descartados.append({"indice": idx, "motivo": f"kind_desconhecido: {kind_item!r}"}); continue
            try:
                item = modelo.model_validate({k: v for k, v in bruto.items() if k != "kind"})
            except ValidationError as e:
                descartados.append({"indice": idx, "motivo": f"invalido: {e.errors()[0].get('msg', '?')[:80]}"})
                continue
            fact_key = getattr(item, "fact_key", None)
            if kind_item == "fato":
                try:
                    await escrita.validar_fato(conn, fact_key, item.valor)
                except escrita.FatoInvalido as e:
                    descartados.append({"indice": idx, "motivo": f"fato: {e}"}); continue
            validos.append((kind_item, fact_key, item.model_dump(exclude_none=True)))

    # gravação — SAVEPOINT por item (gate do banco recusa só o item, não o lote)
    async with db.service_session() as conn:
        seq = 0
        for kind_item, fact_key, payload in validos:
            seq += 1
            try:
                async with conn.transaction():
                    await conn.execute(
                        "insert into context.intake_items "
                        "  (submission_id, scope_id, user_id, seq, kind, fact_key, payload) "
                        "values (%s, %s, %s, %s, %s::context.intake_item_kind, %s, %s)",
                        (submission_id, scope_id, user_id, seq, kind_item, fact_key, Jsonb(payload)))
            except Exception as exc:
                descartados.append({"seq": seq, "motivo": f"banco: {type(exc).__name__}"})
        await conn.execute(
            "update context.intake_submissions set status = 'extraido', extracted_at = now() "
            " where id = %s", (submission_id,))
        if descartados:
            await audit.registrar(conn, actor_kind="job", action=ACAO_DESCARTES,
                                  object_kind="intake_submission", object_id=submission_id,
                                  scope_id=scope_id, details={"descartados": descartados})
        await upsert_cost_ledger(conn, scope_id=scope_id, ref_kind="job", ref_id=submission_id,
                                 call_ids=call_ids, input_tokens=tokens[0], cached_tokens=tokens[1],
                                 output_tokens=tokens[2])
        itens = await _itens_de(conn, submission_id)
        await audit.registrar(conn, actor_kind="job", action=ACAO_SUCESSO,
                              object_kind="intake_submission", object_id=submission_id,
                              scope_id=scope_id,
                              details={"itens": len(itens), "descartados": len(descartados)})

    return ResultadoIntake(submission_id, "extraido", itens, descartados)
