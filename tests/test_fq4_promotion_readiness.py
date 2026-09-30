"""Contratos puros do estado promovido do FQ4.

O gate PostgreSQL 18 já ficou verde; estes testes garantem que as capacidades promovidas entram no
catálogo e que o alias temporário de event study v2 não permanece registrado.
"""
from pathlib import Path

from app.agents.turn import filtrar_tools
from app.tools import carregar_tools
from app.tools.registry import specs_registradas

ROOT = Path(__file__).resolve().parent.parent
PLANNER = ROOT / "prompts" / "analista.planner.j2"

carregar_tools()

FQ4_PUBLIC = {
    "quant.analise_condicional": "1.0.1",
    "quant.sensibilidade": "1.0.1",
    "quant.regimes": "1.0.1",
    "quant.event_study": "2.0.0",
}


def test_fq4_promovido_entra_no_catalogo() -> None:
    specs = {s.code: s for s in specs_registradas()}
    assert set(FQ4_PUBLIC) <= set(specs)
    for code, semver in FQ4_PUBLIC.items():
        assert specs[code].exposed_to_llm is True
        assert specs[code].semver == semver

    assert "quant.event_study_v2" not in specs
    visiveis = {
        s.code for s in filtrar_tools(specs_registradas(), familias=["quant", "dados"], plano="free")
    }
    assert set(FQ4_PUBLIC) <= visiveis
    assert {"quant.risco_retorno", "quant.dependencia"} <= visiveis


def test_planner_usa_codigos_canonicos_promovidos() -> None:
    text = PLANNER.read_text(encoding="utf-8")
    assert "`quant.analise_condicional`" in text
    assert "`quant.sensibilidade`" in text
    assert "`quant.regimes`" in text
    assert "Não substitua uma pergunta condicional" in text
    assert "quant.event_study_v2" not in text
    assert "`quant.event_study`" in text
