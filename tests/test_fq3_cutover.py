from __future__ import annotations

from pathlib import Path

from app.agents.turn import filtrar_tools
from app.tools import carregar_tools
from app.tools.registry import spec_de, specs_registradas

RAIZ = Path(__file__).parent.parent


def test_cutover_atomico_catalogo_llm():
    carregar_tools()
    codes = {s.code for s in filtrar_tools(specs_registradas(), familias=("dados", "quant"), plano="wealth")}
    assert "quant.risco_retorno" in codes
    assert "quant.dependencia" in codes
    assert "quant.retorno_volatilidade" not in codes
    assert "quant.correlacao" not in codes


def test_legacy_continua_registrada_executavel_mas_oculta():
    carregar_tools()
    rv = spec_de("quant.retorno_volatilidade")
    corr = spec_de("quant.correlacao")
    assert rv.exposed_to_llm is False and rv.semver == "1.0.4"
    assert corr.exposed_to_llm is False and corr.semver == "1.0.3"
    assert callable(rv.calcular) and callable(corr.calcular)


def test_canonicas_expostas_com_novas_versoes():
    carregar_tools()
    rr = spec_de("quant.risco_retorno")
    dep = spec_de("quant.dependencia")
    assert rr.exposed_to_llm is True and rr.semver == "1.0.1"
    assert dep.exposed_to_llm is True and dep.semver == "2.0.0"


def test_planner_nao_instrui_mais_tools_legacy():
    prompt = (RAIZ / "prompts" / "analista.planner.j2").read_text(encoding="utf-8")
    assert "quant.risco_retorno" in prompt
    assert "quant.dependencia" in prompt
    assert "quant.retorno_volatilidade" not in prompt
    assert "quant.correlacao" not in prompt


def test_evals_novos_apontam_para_tools_canonicas():
    casos = (RAIZ / "tests" / "evals" / "casos.yaml").read_text(encoding="utf-8")
    trecho = casos[casos.index("# ------------------------------------------------------------------ analista"):]
    assert "tool: quant.risco_retorno" in trecho
    assert "tool: quant.dependencia" in trecho
    assert "tool: quant.retorno_volatilidade" not in trecho
    assert "tool: quant.correlacao" not in trecho


def _ev():
    return {
        "fonte": "b3", "instrument_ids": [], "tickers": [], "index_codes": [],
        "cutoff_date": "2024-01-31", "as_of": "2024-01-31", "n_observacoes": 20,
        "lacunas": [], "metodo": "teste", "nota_metodo": "teste", "suficiente": True,
        "avisos": [], "metricas": {}, "ingestion_batch_ids": [],
    }


def test_blocos_canonicos_estao_mapeados_sem_remover_replay_legacy():
    from app.agents.blocos import blocos_de

    rr = {"ticker": "PETR4", "periodo": {"de": "2024-01-01", "ate": "2024-01-31", "n": 20},
          "retorno_acumulado_pct": 3.0, "retorno_anualizado_pct": 40.0,
          "vol_anualizada_pct": 25.0, "max_drawdown_pct": -8.0, "evidencia": _ev()}
    dep = {"par": "PETR4 × VALE3", "metodo": "spearman", "coeficiente": 0.42,
           "n_pares": 19, "defasagem_observacoes": -1, "evidencia": _ev()}
    assert blocos_de("quant.risco_retorno", rr, execution_id="rr")
    blocos = blocos_de("quant.dependencia", dep, execution_id="dep")
    assert len(blocos) == 2
    assert blocos[1]["dados"]["itens"][2]["detalhe"] == "observações comuns"
    # Replay histórico continua tendo mapeador determinístico.
    assert blocos_de("quant.retorno_volatilidade", rr, execution_id="legacy")
