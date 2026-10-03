from pathlib import Path

from app.agents.blocos import blocos_de
from app.agents.turn import filtrar_tools
from app.tools import carregar_tools
from app.tools.registry import spec_de, specs_registradas

ROOT = Path(__file__).resolve().parent.parent
PLANNER = ROOT / "prompts" / "analista.planner.j2"

carregar_tools()


def _evidencia():
    return {
        "fonte": "b3",
        "instrument_ids": ["iid"],
        "tickers": ["PETR4"],
        "index_codes": [],
        "cutoff_date": "2026-10-02",
        "as_of": "2026-10-02",
        "n_observacoes": 100,
        "lacunas": [],
        "metodo": "risco_retorno:adjusted_close:retrospective_as_known_now:log:base_252",
        "nota_metodo": "target periódico 0%; intervalos observados",
        "suficiente": True,
        "avisos": [],
        "metricas": {
            "retorno_acumulado_pct": 10.0,
            "retorno_anualizado_pct": 12.0,
            "vol_anualizada_pct": 20.0,
            "downside_deviation_anualizada_pct": 13.5,
            "max_drawdown_pct": -18.0,
        },
        "ingestion_batch_ids": ["batch"],
    }


def test_risco_retorno_1_1_publico_sem_tool_paralela():
    spec = spec_de("quant.risco_retorno")
    assert spec.semver == "1.1.0"
    assert spec.exposed_to_llm is True
    visible = {
        s.code
        for s in filtrar_tools(
            specs_registradas(),
            familias=["quant", "dados"],
            plano="free",
        )
    }
    assert "quant.risco_retorno" in visible
    assert "quant.downside_risk" not in {s.code for s in specs_registradas()}
    assert "quant.drawdown_recovery" not in {s.code for s in specs_registradas()}


def test_bloco_expoe_downside_e_drawdown_em_intervalos_observados():
    payload = {
        "ticker": "PETR4",
        "periodo": {"de": "2026-01-02", "ate": "2026-10-02", "n": 100},
        "price_basis": "adjusted_close",
        "temporal_semantics": "retrospective_as_known_now",
        "retorno_acumulado_pct": 10.0,
        "retorno_anualizado_pct": 12.0,
        "vol_anualizada_pct": 20.0,
        "downside_deviation_anualizada_pct": 13.5,
        "downside_target_periodic_pct": 0.0,
        "max_drawdown_pct": -18.0,
        "drawdown": {
            "peak_date": "2026-03-02",
            "trough_date": "2026-04-02",
            "recovery_date": "2026-06-02",
            "depth_pct": -18.0,
            "time_to_trough_intervals": 22,
            "recovery_intervals": 41,
            "duration_intervals": 63,
            "recovered": True,
        },
        "evidencia": _evidencia(),
    }
    block = blocos_de("quant.risco_retorno", payload, execution_id="risk")[0]
    assert block["tipo"] == "indicadores"
    by_label = {item["rotulo"]: item for item in block["dados"]["itens"]}
    assert by_label["Downside deviation anualizada (alvo periódico 0%)"]["valor"] == 13.5
    assert by_label["Duração do pior drawdown"]["valor"] == 63
    assert by_label["Duração do pior drawdown"]["detalhe"] == "intervalos observados"
    assert by_label["Recuperação após o fundo"]["valor"] == 41
    assert "não em dias corridos" in block["nota"]


def test_planner_roteia_intencoes_avancadas_para_tool_existente():
    text = PLANNER.read_text(encoding="utf-8")
    for token in (
        "downside risk",
        "semidesvio",
        "duração do pior drawdown",
        "tempo de recuperação da maior queda",
        "`quant.risco_retorno`",
    ):
        assert token.replace("\\", "") in text
    assert "quant.downside_risk" not in text
    assert "quant.drawdown_recovery" not in text
