"""FQ1 — contrato puro do MarketSeriesLoader.

Sem banco: um reader fake prova semântica de cutoff/calendário/base/quality. Integração SQL entra nos
testes existentes do Analista quando o ambiente PostgreSQL estiver disponível.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.market.series import (
    ADJUSTED_CLOSE_RETROSPECTIVE,
    CALENDAR_FALLBACK_FROM_PRICES,
    AdjustedCloseRequiresRetrospective,
    CalendarRecord,
    DuplicateSeriesDates,
    InvalidSeriesValue,
    IndexDefinition,
    IndexRecord,
    MarketSeriesLoader,
    PriceBasis,
    PriceRecord,
    TemporalSemantics,
    UnknownIndex,
    align_values,
)


class FakeReader:
    def __init__(self, *, prices=None, calendar=None, fallback=None, index_definition=None, index_values=None):
        self.prices = list(prices or [])
        self.calendar = list(calendar or [])
        self.fallback = list(fallback or [])
        self.index_definition = index_definition
        self.index_values = list(index_values or [])
        self.price_calls = []
        self.index_calls = []
        self.calendar_calls = []
        self.fallback_calls = []

    async def read_prices(self, instrument_id, *, de, ate, cutoff, basis):
        self.price_calls.append((instrument_id, de, ate, cutoff, basis))
        return [r for r in self.prices if de <= r.data <= ate and r.data <= cutoff]

    async def read_index_definition(self, code):
        if self.index_definition is None or self.index_definition.code != code:
            return None
        return self.index_definition

    async def read_index_values(self, code, *, de, ate, cutoff):
        self.index_calls.append((code, de, ate, cutoff))
        return [r for r in self.index_values if de <= r.data <= ate and r.data <= cutoff]

    async def read_calendar(self, calendar_name, *, de, ate, cutoff):
        self.calendar_calls.append((calendar_name, de, ate, cutoff))
        return [r for r in self.calendar if de <= r.data <= ate and r.data <= cutoff]

    async def read_price_calendar_fallback(self, *, de, ate, cutoff):
        self.fallback_calls.append((de, ate, cutoff))
        return [d for d in self.fallback if de <= d <= ate and d <= cutoff]


def _price(d: int, value: float, *, source="b3", batch=None) -> PriceRecord:
    return PriceRecord(data=date(2024, 1, d), valor=value, source_code=source, ingestion_batch_id=batch)


def _cal(d: int, business=True, *, batch=None) -> CalendarRecord:
    return CalendarRecord(data=date(2024, 1, d), is_business_day=business, source_code="b3", ingestion_batch_id=batch)


def _index(d: int, value: float, *, batch=None) -> IndexRecord:
    return IndexRecord(data=date(2024, 1, d), valor=value, ingestion_batch_id=batch)


@pytest.mark.asyncio
async def test_raw_close_strict_respeita_cutoff_e_proveniencia():
    reader = FakeReader(
        prices=[_price(2, 10, batch="b1"), _price(3, 11, batch="b1"), _price(4, 12, batch="b2")],
        calendar=[_cal(2), _cal(3), _cal(4)],
    )
    loader = MarketSeriesLoader(reader)
    serie = await loader.load_prices(
        "iid", code="PETR4", de=date(2024, 1, 2), ate=date(2024, 1, 31), cutoff=date(2024, 1, 3),
    )

    assert [p.data for p in serie.points] == [date(2024, 1, 2), date(2024, 1, 3)]
    assert serie.provenance.dataset == "market.prices"
    assert serie.provenance.price_basis == PriceBasis.RAW_CLOSE
    assert serie.provenance.temporal_semantics == TemporalSemantics.OBSERVATION_DATE_CUTOFF
    assert serie.provenance.ingestion_batch_ids == ["b1"]
    assert reader.price_calls[0][2] == date(2024, 1, 3)  # `ate` é limitado pelo cutoff antes da query


@pytest.mark.asyncio
async def test_calendario_oficial_tem_precedencia_e_mede_lacunas():
    reader = FakeReader(
        prices=[_price(2, 10), _price(4, 12)],
        calendar=[_cal(2, batch="cal1"), _cal(3, batch="cal1"), _cal(4, batch="cal2")],
        fallback=[date(2024, 1, 2), date(2024, 1, 4)],
    )
    serie = await MarketSeriesLoader(reader).load_prices(
        "iid", code="X", de=date(2024, 1, 2), ate=date(2024, 1, 4), cutoff=date(2024, 1, 4),
    )

    assert serie.quality.missing_dates == [date(2024, 1, 3)]
    assert serie.quality.coverage_ratio == pytest.approx(2 / 3)
    assert serie.quality.calendar_source == "market.trading_calendar"
    assert serie.quality.calendar_fallback_used is False
    assert serie.provenance.calendar_ingestion_batch_ids == ["cal1", "cal2"]
    assert reader.fallback_calls == []


@pytest.mark.asyncio
async def test_calendario_oficial_parcial_nao_finge_cobertura_completa():
    reader = FakeReader(
        prices=[_price(2, 10), _price(4, 12)],
        calendar=[_cal(2), _cal(4)],  # falta o dia civil 3: carga oficial incompleta
        fallback=[date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
    )
    serie = await MarketSeriesLoader(reader).load_prices(
        "iid", code="X", de=date(2024, 1, 2), ate=date(2024, 1, 4), cutoff=date(2024, 1, 4),
    )

    assert serie.quality.calendar_fallback_used is True
    assert serie.quality.missing_dates == [date(2024, 1, 3)]
    assert len(reader.fallback_calls) == 1


@pytest.mark.asyncio
async def test_fallback_de_calendario_e_expresso_na_proveniencia():
    reader = FakeReader(
        prices=[_price(2, 10), _price(4, 12)],
        calendar=[],
        fallback=[date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
    )
    serie = await MarketSeriesLoader(reader).load_prices(
        "iid", code="X", de=date(2024, 1, 2), ate=date(2024, 1, 4), cutoff=date(2024, 1, 4),
    )

    assert serie.quality.missing_dates == [date(2024, 1, 3)]
    assert serie.quality.calendar_fallback_used is True
    assert serie.quality.calendar_source == "market.prices:universe_fallback"
    assert CALENDAR_FALLBACK_FROM_PRICES in serie.provenance.warnings


@pytest.mark.asyncio
async def test_adjusted_close_exige_semantica_retroativa_antes_da_leitura():
    reader = FakeReader(prices=[_price(2, 9)])
    loader = MarketSeriesLoader(reader)

    with pytest.raises(AdjustedCloseRequiresRetrospective):
        await loader.load_prices(
            "iid", code="X", de=date(2024, 1, 1), ate=date(2024, 1, 31), cutoff=date(2024, 1, 31),
            basis=PriceBasis.ADJUSTED_CLOSE,
            temporal_semantics=TemporalSemantics.OBSERVATION_DATE_CUTOFF,
        )
    assert reader.price_calls == []


@pytest.mark.asyncio
async def test_adjusted_close_retroativo_e_rotulado_sem_disfarcar_pit():
    reader = FakeReader(prices=[_price(2, 9), _price(3, 9)], fallback=[date(2024, 1, 2), date(2024, 1, 3)])
    serie = await MarketSeriesLoader(reader).load_prices(
        "iid", code="X", de=date(2024, 1, 2), ate=date(2024, 1, 3), cutoff=date(2024, 1, 3),
        basis=PriceBasis.ADJUSTED_CLOSE,
        temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
    )

    assert serie.provenance.dataset == "market.v_precos_ajustados"
    assert serie.provenance.price_basis == PriceBasis.ADJUSTED_CLOSE
    assert serie.provenance.temporal_semantics == TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW
    assert ADJUSTED_CLOSE_RETROSPECTIVE in serie.provenance.warnings


@pytest.mark.asyncio
async def test_calendario_e_cacheado_no_loader_para_multiplas_series():
    reader = FakeReader(
        prices=[_price(2, 10), _price(3, 11)],
        calendar=[_cal(2), _cal(3)],
    )
    loader = MarketSeriesLoader(reader)
    kwargs = dict(de=date(2024, 1, 2), ate=date(2024, 1, 3), cutoff=date(2024, 1, 3))
    await loader.load_prices("a", code="A", **kwargs)
    await loader.load_prices("b", code="B", **kwargs)

    assert len(reader.calendar_calls) == 1


@pytest.mark.asyncio
async def test_align_values_usa_intersecao_sem_preenchimento_silencioso():
    reader_a = FakeReader(prices=[_price(2, 10), _price(3, 11)], calendar=[_cal(2), _cal(3), _cal(4)])
    reader_b = FakeReader(prices=[_price(3, 20), _price(4, 21)], calendar=[_cal(2), _cal(3), _cal(4)])
    a = await MarketSeriesLoader(reader_a).load_prices(
        "a", code="A", de=date(2024, 1, 2), ate=date(2024, 1, 4), cutoff=date(2024, 1, 4))
    b = await MarketSeriesLoader(reader_b).load_prices(
        "b", code="B", de=date(2024, 1, 2), ate=date(2024, 1, 4), cutoff=date(2024, 1, 4))

    alinhado = align_values(a, b)
    assert [(x.data, x.left, x.right) for x in alinhado] == [(date(2024, 1, 3), 11.0, 20.0)]


@pytest.mark.asyncio
async def test_inicio_depois_do_cutoff_permanece_janela_vazia_sem_inventar_observacao():
    reader = FakeReader(prices=[_price(3, 11)], calendar=[_cal(3)])
    serie = await MarketSeriesLoader(reader).load_prices(
        "iid", code="X", de=date(2024, 1, 10), ate=date(2024, 1, 31), cutoff=date(2024, 1, 3),
    )
    assert serie.points == []
    assert reader.price_calls == []


@pytest.mark.asyncio
async def test_reader_com_data_duplicada_falha_fechado():
    reader = FakeReader(prices=[_price(2, 10, source="a"), _price(2, 11, source="b")])
    with pytest.raises(DuplicateSeriesDates):
        await MarketSeriesLoader(reader).load_prices(
            "iid", code="X", de=date(2024, 1, 2), ate=date(2024, 1, 2), cutoff=date(2024, 1, 2),
            include_calendar=False,
        )


@pytest.mark.asyncio
async def test_reader_com_preco_nao_positivo_falha_fechado():
    reader = FakeReader(prices=[_price(2, 0)])
    with pytest.raises(InvalidSeriesValue):
        await MarketSeriesLoader(reader).load_prices(
            "iid", code="X", de=date(2024, 1, 2), ate=date(2024, 1, 2), cutoff=date(2024, 1, 2),
            include_calendar=False,
        )


@pytest.mark.asyncio
async def test_indice_usa_mesmo_cutoff_e_proveniencia_do_loader():
    reader = FakeReader(
        index_definition=IndexDefinition(code="selic_meta", unit="taxa_aa", source_code="bacen_sgs"),
        index_values=[_index(2, 11.75, batch="i1"), _index(3, 11.75, batch="i1"), _index(4, 11.50, batch="i2")],
    )
    serie = await MarketSeriesLoader(reader).load_index(
        "selic_meta", de=date(2024, 1, 2), ate=date(2024, 1, 31), cutoff=date(2024, 1, 3),
    )
    assert serie.index_code == "selic_meta" and serie.instrument_id is None
    assert serie.unit == "taxa_aa"
    assert [p.valor for p in serie.points] == [11.75, 11.75]
    assert serie.provenance.dataset == "market.index_values"
    assert serie.provenance.source_codes == ["bacen_sgs"]
    assert serie.provenance.ingestion_batch_ids == ["i1"]
    assert serie.provenance.price_basis is None


@pytest.mark.asyncio
async def test_indice_desconhecido_falha_sem_inventar_serie():
    with pytest.raises(UnknownIndex):
        await MarketSeriesLoader(FakeReader()).load_index(
            "nao_existe", de=date(2024, 1, 1), ate=date(2024, 1, 2), cutoff=date(2024, 1, 2),
        )


@pytest.mark.asyncio
async def test_postgres_loader_adjusted_close_remove_queda_mecanica_do_ex_date(db):
    """Integração com a view F22: adjusted_close é retroativo e remove a queda mecânica do dividendo.

    Este teste exige o Postgres do projeto; fica como regressão executável no ambiente oficial mesmo
    quando a sessão local atual não possui conexão configurada.
    """
    import uuid

    from app.market.series import PostgresSeriesReader

    iid = str(uuid.uuid4())
    ticker = f"FQ1{uuid.uuid4().hex[:5].upper()}"
    async with db.service_session() as conn:
        await conn.execute(
            "insert into market.instruments (id, kind, name, ticker, is_in_universe, source_code) "
            "values (%s, 'acao', 'FQ1 Ajuste', %s, true, 'b3')",
            (iid, ticker),
        )
        await conn.execute(
            """insert into market.prices (price_date, instrument_id, kind, value, source_code) values
                 (date '2020-06-01', %s, 'close', 10.00, 'b3'),
                 (date '2020-06-02', %s, 'close', 10.00, 'b3'),
                 (date '2020-06-03', %s, 'close',  9.00, 'b3'),
                 (date '2020-06-04', %s, 'close',  9.50, 'b3')""",
            (iid, iid, iid, iid),
        )
        await conn.execute(
            "insert into market.corporate_actions (instrument_id, kind, ex_date, amount_per_unit, source_code) "
            "values (%s, 'dividendo', date '2020-06-03', 1.00, 'b3')",
            (iid,),
        )

    async with db.app_session(user_id=None, scope_id=None) as conn:
        loader = MarketSeriesLoader(PostgresSeriesReader(conn))
        raw = await loader.load_prices(
            iid, code=ticker, de=date(2020, 6, 1), ate=date(2020, 6, 4), cutoff=date(2020, 6, 4),
            basis=PriceBasis.RAW_CLOSE, include_calendar=False,
        )
        adjusted = await loader.load_prices(
            iid, code=ticker, de=date(2020, 6, 1), ate=date(2020, 6, 4), cutoff=date(2020, 6, 4),
            basis=PriceBasis.ADJUSTED_CLOSE,
            temporal_semantics=TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW,
            include_calendar=False,
        )

    assert [p.valor for p in raw.points] == [10.0, 10.0, 9.0, 9.5]
    assert [p.valor for p in adjusted.points] == [9.0, 9.0, 9.0, 9.5]
    assert adjusted.provenance.dataset == "market.v_precos_ajustados"


@pytest.mark.asyncio
async def test_indice_aceita_valor_negativo_legitimo_como_ipca():
    reader = FakeReader(
        index_definition=IndexDefinition(code="ipca", unit="percentual", source_code="bacen_sgs"),
        index_values=[_index(2, -0.16)],
    )
    serie = await MarketSeriesLoader(reader).load_index(
        "ipca", de=date(2024, 1, 2), ate=date(2024, 1, 2), cutoff=date(2024, 1, 2),
    )
    assert serie.points[0].valor == -0.16
