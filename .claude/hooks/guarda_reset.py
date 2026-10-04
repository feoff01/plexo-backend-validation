#!/usr/bin/env python3
"""Hook PreToolUse (Bash|PowerShell): guarda contra comando destrutivo no banco compartilhado.

Dev e produção COMPARTILHAM o Aiven (CLAUDE.md, regra 1): `db_runner.py reset` apaga produção.
Até aqui essa regra vivia só como texto; este hook a torna mecânica, no mesmo espírito do
migrations.py (append-only). A decisão é SEMPRE pelo DATABASE_URL do arquivo
`plexo-backend/.env` — os tools do projeto leem do ARQUIVO, não do ambiente, então um
`DATABASE_URL=... comando` inline não muda o alvo real e não engana o guarda.

Comportamento:
  - comando sem padrão destrutivo          -> exit 0 (silencioso; 99% sai aqui)
  - padrão destrutivo + .env em localhost  -> exit 0 (Postgres docker local: caminho seguro)
  - padrão destrutivo + .env remoto        -> exit 2 (recusa didática no stderr)
  - padrão destrutivo + .env ilegível      -> exit 2 (FAIL-CLOSED: sem certeza = trata como
    remoto; ao contrário do migrations.py, aqui o custo do falso negativo é apagar produção)

A detecção é por substring sobre o comando normalizado (case-insensitive, backslash->slash):
pega heredoc e `python -c`, e sobrevive à reescrita do rtk (que só PREFIXA comandos que
conhece). É guarda-corpo contra acidente, não sandbox contra adversário — string montada
dinamicamente escapa, e tudo bem.

A mensagem de recusa NUNCA cita host/URL (SECRETS do db_runner incluem hostname e username).
Falso positivo aceito: `grep "DROP SCHEMA" sql/` é recusado — pesquise com a tool Grep/Read.
Teste de sabotagem: `python teste_guarda_reset.py` ao lado deste arquivo (não toca banco).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

BACKEND = Path(__file__).resolve().parent.parent.parent      # plexo-backend/
HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1"}

PADROES_DESTRUTIVOS = [
    re.compile(r"db_runner(\.py)?\s+reset"),
    re.compile(r"alembic\s+downgrade"),
    re.compile(r"drop\s+(database|schema)\b"),
    re.compile(r"drop\s+table\s+(if\s+exists\s+)?(public\.)?alembic_version"),
]


def host_do_env(env: Path) -> str | None:
    """Hostname do DATABASE_URL no .env — ou None quando não dá para ter certeza."""
    try:
        for linha in env.read_text(encoding="utf-8", errors="replace").splitlines():
            linha = linha.strip()
            if linha.startswith("export "):
                linha = linha[len("export "):].lstrip()
            chave, sep, valor = linha.partition("=")
            if not sep or chave.strip() != "DATABASE_URL":
                continue
            valor = valor.strip().strip('"').strip("'")
            if not valor:
                return None
            return urlsplit(valor).hostname   # urlsplit aceita postgresql+psycopg://
    except (OSError, ValueError):
        return None
    return None


def main() -> int:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # acentos × cp1252
    except Exception:
        pass
    env = BACKEND / ".env"
    argv = sys.argv[1:]
    if "--env" in argv:                      # injeção SÓ para o teste de sabotagem
        env = Path(argv[argv.index("--env") + 1])
    try:
        evento = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                             # stdin imprestável: não virar impedimento
    comando = (evento.get("tool_input") or {}).get("command") or ""
    if not comando:
        return 0
    normalizado = comando.replace("\\", "/").lower()
    if not any(p.search(normalizado) for p in PADROES_DESTRUTIVOS):
        return 0
    host = host_do_env(env)
    if host is not None and host.lower() in HOSTS_LOCAIS:
        return 0
    print(
        "RECUSADO: comando destrutivo de banco com DATABASE_URL fora de localhost.\n"
        "Dev e produção COMPARTILHAM o Aiven — reset/downgrade/DROP apaga produção\n"
        "(CLAUDE.md, regra 1). Caminho seguro para verificar do zero: Postgres local:\n"
        "  docker run -d -e POSTGRES_PASSWORD=plexo -e POSTGRES_DB=plexo -p 5433:5432 postgres:18\n"
        "  (backup do .env; DATABASE_URL para localhost:5433 com ?sslmode=disable; então\n"
        "   alembic upgrade head + python tools/preparar_ambiente.py — suíte ~33 s).\n"
        "Se este comando PRECISA mesmo rodar no banco remoto, peça ao usuário que rode à mão.",
        file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
