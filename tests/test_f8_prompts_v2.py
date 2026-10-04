"""
F8 — Prompts v2 dos agentes e do roteador, cobertura de mercado no contexto e exceções de vocabulário.

Decisões do usuário (2026-08-25): Educador explica com conhecimento geral ROTULADO fora da base aprovada
(sem números, sem opinião sobre produto); Assessor faz leitura qualitativa SEM número quando não há tool;
Analista recebe a cobertura de mercado no prompt; roteador devolve `resposta_curta` para saudação/meta/
fora de finanças; "custo de oportunidade" deixa de derrubar a resposta inteira.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import pytest_asyncio

from app.agents import eventos as ev
from app.agents.turn import TurnoCopiloto, TurnoInput
from app.config.policies import PolicyStore
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.db.repos.prompts import encontrar_vocabulario_proibido, termos_proibidos, vocabulario_excecoes
from app.llm.client import ChatResponse, ToolCall, Usage
from app.llm.fake import FakeLLM
from app.llm.prompts import variaveis_do_template
from app.tools import carregar_tools
from app.tools.context_pack import cobertura_mercado, pacote_do_escopo
from app.tools.registry import specs_registradas
from app.tools.sync import sincronizar
from tests.test_f4_educador import EDUCACAO_EXEMPLOS, EDUCACAO_PARAMS

carregar_tools()

PROMPTS = pathlib.Path(__file__).parent.parent / "prompts"
EDUCADOR = (PROMPTS / "agent.educador.system.j2").read_text(encoding="utf-8")
ASSESSOR = (PROMPTS / "agent.assessor.system.j2").read_text(encoding="utf-8")
ANALISTA = (PROMPTS / "agent.analista.system.j2").read_text(encoding="utf-8")
ROUTER = (PROMPTS / "copiloto.router.j2").read_text(encoding="utf-8")
ROTULO_GERAL = "Explicação geral, não revisada por compliance"


# ---------------------------------------------------------------- estrutura dos prompts (sem banco)
@pytest.mark.parametrize("nome, texto", [("educador", EDUCADOR), ("assessor", ASSESSOR), ("analista", ANALISTA), ("router", ROUTER)])
def test_prompts_v2_sem_pendencia_nem_vocabulario_vetado(nome, texto):
    assert "[PENDENTE" not in texto
    assert encontrar_vocabulario_proibido(texto, termos_proibidos()) == []


def test_prompts_v2_variaveis_exatas():
    assert variaveis_do_template(EDUCADOR) == ["contexto_escopo"]
    assert variaveis_do_template(ASSESSOR) == ["contexto_escopo"]
    assert variaveis_do_template(ANALISTA) == ["cobertura_mercado", "contexto_escopo"]
    assert variaveis_do_template(ROUTER) == ["pergunta"]


def test_educador_v2_explica_fora_da_base_com_rotulo_e_sem_numero():
    assert ROTULO_GERAL in EDUCADOR
    assert "encontrado=false" in EDUCADOR
    assert "## Conversa" in EDUCADOR                       # saudação, follow-up, capacidades, reformulação
    assert "[dados medidos:" in EDUCADOR                   # o modelo sabe ler o histórico com números


def test_assessor_v2_responde_qualitativo_sem_numero_quando_nao_ha_tool():
    assert "qualitativ" in ASSESSOR.lower()
    assert "## Conversa" in ASSESSOR
    assert "p5" in ASSESSOR                                # regra do pessimista junto da mediana continua
    assert "[dados medidos:" in ASSESSOR


def test_analista_v2_conhece_a_cobertura_e_nao_nega_previsao_com_verbo_de_previsao():
    assert "{{ cobertura_mercado }}" in ANALISTA
    assert "## Conversa" in ANALISTA
    assert "correlação não é causalidade" in ANALISTA.lower()
    assert "retorno passado" in ANALISTA.lower() and "não indica" in ANALISTA.lower()


def test_router_v2_devolve_resposta_curta_para_saudacao_e_fora_de_financas():
    assert "resposta_curta" in ROUTER
    assert "null" in ROUTER
    assert "saudação" in ROUTER.lower() or "saudacao" in ROUTER.lower()


# ---------------------------------------------------------------- exceções de vocabulário
def test_vocabulario_respeita_excecoes():
    assert "custo de oportunidade" in vocabulario_excecoes()
    assert encontrar_vocabulario_proibido("O custo de oportunidade de manter o dinheiro parado é a taxa que você deixa de receber.") == []
    assert encontrar_vocabulario_proibido("É uma oportunidade única de investimento.") == ["oportunidade"]
    assert encontrar_vocabulario_proibido("O custo de oportunidade é alto; aproveite a oportunidade.") == ["oportunidade"]


# ---------------------------------------------------------------- cobertura de mercado
@pytest_asyncio.fixture
async def cobertura_semeada(db):
    """Preço e índice NA TRANSAÇÃO DO TESTE. Antes isto dependia do que estava commitado no dev
    ("dados do dev"), o que fazia o teste falhar em banco novo — a mesma armadilha do T43: afirmar
    sobre estado que não se cria."""
    async with db.service_session() as conn:
        cur = await conn.execute(
            "insert into market.ingestion_batches (source_code, dataset, status, file_hash, "
            " finished_at, rows_ingested) values ('b3', 'teste-cobertura', 'succeeded', %s, now(), 3) "
            "returning id::text", ("f" * 64,))
        (lote,) = await cur.fetchone()
        cur = await conn.execute("select id::text from market.instruments where ticker = 'PETR4'")
        (instrumento,) = await cur.fetchone()
        for dias in range(3):
            await conn.execute(
                "insert into market.prices (price_date, instrument_id, kind, value, source_code, "
                " ingestion_batch_id) values (current_date - %s, %s, 'close', 30.0, 'b3', %s) "
                "on conflict do nothing", (dias, instrumento, lote))
        await conn.execute(
            "insert into market.index_values (index_code, value_date, value, ingestion_batch_id) "
            "values ('cdi', current_date, 0.05, %s) on conflict do nothing", (lote,))
    return lote


async def test_cobertura_mercado_e_tamanho_e_faixa_nunca_a_lista(db, escopos, cobertura_semeada):
    """A F22 trocou o CONTRATO desta seção, e este teste guarda o contrato novo.

    Até a F22 o texto era uma linha por instrumento do universo ("### Ativos na cobertura", com
    ticker e pregões de cada um). Com os 5 ativos do dev isso era irrelevante; com os milhares de
    papéis do acervo viraria ~7.500 tokens em TODA chamada ao modelo (duas por turno, para sempre),
    calculados por um `count(*)` agrupado sobre `market.prices` inteira a cada turno — foi carga
    desse tipo que derrubou a escrita do nó de 1 GB. Agora a seção declara TAMANHO e FAIXA, e quem
    pergunta por um papel específico chama `dados.resolver_instrumento`.

    Por isso a asserção que mais importa aqui é a NEGATIVA: o ticker semeado não pode reaparecer no
    texto. Ela é o que impede a lista de voltar por descuido."""
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        texto = await cobertura_mercado(conn)

    assert "### Cobertura de mercado" in texto
    # Tamanho: contagem por tipo, sem depender de quantos papéis o acervo tem hoje.
    assert re.search(r"- \d+ ativos na cobertura: .*\d+ ações", texto), texto
    # Faixa: a janela de fechamentos, não a data de cada instrumento.
    assert "fechamentos de " in texto
    # A porta para o caso específico, que substituiu a lista.
    assert "dados.resolver_instrumento" in texto
    assert "Índices e taxas: " in texto and "cdi" in texto

    # O ticker semeado pela fixture NÃO entra: a lista é justamente o que a F22 tirou do prompt.
    assert "PETR4" not in texto, "a lista de tickers voltou ao prompt do Analista"
    assert "pregões" not in texto, "contagem por instrumento voltou ao prompt do Analista"


# ---------------------------------------------------------------- Educador fora da base (turno com FakeLLM)
def _resp(texto="", tool_calls=()):
    return ChatResponse(text=texto, tool_calls=list(tool_calls), usage=Usage(100, 0, 40),
                        finish_reason="stop", model="fake-m", provider="fake", latency_ms=5)


@pytest.fixture
async def mundo_educador(db, escopos):
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        for code, payload in (("EDUCACAO_PARAMS", EDUCACAO_PARAMS), ("EDUCACAO_EXEMPLOS", EDUCACAO_EXEMPLOS),
                              ("AGENT_CONVERSATIONS", {"inatividade_minutos": 30, "max_historico_mensagens": 20,
                                                       "max_tools_por_turno": 4, "max_erros_de_tool_por_turno": 2})):
            await policies_repo.set_policy(conn, code, payload)
            await policies_repo.approve_current(conn, code, approved_by=escopos.u1)
        await prompts_repo.reabrir_rascunho(conn, "agent.educador.system", EDUCADOR)   # o prompt REAL v2
        atual = await prompts_repo.get_current(conn, "agent.educador.system")
        await prompts_repo.approve(conn, "agent.educador.system", version=atual.version, approved_by=escopos.u1)
    return escopos


async def test_educador_fora_da_base_responde_rotulado_sem_rodape_nem_fonte(db, mundo_educador):
    e = mundo_educador
    explicacao = (f"{ROTULO_GERAL}: uma debênture incentivada é um título de dívida emitido por empresa para financiar "
                  "projetos de infraestrutura, com tratamento tributário próprio previsto em lei. Não há material aprovado "
                  "sobre o tema na base; posso explicar renda fixa, que já está aprovada.")
    fake = FakeLLM([
        _resp(tool_calls=[ToolCall(id="tc1", name="educacao.glossario", arguments={"termo": "debênture incentivada"})]),
        _resp(texto=explicacao),
    ])
    turno = TurnoCopiloto(db=db, llm=fake, policies=PolicyStore(db, ttl_s=0))
    eventos = [x async for x in turno.executar(TurnoInput(texto="o que é debênture incentivada?", user_id=e.u1,
                                                          scope_id=e.s1, agent_code="educador"))]
    done = eventos[-1]
    assert isinstance(done, ev.Done)
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert texto.startswith(ROTULO_GERAL)
    assert "ilustrativ" not in texto.lower()                              # glossário não emite número: sem rodapé
    assert not any(r["kind"] == "education_content" for r in done.cited_refs)   # nada aprovado foi citado
    assert any(r["kind"] == "tool_execution" for r in done.cited_refs)       # a busca fica na proveniência
    assert "Explique com base APENAS" not in texto and "encontrado" not in texto   # nada da nota interna vaza


# ---------------------------------------------------------------- orçamento no contexto do escopo
async def test_pacote_do_escopo_traz_custo_de_vida_dos_meses_fechados(db, escopos):
    """Eval `ass_reserva` (2026-08-25): o Assessor perguntava o custo de vida em vez de medir a reserva, porque o
    contexto não mostrava que o orçamento já tem meses fechados. Agora mostra a média e quantos meses."""
    async with db.service_session() as conn:
        for i in range(1, 4):
            await conn.execute(
                "insert into budget.monthly_summaries (scope_id, month, income_brl, expense_brl) "
                "values (%s, (date_trunc('month', current_date) - (%s || ' month')::interval)::date, 20000, 9000)",
                (escopos.s1, i))
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        texto = await pacote_do_escopo(conn, escopos.s1)
    assert "### Orçamento" in texto
    assert "R$ 9000.00" in texto and "3 meses" in texto
