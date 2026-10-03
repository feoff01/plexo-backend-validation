from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from app.db.repos import policies as policies_repo
from app.market.series import (
    ADJUSTED_CLOSE_RETROSPECTIVE,
    PriceBasis,
    TemporalSemantics,
)
from app.tools.analista import _risco_retorno_rolling_shadow as shadow
from app.tools.analista import risco_retorno
from app.tools.executor import ToolContext

POLICY = {
    "janela_padrao_dias": 365,
    "metodo_retorno": "log",
    "dias_uteis_ano": 252,
    "min_observacoes": 30,
    "max_dias_defasagem": 5,
}


@pytest.fixture
async def rolling_db_world(db, escopos):
    start = date(2024, 1, 2)
    cutoff = start + timedelta(days=119)
    ticker = "ROLLDB3"

    async with db.service_session() as conn:
        await policies_repo.set_policy(conn, "ANALISE_PARAMS", POLICY)
        await policies_repo.approve_current(conn, "ANALISE_PARAMS", approved_by=escopos.u1)

        cur = await conn.execute(
            """insert into market.ingestion_batches
                   (source_code,dataset,reference_date,file_hash,status,finished_at,rows_ingested)
               values ('b3','test.risk_rolling',%s,%s,'succeeded',
                       %s::date + time '20:00',120)
               returning id::text""",
            (cutoff, "6" * 64, cutoff),
        )
        batch_id = (await cur.fetchone())[0]

        cur = await conn.execute(
            """insert into market.instruments
                   (kind,name,ticker,is_in_universe,source_code)
               values ('acao','Rolling DB Test',%s,true,'b3')
               returning id::text""",
            (ticker,),
        )
        instrument_id = (await cur.fetchone())[0]

        await conn.execute(
            """insert into market.prices
                   (price_date,instrument_id,kind,value,currency,source_code,ingestion_batch_id)
               select d::date, %s, 'close',
                      100.0
                      + ((d::date - %s::date) * 0.04)
                      + (mod((d::date - %s::date), 11) * 0.17),
                      'BRL','b3',%s
                 from generate_series(%s::date,%s::date,interval '1 day') as g(d)""",
            (instrument_id, start, start, batch_id, start, cutoff),
        )

    return {
        "user_id": escopos.u1,
        "scope_id": escopos.s1,
        "ticker": ticker,
        "instrument_id": instrument_id,
        "batch_id": batch_id,
        "start": start,
        "cutoff": cutoff,
    }


async def _candidate(db, world, basis: PriceBasis):
    async with db.app_session(user_id=world["user_id"], scope_id=world["scope_id"]) as conn:
        ctx = ToolContext(
            conn=conn,
            scope_id=world["scope_id"],
            conversation_id=None,
            cutoff_date=world["cutoff"],
        )
        params = risco_retorno.RiscoRetornoParams(
            ticker=world["ticker"],
            de=world["start"],
            ate=world["cutoff"],
            price_basis=basis,
        )
        resolvido = await risco_retorno.preparar_risco_retorno(params, ctx)
        base = risco_retorno.calcular_risco_retorno(resolvido)
        candidato = shadow.calcular_risco_retorno_rolling_shadow(
            resolvido,
            janela_observacoes=20,
        )
        return resolvido, base, candidato, list(ctx.insumos), tuple(ctx.politicas_meta)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("basis", "semantics", "dataset"),
    [
        (
            PriceBasis.ADJUSTED_CLOSE,
            TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
            "market.v_precos_ajustados",
        ),
        (
            PriceBasis.RAW_CLOSE,
            TemporalSemantics.OBSERVATION_DATE_CUTOFF,
            "market.prices",
        ),
    ],
)
async def test_shadow_preparacao_postgres_preserva_semantica_provenance_e_payload(
    db,
    rolling_db_world,
    basis,
    semantics,
    dataset,
):
    r, base, candidato, insumos, policies = await _candidate(db, rolling_db_world, basis)

    assert r.instrument_id == rolling_db_world["instrument_id"]
    assert r.price_basis == basis
    assert r.temporal_semantics == semantics
    assert r.serie is not None
    assert r.serie.provenance.dataset == dataset
    assert r.serie.provenance.price_basis == basis
    assert r.serie.provenance.temporal_semantics == semantics
    assert r.serie.provenance.ingestion_batch_ids == [rolling_db_world["batch_id"]]
    assert len(r.serie.points) == 120
    assert r.serie.points[-1].data == rolling_db_world["cutoff"]

    assert insumos[-1]["kind"] == "market.prices"
    assert insumos[-1]["dataset"] == dataset
    assert insumos[-1]["price_basis"] == basis.value
    assert insumos[-1]["temporal_semantics"] == semantics.value
    assert any(p["code"] == "ANALISE_PARAMS" for p in policies)

    if basis == PriceBasis.ADJUSTED_CLOSE:
        assert ADJUSTED_CLOSE_RETROSPECTIVE in r.serie.provenance.warnings
        assert ADJUSTED_CLOSE_RETROSPECTIVE in candidato.evidencia.avisos
    else:
        assert ADJUSTED_CLOSE_RETROSPECTIVE not in r.serie.provenance.warnings
        assert ADJUSTED_CLOSE_RETROSPECTIVE not in candidato.evidencia.avisos

    payload = candidato.model_dump(mode="json")
    payload_base = dict(payload)
    payload_base.pop("evolucao_volatilidade")
    payload_base.pop("avisos_candidato")
    assert payload_base == base.model_dump(mode="json")

    evolucao = candidato.evolucao_volatilidade
    assert evolucao is not None
    assert evolucao.janela_observacoes == 20
    assert evolucao.n_janelas_total == 100
    assert evolucao.primeira_data <= evolucao.ultima_data
    assert len(evolucao.pontos) <= shadow.MAX_PONTOS_ROLLING_SHADOW
    assert evolucao.amostrado is True
    assert shadow.SERIE_RISCO_AMOSTRADA in candidato.avisos_candidato

    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(compact) < 5_000

    assert candidato.evidencia.fonte == "b3"
    assert candidato.evidencia.instrument_ids == [rolling_db_world["instrument_id"]]
    assert candidato.evidencia.ingestion_batch_ids == [rolling_db_world["batch_id"]]
    assert candidato.evidencia.cutoff_date == rolling_db_world["cutoff"]
    assert candidato.evidencia.as_of == rolling_db_world["cutoff"]
    assert candidato.evidencia.n_observacoes == 120
    assert candidato.evidencia.suficiente is True
