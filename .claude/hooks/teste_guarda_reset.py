#!/usr/bin/env python3
"""Teste de sabotagem do guarda_reset.py — prova que ele RECUSA e que PERMITE (não toca banco).

Padrão da casa: um guarda que ninguém tentou violar é um guarda não testado. Cada caso simula
o JSON que o Claude Code entrega no stdin do hook e confere o exit code. O .env é sempre uma
fixture temporária (`--env`), nunca o real — o teste roda em qualquer máquina, inclusive CI.

Uso: python teste_guarda_reset.py   (exit 0 = todos os casos passaram)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).with_name("guarda_reset.py")

FIXTURE_REMOTO = (
    'DATABASE_URL="postgresql+psycopg://usuario:senha@exemplo-plexo.a.aivencloud.com:12345/'
    'plexo?sslmode=require"\n'
)
FIXTURE_LOCAL = "DATABASE_URL=postgresql://postgres:plexo@localhost:5433/plexo?sslmode=disable\n"

CASOS = [
    # (nome, comando simulado, conteúdo do .env fixture | None = arquivo inexistente, exit esperado)
    ("reset com .env remoto -> recusa", "python tools/db_runner.py reset", FIXTURE_REMOTO, 2),
    ("reset com .env localhost -> permite", "python tools/db_runner.py reset", FIXTURE_LOCAL, 0),
    ("reset com .env ilegível -> recusa (fail-closed)", "python tools/db_runner.py reset", None, 2),
    ("comando inocente -> passa", "python tools/db_runner.py tests plexo_service", FIXTURE_REMOTO, 0),
    ("caminho Windows/backslash -> recusa", r"python tools\db_runner.py reset", FIXTURE_REMOTO, 2),
    ("alembic downgrade -> recusa", ".venv/Scripts/python.exe -m alembic downgrade -1", FIXTURE_REMOTO, 2),
    ("DROP SCHEMA via python -c -> recusa",
     "python -c \"cur.execute('DROP SCHEMA core CASCADE')\"", FIXTURE_REMOTO, 2),
    ("forma prefixada pelo rtk -> recusa igual",
     "rtk proxy python tools/db_runner.py reset", FIXTURE_REMOTO, 2),
    ("MAIÚSCULAS -> recusa (case-insensitive)", "python TOOLS/DB_RUNNER.PY RESET", FIXTURE_REMOTO, 2),
    ("stdin sem comando -> passa", "", FIXTURE_REMOTO, 0),
]


def roda(comando: str, env_conteudo: str | None) -> int:
    if env_conteudo is None:
        caminho_env = Path(tempfile.gettempdir()) / "guarda_reset_env_inexistente.env"
        caminho_env.unlink(missing_ok=True)
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as f:
            f.write(env_conteudo)
            caminho_env = Path(f.name)
    try:
        entrada = json.dumps({"tool_input": {"command": comando}})
        r = subprocess.run([sys.executable, str(HOOK), "--env", str(caminho_env)],
                           input=entrada, capture_output=True, text=True, timeout=30)
        return r.returncode
    finally:
        if env_conteudo is not None:
            caminho_env.unlink(missing_ok=True)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # acentos × cp1252
    except Exception:
        pass
    falhas = 0
    for nome, comando, env_conteudo, esperado in CASOS:
        obtido = roda(comando, env_conteudo)
        ok = obtido == esperado
        print(f"{'PASSOU' if ok else 'FALHOU'}  {nome}  (exit {obtido}, esperado {esperado})")
        if not ok:
            falhas += 1
    print(f"\n{len(CASOS) - falhas}/{len(CASOS)} casos passaram")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
