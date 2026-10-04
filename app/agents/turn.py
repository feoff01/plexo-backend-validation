"""O TURNO do Copiloto — o único lugar que costura banco + LLM + tools.

Duas transações e escritas curtas entre elas (desenho do PLANO_AGENTES_IA §3):
  Tx A  pergunta + cota (fatos que sobrevivem a falha do provedor; 23514 'Cota mensal' → Paywall);
  [ac]  llm.model_calls e tools.tool_executions gravadas AO CONCLUIR (append-only);
  Tx B  resposta do agente + proveniência + guardrails + 2ª opinião + cost_ledger — juntos ou nada.

O LLM nunca calcula: ele escolhe a tool (param_schema do registro) e sintetiza o output dela.
Gates de família/plano/política são do BANCO; aqui eles viram eventos, não regras duplicadas.

F8 (2026-08-25): um laço único de tool-use. O modelo pode devolver várias tool_calls por resposta
(todas executadas, todas respondidas — o provedor exige uma resposta por id); erro de tool (parâmetro
inválido, insumo faltante, conteúdo indisponível) volta ao modelo como resultado da chamada e ELE
redige a pergunta/negativa — texto fixo só quando `AGENT_CONVERSATIONS.max_erros_de_tool_por_turno`
é ultrapassado. Tetos: `max_tools_por_turno` (execuções) e `LLM_BUDGETS` (chamadas/tokens).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from psycopg.types.json import Jsonb

from app.agents import conversations as convs
from app.agents import eventos as ev
from app.context import propostas as ctx_propostas
from app.agents import analysis, blocos as blocos_mod, guardrails, router, second_opinion
from app.agents.router import Rota
from app.config.policies import PolicyStore
from app.db.errors import DbError, PromptNotApproved, QuotaExceeded
from app.db.repos import identity as identity_repo
from app.llm.budget import BudgetExceeded, TurnBudget
from app.llm.client import (CallMeta, ChatRequest, ChatResponse, LLMClient, Message, ProviderUnavailable, ToolCall,
                            ToolDef, streamar)
from app.llm.custos import upsert_cost_ledger
from app.llm.prompts import PromptLoader
from app.llm.recorder import ModelCallRecorder
from app.tools.context_pack import cobertura_mercado, pacote_do_escopo
from app.tools.executor import (ToolConteudoIndisponivel, ToolInsumoFaltante, ToolParamsInvalid, ToolResult,
                                executar_tool)
from app.tools.hashing import canonical_json
from app.tools.registry import ToolSpec, spec_de, specs_registradas

TOOL_VERIFICAR_MUDANCA = "contexto.verificar_mudanca"

_ORDEM_PLANOS = {"free": 0, "essential": 1, "advanced": 2, "wealth": 3}

TEXTO_ANALISE_EM_ANDAMENTO = ("Análise aprofundada registrada. Vou medir o que você pediu com as ferramentas do Analista e "
                              "publicar o relatório nesta conversa assim que ficar pronto.")

ENCAMINHAR = ToolDef(
    name="encaminhar",
    description=("Use quando a pergunta é assunto de OUTRO agente (analista: mercado/teses; "
                 "educador: conceitos; assessor: planejamento do cliente). Não abre conversa — "
                 "só sugere ao cliente. Escreva também, no texto, uma frase explicando o encaminhamento."),
    parameters={"type": "object", "additionalProperties": False,
                "properties": {"agent_code": {"type": "string", "enum": ["assessor", "analista", "educador"]},
                               "motivo": {"type": "string"}},
                "required": ["agent_code", "motivo"]},
)

# Defaults quando a policy vigente ainda não traz a chave (dev antigo): espelham o comportamento anterior.
# Pedido explícito quando o modelo mediu e não redigiu. Sem tools, sem rodeio: os resultados
# já estão na lista de mensagens, e o que falta é alguém escrever a leitura deles.
INSTRUCAO_REDIGIR = (
    "Você já fez as medições necessárias e os resultados estão acima. Escreva agora a resposta "
    "ao cliente com base neles, em português, sem pedir mais nenhuma medição. Traga os números "
    "que importam para a pergunta, diga o que eles significam e mantenha as ressalvas de "
    "sempre. Se algum dado faltou, diga qual falta em vez de estimar.")

_PADRAO_MAX_TOOLS = 1
_PADRAO_MAX_ERROS_DE_TOOL = 1


def filtrar_tools(specs: list[ToolSpec], *, familias: tuple[str, ...] | list[str], plano: str) -> list[ToolSpec]:
    """O LLM só vê tool explicitamente exposta, de família permitida e plano compatível.

    Os gates do banco continuam sendo o backstop de execução. `exposed_to_llm=False` serve
    à migração: a tool permanece registrada/auditável, mas não entra no catálogo do modelo.
    """
    return [s for s in specs
            if s.exposed_to_llm
            and s.family in tuple(familias)
            and _ORDEM_PLANOS[s.min_plan] <= _ORDEM_PLANOS[plano]]


def _erro_de_tool(e: Exception) -> tuple[str, Any, str]:
    """(código para o modelo, detalhe para o modelo, texto fixo de último recurso para o cliente)."""
    if isinstance(e, ToolParamsInvalid):
        detalhe = e.erros[0].get("msg", "") if e.erros else ""
        return ("parametros_invalidos", e.erros[:5],
                "Não consegui montar os parâmetros do cálculo a partir da conversa. "
                f"Reformule com os valores ({detalhe}).")
    if isinstance(e, ToolInsumoFaltante):
        return "insumo_faltante", str(e), f"Antes de calcular, preciso de um dado seu: {e}."
    return ("conteudo_indisponivel", str(e),
            f"Ainda não tenho conteúdo aprovado sobre isso ({e}). Posso explicar outro conceito que já esteja "
            "na base, se quiser.")


@dataclass(frozen=True)
class TurnoInput:
    texto: str
    user_id: str
    scope_id: str
    agent_code: str | None = None
    chip_id: str | None = None
    conversation_id: str | None = None
    mode: str = "standard"         # research = análise aprofundada assíncrona (F6; só Analista)


@dataclass
class _Acumulado:
    call_ids: list[str] = field(default_factory=list)
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    tool_executions: int = 0
    guardrails: list[tuple[str, str, str]] = field(default_factory=list)   # (kind, action, detalhe)


class TurnoCopiloto:
    def __init__(self, db, llm: LLMClient, policies: PolicyStore, enfileirar_analise=None, streaming: bool = True):
        self._db = db
        self._llm = llm
        self._policies = policies
        self._enfileirar_analise = enfileirar_analise     # async (analysis_id) -> None; None = sem fila (CLI `analise run`)
        self._streaming = streaming                       # F9: deltas ao vivo (settings.llm_stream)

    # ------------------------------------------------------------------ LLM com registro e orçamento
    async def _registrar(self, resp: ChatResponse, req: ChatRequest, budget: TurnBudget, acum: _Acumulado) -> ChatResponse:
        async with self._db.app_session(user_id=self._user, scope_id=self._scope) as conn:
            call_id = await ModelCallRecorder(conn).gravar(resp, req.metadata)
        acum.call_ids.append(call_id)
        acum.input_tokens += resp.usage.input_tokens
        acum.cached_tokens += resp.usage.cached_tokens
        acum.output_tokens += resp.usage.output_tokens
        budget.registrar(resp)
        resp.model_call_id = call_id  # type: ignore[attr-defined]
        return resp

    async def _chamar(self, req: ChatRequest, budget: TurnBudget, acum: _Acumulado) -> ChatResponse:
        budget.reservar_chamada(req.metadata.purpose)
        return await self._registrar(await self._llm.chat(req), req, budget, acum)

    async def _chamar_stream(self, req: ChatRequest, budget: TurnBudget, acum: _Acumulado, saida: dict) -> AsyncIterator[ev.Evento]:
        """F9: como `_chamar`, mas emitindo `Delta` ao vivo. `saida['resp']` recebe a resposta final e
        `saida['emitido']` o texto que chegou ao cliente nesta chamada. Um '<' solto no fim fica retido
        (pode ser início de marcação); se aparecer marcação de tool, a emissão é suspensa até o fim —
        o fechamento do turno corrige com `Replace`."""
        budget.reservar_chamada(req.metadata.purpose)
        emitido = ""
        if not self._streaming:
            resp = await self._llm.chat(req)
        else:
            resp = None
            pendente = ""
            suspenso = False
            async for trecho in streamar(self._llm, req):
                if trecho.final is not None:
                    resp = trecho.final
                    break
                if not trecho.texto or suspenso:
                    continue
                pendente += trecho.texto
                if guardrails.parece_marcacao_de_tool(pendente):
                    suspenso = True
                    continue
                corte = pendente.rfind("<")
                if corte != -1 and len(pendente) - corte < 12:
                    emitir, pendente = pendente[:corte], pendente[corte:]
                else:
                    emitir, pendente = pendente, ""
                if emitir:
                    emitido += emitir
                    yield ev.Delta(texto=emitir)
            if resp is None:
                raise ProviderUnavailable("o stream do provedor terminou sem a resposta final")
        saida["resp"] = await self._registrar(resp, req, budget, acum)
        saida["emitido"] = emitido

    # ------------------------------------------------------------------ turno
    async def executar(self, inp: TurnoInput) -> AsyncIterator[ev.Evento]:
        self._user, self._scope = inp.user_id, inp.scope_id
        acum = _Acumulado()
        for g in guardrails.pre_llm(inp.texto):
            acum.guardrails.append((g.kind, g.action, g.detalhe))

        # ---------- rota
        texto = inp.texto
        rota: Rota | None = None
        if inp.conversation_id is None:
            if inp.chip_id:
                rota = router.rota_por_chip(inp.chip_id)
                if rota is None:
                    yield ev.Erro(tipo="chip_desconhecido", mensagem=inp.chip_id)
                    return
                texto = texto or rota.texto or ""
            elif inp.agent_code:
                rota = Rota(agent_code=inp.agent_code, mode="forced")
            else:
                async for evento in self._rotear_por_llm(texto, acum):
                    if isinstance(evento, Rota):
                        rota = evento
                    else:
                        yield evento
                        if isinstance(evento, (ev.Clarify, ev.Erro)):
                            return
        # ---------- pré-checagens (antes de emitir Routed e de gravar qualquer coisa)
        async with self._db.app_session(user_id=inp.user_id, scope_id=inp.scope_id) as conn:
            if inp.conversation_id is not None:
                atual = await convs.travar(conn, inp.conversation_id)
                if atual is not None and atual.status in ("encerrada", "processada"):
                    # Escrever reabre. O job de inatividade encerra depois de 30 minutos de
                    # silêncio, e antes disso a conversa virava só-leitura PARA SEMPRE: quem
                    # voltasse no dia seguinte tinha que recomeçar do zero.
                    if await convs.reabrir(conn, inp.conversation_id):
                        atual = await convs.travar(conn, inp.conversation_id)
                if atual is None or atual.status != "aberta":
                    yield ev.Erro(tipo="conversa_indisponivel", mensagem=str(inp.conversation_id))
                    return
                rota = Rota(agent_code=atual.agent_code, mode="continuacao")
            agent = await convs.agente(conn, rota.agent_code)
            if agent is None or not agent.is_active or not agent.is_user_facing:
                yield ev.Erro(tipo="agente_indisponivel", mensagem=rota.agent_code)
                return
            plano = await identity_repo.plano_do_escopo(conn, inp.scope_id)
            if _ORDEM_PLANOS[plano] < _ORDEM_PLANOS[agent.min_plan]:
                yield ev.Paywall(gate_code=f"agente_{agent.code}_min_plan",
                                 mensagem=f"O agente {agent.display_name} exige o plano {agent.min_plan}.")
                return
            try:
                prompt = await PromptLoader(conn).carregar_para_agente(agent.code)
            except PromptNotApproved as e:
                yield ev.Erro(tipo="prompt_nao_aprovado", mensagem=str(e))
                return
            contexto = await pacote_do_escopo(conn, inp.scope_id)
            cobertura = await cobertura_mercado(conn) if "cobertura_mercado" in prompt.variables else None

        modo = inp.mode if inp.mode != "standard" else getattr(rota, "modo", "standard")
        if modo == "research" and agent.code != "analista":
            yield ev.Erro(tipo="modo_indisponivel", mensagem=f"análise aprofundada só existe para o Analista (agente {agent.code})")
            return

        yield ev.Routed(agent_code=agent.code, mode=rota.mode, confidence=rota.confidence, reason=rota.reason)

        # ---------- Tx A: conversa + pergunta + cota
        try:
            async with self._db.app_session(user_id=inp.user_id, scope_id=inp.scope_id) as conn:
                if inp.conversation_id is not None:
                    conversa = await convs.travar(conn, inp.conversation_id)
                    conversation_id, seq = conversa.id, conversa.message_count + 1
                else:
                    conversation_id = await convs.criar(
                        conn, scope_id=inp.scope_id, user_id=inp.user_id, agent_code=agent.code,
                        plan_code=plano,
                        metadata={"routing": {"mode": rota.mode, "confidence": rota.confidence,
                                              "reason": rota.reason, "chip_id": inp.chip_id,
                                              "model_call_id": rota.model_call_id}})
                    seq = 1
                user_msg_id = await convs.inserir_mensagem(
                    conn, conversation_id=conversation_id, scope_id=inp.scope_id, seq=seq,
                    role="user", content=texto)
                analysis_id = cutoff = msg_pendente = None
                if agent.code == "analista":   # F5: toda pergunta ao Analista é uma análise point-in-time
                    orc = await self._policies.payload("LLM_BUDGETS")
                    research = await self._policies.payload("ANALISE_RESEARCH") if modo == "research" else {}
                    analysis_id, cutoff = await analysis.criar(
                        conn, scope_id=inp.scope_id, user_id=inp.user_id, conversation_id=conversation_id,
                        question=texto, mode=modo, max_replans=orc.get("max_replans_por_analise"),
                        budget={"max_usd": orc.get("max_usd_por_analise"), "max_tasks": research.get("max_tasks")})
                    if modo == "research":     # F6: o relatório chega por job, nesta conversa
                        msg_pendente = await convs.inserir_mensagem(
                            conn, conversation_id=conversation_id, scope_id=inp.scope_id, seq=seq + 1, role="agent",
                            content=TEXTO_ANALISE_EM_ANDAMENTO, content_json={"analysis_id": analysis_id, "status": "received"})
        except QuotaExceeded as e:
            async with self._db.app_session(user_id=inp.user_id, scope_id=inp.scope_id) as conn:
                await conn.execute(
                    "insert into analytics.paywall_impressions (user_id, scope_id, gate_code, plan_shown) "
                    "values (%s, %s, %s, %s::billing.plan_code)",
                    (inp.user_id, inp.scope_id, f"agente_{agent.code}_cota", plano))
            yield ev.Paywall(gate_code=f"agente_{agent.code}_cota", mensagem=e.mensagem)
            return

        if modo == "research":
            yield ev.Delta(texto=TEXTO_ANALISE_EM_ANDAMENTO)
            yield ev.AnalysisQueued(analysis_id=analysis_id, conversation_id=conversation_id, message_id=msg_pendente)
            if self._enfileirar_analise is not None:
                await self._enfileirar_analise(analysis_id)
            yield ev.Done(conversation_id=conversation_id, message_id=msg_pendente, cited_refs=[])
            return

        # ---------- parametrização
        budget = TurnBudget.from_policy(await self._policies.payload("LLM_BUDGETS"))
        conv_cfg = await self._policies.payload("AGENT_CONVERSATIONS")
        limite_hist = conv_cfg.get("max_historico_mensagens")
        max_tools = int(conv_cfg.get("max_tools_por_turno", _PADRAO_MAX_TOOLS))
        max_erros = int(conv_cfg.get("max_erros_de_tool_por_turno", _PADRAO_MAX_ERROS_DE_TOOL))
        chars_hist = conv_cfg.get("max_chars_resultado_no_historico")
        max_blocos = int(conv_cfg.get("max_blocos_por_mensagem", blocos_mod.PADRAO_MAX_BLOCOS))
        max_pontos = int(conv_cfg.get("max_pontos_por_bloco", blocos_mod.PADRAO_MAX_PONTOS))
        blocos_msg: list[dict] = []          # F11: o que a tela viu ao vivo = o que fica em content_json
        mudancas: list[dict[str, Any]] = []   # F14: saídas de contexto.verificar_mudanca do turno
        propostas_criadas: list[dict[str, Any]] = []
        variaveis = {"contexto_escopo": contexto, "cobertura_mercado": cobertura}
        system = prompt.render(**{k: v for k, v in variaveis.items() if k in prompt.variables})
        mensagens = [Message(role="system", content=system)]
        if inp.conversation_id is not None:
            async with self._db.app_session(user_id=inp.user_id, scope_id=inp.scope_id) as conn:
                for role, content in await convs.historico(conn, conversation_id, limite_hist,
                                                           max_chars_resultado=chars_hist):
                    mensagens.append(Message(role="assistant" if role == "agent" else "user", content=content))
        mensagens.append(Message(role="user", content=texto))
        tools = [ToolDef(name=s.code, description=s.description, parameters=s.param_schema)
                 for s in filtrar_tools(specs_registradas(), familias=agent.allowed_tool_families, plano=plano)]
        meta = dict(agent_code=agent.code, scope_id=inp.scope_id, conversation_id=conversation_id,
                    message_id=user_msg_id, prompt_version_id=prompt.id, analysis_id=analysis_id)

        # ---------- laço único de tool-use (F8)
        executadas: list[tuple[str, ToolResult]] = []
        texto_final: str | None = None
        sintese_call_id: str | None = None
        handoff: dict | None = None
        erros_de_tool = 0
        texto_fixo_do_erro: str | None = None
        purpose = "parametrizacao"
        visto = ""                     # o que o cliente já tem na tela (deltas ao vivo desta resposta)
        yield ev.Status(fase="entendendo")
        while True:
            pode_encadear = len(executadas) < max_tools
            saida: dict = {}
            try:
                async for evento in self._chamar_stream(ChatRequest(
                        messages=mensagens, tools=(tools + [ENCAMINHAR]) if pode_encadear else [],
                        tool_choice="auto" if pode_encadear else "none",
                        # `tokens_para` guarda a reserva da redação enquanto o turno ainda
                        # pode encadear tool; na chamada forçada a texto, devolve tudo.
                        max_output_tokens=min(
                            budget.tokens_para("parametrizacao" if pode_encadear else "sintese"),
                            budget.max_output_tokens),
                        metadata=CallMeta(purpose=purpose, **meta)), budget, acum, saida):
                    yield evento
                resp = saida["resp"]
                visto = saida.get("emitido", "")
            except BudgetExceeded as e:
                async for evento in self._fechar_por_orcamento(conversation_id, seq, inp, acum, str(e),
                                                               tool_result=executadas[-1][1] if executadas else None,
                                                               analysis_id=analysis_id):
                    yield evento
                return
            except ProviderUnavailable as e:
                yield ev.Erro(tipo="provedor_indisponivel", mensagem=str(e))
                return
            purpose = "sintese"
            sintese_call_id = getattr(resp, "model_call_id", None)
            chamadas: list[ToolCall] = list(resp.tool_calls) if pode_encadear else []
            if not chamadas:
                texto_final = resp.text
                break
            if visto:                  # texto que acompanhou uma tool_call não é a leitura: some da tela
                yield ev.Replace(texto="")
                visto = ""
            encaminhar = next((c for c in chamadas if c.name == "encaminhar"), None)
            if encaminhar is not None:
                handoff = {"para": encaminhar.arguments.get("agent_code", "assessor"),
                           "motivo": encaminhar.arguments.get("motivo", "")}
                texto_final = resp.text
                break
            # executa TODAS as chamadas da resposta, na ordem; cada uma recebe a sua resposta (ou o seu erro)
            respostas: list[tuple[ToolCall, str]] = []
            for chamada in chamadas:
                if len(executadas) >= max_tools:
                    respostas.append((chamada, canonical_json(
                        {"erro": "limite_de_tools", "detalhe": f"máximo de {max_tools} medições por turno já atingido; "
                                                              "responda com o que já foi medido"})))
                    continue
                yield ev.Status(fase=f"calculando:{chamada.name}")
                try:
                    async with self._db.app_session(user_id=inp.user_id, scope_id=inp.scope_id) as conn:
                        resultado = await executar_tool(conn, chamada.name, chamada.arguments,
                                                        scope_id=inp.scope_id, conversation_id=conversation_id,
                                                        cutoff_date=cutoff, analysis_id=analysis_id)
                except (ToolParamsInvalid, ToolInsumoFaltante, ToolConteudoIndisponivel) as e:
                    erros_de_tool += 1
                    codigo, detalhe, texto_fixo_do_erro = _erro_de_tool(e)
                    respostas.append((chamada, canonical_json({"erro": codigo, "detalhe": detalhe})))
                    continue
                except DbError as e:
                    yield ev.Erro(tipo="gate_do_banco", mensagem=e.mensagem)
                    return
                executadas.append((chamada.name, resultado))
                # F13b: o output de tool é o único texto client-facing que nunca passava por
                # checagem. Aqui REGISTRA e segue — o gate que barra é a aprovação do documento
                # no banco (34). Bloquear aqui apagaria uma resposta correta por causa de um
                # texto que um humano já aprovou.
                saida_json = resultado.output.model_dump(mode="json")
                vetados = guardrails.vocabulario_em_tool(saida_json)
                if vetados:
                    acum.guardrails.append(("vocabulario_proibido", "registrado",
                                            f"{chamada.name}: {', '.join(vetados)}"))
                yield ev.ToolDone(code=chamada.name, execution_id=resultado.execution_id, cache_hit=resultado.cache_hit)
                for bloco in blocos_mod.blocos_de(chamada.name, saida_json,
                                                  execution_id=resultado.execution_id,
                                                  max_blocos=max(0, max_blocos - len(blocos_msg)), max_pontos=max_pontos):
                    blocos_msg.append(bloco)
                    yield ev.Bloco(execution_id=resultado.execution_id, bloco=bloco)
                # F14: o modelo notou um número novo sobre a vida do cliente. A tool só
                # COMPARA; quem grava é a Tx B, porque o executor devolve output de cache
                # sem executar — uma tool que escrevesse seria pulada na segunda vez.
                if chamada.name == TOOL_VERIFICAR_MUDANCA:
                    mudancas.append(saida_json)
                respostas.append((chamada, canonical_json(saida_json)))
            if erros_de_tool > max_erros:
                # O modelo insistiu no erro além do teto: texto fixo de último recurso (registrado).
                texto_final = texto_fixo_do_erro
                acum.guardrails.append(("outro", "bloqueado", f"teto_de_erros_de_tool:{erros_de_tool}"))
                break
            mensagens.append(Message(role="assistant", tool_calls=chamadas,
                                     reasoning_content=getattr(resp, "reasoning_content", None)))
            for chamada, conteudo in respostas:
                mensagens.append(Message(role="tool", tool_call_id=chamada.id, name=chamada.name, content=conteudo))
            if executadas:
                yield ev.Status(fase="sintetizando")

        tool_result: ToolResult | None = executadas[-1][1] if executadas else None

        # ---------- guardrail pós + handoff
        if handoff is not None and not (texto_final or "").strip():
            texto_final = (f"Isso é assunto para outro agente ({handoff['para']}): {handoff['motivo']}. "
                           "Quer que a próxima conversa seja com ele? Você decide.")
        if not (texto_final or "").strip() and executadas:
            # UMA retentativa antes de desistir. O modelo mediu e não escreveu — quase sempre
            # por falta de espaço (a reserva da 51 ataca a causa; isto é a segunda rede) ou
            # porque gastou o fôlego raciocinando. Pedir de novo, sem tools e com instrução
            # explícita, custa uma chamada e devolve a resposta que o cliente esperava.
            try:
                retomada = await self._chamar(ChatRequest(
                    messages=mensagens + [Message(role="user", content=INSTRUCAO_REDIGIR)],
                    max_output_tokens=budget.tokens_para("sintese"),
                    metadata=CallMeta(purpose="sintese", **meta)), budget, acum)
                if (retomada.text or "").strip():
                    texto_final = retomada.text
                    sintese_call_id = getattr(retomada, "model_call_id", sintese_call_id)
                    acum.guardrails.append(("outro", "registrado", "sintese_refeita"))
            except (BudgetExceeded, ProviderUnavailable):
                pass
        if not (texto_final or "").strip():
            texto_final = guardrails.texto_seguro_tool([code for code, _ in executadas])
            acum.guardrails.append(("outro", "bloqueado", "sintese_vazia"))
        achados = guardrails.vocabulario(texto_final or "")
        if achados:
            reescrito = None
            try:
                reparo = await self._chamar(ChatRequest(
                    messages=mensagens + [Message(role="assistant", content=texto_final),
                                          Message(role="user", content=guardrails.instrucao_de_reescrita(achados))],
                    max_output_tokens=budget.tokens_restantes(),
                    metadata=CallMeta(purpose="guardrail", **meta)), budget, acum)
                reescrito = reparo.text
                sintese_call_id = getattr(reparo, "model_call_id", sintese_call_id)
            except (BudgetExceeded, ProviderUnavailable):
                pass
            if reescrito and not guardrails.vocabulario(reescrito):
                texto_final = reescrito
                acum.guardrails.append(("vocabulario_proibido", "reescrito", ", ".join(achados)))
            else:
                texto_final = guardrails.TEXTO_SEGURO_VOCABULARIO
                acum.guardrails.append(("vocabulario_proibido", "bloqueado", ", ".join(achados)))
        limpo, vazou = guardrails.limpar_marcacao_de_tool(texto_final or "")
        if vazou:
            # O provedor "respondeu" com uma chamada de ferramenta em texto. Uma tentativa de reparo, SEM
            # tools, pedindo a leitura só com o que já foi medido; se ainda vazar, texto seguro do agente.
            reparado = None
            try:
                reparo = await self._chamar(ChatRequest(
                    messages=mensagens + [Message(role="assistant", content=guardrails.RESPOSTA_DESCARTADA),
                                          Message(role="user", content=guardrails.INSTRUCAO_SEM_TOOL)],
                    tools=[], tool_choice="none",
                    max_output_tokens=budget.tokens_restantes(),
                    metadata=CallMeta(purpose="guardrail", **meta)), budget, acum)
                reparado, vazou_de_novo = guardrails.limpar_marcacao_de_tool(reparo.text or "")
                if vazou_de_novo or not reparado.strip() or guardrails.vocabulario(reparado):
                    reparado = None
                else:
                    sintese_call_id = getattr(reparo, "model_call_id", sintese_call_id)
            except (BudgetExceeded, ProviderUnavailable) as e:
                acum.guardrails.append(("limite_orcamento_llm", "registrado", f"reparo_de_marcacao_descartado: {e}"))
            if reparado:
                texto_final = reparado
                acum.guardrails.append(("outro", "reescrito", "marcacao_de_tool_vazada"))
            else:
                texto_final = limpo or guardrails.texto_seguro_tool([code for code, _ in executadas])
                acum.guardrails.append(("outro", "bloqueado", "marcacao_de_tool_vazada"))
        texto_final = guardrails.garantir_ilustrativo(
            texto_final or "", houve_calculo=any(spec_de(code).emite_numero for code, _ in executadas))

        # ---------- entrega ao cliente: o que faltou (rodapé) como Delta; texto diferente do visto = Replace
        texto_final = texto_final or ""
        if visto and texto_final.startswith(visto):
            if texto_final[len(visto):]:
                yield ev.Delta(texto=texto_final[len(visto):])
        elif visto:
            yield ev.Replace(texto=texto_final)
        else:
            for frase in re.split(r"(?<=[.!?\n])\s+", texto_final):
                if frase:
                    yield ev.Delta(texto=frase + " ")

        # ---------- Tx B
        cited: list[dict[str, Any]] = []
        for _code, r in executadas:
            cited.append({"kind": "tool_execution", "id": r.execution_id})
            cited.extend({"kind": "policy", "code": m["code"], "version": m["version"]}
                         for m in r.politicas_meta)
            # Educador (F4): conteúdo aprovado citado pela tool (slugs de content.v_education_approved)
            slugs = getattr(r.output, "slugs", None) or ([r.output.slug] if getattr(r.output, "slug", None) else [])
            cited.extend({"kind": "education_content", "slug": sl} for sl in slugs)
            # Analista (F5): preço/índice point-in-time citados pela tool
            cited.extend(analysis.cited_refs_de(getattr(r.output, "evidencia", None)))
            # F13a: documento oficial citado pela tool `contexto.*` (url e data vão para a tela).
            # DENTRO do laço: fora dele, só a última tool era lida — e o turno quebrava com
            # UnboundLocalError quando nenhuma tool rodava (resposta puramente textual).
            cited.extend(analysis.cited_refs_documentais(getattr(r.output, "evidencia_documental", None)))
        async with self._db.app_session(user_id=inp.user_id, scope_id=inp.scope_id) as conn:
            if analysis_id is not None:
                ids_findings, com_avisos = await analysis.registrar_findings(conn, analysis_id, executadas)
                cited.extend({"kind": "analysis_finding", "id": fid} for fid in ids_findings)
                await analysis.finalizar(conn, analysis_id,
                                         analysis.STATUS_CANCELADA if (handoff is not None or not executadas)
                                         else analysis.STATUS_COM_AVISOS if com_avisos else analysis.STATUS_FINAL)
            conversa = await convs.travar(conn, conversation_id)
            msg_id = await convs.inserir_mensagem(
                conn, conversation_id=conversation_id, scope_id=inp.scope_id,
                seq=conversa.message_count + 1, role="agent", content=texto_final,
                content_json=({"handoff": handoff} if handoff else {}) | ({"blocos": blocos_msg} if blocos_msg else {}) or None,
                tool_execution_id=tool_result.execution_id if tool_result else None,
                model_call_id=sintese_call_id, cited_refs=cited)
            for kind, action, detalhe in acum.guardrails:
                await conn.execute(
                    "insert into agents.guardrail_events (conversation_id, message_id, scope_id, kind, action_taken, details) "
                    "values (%s, %s, %s, %s, %s, %s)",
                    (conversation_id, msg_id, inp.scope_id, kind, action,
                     Jsonb({"detalhe": detalhe})))
            if tool_result is not None and getattr(tool_result.output, "indicado_por_terceiro", False):
                await second_opinion.registrar(
                    conn, scope_id=inp.scope_id, user_id=inp.user_id, agent_message_id=msg_id,
                    user_message_id=user_msg_id, tool_execution_id=tool_result.execution_id,
                    produto=tool_result.output.model_dump(mode="json"))
            # F14: mudança de contexto notada no turno vira PROPOSTA — nunca escrita direta.
            # As evidências são as mensagens reais deste turno (a do cliente e a do agente),
            # e o banco recusa o que for imaterial, repetido ou acima do teto da semana.
            for saida in mudancas:
                try:
                    criada = await ctx_propostas.propor_do_turno(
                        conn, scope_id=inp.scope_id, user_id=inp.user_id,
                        conversation_id=conversation_id,
                        message_ids=[user_msg_id, msg_id], saida_tool=saida)
                except ctx_propostas.PropostaRecusada as e:
                    # Recusa de governança não derruba o turno: o cliente já teve a resposta.
                    acum.guardrails.append(("outro", "registrado", f"proposta_recusada:{e}"))
                    continue
                if criada is not None:
                    propostas_criadas.append(criada.para_evento())

            acum.tool_executions = len(executadas)
            await self._upsert_cost_ledger(conn, inp.scope_id, conversation_id, acum)

        if handoff is not None:
            yield ev.HandoffSuggested(para=handoff["para"], motivo=handoff["motivo"])
        for proposta in propostas_criadas:
            yield ev.Proposta(proposta=proposta)
        yield ev.Done(conversation_id=conversation_id, message_id=msg_id, cited_refs=cited)

    # ------------------------------------------------------------------ auxiliares
    async def _rotear_por_llm(self, texto: str, acum: _Acumulado):
        routing_cfg = await self._policies.payload("AGENT_ROUTING")
        async with self._db.app_session(user_id=self._user, scope_id=self._scope) as conn:
            prompt = await PromptLoader(conn).carregar_por_code("copiloto.router")
            opcoes = await convs.agentes_visiveis(conn)
        budget = TurnBudget.from_policy(await self._policies.payload("LLM_BUDGETS"))
        variaveis = {"pergunta": texto, "agentes": opcoes}
        try:
            resp = await self._chamar(ChatRequest(
                messages=[Message(role="system", content=prompt.render(
                    **{k: v for k, v in variaveis.items() if k in prompt.variables}))],
                response_format={"type": "json_object"},
                metadata=CallMeta(purpose="intencao", agent_code=None, scope_id=self._scope)), budget, acum)
        except ProviderUnavailable as e:
            yield ev.Erro(tipo="provedor_indisponivel", mensagem=str(e))
            return
        intencao = router.parse_intencao(resp.text)
        minimo = float(routing_cfg.get("min_confidence") or 0)
        if intencao.agent_code in {o["code"] for o in opcoes} and intencao.confidence >= minimo:
            yield Rota(agent_code=intencao.agent_code, mode="auto", confidence=intencao.confidence,
                       reason=intencao.reason, model_call_id=getattr(resp, "model_call_id", None))
        else:
            # Saudação, pergunta sobre o Copiloto ou assunto fora de finanças: a resposta curta do modelo
            # (se passar no vocabulário) — sem conversa, sem cota. Senão, a pergunta padrão.
            curta = (intencao.resposta_curta or "").strip()
            if curta and guardrails.vocabulario(curta):
                acum.guardrails.append(("vocabulario_proibido", "bloqueado", "resposta_curta_do_roteador"))
                curta = ""
            yield ev.Clarify(
                mensagem=curta or router.MENSAGEM_CLARIFY_PADRAO,
                opcoes=[{"code": o["code"], "display_name": o["display_name"]} for o in opcoes])

    async def _fechar_por_orcamento(self, conversation_id: str, seq_base: int, inp: TurnoInput,
                                    acum: _Acumulado, detalhe: str, tool_result: ToolResult | None = None,
                                    analysis_id: str | None = None):
        acum.guardrails.append(("limite_orcamento_llm", "bloqueado", detalhe))
        async with self._db.app_session(user_id=inp.user_id, scope_id=inp.scope_id) as conn:
            if analysis_id is not None:
                await analysis.finalizar(conn, analysis_id, analysis.STATUS_BLOQUEADA)
            conversa = await convs.travar(conn, conversation_id)
            msg_id = await convs.inserir_mensagem(
                conn, conversation_id=conversation_id, scope_id=inp.scope_id,
                seq=conversa.message_count + 1, role="agent",
                content=guardrails.TEXTO_SEGURO_ORCAMENTO,
                tool_execution_id=tool_result.execution_id if tool_result else None)
            for kind, action, det in acum.guardrails:
                await conn.execute(
                    "insert into agents.guardrail_events (conversation_id, message_id, scope_id, kind, action_taken, details) "
                    "values (%s, %s, %s, %s, %s, %s)",
                    (conversation_id, msg_id, inp.scope_id, kind, action,
                     Jsonb({"detalhe": det})))
            acum.tool_executions = 1 if tool_result is not None else 0
            await self._upsert_cost_ledger(conn, inp.scope_id, conversation_id, acum)
        yield ev.Done(conversation_id=conversation_id, message_id=msg_id, cited_refs=[])

    async def _upsert_cost_ledger(self, conn, scope_id: str, conversation_id: str, acum: _Acumulado):
        await upsert_cost_ledger(conn, scope_id=scope_id, ref_kind="conversation", ref_id=conversation_id,
                                 call_ids=acum.call_ids, input_tokens=acum.input_tokens,
                                 cached_tokens=acum.cached_tokens, output_tokens=acum.output_tokens,
                                 tool_executions=acum.tool_executions)
