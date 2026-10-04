from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.market.yield_curve_ingest import (
    AnbimaYieldCurvePoint,
    DATASET_ANBIMA_ETTJ,
    YieldCurveIngestConflict,
    ingest_anbima_yield_curve,
)
from app.market.yield_curves import load_yield_curve


def _points(ref: date, *, pre_21: float = 14.0):
    return [
        AnbimaYieldCurvePoint(
            reference_date=ref,
            business_days=21,
            pre_rate_pct=pre_21,
            ipca_rate_pct=7.0,
            implied_inflation_pct=6.5,
        ),
        AnbimaYieldCurvePoint(
            reference_date=ref,
            business_days=252,
            pre_rate_pct=13.5,
            ipca_rate_pct=6.5,
            implied_inflation_pct=6.1,
        ),
    ]


@pytest.mark.asyncio
async def test_yield_curve_ingest_is_idempotent_and_loader_returns_exact_vertices(db):
    ref = date(2026, 10, 2)
    async with db.service_session() as conn:
        first = await ingest_anbima_yield_curve(
            conn,
            _points(ref),
            file_hash="7" * 64,
            dataset=DATASET_ANBIMA_ETTJ,
        )
        assert first.rows_inserted == 6
        assert first.rows_already_equal == 0

        again = await ingest_anbima_yield_curve(
            conn,
            _points(ref),
            file_hash="7" * 64,
            dataset=DATASET_ANBIMA_ETTJ,
        )
        assert again.reused_existing_batch is True
        assert again.rows_inserted == 0
        assert again.rows_already_equal == 6

        same_values_new_file = await ingest_anbima_yield_curve(
            conn,
            _points(ref),
            file_hash="8" * 64,
            dataset=DATASET_ANBIMA_ETTJ,
        )
        assert same_values_new_file.rows_inserted == 0
        assert same_values_new_file.rows_already_equal == 6

        curve = await load_yield_curve(
            conn,
            "ettj_pre",
            cutoff=date(2026, 10, 3),
            reference_date=ref,
            strict_pit=True,
        )
        assert curve.reference_date == ref
        assert [(p.business_days, p.rate_pct) for p in curve.points] == [
            (21, 14.0),
            (252, 13.5),
        ]
        assert all(p.day_count == "du_252" for p in curve.points)
        assert all(p.calendar_days is None for p in curve.points)
        assert curve.provenance.source_codes == ["anbima"]
        assert curve.provenance.strict_pit is True


@pytest.mark.asyncio
async def test_yield_curve_conflict_fails_closed_without_overwriting(db):
    ref = date(2026, 9, 29)
    async with db.service_session() as conn:
        await ingest_anbima_yield_curve(
            conn,
            _points(ref, pre_21=14.0),
            file_hash="9" * 64,
        )
        with pytest.raises(YieldCurveIngestConflict, match="ettj_conflito_append_only"):
            await ingest_anbima_yield_curve(
                conn,
                _points(ref, pre_21=99.0),
                file_hash="a" * 64,
            )

        cur = await conn.execute(
            """select rate_pct from market.yield_curve
                where curve_name='ettj_pre' and reference_date=%s
                  and business_days=21 and source_code='anbima'""",
            (ref,),
        )
        assert Decimal((await cur.fetchone())[0]) == Decimal("14.000000")

        cur = await conn.execute(
            """select status from market.ingestion_batches
                where source_code='anbima' and dataset=%s and file_hash=%s""",
            (DATASET_ANBIMA_ETTJ, "a" * 64),
        )
        assert (await cur.fetchone())[0] == "failed"


@pytest.mark.asyncio
async def test_yield_curve_strict_pit_uses_batch_finished_at_not_only_reference_date(db):
    old_ref = date(2026, 9, 20)
    available_late = datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)
    async with db.service_session() as conn:
        cur = await conn.execute(
            """insert into market.ingestion_batches
                   (source_code,dataset,reference_date,file_hash,status,finished_at,rows_ingested)
               values ('anbima',%s,%s,%s,'succeeded',%s,1)
               returning id::text""",
            (DATASET_ANBIMA_ETTJ, old_ref, "b" * 64, available_late),
        )
        batch = (await cur.fetchone())[0]
        await conn.execute(
            """insert into market.yield_curve
                   (curve_name,reference_date,business_days,calendar_days,rate_pct,day_count,
                    source_code,ingestion_batch_id)
               values ('ettj_pre',%s,63,null,13.25,'du_252','anbima',%s)""",
            (old_ref, batch),
        )

        hidden = await load_yield_curve(
            conn,
            "ettj_pre",
            cutoff=date(2026, 9, 30),
            reference_date=old_ref,
            strict_pit=True,
        )
        assert hidden.points == []
        assert "curva_juros_indisponivel" in hidden.provenance.warnings

        visible = await load_yield_curve(
            conn,
            "ettj_pre",
            cutoff=date(2026, 10, 3),
            reference_date=old_ref,
            strict_pit=True,
        )
        assert [(p.business_days, p.rate_pct) for p in visible.points] == [(63, 13.25)]
        assert visible.provenance.availability_date == date(2026, 10, 2)


@pytest.mark.asyncio
async def test_yield_curve_latest_respects_economic_date_and_non_pit_is_explicit(db):
    async with db.service_session() as conn:
        for ref, file_hash, rate in (
            (date(2026, 8, 29), "c" * 64, 12.0),
            (date(2026, 8, 30), "d" * 64, 12.1),
        ):
            cur = await conn.execute(
                """insert into market.ingestion_batches
                       (source_code,dataset,reference_date,file_hash,status,finished_at,rows_ingested)
                   values ('anbima',%s,%s,%s,'succeeded',%s,1)
                   returning id::text""",
                (
                    DATASET_ANBIMA_ETTJ,
                    ref,
                    file_hash,
                    datetime(2026, 8, 31, 21, 0, tzinfo=timezone.utc),
                ),
            )
            batch = (await cur.fetchone())[0]
            await conn.execute(
                """insert into market.yield_curve
                       (curve_name,reference_date,business_days,calendar_days,rate_pct,day_count,
                        source_code,ingestion_batch_id)
                   values ('ettj_ipca',%s,126,null,%s,'du_252','anbima',%s)""",
                (ref, rate, batch),
            )

        latest = await load_yield_curve(
            conn,
            "ettj_ipca",
            cutoff=date(2026, 9, 1),
            strict_pit=True,
        )
        assert latest.reference_date == date(2026, 8, 30)
        assert latest.points[0].rate_pct == 12.1

        non_pit = await load_yield_curve(
            conn,
            "ettj_ipca",
            cutoff=date(2026, 9, 1),
            reference_date=date(2026, 8, 29),
            strict_pit=False,
        )
        assert non_pit.reference_date == date(2026, 8, 29)
        assert "curva_juros_sem_vintage_pit" in non_pit.provenance.warnings
