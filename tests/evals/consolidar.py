"""Consolida vários relatórios de evals (rodadas por bloco) em um só e imprime o resumo por caso.

Uso: python tests/evals/consolidar.py <saida.json> <relatorio1.json> [<relatorio2.json> ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def consolidar(destino: Path, fontes: list[Path]) -> dict:
    # mesmo id em mais de um relatório (rerun de um bloco): a ocorrência mais recente vence
    por_id: dict[str, dict] = {}
    for f in fontes:
        for c in json.loads(f.read_text(encoding="utf-8"))["casos"]:
            por_id[c["id"]] = c
    casos = list(por_id.values())
    checks = [c for caso in casos for c in caso["checagens"]]
    ok = sum(1 for c in checks if c["ok"])
    por_agente: dict[str, dict[str, int]] = {}
    for caso in casos:
        d = por_agente.setdefault(caso["agente"] or "roteador", {"casos": 0, "ok": 0})
        d["casos"] += 1
        d["ok"] += int(caso["ok"])
    resumo = {"casos": len(casos), "casos_ok": sum(1 for c in casos if c["ok"]),
              "checagens": len(checks), "checagens_ok": ok,
              "taxa_checagens": round(ok / len(checks), 4) if checks else None,
              "custo_usd": round(sum(c["custo_usd"] or 0 for c in casos), 4),
              "latencia_media_ms": int(sum(c["latencia_ms"] for c in casos) / len(casos)) if casos else None,
              "por_agente": por_agente}
    dados = {"fontes": [f.name for f in fontes], "resumo": resumo, "casos": casos}
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return dados


def imprimir(dados: dict) -> None:
    print(json.dumps(dados["resumo"], ensure_ascii=False))
    for c in dados["casos"]:
        falhas = [f"{x['criterio']}: {x['detalhe']}" for x in c["checagens"] if not x["ok"]]
        print(f"{'OK   ' if c['ok'] else 'FALHA'} {c['id']}" + (f"  ← {falhas}" if falhas else ""))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    imprimir(consolidar(Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]))
