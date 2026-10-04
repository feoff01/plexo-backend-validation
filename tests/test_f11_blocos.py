"""
F11 — Blocos ricos (gráfico/tabela/indicadores) derivados do output DETERMINÍSTICO das tools.

O LLM nunca calcula nem desenha: `app/agents/blocos.py` traduz o `output_payload` de cada tool num descritor
neutro (`serie` | `barras` | `indicadores` | `progresso` | `tabela`) com proveniência obrigatória. O turno emite o
evento `bloco` logo após `tool_done` (a tela mostra antes da leitura) e grava os mesmos blocos em
`agents.messages.content_json.blocos` (reabrir a conversa mostra igual). Goldens em `tests/golden/blocos_*.json`
nascem dos goldens de output já conferidos à mão; mudança de bloco é decisão humana.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.agents import eventos as ev
from app.agents.blocos import TIPOS, blocos_de, blocos_de_execucoes
from app.agents.turn import TurnoCopiloto, TurnoInput
from app.config.policies import PolicyStore
from app.db.repos import policies as policies_repo
from app.db.repos.prompts import encontrar_vocabulario_proibido
from app.llm.fake import FakeLLM
from app.tools import carregar_tools
from app.tools.executor import executar_tool
from tests.test_f8_turno_conversacional import CONV_CFG, _resp, _tc, mundo  # noqa: F401

carregar_tools()

GOLDEN = pathlib.Path(__file__).parent / "golden"
PROMPTS = pathlib.Path(__file__).parent.parent / "prompts"

# golden de output → código da tool
GOLDENS = {
    "educacao_juros_compostos": "educacao.simulador_juros_compostos",
    "educacao_exemplo_come_cotas": "educacao.exemplo_didatico",
    "educacao_exemplo_ir_regressivo": "educacao.exemplo_didatico",
    "educacao_exemplo_taxa_administracao": "educacao.exemplo_didatico",
    "orcamento_reserva_emergencia": "orcamento.reserva_emergencia",
    "orcamento_capacidade_aporte": "orcamento.capacidade_aporte",
    "planejamento_projecao_objetivo": "planejamento.projecao_objetivo",
    "dados_serie_precos": "dados.serie_precos",
    "dados_serie_indice": "dados.serie_indice",
    "quant_retorno_volatilidade": "quant.retorno_volatilidade",
    "quant_correlacao": "quant.correlacao",
    "quant_event_study": "quant.event_study",
    # [F17] O primeiro item do primeiro bloco é o CENÁRIO RUIM, e o golden trava isso:
    # é o guardrail do §8 virado contrato, não convenção de quem escreveu o mapeador.
    "planejamento_simulacao_objetivo": "planejamento.simulacao_objetivo",
    # [F19] Os dois de patrimônio entraram aqui em 2026-08-30. O da composição EXISTIA em
    # disco desde a F12, num formato próprio (array no topo), conferido só por
    # `test_f12_persona.py` — logo, fora das asserções estruturais deste arquivo (tipo
    # conhecido, prefixo do id, fonte, nota). Golden que só um teste enxerga é golden que
    # envelhece sozinho.
    "planejamento_composicao_patrimonio": "planejamento.composicao_patrimonio",
    "planejamento_posicoes_carteira": "planejamento.posicoes_carteira",
    "planejamento_pontos_de_atencao": "planejamento.pontos_de_atencao",
}


def _output(nome: str) -> dict:
    return json.loads((GOLDEN / f"{nome}.json").read_text(encoding="utf-8"))["esperado"]


def test_a_simulacao_mostra_o_cenario_ruim_antes_da_mediana():
    """O §8 do documento como asserção sobre o BLOCO, não sobre o prompt.

    Um fan chart lido de cima para baixo vira promessa de retorno. Aqui o primeiro número
    que o cliente lê é o piso, e a comparação entre carteiras é feita sobre ele.
    """
    blocos = blocos_de("planejamento.simulacao_objetivo",
                       _output("planejamento_simulacao_objetivo"), execution_id="exec-1")
    assert blocos, "a simulação precisa produzir bloco"

    # O bloco virou `faixa` (F18): o guardrail deixou de depender da ORDEM de uma lista de
    # rótulos e passou a ser estrutural. A faixa não consegue desenhar a mediana sem desenhar
    # o piso — os dois são extremos do mesmo traço.
    faixa = blocos[0]
    assert faixa["tipo"] == "faixa"
    d = faixa["dados"]
    assert d["p5"] is not None and d["p50"] is not None, (
        "cenário ruim e valor mais provável saem juntos, sempre: mostrar só a mediana "
        "transforma simulação em promessa")
    assert d["p5"] <= d["p50"] <= d["p95"]
    assert d["alvo"] is not None, "sem o alvo na figura, o leitor não tem contra o que comparar"
    assert d["arrependimento"] is not None, (
        "o arrependimento é o risco que percentil nenhum comunica — não pode sumir do bloco")
    assert 0 <= d["probabilidade"] <= 1, "a probabilidade é fração; o formato é que multiplica"
    comparativo = [b for b in blocos if b["tipo"] == "barras"]
    assert comparativo and "ruim" in comparativo[0]["titulo"].lower(), (
        "a comparação entre carteiras é sobre o PISO, não sobre a mediana")


# ---------------------------------------------------------------- goldens
@pytest.mark.parametrize("nome", sorted(GOLDENS))
def test_blocos_batem_com_o_golden(nome):
    esperado = json.loads((GOLDEN / f"blocos_{nome}.json").read_text(encoding="utf-8"))
    blocos = blocos_de(GOLDENS[nome], _output(nome), execution_id="exec-1")
    assert blocos == esperado["blocos"], "Bloco difere do golden — mudança de representação exige justificativa no commit."


@pytest.mark.parametrize("nome", sorted(GOLDENS))
def test_todo_bloco_tem_tipo_conhecido_e_proveniencia(nome):
    for b in blocos_de(GOLDENS[nome], _output(nome), execution_id="exec-1"):
        assert b["tipo"] in TIPOS
        assert b["id"].startswith("exec-1:")
        assert b["titulo"]
        assert b["proveniencia"]["fonte"]                      # sem fonte, sem bloco
        assert "nota" in b


def test_tools_nao_numericas_nao_geram_bloco():
    assert blocos_de("educacao.glossario", _output("educacao_glossario"), execution_id="e") == []
    assert blocos_de("dados.resolver_instrumento", _output("dados_resolver_instrumento"), execution_id="e") == []
    assert blocos_de("tool.inexistente", {"x": 1}, execution_id="e") == []


def test_evidencia_insuficiente_nao_gera_bloco_numerico():
    out = _output("quant_retorno_volatilidade")
    out["evidencia"]["suficiente"] = False
    out["retorno_acumulado_pct"] = None
    assert blocos_de("quant.retorno_volatilidade", out, execution_id="e") == []


def test_chave_ausente_omite_o_bloco_sem_excecao():
    out = _output("planejamento_projecao_objetivo")
    del out["cenarios"]
    blocos = blocos_de("planejamento.projecao_objetivo", out, execution_id="e")
    assert all(b["tipo"] != "barras" for b in blocos)


def test_teto_de_pontos_amostra_a_serie_sem_perder_as_pontas():
    out = _output("dados_serie_precos")
    out["pontos"] = [{"data": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}", "valor": float(i)} for i in range(200)]
    serie = next(b for b in blocos_de("dados.serie_precos", out, execution_id="e", max_pontos=50) if b["tipo"] == "serie")
    pontos = serie["dados"]["series"][0]["pontos"]
    assert len(pontos) <= 50
    assert pontos[0]["y"] == 0.0 and pontos[-1]["y"] == 199.0
    assert "serie_amostrada" in serie["proveniencia"]["avisos"]


def test_teto_de_blocos_por_mensagem():
    out = _output("orcamento_capacidade_aporte")
    assert len(blocos_de("orcamento.capacidade_aporte", out, execution_id="e", max_blocos=1)) == 1


def test_serie_de_juros_e_empilhada_com_duas_series_e_indicadores():
    blocos = blocos_de("educacao.simulador_juros_compostos", _output("educacao_juros_compostos"), execution_id="e")
    serie = next(b for b in blocos if b["tipo"] == "serie")
    assert serie["dados"]["empilhada"] is True
    assert [s["nome"] for s in serie["dados"]["series"]] == ["Aportado", "Juros"]
    assert serie["dados"]["series"][1]["pontos"][-1]["y"] == pytest.approx(535.46)
    kpis = next(b for b in blocos if b["tipo"] == "indicadores")
    assert {i["rotulo"] for i in kpis["dados"]["itens"]} >= {"Montante final", "Total aportado", "Juros"}


def test_historico_comparado_vira_grafico_interativo_com_consulta_auditavel():
    out = {
        "ticker": "PETR4", "benchmark": "BOVA11", "periodo": "1a", "de": "2025-08-26", "ate": "2026-08-26",
        "series": [
            {"nome": "PETR4", "papel": "ativo", "pontos": [
                {"data": "2025-08-26", "indice": 100, "valor_original": 31.2, "variacao_pct": 0},
                {"data": "2026-08-26", "indice": 112.5, "valor_original": 35.1, "variacao_pct": 12.5}]},
            {"nome": "BOVA11", "papel": "benchmark", "pontos": [
                {"data": "2025-08-26", "indice": 100, "valor_original": 126.0, "variacao_pct": 0},
                {"data": "2026-08-26", "indice": 108.0, "valor_original": 136.08, "variacao_pct": 8.0}]},
        ],
        "resumo": {"ultimo_preco": 35.1, "variacao_periodo_pct": 12.5, "as_of": "2026-08-26"},
        "evidencia": {"fonte": "b3", "instrument_ids": ["i1", "i2"], "tickers": ["PETR4", "BOVA11"],
                      "cutoff_date": "2026-08-26", "as_of": "2026-08-26", "n_observacoes": 2,
                      "metodo": "fechamentos_alinhados_base_100", "nota_metodo": "base 100", "suficiente": True,
                      "avisos": [], "metricas": {}, "ingestion_batch_ids": ["l1"]},
    }
    serie = blocos_de("dados.historico_comparado", out, execution_id="e")[0]
    assert serie["tipo"] == "serie" and serie["dados"]["eixo_y"]["formato"] == "indice_base_100"
    assert serie["dados"]["consulta"] == {
        "ticker": "PETR4", "benchmark": "BOVA11", "periodo": "1a",
        "periodos": ["1m", "3m", "1a", "5a", "tudo"], "cutoff_date": "2026-08-26", "interativa": True,
    }
    assert serie["dados"]["series"][1]["papel"] == "benchmark"
    assert serie["dados"]["series"][0]["pontos"][-1]["valor_original"] == 35.1


def test_comparacao_de_alternativas_nao_ordena_por_valor():
    out = {"valor_aplicado_brl": 10000, "horizonte_anos": 5, "metodo": "aprox", "avisos": [], "premissas_usadas": {},
           "produtos": [{"descricao": "B", "classe": "multimercado", "taxa_adm_aa": 0.02, "custo_adm_total_estimado_brl": 1000,
                         "referencia_classe_aa": 0.02, "acima_da_referencia": False, "liquidez_dias": 30, "come_cotas": True, "compativel_com_vetos": True},
                        {"descricao": "A", "classe": "acoes", "taxa_adm_aa": 0.005, "custo_adm_total_estimado_brl": 250,
                         "referencia_classe_aa": 0.015, "acima_da_referencia": False, "liquidez_dias": 1, "come_cotas": False, "compativel_com_vetos": False}]}
    blocos = blocos_de("produto.comparar_alternativas", out, execution_id="e")
    barras = next(b for b in blocos if b["tipo"] == "barras")
    assert [i["rotulo"] for i in barras["dados"]["itens"]] == ["B", "A"]      # ordem de entrada, nunca ranking
    tabela = next(b for b in blocos if b["tipo"] == "tabela")
    assert tabela["dados"]["linhas"][1]["compativel_com_vetos"] is False     # veto marcado, não escondido


# ---------------------------------------------------------------- turno: evento + persistência
async def test_turno_emite_bloco_apos_tool_done_e_grava_no_content_json(db, mundo):
    e = mundo
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "AGENT_CONVERSATIONS", {**CONV_CFG, "max_blocos_por_mensagem": 6, "max_pontos_por_bloco": 400})
        await policies_repo.approve_current(conn, "AGENT_CONVERSATIONS", approved_by=e.u1)
    fake = FakeLLM([
        _resp(tool_calls=[_tc("educacao.simulador_juros_compostos", {"aporte_mensal_brl": 500, "taxa_anual_pct": 10, "prazo_anos": 20})]),
        _resp(texto="A curva mostra o efeito dos juros ao longo dos anos."),
    ])
    turno = TurnoCopiloto(db=db, llm=fake, policies=PolicyStore(db, ttl_s=0))
    eventos = [x async for x in turno.executar(TurnoInput(texto="simula 500 por mês a 10% por 20 anos", user_id=e.u1, scope_id=e.s1, agent_code="educador"))]
    tipos = [type(x).__name__ for x in eventos]
    assert "Bloco" in tipos
    assert tipos.index("ToolDone") < tipos.index("Bloco") < tipos.index("Delta")   # o gráfico chega antes da leitura
    emitidos = [x.bloco for x in eventos if isinstance(x, ev.Bloco)]
    assert {b["tipo"] for b in emitidos} == {"serie", "indicadores"}
    done = eventos[-1]
    async with db.service_session() as conn:
        cur = await conn.execute("select content_json from agents.messages where id = %s", (done.message_id,))
        (cj,) = await cur.fetchone()
    assert cj["blocos"] == emitidos                                              # o que a tela viu = o gravado


async def test_blocos_de_execucoes_reconstroi_a_partir_do_output_payload(db, mundo):
    e = mundo
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        r = await executar_tool(conn, "educacao.simulador_juros_compostos",
                                {"aporte_mensal_brl": 300, "taxa_anual_pct": 8, "prazo_anos": 10},
                                scope_id=e.s1, conversation_id=None)
        blocos = await blocos_de_execucoes(conn, [("educacao.simulador_juros_compostos", r.execution_id)])
    assert blocos and blocos[0]["id"].startswith(r.execution_id)
    assert blocos == blocos_de("educacao.simulador_juros_compostos", r.output.model_dump(mode="json"), execution_id=r.execution_id)


# ---------------------------------------------------------------- prompts v3
@pytest.mark.parametrize("arquivo", ["agent.educador.system.j2", "agent.assessor.system.j2", "agent.analista.system.j2", "analista.report.j2"])
def test_prompts_v3_avisam_que_a_tela_mostra_o_grafico(arquivo):
    texto = (PROMPTS / arquivo).read_text(encoding="utf-8")
    assert "gráfico" in texto.lower() and "ponto a ponto" in texto.lower()
    assert encontrar_vocabulario_proibido(texto) == []
