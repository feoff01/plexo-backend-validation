"""Projeta o acervo do Mercado Brasil Collector para `market.*` — backfill offline.

RODA NO PYTHON DO SISTEMA, não na `.venv`: é ele que tem pandas e pyarrow. O backend não os tem e
não deve ter — isto é backfill de uma vez, não runtime da API, e `requirements.txt` é a lista de
deploy. A rotina DIÁRIA continua sendo `plexo mercado ingerir`, que lê o TXT da B3 sem pandas.

O que este script NÃO faz: decidir regra. As regras são do BANCO (migrations 31 e 61) — append-only,
sem data futura, fechamento > 0, um arquivo = um lote `succeeded`. E as decisões de leitura que
produziriam número errado em silêncio (FATCOT, filtro de mercado à vista, formato de ticker, kind)
moram em `app/market/acervo.py`, que o pytest cobre.

**Vetorização e a regra escalar.** Os filtros rodam sobre ~24 milhões de linhas, e um laço Python
levaria minutos por arquivo. As máscaras são vetorizadas, mas construídas a partir das MESMAS
constantes de `acervo` e conferidas contra a função escalar numa amostra de cada arquivo — se
divergirem, o script para. Duas fontes da verdade para a mesma regra é o defeito que a migration 53
corrigiu na carteira; aqui a fonte continua sendo uma.

    python tools/projetar_acervo.py status
    python tools/projetar_acervo.py instrumentos
    python tools/projetar_acervo.py precos --de 2020 --ate 2026
    python tools/projetar_acervo.py precos --de 1995 --ate 2019 --teto-mb 1500
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402  (depois do sys.path)
import psycopg  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

from app.market import acervo  # noqa: E402  — as regras puras, compartilhadas com o pytest

# Onde a serie comeca, MEDIDO no acervo: de 1986 a 1997 o COTAHIST usa o codigo antigo da Bovespa
# (3 letras, espaco e digito - 'ACE 3', 'ALP 4'), e 100% das linhas desses anos sao recusadas pelo
# padrao de 4 caracteres. 1998 e a transicao (18,4% ainda no formato antigo) e de 1999 em diante e
# zero. Os anos antigos NAO estao perdidos: as linhas recusadas trazem ISIN, e uma ponte por ISIN
# os ligaria aos papeis de hoje - fica registrado como limitacao, nao feito aqui. Antes de julho de
# 1994 ha tambem quatro trocas de moeda, e o coletor nao deflaciona: ali a ponte nao bastaria.
PRIMEIRO_ANO = 1998

ACERVO = pathlib.Path(r"C:\dev\plexo\_acervo\data\normalized")
FONTE = "b3"
DATASET_COTAHIST = "acervo.cotahist@1"
# 10 mil e nao 25 mil: o no da Aiven free tem 1 GB de RAM, e um INSERT com tres arrays de 25 mil
# elementos derrubou a conexao no meio do backfill (AdminShutdown). A disciplina de lote da 31
# segurou o estrago - o arquivo que caiu nao deixou linha nem lote orfao -, mas o custo foi refazer.
LOTE_LINHAS = 10_000
AMOSTRA_CONFERENCIA = 5_000

COLUNAS = ["date", "bdi_code", "ticker", "market_type", "issuer_name",
           "specification", "isin", "close", "quote_factor"]
_ANO_NO_NOME = re.compile(r"cotahist_(\d{4})_")

sys.stdout.reconfigure(line_buffering=True)   # backfill longo: progresso tem de aparecer


# --------------------------------------------------------------------------- infra
def conectar() -> psycopg.Connection:
    url = dotenv_values(ROOT / ".env").get("DATABASE_URL") or ""
    if not url:
        sys.exit("DATABASE_URL ausente em plexo-backend/.env")
    url = re.sub(r"^postgres(ql)?\+[a-z0-9]+://", "postgresql://", url)
    conn = psycopg.connect(url, connect_timeout=30)
    conn.execute("set statement_timeout = '900s'")
    return conn


def tamanho_mb(conn: psycopg.Connection) -> float:
    return float(conn.execute(
        "select pg_database_size(current_database()) / 1048576.0").fetchone()[0])


def sha256_do_arquivo(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def arquivos_cotahist(de: int, ate: int) -> list[tuple[int, pathlib.Path]]:
    saida = []
    for p in sorted((ACERVO / "b3").glob("cotahist_*.parquet")):
        m = _ANO_NO_NOME.search(p.name)
        if m and de <= int(m.group(1)) <= ate:
            saida.append((int(m.group(1)), p))
    return saida


# --------------------------------------------------------------------------- leitura
def _codigos(serie: pd.Series, largura: int) -> pd.Series:
    return serie.astype("string").fillna("").str.strip().str.zfill(largura)


def _conferir(mascara: pd.Series, df: pd.DataFrame) -> None:
    """A máscara vetorizada tem de concordar com a regra escalar que o pytest cobre."""
    amostra = df.head(AMOSTRA_CONFERENCIA)
    esperado = [acervo.eh_mercado_a_vista(mt, bdi)
                for mt, bdi in zip(amostra["market_type"], amostra["bdi_code"])]
    if list(mascara.head(AMOSTRA_CONFERENCIA)) != esperado:
        raise RuntimeError(
            "máscara vetorizada divergiu de acervo.eh_mercado_a_vista — regra duplicada e fora de sincronia")


def ler_a_vista(p: pathlib.Path) -> tuple[pd.DataFrame, int]:
    """Linhas de mercado à vista com ticker válido. Devolve também quantos códigos foram recusados."""
    df = pd.read_parquet(p, columns=COLUNAS)
    mascara = _codigos(df["market_type"], 3).eq(acervo.MERCADO_A_VISTA) & \
        _codigos(df["bdi_code"], 2).isin(acervo.BDI_A_VISTA)
    _conferir(mascara, df)
    df = df[mascara]
    valido = df["ticker"].astype("string").fillna("").str.fullmatch(acervo.PADRAO_TICKER)
    recusados = int((~valido).sum())
    df = df[valido].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df, recusados


# --------------------------------------------------------------------------- lotes
def abrir_lote(conn, *, dataset: str, file_hash: str, reference_date) -> str | None:
    """Novo lote `running`, ou None se o arquivo já foi ingerido (a 31 garante por índice único)."""
    if conn.execute(
        "select 1 from market.ingestion_batches "
        "where source_code = %s and dataset = %s and file_hash = %s and status = 'succeeded'",
            (FONTE, dataset, file_hash)).fetchone():
        return None
    return conn.execute(
        "insert into market.ingestion_batches (source_code, dataset, reference_date, file_hash) "
        "values (%s, %s, %s, %s) returning id::text",
        (FONTE, dataset, reference_date, file_hash)).fetchone()[0]


def fechar_lote(conn, batch_id: str, *, status: str, rows: int | None, erro: str | None = None) -> None:
    conn.execute(
        "update market.ingestion_batches set status = %s, finished_at = clock_timestamp(), "
        "rows_ingested = %s, error_detail = %s where id = %s",
        (status, rows, erro, batch_id))


# --------------------------------------------------------------------------- instrumentos
def cmd_instrumentos(conn, args) -> None:
    """Catálogo de papéis a partir dos COTAHIST: ticker, nome, ISIN, kind e classe."""
    arquivos = arquivos_cotahist(args.de, args.ate)
    if not arquivos:
        sys.exit(f"nenhum COTAHIST em {ACERVO / 'b3'} entre {args.de} e {args.ate}")

    partes, recusados = [], 0
    for ano, p in arquivos:
        df, n_recusados = ler_a_vista(p)
        recusados += n_recusados
        if df.empty:
            continue
        ult = df.sort_values("date").groupby("ticker", sort=False).tail(1)
        agregado = df.groupby("ticker", sort=False)["date"].agg(["min", "max"])
        parte = ult.set_index("ticker")[["bdi_code", "issuer_name", "specification", "isin"]]
        parte = parte.join(agregado)
        partes.append(parte.reset_index())
        print(f"  {ano}: {len(df):,} linhas à vista · {parte.shape[0]:,} papéis")

    todos = pd.concat(partes, ignore_index=True)
    # A leitura MAIS RECENTE de cada papel é a que vale para nome, kind e ISIN.
    todos = todos.sort_values("max")
    ultimo = todos.groupby("ticker", sort=False).tail(1).set_index("ticker")
    primeiro = todos.groupby("ticker", sort=False)["min"].min()
    isin_qualquer = (todos.dropna(subset=["isin"]).groupby("ticker", sort=False)["isin"].last())

    catalogo = {}
    for tk, linha in ultimo.iterrows():
        kind = acervo.kind_do_instrumento(linha["bdi_code"], tk)
        isin = isin_qualquer.get(tk)
        catalogo[tk] = {
            "kind": kind,
            "nome": acervo.nome_do_instrumento(linha["issuer_name"], linha["specification"]) or tk,
            "classe": acervo.classe_de_ativo(kind),
            "isin": (str(isin).strip()[:12] if isin and str(isin).strip() else None),
            "primeiro": primeiro[tk],
            "ultimo": linha["max"],
        }

    # Um ISIN, um instrumento. Ticker renomeado (BIDI11 → INBR32) vira alias do mais recente —
    # senão o índice único `instruments_isin_uk` recusaria o segundo e a série ficaria partida.
    por_isin: dict[str, list[str]] = {}
    for tk, reg in catalogo.items():
        if reg["isin"]:
            por_isin.setdefault(reg["isin"], []).append(tk)
    antigos: list[tuple[str, str]] = []
    for tickers in por_isin.values():
        if len(tickers) == 1:
            continue
        canonico = max(tickers, key=lambda t: catalogo[t]["ultimo"])
        for t in tickers:
            if t != canonico:
                catalogo[t]["isin"] = None
                antigos.append((canonico, t))

    print(f"\ncatálogo: {len(catalogo):,} papéis · {len(antigos)} renomeações por ISIN · "
          f"{recusados:,} linhas com código fora do padrão")
    por_kind: dict[str, int] = {}
    for reg in catalogo.values():
        por_kind[reg["kind"]] = por_kind.get(reg["kind"], 0) + 1
    print("  por kind:", dict(sorted(por_kind.items(), key=lambda kv: -kv[1])))
    if args.dry_run:
        for tk in sorted(catalogo)[:3]:
            print("  exemplo:", tk, catalogo[tk])
        return

    tickers = list(catalogo)
    novos = 0
    for i in range(0, len(tickers), LOTE_LINHAS):
        fatia = tickers[i:i + LOTE_LINHAS]
        r = conn.execute(
            """insert into market.instruments as i
                 (kind, name, ticker, asset_class_code, currency, source_code)
               select k::market.instrument_kind, n, t, c, 'BRL', %s
                 from unnest(%s::text[], %s::text[], %s::text[], %s::text[]) as u(k, n, t, c)
               on conflict (ticker) where ticker is not null do update
                 set asset_class_code = coalesce(i.asset_class_code, excluded.asset_class_code),
                     source_code      = coalesce(i.source_code, excluded.source_code)
               returning (xmax = 0) as inseriu""",
            (FONTE, [catalogo[t]["kind"] for t in fatia], [catalogo[t]["nome"] for t in fatia],
             fatia, [catalogo[t]["classe"] for t in fatia])).fetchall()
        novos += sum(int(x[0]) for x in r)
    conn.commit()
    print(f"instrumentos: {novos:,} novos · {len(tickers) - novos:,} já existiam "
          f"(nome e kind de quem já estava lá são PRESERVADOS)")

    # ISIN em passe separado e só onde estiver livre: um choque com linha pré-existente do dev
    # não pode abortar a transação inteira — ele aparece na contagem.
    com_isin = [(t, catalogo[t]["isin"]) for t in tickers if catalogo[t]["isin"]]
    gravados = 0
    for i in range(0, len(com_isin), LOTE_LINHAS):
        fatia = com_isin[i:i + LOTE_LINHAS]
        gravados += conn.execute(
            """update market.instruments m set isin = u.isin
                 from unnest(%s::text[], %s::text[]) as u(ticker, isin)
                where m.ticker = u.ticker and m.isin is null
                  and not exists (select 1 from market.instruments o where o.isin = u.isin)""",
            ([t for t, _ in fatia], [v for _, v in fatia])).rowcount
    conn.commit()
    print(f"ISIN preenchido em {gravados:,} de {len(com_isin):,} instrumentos com ISIN no acervo")

    aliases = 0
    if antigos:
        aliases = conn.execute(
            """insert into market.instrument_aliases (instrument_id, alias_kind, alias_value, source_code)
               select m.id, 'ticker_antigo', u.antigo, %s
                 from unnest(%s::text[], %s::text[]) as u(canonico, antigo)
                 join market.instruments m on m.ticker = u.canonico
               on conflict (alias_kind, alias_value) do nothing""",
            (FONTE, [c for c, _ in antigos], [a for _, a in antigos])).rowcount
    conn.commit()
    print(f"aliases de ticker antigo: {aliases:,}")


# --------------------------------------------------------------------------- preços
def _inserir(conn, linhas: list[tuple], batch_id: str) -> int:
    datas, ids, valores = zip(*linhas)
    return conn.execute(
        """insert into market.prices
             (price_date, instrument_id, kind, value, currency, source_code, ingestion_batch_id)
           select d, i, 'close', v, 'BRL', %s, %s
             from unnest(%s::date[], %s::uuid[], %s::numeric[]) as t(d, i, v)
           on conflict (price_date, instrument_id, kind, source_code) do nothing""",
        (FONTE, batch_id, list(datas), list(ids), list(valores))).rowcount


def cmd_precos(conn, args) -> None:
    mapa = {tk: iid for tk, iid in conn.execute(
        "select ticker, id::text from market.instruments where ticker is not null").fetchall()}
    print(f"universo mapeado: {len(mapa):,} tickers")

    for ano, p in arquivos_cotahist(args.de, args.ate):
        antes = tamanho_mb(conn)
        if antes > args.teto_mb:
            print(f"PARADA: banco em {antes:.0f} MB, acima do teto de {args.teto_mb:.0f} MB")
            return
        fh = sha256_do_arquivo(p)
        df, _ = ler_a_vista(p)
        if df.empty:
            print(f"  {ano}: nenhuma linha à vista")
            continue
        batch_id = abrir_lote(conn, dataset=DATASET_COTAHIST, file_hash=fh,
                              reference_date=max(df["date"]))
        if batch_id is None:
            conn.commit()
            print(f"  {ano}: já ingerido (lote succeeded com o mesmo hash) — nada a fazer")
            continue
        t0 = time.time()
        inseridos = fora = tentados = 0
        pendentes: list[tuple] = []
        try:
            for d, tk, v, qf in zip(df["date"], df["ticker"], df["close"], df["quote_factor"]):
                iid = mapa.get(tk)
                if iid is None:
                    fora += 1
                    continue
                preco = acervo.preco_com_fatcot(v, qf)
                if preco is None or preco <= 0:     # o banco recusaria (price_close_positive)
                    fora += 1
                    continue
                pendentes.append((d, iid, preco))
                tentados += 1
                if len(pendentes) >= LOTE_LINHAS:
                    inseridos += _inserir(conn, pendentes, batch_id)
                    pendentes = []
            if pendentes:
                inseridos += _inserir(conn, pendentes, batch_id)
            fechar_lote(conn, batch_id, status="succeeded", rows=inseridos)
            conn.commit()
        except Exception as e:
            conn.rollback()
            novo = abrir_lote(conn, dataset=DATASET_COTAHIST, file_hash=fh,
                              reference_date=max(df["date"]))
            if novo:
                fechar_lote(conn, novo, status="failed", rows=None, erro=str(e)[:400])
                conn.commit()
            raise
        depois = tamanho_mb(conn)
        print(f"  {ano}: {inseridos:,} inseridos · {tentados - inseridos:,} já existiam · "
              f"{fora:,} sem instrumento ou preço inválido · {time.time() - t0:.0f}s · "
              f"banco {antes:.0f}→{depois:.0f} MB")


# --------------------------------------------------------------------------- status
def cmd_status(conn, args) -> None:
    print(f"banco: {tamanho_mb(conn):.0f} MB")
    for titulo, sql in [
        ("instrumentos por kind",
         "select kind::text, count(*), count(*) filter (where is_in_universe) as no_universo, "
         "count(isin) as com_isin from market.instruments group by 1 order by 2 desc"),
        ("preços",
         "select count(*), min(price_date), max(price_date), count(distinct instrument_id) "
         "from market.prices"),
        ("lotes do acervo",
         "select dataset, status, count(*), sum(rows_ingested) "
         "from market.ingestion_batches where dataset like 'acervo.%%' group by 1,2 order by 1,2"),
    ]:
        print(f"\n== {titulo}")
        for linha in conn.execute(sql).fetchall():
            print("   ", linha)


def main() -> int:
    ap = argparse.ArgumentParser(description="Projeção do acervo de mercado para market.*")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome, fn in (("instrumentos", cmd_instrumentos), ("precos", cmd_precos), ("status", cmd_status)):
        s = sub.add_parser(nome)
        s.set_defaults(fn=fn)
        if nome != "status":
            s.add_argument("--de", type=int, default=PRIMEIRO_ANO)
            s.add_argument("--ate", type=int, default=2026)
            s.add_argument("--teto-mb", type=float, default=1500.0,
                           help="para antes de passar deste tamanho de banco (o Aiven free tem ~5 GB)")
            s.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = conectar()
    try:
        args.fn(conn, args)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
