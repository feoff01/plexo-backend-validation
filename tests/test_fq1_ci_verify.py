from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "verify.yml"


def _workflow() -> tuple[dict, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data, text


def test_verify_ci_roda_postgres_18_e_suite_quant() -> None:
    data, text = _workflow()

    on = data.get("on", data.get(True))  # PyYAML 1.1 pode converter `on` para True.
    assert isinstance(on, dict)
    assert "pull_request" in on
    assert "workflow_dispatch" in on

    job = data["jobs"]["postgres"]
    assert job["services"]["postgres"]["image"] == "postgres:18"

    obrigatorios = (
        "python -m alembic upgrade head",
        "python tools/preparar_ambiente.py",
        "python tools/db_runner.py tests",
        "python tools/db_runner.py tests plexo_service",
        "tests/test_fq1_market_series.py",
        "tests/test_f5_analista_tools.py",
        "tests/test_f22_acervo.py",
        "tests/test_fq4_integration_db.py",
        "tests/test_fq5_integration_db.py",
        "python -m pytest -q",
        "python -m app.cli prompts check",
        "python -m app.cli tools sync --check",
    )
    for trecho in obrigatorios:
        assert trecho in text


def test_verify_ci_e_isolada_de_producao() -> None:
    _, text = _workflow()

    proibidos = (
        "PLEXO_ENV",
        "EC2_SSH_KEY",
        "deploy/deploy.sh",
        ".env.producao",
        "secrets.",
        "aiven",
    )
    lower = text.lower()
    for trecho in proibidos:
        assert trecho.lower() not in lower

    assert "DATABASE_URL=postgresql://postgres:plexo@localhost:5432/plexo?sslmode=disable" in text
