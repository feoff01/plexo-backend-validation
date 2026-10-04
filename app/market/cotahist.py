"""Leitor do COTAHIST (série histórica de cotações da B3) — layout posicional, registro tipo 01.

Referência: "Layout do arquivo COTAHIST" (B3). Cada linha tem 245 colunas; o registro 00 é o cabeçalho,
o 99 o trailer, o 01 uma cotação. As posições abaixo são do manual (1-based no manual; aqui 0-based).
Só o fechamento (PREULT) vai para market.prices — D-1 é o contrato do produto (04_market.sql);
abertura/máx/mín/volume são lidos e devolvidos, mas só entram no banco com o asset master (onda futura).

Nada aqui toca o banco nem a rede: `abrir_linhas` lê ZIP ou TXT local, linha a linha (o anual tem
~300 MB descompactado — nunca é materializado), e `iter_registros` é um gerador.
"""
from __future__ import annotations

import hashlib
import io
import pathlib
import zipfile
from datetime import date
from decimal import Decimal
from typing import Iterable, Iterator, NamedTuple

TIPREG_COTACAO = "01"
TPMERC_VISTA = "010"                          # mercado à vista (exclui termo, opções, fracionário)
# CODBDI aceitos no à vista: 02 lote padrão (ações), 12 fundos imobiliários, 14 investimento coletivo (ETFs como
# BOVA11/IVVB11 — conferido no arquivo real de 2026-08-21). 96 = fracionário, fora.
CODBDI_LOTE_PADRAO = frozenset({"02", "12", "14"})
# Versão do contrato de leitura: entra no `dataset` do lote ("cotahist@N"). Mudar o filtro/layout muda a versão,
# senão o mesmo arquivo (mesmo hash) já é lote succeeded e a reingestão seria no-op.
LAYOUT_VERSAO = "2"
DATASET = f"cotahist@{LAYOUT_VERSAO}"
_ENCODING = "latin-1"

# (início, fim) em colunas 0-based — registro 01
LAYOUT = {
    "tipreg": (0, 2), "data": (2, 10), "codbdi": (10, 12), "codneg": (12, 24), "tpmerc": (24, 27),
    "preabe": (56, 69), "premax": (69, 82), "premin": (82, 95), "preult": (108, 121),
    "quatot": (152, 170), "voltot": (170, 188), "fatcot": (210, 217), "codisi": (230, 242),
}
_CENTAVOS = Decimal(100)


class Cotacao(NamedTuple):
    data: date
    codneg: str
    codbdi: str
    tpmerc: str
    fechamento: Decimal
    abertura: Decimal | None
    maximo: Decimal | None
    minimo: Decimal | None
    quantidade: int | None
    volume: Decimal | None
    fatcot: int
    codisi: str


def _campo(linha: str, nome: str) -> str:
    a, b = LAYOUT[nome]
    return linha[a:b]


def _preco(bruto: str) -> Decimal:
    return Decimal(int(bruto)) / _CENTAVOS


def parse_registro(linha: str) -> Cotacao | None:
    """Converte uma linha do arquivo. Devolve None para cabeçalho/trailer/linhas curtas."""
    if len(linha) < LAYOUT["codisi"][1] or _campo(linha, "tipreg") != TIPREG_COTACAO:
        return None
    d = _campo(linha, "data")
    return Cotacao(
        data=date(int(d[0:4]), int(d[4:6]), int(d[6:8])),
        codneg=_campo(linha, "codneg").strip(),
        codbdi=_campo(linha, "codbdi"),
        tpmerc=_campo(linha, "tpmerc"),
        fechamento=_preco(_campo(linha, "preult")),
        abertura=_preco(_campo(linha, "preabe")),
        maximo=_preco(_campo(linha, "premax")),
        minimo=_preco(_campo(linha, "premin")),
        quantidade=int(_campo(linha, "quatot")),
        volume=_preco(_campo(linha, "voltot")),
        fatcot=int(_campo(linha, "fatcot")),
        codisi=_campo(linha, "codisi").strip(),
    )


def iter_registros(linhas: Iterable[str], *, tpmerc: str = TPMERC_VISTA,
                   codbdi: frozenset[str] = CODBDI_LOTE_PADRAO) -> Iterator[Cotacao]:
    """Gerador das cotações à vista em lote padrão (o que o Analista chama de 'preço de fechamento')."""
    for linha in linhas:
        c = parse_registro(linha.rstrip("\r\n"))
        if c is None or c.tpmerc != tpmerc or c.codbdi not in codbdi:
            continue
        yield c


def abrir_linhas(caminho: str | pathlib.Path) -> Iterator[str]:
    """Linhas do arquivo (ZIP oficial ou TXT extraído), em streaming, latin-1."""
    caminho = pathlib.Path(caminho)
    if zipfile.is_zipfile(caminho):
        with zipfile.ZipFile(caminho) as z:
            nome = next(n for n in z.namelist() if not n.endswith("/"))
            with z.open(nome) as bruto:
                for linha in io.TextIOWrapper(bruto, encoding=_ENCODING, newline=""):
                    yield linha
        return
    with caminho.open("r", encoding=_ENCODING, newline="") as f:
        for linha in f:
            yield linha


def hash_arquivo(caminho: str | pathlib.Path, *, bloco: int = 1 << 20) -> str:
    """sha256 do arquivo cru (ZIP ou TXT) — é o `file_hash` do lote; mesmo arquivo = mesmo lote."""
    h = hashlib.sha256()
    with pathlib.Path(caminho).open("rb") as f:
        while True:
            parte = f.read(bloco)
            if not parte:
                break
            h.update(parte)
    return h.hexdigest()
