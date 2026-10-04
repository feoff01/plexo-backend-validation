"""Parser determinístico de classificação setorial em exports XLSX Economatica.

A fonte é auxiliar e explicitamente NÃO é tratada como B3. O parser só extrai
classificação corrente por ticker exato; o ano do workbook não é usado como vintage.
Não há dependência de openpyxl: XLSX é lido como ZIP/XML com stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REF = re.compile(r"^([A-Z]+)")


class EconomaticaSectorParseError(ValueError):
    pass


@dataclass(frozen=True)
class EconomaticaSectorRecord:
    ticker: str
    economic_sector: str | None
    subsector: str | None

    @property
    def key(self) -> tuple[str | None, str | None]:
        return (self.economic_sector, self.subsector)


@dataclass(frozen=True)
class EconomaticaSectorSnapshot:
    records: tuple[EconomaticaSectorRecord, ...]
    rows_seen: int
    rows_filtered: int


def _col_index(ref: str) -> int:
    match = _CELL_REF.match(ref)
    if not match:
        raise EconomaticaSectorParseError(f"referencia_celula_invalida:{ref}")
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - 64)
    return value - 1


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value == "-":
        return None
    return value


def _shared_strings(zf: ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    out: list[str] = []
    for si in root.findall(_MAIN + "si"):
        out.append("".join((node.text or "") for node in si.iter(_MAIN + "t")))
    return out


def _cell_value(cell: ET.Element, shared: list[str]) -> str | None:
    kind = cell.attrib.get("t")
    value = cell.find(_MAIN + "v")
    if kind == "s" and value is not None:
        try:
            return shared[int(value.text or "0")]
        except (ValueError, IndexError) as exc:
            raise EconomaticaSectorParseError("shared_string_invalida") from exc
    if kind == "inlineStr":
        inline = cell.find(_MAIN + "is")
        if inline is None:
            return None
        return "".join((node.text or "") for node in inline.iter(_MAIN + "t"))
    return value.text if value is not None else None


def parse_economatica_sector_xlsx(data: bytes) -> EconomaticaSectorSnapshot:
    """Extrai ações ativas Bovespa/B3 com setor/subsetor do primeiro worksheet.

    Campos obrigatórios observados nos exports 2009–2025:
    - Bolsa / Fonte
    - Ativo / Cancelado
    - Código
    - Setor Econômico Bovespa
    - Subsetor Bovespa

    ``Tipo de Ativo`` é opcional porque exports antigos não o possuem. Quando existe,
    somente ``Ação`` é elegível. Ticker duplicado divergente falha fechado.
    """
    try:
        zf = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise EconomaticaSectorParseError("xlsx_invalido") from exc
    with zf:
        shared = _shared_strings(zf)
        try:
            sheet_raw = zf.read("xl/worksheets/sheet1.xml")
        except KeyError as exc:
            raise EconomaticaSectorParseError("worksheet_principal_ausente") from exc
        root = ET.fromstring(sheet_raw)
        sheet_data = root.find(_MAIN + "sheetData")
        if sheet_data is None:
            raise EconomaticaSectorParseError("sheetdata_ausente")
        rows = iter(sheet_data)
        try:
            header_row = next(rows)
        except StopIteration as exc:
            raise EconomaticaSectorParseError("planilha_vazia") from exc

        headers: dict[str, int] = {}
        for cell in header_row:
            value = _clean(_cell_value(cell, shared))
            if value is not None:
                headers[" ".join(value.replace("\n", " ").split()).casefold()] = _col_index(cell.attrib["r"])

        required = {
            "exchange": "bolsa / fonte",
            "status": "ativo / cancelado",
            "ticker": "código",
            "sector": "setor econômico bovespa",
            "subsector": "subsetor bovespa",
        }
        index: dict[str, int] = {}
        for key, label in required.items():
            if label.casefold() not in headers:
                raise EconomaticaSectorParseError(f"cabecalho_obrigatorio_ausente:{label}")
            index[key] = headers[label.casefold()]
        type_index = headers.get("tipo de ativo")

        by_ticker: dict[str, EconomaticaSectorRecord] = {}
        rows_seen = rows_filtered = 0
        for row in rows:
            rows_seen += 1
            cells = {_col_index(cell.attrib["r"]): _clean(_cell_value(cell, shared)) for cell in row}
            exchange = (cells.get(index["exchange"]) or "").casefold()
            status = (cells.get(index["status"]) or "").casefold()
            if exchange not in {"bovespa", "b3"} or status != "ativo":
                rows_filtered += 1
                continue
            if type_index is not None and (cells.get(type_index) or "").casefold() != "ação".casefold():
                rows_filtered += 1
                continue
            ticker = (cells.get(index["ticker"]) or "").strip().upper()
            if not ticker:
                rows_filtered += 1
                continue
            record = EconomaticaSectorRecord(
                ticker=ticker,
                economic_sector=_clean(cells.get(index["sector"])),
                subsector=_clean(cells.get(index["subsector"])),
            )
            previous = by_ticker.get(ticker)
            if previous is not None and previous.key != record.key:
                raise EconomaticaSectorParseError(f"ticker_setorial_divergente:{ticker}")
            by_ticker[ticker] = record

        records = tuple(by_ticker[ticker] for ticker in sorted(by_ticker))
        if not records:
            raise EconomaticaSectorParseError("nenhuma_acao_b3_ativa_encontrada")
        return EconomaticaSectorSnapshot(records=records, rows_seen=rows_seen, rows_filtered=rows_filtered)
