from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.blocos import blocos_de
from app.agents.turn import filtrar_tools
from app.tools import carregar_tools
from app.tools.analista import risco_retorno
from app.tools.analista import risco_retorno_legacy_1_1_0 as legacy
from app.tools.registry import spec_de, specs_registradas

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden" / "quant_risco_retorno_1_1_0.json"
PLANNER = ROOT / "prompts" / "analista.planner.j2"
SEED = ROOT / "seeds" / "dev.sql"


def _golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_replay_golden_1_1_0_usa_modulo_legacy_congelado():
    dados = _golden()
    assert legacy.LEGACY_SEMVER == dados["tool"]["semver"] == "1.1.0"
    resolvido = legacy.RiscoRetornoResolvido.model_validate(dados["resolvido"])
    saida = legacy.calcular_risco_retorno(resolvido)
    assert saida.model_dump(mode="json") == dados["esperado"]


def test_default_1_2_preserva_payload_numerico_1_1_e_so_adiciona_campo_nulo():
    dados = _golden()
    resolvido = risco_retorno.RiscoRetornoResolvido.model_validate(dados["resolvido"])
    saida = risco_retorno.calcular_risco_retorno(resolvido)
    payload = saida.model_dump(mode="json")
    assert payload.pop("evolucao_volatilidade") is None
    assert payload == dados["esperado"]


def test_contrato_publico_1_2_e_aditivo_sem_tool_paralela():
    carregar_tools()
    spec = spec_de("quant.risco_retorno")
    assert spec.semver == "1.2.0"
    assert spec.exposed_to_llm is True
    assert {"incluir_evolucao_volatilidade", "janela_volatilidade_observacoes"} <= set(
        spec.param_schema.get("properties", {})
    )
    assert "evolucao_volatilidade" in spec.output_schema.get("properties", {})
    codes = {s.code for s in specs_registradas()}
    assert "quant.risco_historico" not in codes
    assert "quant.rolling_volatility" not in codes
    assert len(specs_registradas()) == 37
    assert sum(s.exposed_to_llm for s in specs_registradas()) == 34

    visible = {
        s.code
        for s in filtrar_tools(
            specs_registradas(),
            familias=["quant", "dados"],
            plano="free",
        )
    }
    assert "quant.risco_retorno" in visible


def test_schema_recusa_janela_sem_pedir_evolucao():
    with pytest.raises(ValidationError, match="incluir_evolucao_volatilidade"):
        risco_retorno.RiscoRetornoParams(
            ticker="PETR4",
            janela_volatilidade_observacoes=21,
        )


def test_policy_seed_governa_default_21_observacoes_sem_literal_de_fallback():
    seed = SEED.read_text(encoding="utf-8")
    assert '"risco_janela_movel_observacoes": 21' in seed
    source = Path(risco_retorno.__file__).read_text(encoding="utf-8")
    assert 'cfg["risco_janela_movel_observacoes"]' in source
    assert "else 21" not in source
    assert "or 21" not in source


def test_payload_rolling_representativo_fica_abaixo_de_5kb():
    dados = _golden()
    resolvido_payload = {
        **dados["resolvido"],
        "incluir_evolucao_volatilidade": True,
        "janela_volatilidade_observacoes": 2,
    }
    resolvido = risco_retorno.RiscoRetornoResolvido.model_validate(resolvido_payload)
    candidato = risco_retorno.calcular_risco_retorno(resolvido)

    assert candidato.evolucao_volatilidade is not None
    assert candidato.evolucao_volatilidade.janela_observacoes == 2
    assert candidato.evolucao_volatilidade.n_janelas_total == 3
    assert candidato.evolucao_volatilidade.amostrado is True
    assert risco_retorno.SERIE_RISCO_AMOSTRADA in candidato.evidencia.avisos

    compact = json.dumps(
        candidato.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(compact) < 5_000


def test_bloco_adiciona_uma_serie_rolling_sem_mudar_indicadores():
    dados = _golden()
    resolvido = risco_retorno.RiscoRetornoResolvido.model_validate({
        **dados["resolvido"],
        "incluir_evolucao_volatilidade": True,
        "janela_volatilidade_observacoes": 2,
    })
    out = risco_retorno.calcular_risco_retorno(resolvido).model_dump(mode="json")
    blocos = blocos_de("quant.risco_retorno", out, execution_id="rr")

    assert [b["tipo"] for b in blocos] == ["indicadores", "serie"]
    assert blocos[0]["titulo"] == "Retorno e volatilidade · PETR4"
    serie = blocos[1]
    assert serie["titulo"] == "Evolução da volatilidade · PETR4"
    assert serie["subtitulo"] == "janela móvel de 2 observações de retorno"
    assert serie["dados"]["eixo_y"]["formato"] == "pct"
    assert serie["dados"]["series"][0]["nome"] == "Volatilidade anualizada"
    assert "não é previsão" in serie["nota"]


def test_planner_ativa_rolling_so_para_intencao_temporal_e_nao_inventa_janela():
    text = PLANNER.read_text(encoding="utf-8")
    for token in (
        "COMO A VOLATILIDADE EVOLUIU NO TEMPO",
        "incluir_evolucao_volatilidade=true",
        "janela_volatilidade_observacoes",
        "policy governada",
        "Não converta dias corridos em observações",
    ):
        assert token in text
