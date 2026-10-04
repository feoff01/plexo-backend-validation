"""
F9 — Streaming token a token do provedor no turno.

Contrato: enquanto o provedor devolve texto, o turno emite `Delta` ao vivo; ao final, os guardrails rodam
sobre o texto completo e a tela recebe só o que faltou (`Delta` do rodapé) ou a substituição (`Replace`).
O que o cliente "vê" (acumulado de Delta/Replace) é SEMPRE igual ao que foi gravado em agents.messages.
Marcação de tool vazada e vocabulário vetado nunca chegam ao cliente nem por um instante.
"""
from __future__ import annotations

import pytest

from app.agents import eventos as ev
from app.agents.turn import TurnoCopiloto, TurnoInput
from app.config.policies import PolicyStore
from app.llm.client import ChatRequest, ChatResponse, ToolCall, Usage
from app.llm.fake import FakeLLM
from tests.test_f8_turno_conversacional import _resp, _tc, mundo  # noqa: F401  (fixture reutilizada)


def _visto(eventos) -> str:
    """Simula a tela: Delta acumula, Replace substitui."""
    acumulado = ""
    for e in eventos:
        if isinstance(e, ev.Delta):
            acumulado += e.texto
        elif isinstance(e, ev.Replace):
            acumulado = e.texto
    return acumulado.strip()


async def _rodar(db, llm, **kw):
    turno = TurnoCopiloto(db=db, llm=llm, policies=PolicyStore(db, ttl_s=0))
    return [e async for e in turno.executar(TurnoInput(**kw))]


async def _gravado(db, conversation_id) -> str:
    async with db.service_session() as conn:
        cur = await conn.execute("select content from agents.messages where conversation_id = %s and role = 'agent'", (conversation_id,))
        return (await cur.fetchone())[0].strip()


class LLMSemStream:
    """Provedor antigo: só `chat`. O turno tem que continuar funcionando (deltas por frase)."""
    provider = "fake"

    def __init__(self, respostas):
        self._r = list(respostas)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return self._r.pop(0)


async def test_deltas_chegam_ao_vivo_antes_do_done_e_batem_com_o_gravado(db, mundo):
    e = mundo
    fake = FakeLLM([_resp(texto="Primeira frase da leitura. Segunda frase, com detalhe. Terceira e última.")], trechos=5)
    eventos = await _rodar(db, fake, texto="me explica como pensar a reserva?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    deltas = [x for x in eventos if isinstance(x, ev.Delta)]
    assert len(deltas) >= 3                                   # token a token (trechos), não uma frase só
    assert isinstance(eventos[-1], ev.Done)
    assert not any(isinstance(x, ev.Replace) for x in eventos)  # nada a corrigir: nenhuma substituição
    assert _visto(eventos) == await _gravado(db, eventos[-1].conversation_id)
    assert fake.streams == 1                                  # a chamada foi feita em modo stream


async def test_texto_que_acompanha_tool_call_nao_fica_na_tela(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(texto="Vou medir a sua capacidade.", tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Sua capacidade estimada aparece abaixo."),
    ], trechos=4)
    eventos = await _rodar(db, fake, texto="quanto posso aportar?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    idx_tool = next(i for i, x in enumerate(eventos) if isinstance(x, ev.ToolDone))
    antes = [x for x in eventos[:idx_tool] if isinstance(x, ev.Delta)]
    # ou nada foi emitido antes da tool, ou o que foi emitido é apagado (Replace vazio) antes da leitura final
    if antes:
        idx_replace = next(i for i, x in enumerate(eventos) if isinstance(x, ev.Replace) and x.texto == "")
        assert idx_replace > eventos.index(antes[-1])
        assert not any(isinstance(x, ev.Delta) for x in eventos[eventos.index(antes[-1]) + 1:idx_replace])
    assert _visto(eventos) == await _gravado(db, eventos[-1].conversation_id)
    assert "Vou medir" not in _visto(eventos)
    assert "ilustrativ" in _visto(eventos).lower()


async def test_rodape_ilustrativo_chega_como_delta_final_sem_replace(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Capacidade estimada: R$ 14.000,00 por mês, pelo piso da renda variável."),
    ], trechos=6)
    eventos = await _rodar(db, fake, texto="quanto posso aportar?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert not any(isinstance(x, ev.Replace) for x in eventos)
    deltas = [x for x in eventos if isinstance(x, ev.Delta)]
    assert "ILUSTRATIVA" in deltas[-1].texto                   # o rodapé é o último delta, não uma substituição
    assert _visto(eventos) == await _gravado(db, eventos[-1].conversation_id)


async def test_marcacao_de_tool_vazada_em_stream_nunca_chega_ao_cliente(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Sua capacidade é boa. <｜DSML｜tool_calls>orcamento.reserva_emergencia{}</｜DSML｜tool_calls>"),
        _resp(texto="Sua capacidade estimada está registrada abaixo."),   # reparo sem tools
    ], trechos=5)
    eventos = await _rodar(db, fake, texto="quanto posso aportar?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert not any("DSML" in x.texto for x in eventos if isinstance(x, (ev.Delta, ev.Replace)))
    assert any(isinstance(x, ev.Replace) for x in eventos)
    assert _visto(eventos) == await _gravado(db, eventos[-1].conversation_id)
    assert "registrada abaixo" in _visto(eventos)


async def test_vocabulario_vetado_em_stream_vira_replace_com_a_reescrita(db, mundo):
    e = mundo
    fake = FakeLLM([
        _resp(tool_calls=[_tc("orcamento.capacidade_aporte", {})]),
        _resp(texto="Recomendo aportar R$ 14.000,00 por mês."),
        _resp(texto="Diagnóstico: a capacidade estimada é R$ 14.000,00 por mês. A decisão é sua."),
    ], trechos=4)
    eventos = await _rodar(db, fake, texto="quanto posso aportar?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    assert any(isinstance(x, ev.Replace) and "Diagnóstico" in x.texto for x in eventos)
    assert "recomendo" not in _visto(eventos).lower()
    assert _visto(eventos) == await _gravado(db, eventos[-1].conversation_id)


async def test_model_calls_grava_usage_do_trecho_final(db, mundo):
    e = mundo
    resp = ChatResponse(text="Leitura curta.", tool_calls=[], usage=Usage(321, 0, 77), finish_reason="stop",
                        model="fake-m", provider="fake", latency_ms=9)
    fake = FakeLLM([resp], trechos=3)
    eventos = await _rodar(db, fake, texto="oi?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    async with db.service_session() as conn:
        cur = await conn.execute("select input_tokens, output_tokens from llm.model_calls where conversation_id = %s",
                                 (eventos[-1].conversation_id,))
        assert (await cur.fetchone()) == (321, 77)


async def test_provedor_sem_chat_stream_continua_funcionando_por_frase(db, mundo):
    e = mundo
    eventos = await _rodar(db, LLMSemStream([_resp(texto="Frase um. Frase dois.")]),
                           texto="oi?", user_id=e.u1, scope_id=e.s1, agent_code="assessor")
    deltas = [x for x in eventos if isinstance(x, ev.Delta)]
    assert len(deltas) == 2
    assert _visto(eventos) == await _gravado(db, eventos[-1].conversation_id)


def test_fake_llm_stream_reparte_o_texto_e_registra_a_requisicao():
    fake = FakeLLM([_resp(texto="abcdefghij")], trechos=3)
    import asyncio

    async def go():
        trechos = [t async for t in fake.chat_stream(ChatRequest(messages=[], metadata=None))]  # type: ignore[arg-type]
        return trechos
    trechos = asyncio.run(go())
    assert "".join(t.texto for t in trechos if t.texto) == "abcdefghij"
    assert trechos[-1].final is not None and trechos[-1].final.text == "abcdefghij"
    assert len(fake.requisicoes) == 1 and fake.streams == 1
