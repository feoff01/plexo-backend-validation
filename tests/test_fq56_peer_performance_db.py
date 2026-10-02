from __future__ import annotations

import json
import time

import pytest

from app.tools.analista.comparaveis_setor import (
    ComparaveisSetorParams,
    calcular_comparaveis_setor,
    preparar_comparaveis_setor,
)
from app.tools.executor import ToolContext
from tests.test_f5_analista_tools import CUTOFF
from tests.test_fq5_integration_db import fq5_mundo
from tests.test_fq56_peer_comparison_db import (
    _action,
    _copy_prices,
    _fundamentals,
    _issuer,
    _sector,
    _sector_batch,
)


class CountingConnection:
    def __init__(self, conn):
        self._conn = conn
        self.execute_count = 0

    async def execute(self, *args, **kwargs):
        self.execute_count += 1
        return await self._conn.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


async def _build_peers(conn, fq5_mundo, peer_count: int) -> None:
    source_id = fq5_mundo["ids"]["FQ5ON"]
    batch = await _sector_batch(conn, "e")
    for iid in (fq5_mundo["ids"]["FQ5ON"], fq5_mundo["ids"]["FQ5PN"]):
        await _sector(conn, iid, batch, subsector="Benchmark Peers")

    for idx in range(1, peer_count + 1):
        root = f"Q{idx:03d}"
        ticker = f"{root}3"
        cnpj = f"5500000000{idx:04d}"
        issuer_id = await _issuer(conn, f"Peer Benchmark {idx:02d}", cnpj)
        instrument_id = await _action(conn, issuer_id, ticker)
        await _copy_prices(conn, source_id, instrument_id, 0.70 + idx / 100)
        await _fundamentals(
            conn,
            cnpj,
            [(instrument_id, 800_000_000.0 + idx * 10_000_000.0)],
            latest_revenue=80_000_000_000.0 + idx * 1_000_000_000.0,
            latest_ebitda=16_000_000_000.0 + idx * 200_000_000.0,
            latest_income=6_000_000_000.0 + idx * 100_000_000.0,
            prior_revenue=70_000_000_000.0 + idx * 900_000_000.0,
            prior_ebitda=14_000_000_000.0 + idx * 180_000_000.0,
            prior_income=5_000_000_000.0 + idx * 90_000_000.0,
        )
        await _sector(conn, instrument_id, batch, subsector="Benchmark Peers")


@pytest.mark.asyncio
@pytest.mark.parametrize("peer_count", [2, 8, 20])
async def test_peer_performance_baseline(db, fq5_mundo, peer_count):
    async with db.service_session() as conn:
        await _build_peers(conn, fq5_mundo, peer_count)

        counted = CountingConnection(conn)
        ctx = ToolContext(
            conn=counted,
            scope_id=fq5_mundo["e"].s1,
            conversation_id=None,
            cutoff_date=CUTOFF,
        )
        params = ComparaveisSetorParams(ticker="FQ5ON", max_exemplos=5)

        t0 = time.perf_counter()
        resolved = await preparar_comparaveis_setor(params, ctx)
        prepare_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        output = calcular_comparaveis_setor(resolved)
        calculate_ms = (time.perf_counter() - t1) * 1000

        resolved_bytes = len(resolved.model_dump_json().encode("utf-8"))
        output_bytes = len(output.model_dump_json().encode("utf-8"))
        assert output.peer_count_total == peer_count
        assert len(output.peer_examples) == min(5, peer_count)
        assert len(output.comparacoes) == 10
        assert output.evidencia.suficiente is True

        sample = {
            "peer_count": peer_count,
            "prepare_query_count": counted.execute_count,
            "prepare_elapsed_ms": round(prepare_ms, 3),
            "calculate_elapsed_ms": round(calculate_ms, 3),
            "resolved_payload_bytes": resolved_bytes,
            "output_payload_bytes": output_bytes,
            "metric_count": len(output.comparacoes),
            "peer_examples_count": len(output.peer_examples),
        }
        print("FQ56_PEER_BENCHMARK " + json.dumps(sample, sort_keys=True))
