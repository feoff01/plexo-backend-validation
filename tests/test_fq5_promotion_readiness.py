"""Contratos de promoção do FQ5 Company/Market Analytics após consolidação de dependência."""
from pathlib import Path

from app.agents.turn import filtrar_tools
from app.tools import carregar_tools
from app.tools.registry import spec_de, specs_registradas

ROOT = Path(__file__).resolve().parent.parent
PLANNER = ROOT / "prompts" / "analista.planner.j2"

carregar_tools()

FQ5_PUBLIC = {
    "dados.fundamentos_empresa": "1.0.0",
    "quant.valor_mercado": "1.0.0",
    "quant.cenario_sensibilidade": "1.0.0",
}


def test_fq5_publico_entra_no_catalogo_sem_portfolio_analytics_e_macro_duplicada():
    specs = {s.code: s for s in specs_registradas()}
    for code, semver in FQ5_PUBLIC.items():
        assert specs[code].semver == semver
        assert specs[code].exposed_to_llm is True
        assert specs[code].requires_market_data is True
    assert spec_de("quant.dependencia").semver == "2.0.0"
    macro = spec_de("quant.dependencia_macro")
    assert macro.semver == "1.0.1" and macro.exposed_to_llm is False
    visible = {s.code for s in filtrar_tools(specs_registradas(), familias=["quant", "dados"], plano="free")}
    assert set(FQ5_PUBLIC) <= visible
    assert "quant.dependencia" in visible
    assert "quant.dependencia_macro" not in visible
    assert not any("portfolio" in code or "carteira" in code or "wealth" in code for code in FQ5_PUBLIC)


def test_planner_separa_market_value_cenario_e_fx_sem_inventar_choque():
    text = PLANNER.read_text(encoding="utf-8")
    for code in FQ5_PUBLIC:
        assert f"`{code}`" in text
    assert "`quant.dependencia`" in text
    assert "quant.dependencia_macro" not in text
    assert '"tipo":"cambio"' in text or '"tipo": "cambio"' in text
    assert "Market cap, EV e múltiplos NÃO são valor justo/intrínseco" in text
    assert "NÃO invente 1 p.p." in text
    assert "choque_driver=1.0" in text
    assert "USD/BRL" in text
    assert "NÃO faça contas entre outputs no LLM" in text
    assert "cenário mecânico associacional" in text
