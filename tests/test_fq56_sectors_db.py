from datetime import date, datetime, timezone

import pytest

from app.market.sectors import (
    SectorClassificationConflict,
    SectorLevel,
    classification_for_instrument,
    peer_issuers,
)


async def _issuer(conn, name: str, cnpj: str) -> str:
    cur = await conn.execute(
        "insert into market.issuers (name, cnpj, kind) values (%s, %s, 'empresa') returning id::text",
        (name, cnpj),
    )
    return (await cur.fetchone())[0]


async def _action(conn, issuer_id: str, ticker: str, *, in_universe: bool = True) -> str:
    cur = await conn.execute(
        """insert into market.instruments
               (kind, name, ticker, issuer_id, is_in_universe, source_code)
           values ('acao', %s, %s, %s, %s, 'b3') returning id::text""",
        (ticker, ticker, issuer_id, in_universe),
    )
    return (await cur.fetchone())[0]


async def _batch(conn, ref: date, finished: date, suffix: str) -> str:
    cur = await conn.execute(
        """insert into market.ingestion_batches
               (source_code, dataset, reference_date, file_hash, status, finished_at, rows_ingested)
           values ('b3', 'b3.sector_classification@1', %s, %s, 'succeeded', %s, 1)
           returning id::text""",
        (ref, (suffix * 64)[:64], datetime.combine(finished, datetime.min.time(), tzinfo=timezone.utc)),
    )
    return (await cur.fetchone())[0]


async def _classification(conn, iid: str, batch: str, ref: date, *,
                          sector='Energia', subsector='Petroleo', segment='Exploracao', listing='N2'):
    await conn.execute(
        """insert into market.sector_classification
               (instrument_id, source_code, reference_date, economic_sector, subsector, segment,
                listing_segment, ingestion_batch_id)
           values (%s, 'b3', %s, %s, %s, %s, %s, %s)""",
        (iid, ref, sector, subsector, segment, listing, batch),
    )


@pytest.mark.asyncio
async def test_sector_loader_strict_pit_uses_finished_at_cutoff(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, 'Target Energia', '11111111000101')
        on = await _action(conn, issuer, 'TGTA3')
        pn = await _action(conn, issuer, 'TGTA4')
        b_old = await _batch(conn, date(2025, 12, 31), date(2026, 3, 1), 'a')
        b_future = await _batch(conn, date(2026, 6, 30), date(2026, 10, 2), 'b')
        for iid in (on, pn):
            await _classification(conn, iid, b_old, date(2025, 12, 31), segment='Antigo')
            await _classification(conn, iid, b_future, date(2026, 6, 30), segment='Futuro')
        resolved = await classification_for_instrument(
            conn, on, cutoff=date(2026, 9, 30), strict_pit=True
        )
        assert resolved.found is True
        assert resolved.segment == 'Antigo'
        assert resolved.provenance.reference_date == date(2025, 12, 31)
        assert resolved.provenance.availability_date == date(2026, 3, 1)
        assert resolved.provenance.strict_pit is True


@pytest.mark.asyncio
async def test_sector_loader_non_strict_warns_and_can_read_legacy_row(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, 'Legacy Energia', '22222222000102')
        iid = await _action(conn, issuer, 'LEGA3')
        await conn.execute(
            """insert into market.sector_classification
                   (instrument_id, source_code, reference_date, economic_sector, subsector, segment)
               values (%s, 'b3', DATE '2026-01-01', 'Energia', 'Petroleo', 'Exploracao')""",
            (iid,),
        )
        strict = await classification_for_instrument(
            conn, iid, cutoff=date(2026, 9, 30), strict_pit=True
        )
        assert strict.found is False
        loose = await classification_for_instrument(
            conn, iid, cutoff=date(2026, 9, 30), strict_pit=False
        )
        assert loose.found is True
        assert 'classificacao_setorial_sem_vintage_pit' in loose.provenance.warnings


@pytest.mark.asyncio
async def test_sector_loader_fails_closed_on_multiclass_divergence(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, 'Divergente SA', '33333333000103')
        on = await _action(conn, issuer, 'DIVA3')
        pn = await _action(conn, issuer, 'DIVA4')
        batch = await _batch(conn, date(2026, 9, 26), date(2026, 9, 27), 'c')
        await _classification(conn, on, batch, date(2026, 9, 26), sector='Energia')
        await _classification(conn, pn, batch, date(2026, 9, 26), sector='Financeiro')
        with pytest.raises(SectorClassificationConflict):
            await classification_for_instrument(conn, on, cutoff=date(2026, 9, 30))


@pytest.mark.asyncio
async def test_peer_universe_deduplicates_issuer_and_does_not_auto_widen(db):
    async with db.service_session() as conn:
        target_issuer = await _issuer(conn, 'Target SA', '44444444000104')
        target = await _action(conn, target_issuer, 'TARG3')
        batch = await _batch(conn, date(2026, 9, 26), date(2026, 9, 27), 'd')
        await _classification(conn, target, batch, date(2026, 9, 26), segment='Exploracao')
        peer1_issuer = await _issuer(conn, 'Peer Um', '55555555000105')
        p13 = await _action(conn, peer1_issuer, 'PERA3')
        p14 = await _action(conn, peer1_issuer, 'PERA4')
        for iid in (p13, p14):
            await _classification(conn, iid, batch, date(2026, 9, 26), segment='Exploracao')
        peer2_issuer = await _issuer(conn, 'Peer Dois', '66666666000106')
        p2 = await _action(conn, peer2_issuer, 'PERB3')
        await _classification(conn, p2, batch, date(2026, 9, 26), segment='Exploracao')
        broad_issuer = await _issuer(conn, 'Mesmo Setor Outro Segmento', '77777777000107')
        broad = await _action(conn, broad_issuer, 'BRDA3')
        await _classification(conn, broad, batch, date(2026, 9, 26), segment='Refino')
        universe = await peer_issuers(
            conn, target, cutoff=date(2026, 9, 30), level=SectorLevel.SEGMENTO
        )
        assert universe.classification_value == 'Exploracao'
        assert [p.issuer_name for p in universe.peers] == ['Peer Dois', 'Peer Um']
        peer_um = next(p for p in universe.peers if p.issuer_name == 'Peer Um')
        assert peer_um.tickers == ['PERA3', 'PERA4']
        assert all(p.issuer_id != target_issuer for p in universe.peers)
        assert 'Mesmo Setor Outro Segmento' not in [p.issuer_name for p in universe.peers]
        assert 'pares_insuficientes' not in universe.warnings


@pytest.mark.asyncio
async def test_peer_universe_rejects_target_outside_universe(db):
    async with db.service_session() as conn:
        issuer = await _issuer(conn, 'Fora Universo SA', '88888888000108')
        target = await _action(conn, issuer, 'FORA3', in_universe=False)
        batch = await _batch(conn, date(2026, 9, 26), date(2026, 9, 27), 'e')
        await _classification(conn, target, batch, date(2026, 9, 26), segment='Exploracao')
        universe = await peer_issuers(
            conn, target, cutoff=date(2026, 9, 30), level=SectorLevel.SEGMENTO
        )
        assert universe.peers == []
        assert universe.warnings == ['fora_da_cobertura']
