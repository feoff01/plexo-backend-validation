from pathlib import Path

from app.agents.blocos import blocos_de
from app.agents.turn import filtrar_tools
from app.tools import carregar_tools
from app.tools.registry import spec_de, specs_registradas

ROOT = Path(__file__).resolve().parent.parent
PLANNER = ROOT / "prompts" / "analista.planner.j2"

carregar_tools()


def _ev(**kw):
    base = {
        "fonte": "b3+cvm",
        "cutoff_date": "2026-10-02",
        "as_of": "2026-10-02",
        "n_observacoes": 12,
        "lacunas": [],
        "metodo": "teste",
        "suficiente": True,
        "avisos": [],
        "metricas": {},
        "ingestion_batch_ids": [],
    }
    base.update(kw)
    return base


def test_comparaveis_setor_promovido_e_visivel_no_catalogo():
    spec = spec_de("quant.comparaveis_setor")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    assert spec.requires_market_data is True

    visible = {
        s.code
        for s in filtrar_tools(
            specs_registradas(),
            familias=["quant", "dados"],
            plano="free",
        )
    }
    assert "quant.comparaveis_setor" in visible
    assert spec_de("quant.valor_mercado").semver == "1.0.0"
    assert spec_de("quant.tendencias_fundamentais").semver == "1.0.1"
    assert spec_de("quant.dependencia").semver == "2.0.0"


def test_planner_rota_comparacao_descritiva_sem_ranking_ou_fair_value():
    text = PLANNER.read_text(encoding="utf-8")
    assert "`quant.comparaveis_setor`" in text
    assert 'nivel="subsetor"' in text
    assert 'nivel="setor"' in text
    assert "melhor ação" in text
    assert "ranking" in text
    assert "mediana dos pares" in text
    assert "fair value" in text
    assert "NÃO use `quant.comparaveis_setor`" in text


def test_bloco_comparaveis_setor_e_descritivo_e_compacto():
    payload = {
        "ticker": "PETR4",
        "nivel": "subsetor",
        "classificacao": "Petróleo gás e biocombustíveis",
        "peer_count_total": 12,
        "comparacoes": [
            {
                "metric": "pe",
                "unit": "x",
                "target_value": 7.2,
                "n_valid": 10,
                "mean": 8.1,
                "median": 7.8,
                "sample_stddev": 1.2,
                "minimum": 5.0,
                "maximum": 11.0,
                "delta_target_vs_median": -0.6,
                "delta_unit": "x",
            },
            {
                "metric": "net_margin_pct",
                "unit": "%",
                "target_value": 14.0,
                "n_valid": 9,
                "mean": 12.0,
                "median": 12.5,
                "sample_stddev": 2.0,
                "minimum": 8.0,
                "maximum": 16.0,
                "delta_target_vs_median": 1.5,
                "delta_unit": "p.p.",
            },
        ],
        "peer_examples": [{"issuer_name": "Peer A", "tickers": ["PEER3"]}],
        "peer_examples_criterion": "ordem_alfabetica",
        "evidencia": _ev(),
    }
    blocks = blocos_de("quant.comparaveis_setor", payload, execution_id="e6")
    assert len(blocks) == 1
    block = blocks[0]
    assert block["tipo"] == "tabela"
    assert "12 pares" in block["subtitulo"]
    assert len(block["dados"]["linhas"]) == 2
    assert block["dados"]["linhas"][0]["mediana_pares"] == 7.8
    assert "não é fair value" in block["nota"]
    assert "ranking" in block["nota"]
    assert "recomendação" in block["nota"]
