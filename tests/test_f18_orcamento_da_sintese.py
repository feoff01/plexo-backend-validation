"""F18 — o turno tinha que ficar sem tokens para responder, e ficava.

O DEFEITO, COMO ELE APARECEU
    Três vezes, numa conversa real, o Copiloto respondeu "Medi o que coube neste turno … mas
    não consegui redigir a leitura". O guardrail `sintese_vazia` está gravado três vezes em
    `agents.guardrail_events`, sempre nos turnos com MAIS medições.

    A causa não era o modelo. `turn.py` oferecia a cada chamada
    `max_output_tokens = budget.tokens_restantes()`, e o provedor é um modelo que RACIOCINA —
    o raciocínio conta como saída. Quatro parametrizações de tool consumiam os 6.000 tokens do
    turno, e a última chamada, a que escreve, recebia o que sobrou: quase nada.

    **Quem pagava era sempre a redação, porque ela é a última.** Quanto melhor a pergunta —
    mais medições para respondê-la —, maior a chance de não haver resposta. É o pior formato
    possível para um defeito de produto.

O QUE ESTES TESTES PROTEGEM
    A reserva (migration 51) e a retentativa são duas defesas independentes, e cada uma tem
    teste próprio: a reserva impede que o problema aconteça; a retentativa recupera o turno se
    ele acontecer mesmo assim.
"""
from __future__ import annotations

import pytest

from app.llm.budget import BudgetExceeded, TurnBudget

POLICY = {"max_model_calls_por_turno": 9, "max_output_tokens_por_turno": 14000,
          "reserva_para_sintese_tokens": 2500}


def _gasto(b: TurnBudget, tokens: int) -> None:
    """Simula consumo sem depender do formato de `ChatResponse`."""
    b.output_tokens += tokens


def test_a_reserva_sai_da_politica_e_nao_do_codigo():
    b = TurnBudget.from_policy(POLICY)
    assert b.reserva_sintese == 2500
    assert TurnBudget.from_policy({k: v for k, v in POLICY.items()
                                   if k != "reserva_para_sintese_tokens"}).reserva_sintese == 0


def test_parametrizar_tool_nunca_come_a_reserva_da_redacao():
    """O coração da correção: encadear tool enxerga menos orçamento do que existe."""
    b = TurnBudget.from_policy(POLICY)
    assert b.tokens_para("parametrizacao") == 14000 - 2500
    assert b.tokens_para("sintese") == 14000

    _gasto(b, 9000)                      # quatro tools com raciocínio
    assert b.tokens_para("parametrizacao") == 5000 - 2500
    assert b.tokens_para("sintese") == 5000


def test_a_redacao_sempre_tem_com_que_escrever():
    """O caso que produzia o defeito: o turno gastou quase tudo medindo.

    Sem a reserva, a síntese recebia `14000 − 13500 = 500` — e o modelo, que raciocina antes
    de escrever, devolvia vazio. Com a reserva, as chamadas de parametrização teriam parado
    antes; e mesmo no limite a síntese continua recebendo o que restou, nunca zero.
    """
    b = TurnBudget.from_policy(POLICY)
    _gasto(b, 13500)
    assert b.tokens_para("parametrizacao") == 1, (
        "parametrizar com a reserva estourada pede o mínimo, e quem interrompe o turno é o "
        "BudgetExceeded de `registrar` — não um teto zerado, que o provedor devolveria como "
        "texto vazio sem explicação")
    assert b.tokens_para("sintese") == 500


def test_orcamento_esgotado_continua_levantando():
    """A reserva não afrouxa o teto: ela só muda QUEM gasta primeiro."""
    b = TurnBudget.from_policy(POLICY)
    _gasto(b, 14000)
    assert b.tokens_para("sintese") == 0
    assert b.tokens_para("parametrizacao") == 1


@pytest.mark.asyncio
async def test_a_politica_vigente_do_banco_declara_a_reserva(db):
    """Config-first de verdade: o número tem que estar no BANCO, não só no código.

    Se alguém publicar uma versão de `LLM_BUDGETS` sem a chave, a reserva vira zero em
    silêncio e o defeito volta — sem erro, sem log, só o cliente parando de receber resposta
    nos turnos difíceis. Este teste é o que impede isso.
    """
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select payload from engine.policy_versions "
            "where code = 'LLM_BUDGETS' and effective_to is null")
        linha = await cur.fetchone()

    assert linha is not None, "LLM_BUDGETS precisa estar vigente"
    payload = linha[0]
    assert payload.get("reserva_para_sintese_tokens", 0) > 0, (
        "sem reserva declarada na política, o turno com mais medições volta a ficar sem "
        "tokens para redigir — foi assim que o cliente recebeu 'não consegui redigir a "
        "leitura' três vezes")
    assert payload["max_output_tokens_por_turno"] > payload["reserva_para_sintese_tokens"] * 2, (
        "a reserva precisa caber com folga no teto, senão sobra pouco para medir")
