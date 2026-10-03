from datetime import date
import json
from pathlib import Path

from app.agents.blocos import blocos_de
from app.agents.turn import filtrar_tools
from app.market.anbima_yield_curve_source import parse_anbima_yield_curve_csv
from app.market.yield_curves import ResolvedYieldCurve, YieldCurvePoint, YieldCurveProvenance
from app.tools import carregar_tools
from app.tools.analista.curva_juros import CurvaJurosResolvida, montar_curva_juros
from app.tools.registry import spec_de, specs_registradas

ROOT = Path(__file__).resolve().parent.parent
PLANNER = ROOT / "prompts" / "analista.planner.j2"
FIXTURE = Path(__file__).parent / "fixtures" / "market" / "anbima_ettj_2026-10-02.csv"

carregar_tools()


def test_curva_juros_publica_e_planner_restritivo():
    spec = spec_de("dados.curva_juros")
    assert spec.semver == "1.0.1"
    assert spec.exposed_to_llm is True
    visible = {
        s.code for s in filtrar_tools(
            specs_registradas(), familias=["quant", "dados"], plano="free"
        )
    }
    assert "dados.curva_juros" in visible
    assert len(specs_registradas()) == 36
    assert sum(s.exposed_to_llm for s in specs_registradas()) == 33

    text = PLANNER.read_text(encoding="utf-8")
    for token in (
        "dados.curva_juros",
        'curva="ettj_pre"',
        'curva="ettj_ipca"',
        'curva="inflacao_implicita"',
        "NÃO invente conversão",
        "delta entre datas",
        "duration/DV01",
        "forecast de juros",
        "dados.serie_indice",
    ):
        assert token in text


def test_bloco_curva_juros_preserva_vertices_e_restricoes():
    payload = {
        "curva": "ettj_pre",
        "unidade": "% a.a./252 d.u.",
        "data_curva": "2026-10-02",
        "pontos": [
            {"vertice_du": 252, "taxa_pct_aa_252": 13.3811},
            {"vertice_du": 504, "taxa_pct_aa_252": 13.7085},
        ],
        "n_vertices_total": 19,
        "n_vertices_retornados": 2,
        "provenance": {
            "source_codes": ["anbima"],
            "reference_date": "2026-10-02",
            "cutoff_date": "2026-10-03",
            "temporal_semantics": "ingestion_finished_at_cutoff",
            "warnings": ["vertice_ettj_indisponivel:378"],
        },
    }
    block = blocos_de("dados.curva_juros", payload, execution_id="yc")[0]
    assert block["tipo"] == "tabela"
    assert block["dados"]["linhas"][0] == {
        "vertice_du": 252, "taxa_pct_aa_252": 13.3811
    }
    assert "nenhum valor aproximado" in block["proveniencia"]["avisos"][0]
    assert "não há interpolação" in block["nota"]
    assert "previsão" in block["nota"]


def test_payload_completo_ipca_permanece_abaixo_de_5kb():
    snapshot = parse_anbima_yield_curve_csv(FIXTURE.read_bytes())
    points = [
        YieldCurvePoint(
            business_days=p.business_days,
            rate_pct=float(p.ipca_rate_pct),
            day_count="du_252",
            source_code="anbima",
            ingestion_batch_id="batch-official",
            availability_date=date(2026, 10, 3),
        )
        for p in snapshot.points
    ]
    provenance = YieldCurveProvenance(
        source_codes=["anbima"],
        ingestion_batch_ids=["batch-official"],
        reference_date=snapshot.reference_date,
        availability_date=date(2026, 10, 3),
        cutoff_date=date(2026, 10, 3),
        strict_pit=True,
    )
    out = montar_curva_juros(
        CurvaJurosResolvida(
            curva="ettj_ipca",
            cutoff_date=date(2026, 10, 3),
            resolved=ResolvedYieldCurve(
                curve_name="ettj_ipca",
                reference_date=snapshot.reference_date,
                points=points,
                provenance=provenance,
            ),
        )
    )
    payload = out.model_dump(mode="json")
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    assert size < 5000
    assert out.n_vertices_retornados == 65
