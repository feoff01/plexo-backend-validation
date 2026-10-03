from __future__ import annotations

import json
from pathlib import Path

from app.tools import carregar_tools
from app.tools.analista import _risco_retorno_rolling_shadow as shadow
from app.tools.analista import risco_retorno
from app.tools.registry import spec_de, specs_registradas

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden" / "quant_risco_retorno_1_1_0.json"
SHADOW_FILE = ROOT / "app" / "tools" / "analista" / "_risco_retorno_rolling_shadow.py"


def _golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_replay_golden_congela_quant_risco_retorno_1_1_0():
    dados = _golden()
    carregar_tools()
    spec = spec_de(dados["tool"]["code"])
    assert spec.semver == dados["tool"]["semver"] == "1.1.0"

    resolvido = risco_retorno.RiscoRetornoResolvido.model_validate(dados["resolvido"])
    saida = risco_retorno.calcular_risco_retorno(resolvido)
    assert saida.model_dump(mode="json") == dados["esperado"]


def test_contrato_publico_1_1_fica_congelado_enquanto_shadow_nao_participa_do_fingerprint():
    carregar_tools()
    spec = spec_de("quant.risco_retorno")
    assert spec.semver == "1.1.0"
    assert spec.exposed_to_llm is True
    assert "incluir_evolucao_volatilidade" not in spec.param_schema.get("properties", {})
    assert "janela_volatilidade_observacoes" not in spec.param_schema.get("properties", {})
    assert "evolucao_volatilidade" not in spec.output_schema.get("properties", {})
    assert "_risco_retorno_rolling_shadow.py" not in {Path(p).name for p in spec.source_files}
    assert len(spec.source_sha256) == 64
    assert len(specs_registradas()) == 37
    assert sum(s.exposed_to_llm for s in specs_registradas()) == 34


def test_shadow_nao_tem_registro_de_tool():
    source = SHADOW_FILE.read_text(encoding="utf-8")
    assert "@tool(" not in source
    assert 'code="quant.' not in source


def test_payload_candidato_representativo_fica_abaixo_de_5kb_sem_mudar_o_replay_base():
    dados = _golden()
    resolvido = risco_retorno.RiscoRetornoResolvido.model_validate(dados["resolvido"])
    candidato = shadow.calcular_risco_retorno_rolling_shadow(
        resolvido,
        janela_observacoes=2,
    )
    payload = candidato.model_dump(mode="json")
    base = dict(payload)
    base.pop("evolucao_volatilidade")
    base.pop("avisos_candidato")
    assert base == dados["esperado"]

    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(compact) < 5_000
    assert candidato.evolucao_volatilidade is not None
    assert candidato.evolucao_volatilidade.janela_observacoes == 2
