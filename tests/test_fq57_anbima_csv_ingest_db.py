from pathlib import Path

import pytest

from app.market.yield_curve_ingest_anbima_csv import ingest_anbima_yield_curve_csv


FIXTURE = Path(__file__).parent / "fixtures" / "market" / "anbima_ettj_2026-10-02.csv"
EXPECTED_SHA256 = "a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7"


@pytest.mark.asyncio
async def test_official_csv_ingests_through_canonical_pipeline_and_is_idempotent(db):
    data = FIXTURE.read_bytes()
    async with db.service_session() as conn:
        report = await ingest_anbima_yield_curve_csv(
            conn,
            data,
            expected_sha256=EXPECTED_SHA256,
            storage_key="fixtures/anbima/CurvaZero_2026-10-02.csv",
        )
        assert report.file_hash == EXPECTED_SHA256
        assert report.bytes_received == 2899
        assert report.reference_date == "2026-10-02"
        assert (report.ipca_vertices, report.pre_vertices, report.implied_vertices) == (65, 19, 19)
        assert report.ingest.vertices_received == 65
        assert report.ingest.rows_expected == 103
        assert report.ingest.rows_inserted == 103
        assert report.ingest.reused_existing_batch is False

        cur = await conn.execute(
            """select curve_name::text, count(*)
                 from market.yield_curve
                where source_code='anbima' and reference_date='2026-10-02'
                group by curve_name order by curve_name"""
        )
        assert dict(await cur.fetchall()) == {
            "ettj_ipca": 65,
            "ettj_pre": 19,
            "inflacao_implicita": 19,
        }

        cur = await conn.execute(
            """select rate_pct::float
                 from market.yield_curve
                where source_code='anbima' and reference_date='2026-10-02'
                  and curve_name='ettj_pre' and business_days=252"""
        )
        assert (await cur.fetchone())[0] == pytest.approx(13.3811)

        again = await ingest_anbima_yield_curve_csv(
            conn,
            data,
            expected_sha256=EXPECTED_SHA256,
        )
        assert again.ingest.reused_existing_batch is True
        assert again.ingest.rows_inserted == 0
        assert again.ingest.rows_already_equal == 103


@pytest.mark.asyncio
async def test_official_csv_rejects_unexpected_hash_before_writing(db):
    async with db.service_session() as conn:
        with pytest.raises(ValueError, match="sha256_ettj_inesperado"):
            await ingest_anbima_yield_curve_csv(
                conn,
                FIXTURE.read_bytes(),
                expected_sha256="0" * 64,
            )
        cur = await conn.execute(
            "select count(*) from market.ingestion_batches where dataset='anbima.yield_curve.ettj@1'"
        )
        assert (await cur.fetchone())[0] == 0
