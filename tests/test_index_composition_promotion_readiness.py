from pathlib import Path

from app.agents.blocos import blocos_de
from app.agents.turn import filtrar_tools
from app.tools import carregar_tools
from app.tools.registry import spec_de, specs_registradas

ROOT = Path(__file__).resolve().parent.parent
PLANNER = ROOT / "prompts" / "analista.planner.j2"

carregar_tools()


def test_composicao_indice_publica_e_planner_restritivo():
    spec = spec_de("dados.composicao_indice")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    visible = {
        s.code
        for s in filtrar_tools(
            specs_registradas(),
            familias=["quant", "dados"],
            plano="free",
        )
    }
    assert "dados.composicao_indice" in visible
    assert len(specs_registradas()) == 37
    assert sum(s.exposed_to_llm for s in specs_registradas()) == 34

    text = PLANNER.read_text(encoding="utf-8")
    for token in (
        "dados.composicao_indice",
        "quais ações compõem o IBrA?",
        "qual o peso de PETR4 no IBrA?",
        "Use `em` somente quando houver data econômica explícita",
        "não infira membership em data sem snapshot",
        "retorno/performance do índice",
        "análise da carteira do cliente",
    ):
        assert token in text


def test_bloco_composicao_indice_preserva_pesos_e_restricoes():
    payload = {
        "indice": "ibra",
        "nome_indice": "Índice Brasil Amplo B3",
        "data_carteira": "2026-10-02",
        "n_componentes_total": 148,
        "peso_total_pct": 100.0,
        "componentes": [
            {
                "ticker": "PETR4",
                "nome": "PETROBRAS",
                "peso_pct": 8.125,
                "quantidade_teorica": 1000000.0,
            },
            {
                "ticker": "VALE3",
                "nome": "VALE",
                "peso_pct": 7.75,
                "quantidade_teorica": 2000000.0,
            },
        ],
        "truncado": False,
        "provenance": {
            "dataset": "market.index_weights",
            "source_codes": ["b3"],
            "ingestion_batch_ids": ["batch-official"],
            "reference_date": "2026-10-02",
            "availability_date": "2026-10-03",
            "cutoff_date": "2026-10-03",
            "strict_pit": True,
            "temporal_semantics": "ingestion_finished_at_cutoff",
            "warnings": ["ticker_fora_da_carteira:MISS3"],
        },
    }

    block = blocos_de(
        "dados.composicao_indice",
        payload,
        execution_id="idx",
    )[0]
    assert block["tipo"] == "tabela"
    assert block["dados"]["linhas"][0]["ticker"] == "PETR4"
    assert block["dados"]["linhas"][0]["peso_pct"] == 8.125
    assert "MISS3 não aparece" in block["proveniencia"]["avisos"][0]
    assert block["proveniencia"]["as_of"] == "2026-10-02"
    assert block["proveniencia"]["premissas"]["membership"] == "snapshot_oficial_persistido"
    assert "Não há inferência de membership" in block["nota"]
    assert "análise de carteira do cliente" in block["nota"]
    assert "recomendação" in block["nota"]
