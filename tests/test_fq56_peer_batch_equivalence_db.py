from __future__ import annotations

import pytest

from app.market import peer_company_metrics
from app.tools.analista import tendencias_fundamentais as trends_tool
from app.tools.analista import valor_mercado as valor_tool
from app.tools.analista.comparaveis_setor import TREND_METRICS, _resolved_from_batch
from app.tools.executor import ToolContext
from tests.test_f5_analista_tools import CUTOFF
from tests.test_fq5_integration_db import fq5_mundo
from tests.test_fq56_peer_comparison_db import _action, _copy_prices, _fundamentals, _issuer


@pytest.mark.asyncio
async def test_peer_batch_resolved_is_equivalent_to_canonical_preparers(db, fq5_mundo):
    async with db.service_session() as conn:
        peer = await _issuer(conn, "Peer Batch Equiv", "66000000000101")
        p3 = await _action(conn, peer, "EQBV3")
        p4 = await _action(conn, peer, "EQBV4")
        source_id = fq5_mundo["ids"]["FQ5ON"]
        await _copy_prices(conn, source_id, p3, 0.80)
        await _copy_prices(conn, source_id, p4, 0.85)
        await _fundamentals(
            conn,
            "66000000000101",
            [(p3, 900_000_000.0), (p4, 300_000_000.0)],
            latest_revenue=95_000_000_000.0,
            latest_ebitda=19_000_000_000.0,
            latest_income=7_500_000_000.0,
            prior_revenue=80_000_000_000.0,
            prior_ebitda=15_500_000_000.0,
            prior_income=6_000_000_000.0,
        )

        ctx = ToolContext(
            conn=conn,
            scope_id=fq5_mundo["e"].s1,
            conversation_id=None,
            cutoff_date=CUTOFF,
        )
        canonical_val = await valor_tool.preparar_valor_mercado(
            valor_tool.ValorMercadoParams(ticker="EQBV3", data_referencia=CUTOFF),
            ctx,
        )
        canonical_trends = await trends_tool.preparar_tendencias_fundamentais(
            trends_tool.TendenciasFundamentaisParams(
                ticker="EQBV3",
                data_referencia=CUTOFF,
                scope="consolidated",
                periodos=2,
                metricas=list(TREND_METRICS),
            ),
            ctx,
        )

        batch = await peer_company_metrics.load_peer_company_metrics(
            conn,
            [
                peer_company_metrics.PeerCompanyRequest(
                    issuer_id=peer,
                    representative_ticker="EQBV3",
                )
            ],
            cutoff=CUTOFF,
            valuation_metrics=valor_tool.VALUATION_METRICS,
            trend_metrics=TREND_METRICS,
            trend_periods=2,
        )
        batch_val, batch_trends = _resolved_from_batch(batch[peer], CUTOFF)

        assert batch_val.model_dump(mode="json") == canonical_val.model_dump(mode="json")
        assert batch_trends.model_dump(mode="json") == canonical_trends.model_dump(mode="json")

        canonical_val_out = valor_tool.calcular_valor_mercado(canonical_val)
        batch_val_out = valor_tool.calcular_valor_mercado(batch_val)
        canonical_trends_out = trends_tool.calcular_tendencias_fundamentais(canonical_trends)
        batch_trends_out = trends_tool.calcular_tendencias_fundamentais(batch_trends)

        assert batch_val_out.model_dump(mode="json") == canonical_val_out.model_dump(mode="json")
        assert batch_trends_out.model_dump(mode="json") == canonical_trends_out.model_dump(mode="json")
