#!/usr/bin/env python3
"""Dry-run read-only: Economatica setor/subsetor × catálogo market do Plexo.

Uso:
  python tools/economatica_sector_coverage.py --arquivo /caminho/export.xlsx

Não grava dados. A conexão é aberta em modo read-only antes da transação.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config.settings import Settings  # noqa: E402
from app.market.economatica_coverage import measure_economatica_catalog_coverage  # noqa: E402
from app.market.economatica_sector_source import parse_economatica_sector_xlsx  # noqa: E402


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arquivo", required=True, type=Path)
    parser.add_argument("--max-exemplos", type=int, default=20)
    return parser.parse_args()


async def _main(path: Path, max_examples: int) -> None:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    snapshot = parse_economatica_sector_xlsx(raw)
    settings = Settings()

    conn = await psycopg.AsyncConnection.connect(settings.pg_conninfo("service"), autocommit=False)
    try:
        await conn.set_read_only(True)
        async with conn.transaction():
            if settings.db_set_role:
                await conn.execute("RESET ROLE")
                await conn.execute(f"SET LOCAL ROLE {settings.papel_sql('service')}")
            await conn.execute(
                "select set_config('app.user_id', '', true), "
                "set_config('app.scope_id', '', true), set_config('app.role', 'service', true)"
            )
            cur = await conn.execute("show transaction_read_only")
            row = await cur.fetchone()
            if row is None or str(row[0]).lower() != "on":
                raise RuntimeError("coverage_dry_run_nao_esta_read_only")
            report = await measure_economatica_catalog_coverage(
                conn, snapshot.records, max_examples=max_examples
            )
    finally:
        await conn.close()

    payload = report.model_dump(mode="json")
    payload["file_sha256"] = digest
    payload["source_rows_seen"] = snapshot.rows_seen
    payload["source_rows_filtered"] = snapshot.rows_filtered
    payload["mode"] = "read_only_dry_run"
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    args = _args()
    asyncio.run(_main(args.arquivo, args.max_exemplos))
