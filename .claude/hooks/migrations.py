#!/usr/bin/env python3
"""Hooks do banco da Plexo. Dois modos, um arquivo:

  --pre    PreToolUse (Edit|Write): RECUSA editar migration já aplicada.
  --pos    PostToolUse (Edit|Write): roda o validador estático quando SQL/tooling muda.

Por que o `--pre` existe: "migrations são append-only" é a regra 3 do CLAUDE.md e a que mais
custa caro quando é quebrada — todas as migrations já foram aplicadas em ambiente real, e editar
uma delas dessincroniza o banco do repositório sem que nada acuse. Até aqui a regra vivia só
como texto num README. Agora ela é mecânica.

Como o hook sabe que uma migration já foi aplicada: **está versionada no git**. `plexo-backend` é
um repositório e o deploy publica dali; arquivo rastreado = já saiu daqui = aplicado. Arquivo
ainda não rastreado é o que você acabou de criar nesta sessão — e esse pode ser corrigido à
vontade, que é o caso legítimo de editar uma migration.

Entrada: JSON do hook no stdin. Saída: exit 2 + mensagem no stderr quando recusa (o agente lê e
corrige). Silencioso quando passa.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent      # plexo-backend/
VALIDADOR = BACKEND / "tools" / "validador.py"

# Só estes dois lugares são append-only. Testes, app/, tools/ e docs mudam à vontade.
def _e_migration(caminho: Path) -> bool:
    try:
        rel = caminho.resolve().relative_to(BACKEND)
    except ValueError:
        return False
    partes = rel.parts
    if len(partes) == 2 and partes[0] == "sql" and rel.suffix == ".sql":
        return True
    return len(partes) == 3 and partes[:2] == ("alembic", "versions") and rel.suffix == ".py"


def _rastreado_no_git(caminho: Path) -> bool:
    try:
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(caminho)],
                           cwd=BACKEND, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False     # sem git disponível, não bloqueia: hook não pode virar impedimento
    return r.returncode == 0


def _caminho_do_evento() -> Path | None:
    try:
        evento = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return None
    bruto = (evento.get("tool_input") or {}).get("file_path")
    return Path(bruto) if bruto else None


def pre() -> int:
    caminho = _caminho_do_evento()
    if caminho is None or not _e_migration(caminho):
        return 0
    if not _rastreado_no_git(caminho):
        return 0     # criada nesta sessão, ainda não publicada: corrigir é legítimo
    proxima = _proxima_numeracao()
    print(
        f"RECUSADO: {caminho.name} já está versionado — ou seja, já foi aplicado em ambiente real.\n"
        "Migrations são append-only (CLAUDE.md, regra 3): editar uma aplicada dessincroniza o banco\n"
        "do repositório e quebra a trilha de auditoria, sem que nada acuse.\n"
        f"O caminho é um arquivo NOVO: sql/{proxima}_<nome>.sql + alembic/versions/{proxima}_<nome>.py,\n"
        "usando CREATE OR REPLACE / ALTER TABLE para evoluir o que já existe.",
        file=sys.stderr)
    return 2


def _proxima_numeracao() -> str:
    numeros = [int(p.name[:2]) for p in (BACKEND / "sql").glob("*.sql")
               if p.name[:2].isdigit()]
    return f"{(max(numeros) + 1) if numeros else 0:02d}"


def pos() -> int:
    caminho = _caminho_do_evento()
    if caminho is None:
        return 0
    try:
        rel = caminho.resolve().relative_to(BACKEND)
    except ValueError:
        return 0
    if rel.parts[0] not in ("sql", "tests", "tools") or rel.suffix not in (".sql", ".py"):
        return 0
    r = subprocess.run([sys.executable, str(VALIDADOR)], cwd=BACKEND,
                       capture_output=True, text=True, timeout=120)
    saida = (r.stdout or "") + (r.stderr or "")
    if "erros: 0" in saida:
        return 0
    print("Validador estático acusou problema depois desta edição:\n" + saida.strip()[-2000:],
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "--pre"
    sys.exit(pre() if modo == "--pre" else pos())
