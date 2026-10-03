"""
F5 — Analista standard. Parte b: tools `dados.*`/`quant.*`, prompt aprovado, turno ponta a ponta.

Regras provadas: as tools canônicas de mercado não leem observações posteriores ao `cutoff_date`; dado insuficiente
NÃO é exceção — a tool devolve `suficiente=false` e o turno grava evidência `missing`; toda pergunta
ao Analista cria `analysis.analyses` e `evidence_findings` com proveniência (`tool_execution_id`);
o gate de família do BANCO vale nos dois sentidos; policy client-facing não aprovada bloqueia (29a);
o prompt real é aprovável e diz que retorno passado não indica futuro; nenhum `decisions.records`
nasce de uma pergunta; escopo alheio não vê a análise; nenhuma premissa numérica no código.
Preços vêm da fixture COTAHIST (tests/fixtures/market) ingerida NA transação do teste.
"""
from __future__ import annotations

import ast
import json
import math
import pathlib
import statistics
from datetime import date

import pytest

from tests.conftest import abrir_conversa
from tests.test_f5_analista import POLICY_INGESTAO, fixture_cotahist_unica

from app.agents import eventos as ev
from app.agents.turn import TurnoCopiloto, TurnoInput, filtrar_tools
from app.config.policies import PolicyStore
from app.db.errors import FamilyNotAllowed, PolicyGateViolation
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.db.repos.prompts import encontrar_vocabulario_proibido
from app.llm.client import ChatResponse, ToolCall, Usage
from app.llm.fake import FakeLLM
from app.llm.prompts import variaveis_do_template
from app.tools import carregar_tools
from app.tools.analista import (_comum, correlacao, dependencia, event_study, historico_comparado, resolver_instrumento,
                                retorno_volatilidade, risco_retorno, serie_indice, serie_precos)
from app.tools.executor import executar_tool
from app.tools.registry import spec_de, specs_registradas
from app.tools.sync import sincronizar

RAIZ = pathlib.Path(__file__).parent.parent
GOLDEN = pathlib.Path(__file__).parent / "golden"
PROMPT_ANALISTA = (RAIZ / "prompts" / "agent.analista.system.j2").read_text(encoding="utf-8")

carregar_tools()

CUTOFF = date(2024, 1, 17)          # último pregão da fixture
ANALISE_PARAMS = {
    # defasagem folgada: a fixture é de 2024 e o cutoff do turno é current_date — o teste de defasagem aperta a sua
    "janela_padrao_dias": 252, "min_observacoes": 5, "max_dias_defasagem": 3650, "dias_uteis_ano": 252,
    "metodo_retorno": "log", "max_pontos": 260, "benchmark_padrao": "F5BOVA",
    "event_study": {"janela_estimacao_dias": 6, "pre_dias": 1, "pos_dias": 1, "metodo": "market_model"},
}
# Catálogo do Analista. Cresce quando o AGENTE ganha uma tool — e a lista é exata de propósito:
# é ela que denuncia tool vazando de outra família. `dados.expectativas_mercado` entrou na F13b.
TOOLS_ANALISTA = {"dados.resolver_instrumento", "dados.serie_precos", "dados.serie_indice",
                  "dados.historico_comparado", "dados.expectativas_mercado",
                  "dados.fundamentos_empresa",
                  "quant.risco_retorno", "quant.dependencia", "quant.analise_condicional",
                  "quant.sensibilidade", "quant.regimes", "quant.event_study",
                  "quant.valor_mercado", "quant.cenario_sensibilidade",
                  "quant.tendencias_fundamentais", "quant.comparaveis_setor"}


def _resp(texto="", tool_calls=(), out=40):
    return ChatResponse(text=texto, tool_calls=list(tool_calls),
                        usage=Usage(input_tokens=100, cached_tokens=0, output_tokens=out),
                        finish_reason="stop", model="fake-m", provider="fake", latency_ms=5)


def _tc(name, args):
    return ToolCall(id="tc1", name=name, arguments=args)


async def _rodar(db, fake, **kw):
    turno = TurnoCopiloto(db=db, llm=fake, policies=PolicyStore(db, ttl_s=0))
    return [e async for e in turno.executar(TurnoInput(**kw))]


@pytest.fixture
async def mundo(db, escopos, tmp_path):
    """Tools sincronizadas, policies aprovadas, prompt REAL do Analista aprovado, universo F5* com os
    preços da fixture COTAHIST e um índice de teste — tudo na transação; nada do banco de dev."""
    from app.jobs import tasks

    e = escopos
    ids = {}
    async with db.service_session() as conn:
        await sincronizar(conn, specs_registradas(), git_sha="a" * 40)
        for code, payload in (("ANALISE_PARAMS", ANALISE_PARAMS),
                              ("AGENT_ROUTING", {"min_confidence": 0.6}),
                              ("AGENT_CONVERSATIONS", {"inatividade_minutos": 30, "max_historico_mensagens": 20,
                                                       "max_tools_por_turno": 2})):
            await policies_repo.set_policy(conn, code, payload)
            await policies_repo.approve_current(conn, code, approved_by=e.u1)
        await policies_repo.set_policy(conn, "MERCADO_INGESTAO", POLICY_INGESTAO)
        if await policies_repo.get_current(conn, "LLM_BUDGETS") is None:
            await policies_repo.set_policy(conn, "LLM_BUDGETS", {"max_model_calls_por_turno": 4,
                                                                 "max_output_tokens_por_turno": 4000})
        for code, template in (("agent.analista.system", PROMPT_ANALISTA),
                               ("copiloto.router", "Roteie. {{ pergunta }}")):
            await prompts_repo.reabrir_rascunho(conn, code, template)
            atual = await prompts_repo.get_current(conn, code)
            await prompts_repo.approve(conn, code, version=atual.version, approved_by=e.u1)
        for ticker, nome, kind in (("F5PETR", "F5 Petróleo PN", "acao"), ("F5VALE", "F5 Mineração ON", "acao"),
                                   ("F5BOVA", "F5 ETF Ibovespa", "etf")):
            cur = await conn.execute(
                "insert into market.instruments (kind, name, ticker, is_in_universe, source_code) "
                "values (%s::market.instrument_kind, %s, %s, true, 'b3') returning id::text", (kind, nome, ticker))
            ids[ticker] = (await cur.fetchone())[0]
        await conn.execute(
            "insert into market.instrument_aliases (instrument_id, alias_kind, alias_value, source_code) "
            "values (%s, 'codigo_b3', 'F5VALEOLD', 'b3')", (ids["F5VALE"],))
        await conn.execute(
            "insert into market.instruments (kind, name, ticker, is_in_universe, source_code) "
            "values ('acao', 'F5 Fora do Universo', 'F5XPTO', false, 'b3')")
        await conn.execute(
            "insert into market.index_definitions (code, display_name, unit, source_code, sgs_series_id) "
            "values ('f5_cdi', 'CDI de teste', 'taxa_aa', 'bacen_sgs', 4389)")
    r = await tasks.ingerir_cotahist({"db": db, "policies": PolicyStore(db, ttl_s=0)},
                                     arquivo=str(fixture_cotahist_unica(tmp_path)))
    assert r["rows_ingested"] == 34
    async with db.service_session() as conn:
        # CDI diário de teste (taxa a.a.) nos mesmos pregões da fixture
        await conn.execute(
            """insert into market.index_values (index_code, value_date, value)
               select 'f5_cdi', d, 10.65 from (select distinct price_date d from market.prices
                                               where ingestion_batch_id = %s) q""", (r["batch_id"],))
    return {"e": e, "ids": ids, "batch_id": r["batch_id"]}


async def _executar(db, mundo, code, params, *, cutoff=CUTOFF, conversa=False):
    e = mundo["e"]
    cid = await abrir_conversa(db, e, agente="analista") if conversa else None
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        return await executar_tool(conn, code, params, scope_id=e.s1, conversation_id=cid, cutoff_date=cutoff)


# ---------------------------------------------------------------- registro
def test_registro_tem_catalogo_publico_do_analista():
    specs = {s.code: s for s in specs_registradas()}
    assert TOOLS_ANALISTA <= set(specs)
    for code in TOOLS_ANALISTA:
        assert specs[code].family == code.split(".")[0] and specs[code].requires_market_data
        assert specs[code].min_plan == "free"
    assert spec_de("dados.resolver_instrumento").emite_numero is False
    assert all(spec_de(c).emite_numero for c in TOOLS_ANALISTA - {"dados.resolver_instrumento"})


def test_filtrar_tools_do_analista_so_ve_quant_e_dados():
    codes = {s.code for s in filtrar_tools(specs_registradas(), familias=["quant", "dados"], plano="free")}
    assert codes == TOOLS_ANALISTA
    assert not any(s.code.startswith(("quant.", "dados.")) for s in
                   filtrar_tools(specs_registradas(), familias=["orcamento", "planejamento", "produto"], plano="free"))


# ---------------------------------------------------------------- dados.*
async def test_resolver_instrumento_por_ticker_alias_e_nome(db, mundo):
    for termo in ("F5VALE", "f5valeold", "Mineração"):
        r = await _executar(db, mundo, "dados.resolver_instrumento", {"termo": termo})
        assert r.output.encontrado and r.output.instrument_id == mundo["ids"]["F5VALE"], termo
        assert r.output.ultimo_preco_em == CUTOFF
    r = await _executar(db, mundo, "dados.resolver_instrumento", {"termo": "F5"})
    assert not r.output.encontrado and len(r.output.ambiguos) >= 3
    assert "instrumento_ambiguo" in r.output.evidencia.avisos


async def test_resolver_instrumento_fora_do_universo_devolve_encontrado_false(db, mundo):
    r = await _executar(db, mundo, "dados.resolver_instrumento", {"termo": "F5XPTO"})
    assert not r.output.encontrado and r.output.is_in_universe is False
    assert "fora_da_cobertura" in r.output.evidencia.avisos
    r = await _executar(db, mundo, "dados.resolver_instrumento", {"termo": "ZZZZ99"})
    assert not r.output.encontrado and "instrumento_desconhecido" in r.output.evidencia.avisos


async def test_serie_precos_respeita_cutoff(db, mundo):
    """Preço posterior ao cutoff existe no banco e NÃO entra; as_of é o último dia <= cutoff."""
    r = await _executar(db, mundo, "dados.serie_precos", {"ticker": "F5PETR"}, cutoff=date(2024, 1, 10))
    o = r.output
    assert o.ultimo.data == date(2024, 1, 10) and o.evidencia.as_of == date(2024, 1, 10)
    assert all(p.data <= date(2024, 1, 10) for p in o.pontos) and len(o.pontos) == 7
    assert o.evidencia.cutoff_date == date(2024, 1, 10) and o.evidencia.fonte == "b3"
    assert o.evidencia.ingestion_batch_ids == [mundo["batch_id"]]
    assert o.evidencia.instrument_ids == [mundo["ids"]["F5PETR"]]
    # cutoff diferente ⇒ resolvido diferente ⇒ input_hash diferente (sem cache cruzado)
    r2 = await _executar(db, mundo, "dados.serie_precos", {"ticker": "F5PETR"}, cutoff=date(2024, 1, 11))
    assert r2.output.ultimo.data == date(2024, 1, 11) and r2.execution_id != r.execution_id and not r2.cache_hit


async def test_historico_comparado_alinha_pregoes_e_normaliza_base_100(db, mundo):
    r = await _executar(db, mundo, "dados.historico_comparado",
                        {"ticker": "F5PETR", "benchmark": "F5BOVA", "periodo": "1m"})
    o = r.output
    assert o.ticker == "F5PETR" and o.benchmark == "F5BOVA" and o.periodo == "1m"
    assert [s.papel for s in o.series] == ["ativo", "benchmark"]
    assert all(s.pontos[0].indice == pytest.approx(100) for s in o.series)
    assert [p.data for p in o.series[0].pontos] == [p.data for p in o.series[1].pontos]
    assert o.resumo.ultimo_preco == o.series[0].pontos[-1].valor_original
    assert o.resumo.variacao_periodo_pct == pytest.approx(o.series[0].pontos[-1].variacao_pct)
    assert o.evidencia.metodo == "fechamentos_alinhados_base_100"
    assert o.evidencia.n_observacoes == len(o.series[0].pontos)


async def test_serie_precos_amostra_mensal_quando_excede_max_pontos(db, mundo):
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", {**ANALISE_PARAMS, "max_pontos": 3})
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=mundo["e"].u1)
    r = await _executar(db, mundo, "dados.serie_precos", {"ticker": "F5PETR"})
    assert r.output.amostrado and len(r.output.pontos) <= 3 and "serie_amostrada" in r.output.evidencia.avisos
    assert r.output.evidencia.n_observacoes == 12         # a evidência conta a série inteira


async def test_historico_comparado_amostra_quando_excede_max_pontos(db, mundo):
    """[F22] O output da tool vai INTEIRO para o modelo como mensagem `role=tool`.

    `periodo='tudo'` são 10 anos: ~2.520 pontos por série, duas séries. Com os 161 pregões do dev
    nunca doeu; com o acervo carregado isso estoura o `LLM_BUDGETS` do turno sozinho. O mecanismo
    já existia — `max_pontos` está em `ANALISE_PARAMS` desde a F5 e só `dados.serie_precos` o lia.
    A série CHEIA continua indo para o bloco, que é desenhado na tela e não passa pelo modelo.
    """
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", {**ANALISE_PARAMS, "max_pontos": 3})
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=mundo["e"].u1)
    r = await _executar(db, mundo, "dados.historico_comparado",
                        {"ticker": "F5PETR", "benchmark": "F5BOVA", "periodo": "tudo"})
    o = r.output
    assert len(o.series) == 2, "o benchmark precisa estar na comparação para provar o alinhamento"
    assert o.amostrado, "série longa foi para o modelo sem amostragem"
    assert all(len(s.pontos) <= 3 for s in o.series)
    # As duas séries continuam alinhadas depois da amostragem — senão o gráfico compara datas diferentes.
    assert [p.data for p in o.series[0].pontos] == [p.data for p in o.series[1].pontos]
    assert "serie_amostrada" in o.evidencia.avisos
    assert o.evidencia.n_observacoes == 12         # a evidência conta a série inteira


async def test_serie_indice_amostra_quando_excede_max_pontos(db, mundo):
    """[F22] Mesma armadilha do histórico: CDI diário desde 1995 são ~7.500 pontos."""
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", {**ANALISE_PARAMS, "max_pontos": 3})
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=mundo["e"].u1)
    r = await _executar(db, mundo, "dados.serie_indice",
                        {"indice": "f5_cdi", "de": "2024-01-02", "ate": "2024-01-17"})
    o = r.output
    assert o.amostrado and len(o.pontos) <= 3 and "serie_amostrada" in o.evidencia.avisos
    assert o.evidencia.n_observacoes == 12
    # O acumulado é da série INTEIRA, não da amostra: amostrar não pode mudar o número.
    esperado = ((1 + 10.65 / 100) ** (12 / 252) - 1) * 100
    assert o.acumulado_periodo_pct == pytest.approx(esperado, abs=1e-6)


async def test_serie_indice_acumula_taxa_aa_por_dia_util(db, mundo):
    r = await _executar(db, mundo, "dados.serie_indice", {"indice": "f5_cdi", "de": "2024-01-02", "ate": "2024-01-17"})
    o = r.output
    assert o.unidade == "taxa_aa" and len(o.pontos) == 12 and o.evidencia.fonte == "bacen_sgs"
    esperado = ((1 + 10.65 / 100) ** (12 / 252) - 1) * 100
    assert o.acumulado_periodo_pct == pytest.approx(esperado, abs=1e-6)
    assert o.evidencia.index_codes == ["f5_cdi"] and o.evidencia.instrument_ids == []


async def test_serie_curta_devolve_suficiente_false_sem_excecao(db, mundo):
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", {**ANALISE_PARAMS, "min_observacoes": 30})
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=mundo["e"].u1)
    r = await _executar(db, mundo, "quant.risco_retorno", {"ticker": "F5PETR"})
    o = r.output
    assert o.evidencia.suficiente is False and "serie_curta" in o.evidencia.avisos
    assert o.retorno_acumulado_pct is None and o.vol_anualizada_pct is None
    assert all(v is None for v in o.evidencia.metricas.values())


async def test_serie_defasada_gera_aviso(db, mundo):
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", {**ANALISE_PARAMS, "max_dias_defasagem": 5})
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=mundo["e"].u1)
    r = await _executar(db, mundo, "quant.risco_retorno", {"ticker": "F5PETR"}, cutoff=date(2024, 2, 20))
    assert r.output.evidencia.as_of == CUTOFF and "serie_defasada" in r.output.evidencia.avisos
    assert r.output.evidencia.suficiente is True          # defasagem é aviso, não ausência


async def test_lacunas_listam_dias_de_pregao_sem_preco(db, mundo):
    """F5VALE não negociou em dois pregões em que F5PETR/F5BOVA negociaram: são lacunas, não feriados."""
    r = await _executar(db, mundo, "dados.serie_precos", {"ticker": "F5VALE"})
    assert r.output.evidencia.lacunas == [date(2024, 1, 8), date(2024, 1, 9)]
    r = await _executar(db, mundo, "dados.serie_precos", {"ticker": "F5PETR"})
    assert r.output.evidencia.lacunas == []


# ---------------------------------------------------------------- quant.* (números conferidos à mão)
def _serie(valores, inicio=date(2024, 1, 2)):
    from datetime import timedelta
    return [_comum.Ponto(data=inicio + timedelta(days=i), valor=v) for i, v in enumerate(valores)]


def test_retorno_volatilidade_bate_com_calculo_manual():
    precos = [100.0, 102.0, 101.0, 104.0, 103.0]
    r = retorno_volatilidade.calcular_retorno(retorno_volatilidade.RetornoResolvido(
        ticker="X", instrument_id="i", cutoff_date=date(2024, 1, 6), serie=_comum.Serie(codigo="X", pontos=_serie(precos)),
        calendario=[p.data for p in _serie(precos)], metodo_retorno="log", dias_uteis_ano=252, min_observacoes=3,
        max_dias_defasagem=5, fonte="b3", ingestion_batch_ids=[]))
    logs = [math.log(b / a) for a, b in zip(precos, precos[1:])]
    assert r.retorno_acumulado_pct == pytest.approx((103 / 100 - 1) * 100, rel=1e-9)
    assert r.retorno_anualizado_pct == pytest.approx(((103 / 100) ** (252 / 4) - 1) * 100, rel=1e-9)
    assert r.vol_anualizada_pct == pytest.approx(statistics.stdev(logs) * math.sqrt(252) * 100, rel=1e-9)
    assert r.max_drawdown_pct == pytest.approx((101 / 102 - 1) * 100, rel=1e-9)   # pico corrente em 101 é 102
    assert r.evidencia.n_observacoes == 5 and r.evidencia.suficiente and r.evidencia.metodo.startswith("log")


def test_correlacao_com_defasagem_desloca_serie_b():
    a = [100, 101, 103, 102, 105, 104, 108, 107]
    b = [50] + [x / 2 for x in a[:-1]]            # b é a com um dia de atraso
    base = dict(ticker_a="A", codigo_b="B", instrument_ids=["ia", "ib"], index_codes=[], cutoff_date=date(2024, 1, 20),
                serie_a=_comum.Serie(codigo="A", pontos=_serie([float(x) for x in a])),
                serie_b=_comum.Serie(codigo="B", pontos=_serie([float(x) for x in b])),
                metodo_retorno="simples", min_observacoes=3, max_dias_defasagem=5, fonte="b3", ingestion_batch_ids=[],
                dias_uteis_ano=252)
    sem = correlacao.calcular_correlacao(correlacao.CorrelacaoResolvida(defasagem_dias=0, **base))
    com = correlacao.calcular_correlacao(correlacao.CorrelacaoResolvida(defasagem_dias=1, **base))
    assert com.correlacao == pytest.approx(1.0, abs=1e-9) and com.n_pares == 6
    assert sem.correlacao is not None and sem.correlacao < 0.99
    assert com.evidencia.metricas["correlacao"] == pytest.approx(1.0, abs=1e-9)


def test_event_study_market_model_recupera_alpha_beta_de_serie_sintetica():
    """r_ativo = 0.001 + 1.5·r_bench exatamente ⇒ alpha/beta exatos e CAR = 0 na janela do evento."""
    rb = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.0, 0.012, -0.008, 0.004, 0.009, -0.003]
    pb, pa = [100.0], [50.0]
    for r in rb:
        pb.append(pb[-1] * (1 + r))
        pa.append(pa[-1] * (1 + 0.001 + 1.5 * r))
    sa, sb = _serie(pa), _serie(pb)
    evento = sa[9].data
    res = event_study.calcular_event_study(event_study.EventStudyResolvido(
        ticker="A", benchmark="B", instrument_ids=["ia", "ib"], cutoff_date=sa[-1].data, data_evento=evento,
        data_evento_efetiva=evento, serie_ativo=_comum.Serie(codigo="A", pontos=sa), serie_benchmark=_comum.Serie(codigo="B", pontos=sb),
        metodo="market_model", metodo_retorno="simples", janela_estimacao_dias=6, pre_dias=1, pos_dias=1,
        min_observacoes=3, max_dias_defasagem=5, fonte="b3", ingestion_batch_ids=[]))
    assert res.alpha == pytest.approx(0.001, abs=1e-12) and res.beta == pytest.approx(1.5, abs=1e-9)
    assert res.car_pct == pytest.approx(0.0, abs=1e-9) and len(res.ar) == 3 and not res.truncada
    assert res.janela_estimacao.n == 6 and res.janela_evento.n == 3
    assert "significância" in res.evidencia.nota_metodo.lower() or "inferência" in res.evidencia.nota_metodo.lower()


async def test_event_study_janela_pos_alem_do_cutoff_e_truncada(db, mundo):
    r = await _executar(db, mundo, "quant.event_study", {"ticker": "F5PETR", "data_evento": "2024-01-17"})   # último pregão: pós-janela não existe
    o = r.output
    assert o.truncada_pre is False and o.truncada_pos is True
    assert "janela_pos_truncada" in o.evidencia.avisos and o.janela_evento.ate == CUTOFF
    # A v2 preserva o CAR parcial como descrição, mas janela truncada não é evidência suficiente.
    assert o.benchmark == "F5BOVA" and o.evidencia.suficiente is False


async def test_event_study_evento_em_dia_sem_pregao_ajusta_para_o_proximo(db, mundo):
    r = await _executar(db, mundo, "quant.event_study", {"ticker": "F5PETR", "data_evento": "2024-01-13"})  # sábado
    assert r.output.data_evento_efetiva == date(2024, 1, 15) and "evento_ajustado" in r.output.evidencia.avisos


async def test_correlacao_com_indice_alinha_por_data(db, mundo):
    r = await _executar(db, mundo, "quant.dependencia", {"ticker_a": "F5PETR", "serie_b": {"tipo": "indice", "codigo": "f5_cdi"}})
    o = r.output
    assert o.n_pares == 11 and o.coeficiente is None and "serie_constante" in o.evidencia.avisos
    assert o.evidencia.index_codes == ["f5_cdi"] and o.evidencia.instrument_ids == [mundo["ids"]["F5PETR"]]


# ---------------------------------------------------------------- goldens e config-first
@pytest.mark.parametrize("nome,calcular,resolvido_model", [
    ("dados_resolver_instrumento", resolver_instrumento.resolver, resolver_instrumento.ResolverResolvido),
    ("dados_serie_precos", serie_precos.montar_serie, serie_precos.SeriePrecosResolvida),
    ("dados_serie_indice", serie_indice.montar_indice, serie_indice.SerieIndiceResolvida),
    ("quant_retorno_volatilidade", retorno_volatilidade.calcular_retorno, retorno_volatilidade.RetornoResolvido),
    ("quant_correlacao", correlacao.calcular_correlacao, correlacao.CorrelacaoResolvida),
    ("quant_event_study", event_study.calcular_event_study, event_study.EventStudyResolvido),
])
def test_golden_master(nome, calcular, resolvido_model):
    dados = json.loads((GOLDEN / f"{nome}.json").read_text(encoding="utf-8"))
    saida = calcular(resolvido_model.model_validate(dados["resolvido"]))
    assert saida.model_dump(mode="json") == dados["esperado"], (
        "Saída difere do golden — mudança de número exige justificativa no commit.")


@pytest.mark.parametrize("modulo", [_comum, resolver_instrumento, serie_precos, serie_indice,
                                    retorno_volatilidade, correlacao, event_study])
def test_tools_do_analista_sem_literal_numerico_de_premissa(modulo):
    permitidos = {0, 1, 2, 12, 100, 0.0, 1.0}
    arvore = ast.parse(pathlib.Path(modulo.__file__).read_text(encoding="utf-8"))
    ofensores = [n.value for n in ast.walk(arvore)
                 if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                 and not isinstance(n.value, bool) and n.value not in permitidos]
    assert ofensores == [], f"números fora de policy em {modulo.__name__}: {ofensores}"


# ---------------------------------------------------------------- gates do banco
async def test_gate_familia_analista_nao_roda_orcamento(db, mundo):
    with pytest.raises(FamilyNotAllowed):
        # custo informado: a tool chega ao INSERT em tool_executions e é o BANCO (T18) que recusa a família
        await _executar(db, mundo, "orcamento.reserva_emergencia", {"custo_mensal_brl": 5000}, conversa=True)


async def test_gate_familia_assessor_nao_roda_quant(db, mundo):
    e = mundo["e"]
    cid = await abrir_conversa(db, e, agente="assessor")
    with pytest.raises(FamilyNotAllowed):
        async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
            await executar_tool(conn, "quant.risco_retorno", {"ticker": "F5PETR"},
                                scope_id=e.s1, conversation_id=cid, cutoff_date=CUTOFF)


async def test_gate_policy_analise_params_nao_aprovada_bloqueia(db, mundo):
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", ANALISE_PARAMS)   # nova versão: draft
    with pytest.raises(PolicyGateViolation):
        await _executar(db, mundo, "quant.risco_retorno", {"ticker": "F5PETR"}, conversa=True)


# ---------------------------------------------------------------- prompt
def test_prompt_analista_real_aprovavel():
    assert "[PENDENTE" not in PROMPT_ANALISTA
    assert encontrar_vocabulario_proibido(PROMPT_ANALISTA) == []
    # F8: o Analista recebe a cobertura de mercado (universo, período com preço, índices) além do contexto do escopo
    assert variaveis_do_template(PROMPT_ANALISTA) == ["cobertura_mercado", "contexto_escopo"]
    texto = PROMPT_ANALISTA.lower()
    assert "retorno passado" in texto and "não indica" in texto
    assert "encaminhar" in texto and "correlação não" in texto


# ---------------------------------------------------------------- turno ponta a ponta
async def test_turno_analista_grava_analysis_e_findings_com_provenance(db, mundo):
    e = mundo["e"]
    # o período é explícito: a janela padrão conta a partir do cutoff (hoje) e a fixture é de 2024
    fake = FakeLLM([_resp(tool_calls=[_tc("quant.risco_retorno",
                                          {"ticker": "F5PETR", "de": "2024-01-01", "ate": "2024-01-31"})]),
                    _resp("A F5PETR teve retorno e volatilidade no período, conforme a tool.")])
    eventos = await _rodar(db, fake, user_id=e.u1, scope_id=e.s1, texto="como foi a F5PETR?", agent_code="analista")
    done = next(x for x in eventos if isinstance(x, ev.Done))
    tool_done = next(x for x in eventos if isinstance(x, ev.ToolDone))
    kinds = {c["kind"] for c in done.cited_refs}
    assert {"tool_execution", "policy", "price_asof", "analysis_finding"} <= kinds
    texto = "".join(x.texto for x in eventos if isinstance(x, ev.Delta))
    assert "ilustrativ" in texto.lower()
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select id::text, mode, status, cutoff_date, question from analysis.analyses where conversation_id = %s",
            (done.conversation_id,))
        rows = await cur.fetchall()
        assert len(rows) == 1
        aid, mode, status, cutoff, question = rows[0]
        # adjusted_close é retrospectivo e a fixture não carrega trading_calendar oficial;
        # ambos são avisos metodológicos materiais, então a análise deve terminar com warnings.
        assert (mode, status, question) == ("standard", "final_with_warnings", "como foi a F5PETR?") and cutoff is not None
        cur = await conn.execute(
            "select kind, finding, provenance from analysis.evidence_findings where analysis_id = %s order by kind", (aid,))
        rows_findings = await cur.fetchall()
        findings = {k: (f, p) for k, f, p in rows_findings if k != "warning"}
        warnings = [f["aviso"] for k, f, _ in rows_findings if k == "warning"]
        assert {"quantitative", "methodology"} <= set(findings) and "missing" not in {k for k, _, _ in rows_findings}
        assert "adjusted_close_retrospective" in warnings
        assert "calendar_fallback_from_prices" in warnings
        assert findings["quantitative"][1][0]["tool_execution_id"] == tool_done.execution_id
        assert "retorno_acumulado_pct" in findings["quantitative"][0]["metricas"]
        assert findings["methodology"][0]["metodo"]
        cur = await conn.execute(
            "select count(*) from llm.model_calls where analysis_id = %s and conversation_id = %s", (aid, done.conversation_id))
        assert (await cur.fetchone())[0] >= 2
        cur = await conn.execute("select count(*) from decisions.records where scope_id = %s", (e.s1,))
        assert (await cur.fetchone())[0] == 0


async def test_turno_analista_serie_curta_grava_missing_e_status_with_warnings(db, mundo):
    e = mundo["e"]
    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", {**ANALISE_PARAMS, "min_observacoes": 30})
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=e.u1)
    fake = FakeLLM([_resp(tool_calls=[_tc("quant.dependencia", {"ticker_a": "F5PETR", "serie_b": {"tipo": "ativo", "codigo": "F5VALE"}})]),
                    _resp("Não há base suficiente para estimar a correlação no período.")])
    eventos = await _rodar(db, fake, user_id=e.u1, scope_id=e.s1, texto="F5PETR e F5VALE andam juntas?", agent_code="analista")
    done = next(x for x in eventos if isinstance(x, ev.Done))
    async with db.service_session() as conn:
        cur = await conn.execute(
            """select a.status, array_agg(f.kind order by f.kind) from analysis.analyses a
                 join analysis.evidence_findings f on f.analysis_id = a.id
                where a.conversation_id = %s group by a.status""", (done.conversation_id,))
        status, kinds = await cur.fetchone()
        assert status == "final_with_warnings" and "missing" in kinds and "quantitative" not in kinds


async def test_turno_analista_handoff_cancela_analise_sem_findings(db, mundo):
    e = mundo["e"]
    fake = FakeLLM([_resp(tool_calls=[_tc("encaminhar", {"agent_code": "assessor", "motivo": "planejamento pessoal"})])])
    eventos = await _rodar(db, fake, user_id=e.u1, scope_id=e.s1, texto="posso me aposentar aos 55?", agent_code="analista")
    assert any(isinstance(x, ev.HandoffSuggested) for x in eventos)
    done = next(x for x in eventos if isinstance(x, ev.Done))
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select status, (select count(*) from analysis.evidence_findings f where f.analysis_id = a.id) "
            "from analysis.analyses a where conversation_id = %s", (done.conversation_id,))
        assert (await cur.fetchone()) == ("cancelled", 0)


async def test_turno_assessor_nao_cria_analysis(db, mundo):
    """Só o Analista abre análise: o mesmo turno para o Assessor não toca em analysis.*."""
    e = mundo["e"]
    fake = FakeLLM([_resp("Posso ajudar com o seu planejamento.")])
    eventos = await _rodar(db, fake, user_id=e.u1, scope_id=e.s1, texto="oi", agent_code="assessor")
    done = next(x for x in eventos if isinstance(x, ev.Done))
    async with db.service_session() as conn:
        cur = await conn.execute("select count(*) from analysis.analyses where conversation_id = %s", (done.conversation_id,))
        assert (await cur.fetchone())[0] == 0


async def test_rls_analysis_de_outro_escopo_invisivel(db, mundo):
    e = mundo["e"]
    fake = FakeLLM([_resp(tool_calls=[_tc("dados.serie_precos", {"ticker": "F5PETR"})]), _resp("Série carregada.")])
    eventos = await _rodar(db, fake, user_id=e.u1, scope_id=e.s1, texto="preços da F5PETR", agent_code="analista")
    done = next(x for x in eventos if isinstance(x, ev.Done))
    async with db.app_session(user_id=e.u2, scope_id=e.s2) as conn:
        cur = await conn.execute("select count(*) from analysis.analyses where conversation_id = %s", (done.conversation_id,))
        assert (await cur.fetchone())[0] == 0
    async with db.app_session(user_id=e.u1, scope_id=e.s1) as conn:
        cur = await conn.execute("select count(*) from analysis.analyses where conversation_id = %s", (done.conversation_id,))
        assert (await cur.fetchone())[0] == 1
