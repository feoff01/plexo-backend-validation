"""Contratos puros de prontidão para promoção do FQ4.

Não promove nada: garante que o planner está preparado, mas as quatro capacidades continuam shadow
até o gate PostgreSQL/sync ser realmente verde.
"""
from pathlib import Path

from app.agents.turn import filtrar_tools
from app.tools import carregar_tools
from app.tools.registry import specs_registradas

ROOT = Path(__file__).resolve().parent.parent
PLANNER = ROOT / "prompts" / "analista.planner.j2"

carregar_tools()


FQ4_SHADOWS = {
    "quant.analise_condicional",
    "quant.sensibilidade",
    "quant.regimes",
    "quant.event_study_v2",
}


def test_fq4_continua_shadow_ate_gate_postgres() -> None:
    specs = {s.code: s for s in specs_registradas()}
    assert FQ4_SHADOWS <= set(specs)
    assert all(specs[c].exposed_to_llm is False for c in FQ4_SHADOWS)

    visiveis = {
        s.code for s in filtrar_tools(specs_registradas(), familias=["quant", "dados"], plano="free")
    }
    assert FQ4_SHADOWS.isdisjoint(visiveis)
    assert {"quant.risco_retorno", "quant.dependencia", "quant.event_study"} <= visiveis


def test_planner_esta_preparado_para_promocao_condicional_ao_catalogo() -> None:
    text = PLANNER.read_text(encoding="utf-8")
    assert "SOMENTE quando os respectivos `tool_code` estiverem presentes em `catalogo_tools`" in text
    assert "`quant.analise_condicional`" in text
    assert "`quant.sensibilidade`" in text
    assert "`quant.regimes`" in text
    assert "Não substitua uma pergunta condicional" in text

    # A implementação v2 é shadow; o cutover deve manter o nome canônico quant.event_study.
    assert "quant.event_study_v2" not in text
    assert "`quant.event_study`" in text
