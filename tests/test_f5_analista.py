"""
F5 — Analista standard. Parte a: dados de mercado (migration 31 + ingestão B3 COTAHIST / BACEN SGS).

O Analista só fundamenta análise em preço oficial, ingerido de forma idempotente e que não muda por
baixo dele. Estes testes provam: o parser lê o layout posicional da B3 sem materializar o arquivo,
o SGS é lido do JSON oficial, cada arquivo vira UM lote com hash (o mesmo hash é no-op), só o
universo cadastrado entra, preços são append-only sob o serviço e as partições cobrem o histórico.
Nenhum teste usa rede (fixtures em tests/fixtures/market) nem depende do estado do banco de dev
(instrumentos e índice próprios, criados na transação do teste).
"""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.config.policies import PolicyStore
from app.db.errors import PermissionDenied
from app.db.repos import policies as policies_repo

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "market"
COTAHIST = FIXTURES / "COTAHIST_A2024_amostra.TXT"
SGS_CDI = FIXTURES / "sgs_4389_amostra.json"
SGS_IPCA = FIXTURES / "sgs_433_amostra.json"

POLICY_INGESTAO = {
    "sgs_base_url": "https://api.bcb.gov.br", "sgs_janela_max_dias": 3650,
    "cotahist_url_anual": "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP",
    "cotahist_url_diario": "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{ddmmaaaa}.ZIP",
    "backfill_anos": 5, "somente_universo": True, "lote_insert_linhas": 7, "timeout_s": 30,
}


@pytest.fixture
async def mundo(db, escopos):
    """Universo próprio (3 instrumentos F5*, um alias) + índice de teste + policy de ingestão, na transação."""
    ids = {}
    async with db.service_session() as conn:
        for ticker, nome in (("F5PETR", "F5 Petróleo"), ("F5VALE", "F5 Mineração"), ("F5BOVA", "F5 ETF Ibovespa")):
            ids[ticker] = str(uuid.uuid4())
            await conn.execute(
                "insert into market.instruments (id, kind, name, ticker, is_in_universe, source_code) "
                "values (%s, %s::market.instrument_kind, %s, %s, true, 'b3')",
                (ids[ticker], "etf" if "BOVA" in ticker else "acao", nome, ticker))
        # F5VALE também é conhecida na B3 por um código antigo — resolve por alias
        await conn.execute(
            "insert into market.instrument_aliases (instrument_id, alias_kind, alias_value, source_code) "
            "values (%s, 'codigo_b3', 'F5VALEOLD', 'b3')", (ids["F5VALE"],))
        await conn.execute(
            "insert into market.index_definitions (code, display_name, unit, source_code, sgs_series_id) "
            "values ('f5_cdi', 'CDI de teste', 'taxa_aa', 'bacen_sgs', 4389)")
        await policies_repo.set_policy(conn, "MERCADO_INGESTAO", POLICY_INGESTAO)
    return {"ids": ids, "escopos": escopos}


def fixture_cotahist_unica(tmp_path) -> pathlib.Path:
    """Cópia da fixture com cabeçalho único: o hash muda a cada teste. A idempotência por hash é do BANCO
    e o dev pode já ter ingerido a fixture original — o teste não pode depender disso (convenção 2)."""
    dest = tmp_path / "COTAHIST_A2024_amostra.TXT"
    linhas = COTAHIST.read_bytes().decode("latin-1").split("\r\n")
    linhas[0] = ("00COTAHIST.2024BOVESPA " + uuid.uuid4().hex).ljust(245)
    dest.write_bytes("\r\n".join(linhas).encode("latin-1"))
    return dest


def _ctx(db):
    return {"db": db, "policies": PolicyStore(db, ttl_s=0), "llm": None}


# ---------------------------------------------------------------- parser COTAHIST
def test_cotahist_parser_le_fixture_filtra_mercado_e_lote():
    from app.market import cotahist

    regs = list(cotahist.iter_registros(cotahist.abrir_linhas(COTAHIST)))
    # 12 pregões × 3 tickers − 2 dias sem F5VALE + 1 fora do universo (F5XPTO, filtrado só na ingestão)
    assert len(regs) == 12 * 3 - 2 + 1
    assert {r.codneg for r in regs} == {"F5PETR", "F5VALE", "F5BOVA", "F5XPTO"}
    assert all(r.tpmerc == "010" and r.codbdi in cotahist.CODBDI_LOTE_PADRAO for r in regs)
    primeiro = next(r for r in regs if r.codneg == "F5PETR" and r.data == date(2024, 1, 2))
    assert primeiro.fechamento == Decimal("36.59")   # 37.15 × (1 − 0.015), centavos exatos
    assert isinstance(primeiro.fechamento, Decimal)
    assert primeiro.codisi == "BRF5PETACNPR"   # ISIN tem 12 posições


def test_cotahist_hash_e_streaming_nao_materializam_arquivo():
    import types

    from app.market import cotahist

    h1, h2 = cotahist.hash_arquivo(COTAHIST), cotahist.hash_arquivo(COTAHIST)
    assert h1 == h2 and len(h1) == 64
    assert isinstance(cotahist.iter_registros(cotahist.abrir_linhas(COTAHIST)), types.GeneratorType)


# ---------------------------------------------------------------- SGS
def test_sgs_parse_fixture_datas_ddmmyyyy_e_url():
    from app.market import sgs

    pontos = sgs.parse_sgs(SGS_CDI.read_text(encoding="utf-8"))
    assert pontos[0] == (date(2024, 1, 2), Decimal("0.043000"))
    assert len(pontos) == 12
    ipca = sgs.parse_sgs(SGS_IPCA.read_text(encoding="utf-8"))
    assert ipca[-1] == (date(2024, 3, 1), Decimal("-0.16"))   # IPCA negativo é legítimo
    url = sgs.url_serie("https://api.bcb.gov.br", 4389, date(2024, 1, 1), date(2024, 12, 31))
    assert url.startswith("https://api.bcb.gov.br/dados/serie/bcdata.sgs.4389/dados?")
    assert "formato=json" in url and "dataInicial=01/01/2024" in url and "dataFinal=31/12/2024" in url
    # janelas: a API limita séries diárias a 10 anos por chamada — o cliente fatia
    janelas = sgs.janelas(date(2000, 1, 1), date(2024, 6, 30), max_dias=3650)
    assert janelas[0][0] == date(2000, 1, 1) and janelas[-1][1] == date(2024, 6, 30) and len(janelas) == 3


# ---------------------------------------------------------------- ingestão
async def test_ingestao_cotahist_grava_precos_so_do_universo_e_fecha_lote(db, mundo, tmp_path):
    from app.jobs import tasks

    r = await tasks.ingerir_cotahist(_ctx(db), arquivo=str(fixture_cotahist_unica(tmp_path)))
    assert r["status"] == "succeeded"
    assert r["rows_ingested"] == 12 * 3 - 2          # F5XPTO fica fora (não está no universo)
    assert r["ignorados_fora_universo"] == 1 and r["conflitos"] == 0
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select count(*), count(distinct instrument_id), min(price_date), max(price_date) "
            "from market.prices where ingestion_batch_id = %s", (r["batch_id"],))
        n, n_instr, d0, d1 = await cur.fetchone()
        assert (n, n_instr, d0, d1) == (34, 3, date(2024, 1, 2), date(2024, 1, 17))
        cur = await conn.execute(
            "select status, rows_ingested, file_hash, finished_at is not null, dataset, source_code "
            "from market.ingestion_batches where id = %s", (r["batch_id"],))
        from app.market import cotahist
        assert (await cur.fetchone()) == ("succeeded", 34, r["file_hash"], True, cotahist.DATASET, "b3")
        cur = await conn.execute(
            "select value from market.prices where instrument_id = %s and price_date = %s and kind = 'close'",
            (mundo["ids"]["F5PETR"], date(2024, 1, 2)))
        assert (await cur.fetchone())[0] == Decimal("36.59")
        cur = await conn.execute(
            "select count(*) from audit.activity_log where action = 'market.ingestion.succeeded' "
            "and object_id = %s", (r["batch_id"],))
        assert (await cur.fetchone())[0] == 1


async def test_ingestao_mesmo_hash_e_noop(db, mundo, tmp_path):
    from app.jobs import tasks

    arquivo = str(fixture_cotahist_unica(tmp_path))
    r1 = await tasks.ingerir_cotahist(_ctx(db), arquivo=arquivo)
    r2 = await tasks.ingerir_cotahist(_ctx(db), arquivo=arquivo)
    assert r2["status"] == "noop" and r2["batch_id"] == r1["batch_id"]
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select count(*) from market.ingestion_batches where file_hash = %s", (r1["file_hash"],))
        assert (await cur.fetchone())[0] == 1
        cur = await conn.execute("select count(*) from market.prices where ingestion_batch_id = %s", (r1["batch_id"],))
        assert (await cur.fetchone())[0] == 34


async def test_ingestao_cotahist_resolve_por_alias_codigo_b3(db, mundo):
    """Um pregão em que a B3 usa o código antigo de F5VALE: o alias resolve para o mesmo instrumento."""
    from app.market import cotahist, ingest

    async with db.service_session() as conn:
        mapa = await ingest.mapa_universo(conn, somente_universo=True)
        assert mapa["F5VALEOLD"] == mapa["F5VALE"] == mundo["ids"]["F5VALE"]
        assert "F5XPTO" not in mapa
        lote = await ingest.abrir_lote(conn, source_code="b3", dataset="cotahist", file_hash="f" * 64,
                                       reference_date=date(2024, 2, 1))
        regs = [cotahist.Cotacao(data=date(2024, 2, 1), codneg="F5VALEOLD", codbdi="02", tpmerc="010",
                                 fechamento=Decimal("71.00"), abertura=None, maximo=None, minimo=None,
                                 quantidade=None, volume=None, fatcot=1, codisi="")]
        res = await ingest.gravar_precos(conn, lote, regs, mapa, source_code="b3", lote_linhas=5)
        assert (res.inseridos, res.ignorados_fora_universo, res.conflitos) == (1, 0, 0)
        cur = await conn.execute("select instrument_id::text from market.prices where ingestion_batch_id = %s", (lote,))
        assert (await cur.fetchone())[0] == mundo["ids"]["F5VALE"]


async def test_ingestao_sgs_grava_index_values_com_lote(db, mundo):
    from app.jobs import tasks

    r = await tasks.ingerir_sgs(_ctx(db), indice="f5_cdi", de=date(2024, 1, 1), ate=date(2024, 1, 31),
                                texto_json=SGS_CDI.read_text(encoding="utf-8"))
    assert r["status"] == "succeeded" and r["rows_ingested"] == 12
    async with db.service_session() as conn:
        cur = await conn.execute(
            "select count(*), min(value_date), max(value) from market.index_values "
            "where index_code = 'f5_cdi' and ingestion_batch_id = %s", (r["batch_id"],))
        n, d0, vmax = await cur.fetchone()
        assert (n, d0) == (12, date(2024, 1, 2)) and vmax == Decimal("0.044100")
        cur = await conn.execute("select dataset, source_code from market.ingestion_batches where id = %s", (r["batch_id"],))
        assert (await cur.fetchone()) == ("sgs_f5_cdi", "bacen_sgs")
    # mesma resposta do provedor → mesmo hash → no-op
    r2 = await tasks.ingerir_sgs(_ctx(db), indice="f5_cdi", de=date(2024, 1, 1), ate=date(2024, 1, 31),
                                 texto_json=SGS_CDI.read_text(encoding="utf-8"))
    assert r2["status"] == "noop"


async def test_ingestao_reprocesso_de_lote_falho_e_permitido(db, mundo):
    """Lote que falhou no meio (status failed) não bloqueia nova tentativa com o mesmo arquivo."""
    from app.market import ingest

    async with db.service_session() as conn:
        b1 = await ingest.abrir_lote(conn, source_code="b3", dataset="cotahist", file_hash="e" * 64,
                                     reference_date=date(2024, 1, 31))
        await ingest.fechar_lote(conn, b1, status="failed", rows=None, error="timeout no download")
        b2 = await ingest.abrir_lote(conn, source_code="b3", dataset="cotahist", file_hash="e" * 64,
                                     reference_date=date(2024, 1, 31))
        assert b2 is not None and b2 != b1
        await ingest.fechar_lote(conn, b2, status="succeeded", rows=0)
        b3 = await ingest.abrir_lote(conn, source_code="b3", dataset="cotahist", file_hash="e" * 64,
                                     reference_date=date(2024, 1, 31))
        assert b3 is None                                     # já há um succeeded com este hash


# ---------------------------------------------------------------- banco (espelho Python da 31)
async def test_precos_sao_append_only_sob_plexo_service(db, mundo, tmp_path):
    from app.jobs import tasks

    r = await tasks.ingerir_cotahist(_ctx(db), arquivo=str(fixture_cotahist_unica(tmp_path)))
    with pytest.raises(PermissionDenied):   # traduzida na saída da sessão (convenção 3)
        async with db.service_session() as conn:
            await conn.execute("update market.prices set value = 1 where ingestion_batch_id = %s", (r["batch_id"],))


async def test_partition_coverage_cobre_dez_anos(db):
    from app.market import ingest

    async with db.service_session() as conn:
        cob = await ingest.cobertura_particoes(conn)
    assert cob.particoes >= 120
    assert cob.inicio <= date(date.today().year - 9, date.today().month, 1)
    assert cob.fim >= date.today()


def test_worker_declara_tasks_de_ingestao():
    from app.jobs.worker import WorkerSettings

    nomes = {f.__name__ for f in WorkerSettings.functions}
    assert {"ingerir_sgs", "ingerir_cotahist"} <= nomes
    crons = {c.name for c in WorkerSettings.cron_jobs}
    assert {"ingerir_sgs", "ingerir_cotahist"} <= crons


@pytest.mark.skipif(not os.getenv("PLEXO_LIVE"), reason="rede real só com PLEXO_LIVE=1")
async def test_sgs_live_um_dia():
    import httpx

    from app.market import sgs

    async with httpx.AsyncClient(timeout=30) as client:
        pontos = await sgs.buscar(client, "https://api.bcb.gov.br", 4389, date(2024, 1, 2), date(2024, 1, 3))
    assert pontos and pontos[0][0] == date(2024, 1, 2)
