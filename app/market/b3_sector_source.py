"""Parser determinístico do download oficial B3 de classificação setorial.

Contrato observado em 2026-10-01 no arquivo ``ClassifSetorial(...).xlsx``:
- cabeçalho em duas linhas;
- ``SETOR`` em A1:A2;
- ``SUBSETOR`` em B1:B2;
- ``CÓDIGO`` em C2;
- dados a partir da terceira linha.

O arquivo oficial observado não contém CNPJ nem o terceiro nível ``segmento``.
Este módulo não faz rede, não acessa banco e não infere data de referência.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REF = re.compile(r"^([A-Z]+)")
_COMPANY_CODE = re.compile(r"^[A-Z0-9]{4}$")


class B3SectorParseError(ValueError):
    """O arquivo B3 não respeita o contrato observado."""


@dataclass(frozen=True)
class B3SectorDownloadRecord:
    company_code: str
    economic_sector: str
    subsector: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.economic_sector, self.subsector)


@dataclass(frozen=True)
class B3SectorDownloadSnapshot:
    records: tuple[B3SectorDownloadRecord, ...]
    rows_seen: int
    duplicate_rows: int


def _col_index(ref: str) -> int:
    match = _CELL_REF.match(ref)
    if not match:
        raise B3SectorParseError(f"referencia_celula_invalida:{ref}")
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - 64)
    return value - 1


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.replace("\n", " ").split()).strip()
    return value or None


def _shared_strings(zf: ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return [
        "".join((node.text or "") for node in si.iter(_MAIN + "t"))
        for si in root.findall(_MAIN + "si")
    ]


def _cell_value(cell: ET.Element, shared: list[str]) -> str | None:
    kind = cell.attrib.get("t")
    value = cell.find(_MAIN + "v")
    if kind == "s" and value is not None:
        try:
            return shared[int(value.text or "0")]
        except (ValueError, IndexError) as exc:
            raise B3SectorParseError("shared_string_invalida") from exc
    if kind == "inlineStr":
        inline = cell.find(_MAIN + "is")
        if inline is None:
            return None
        return "".join((node.text or "") for node in inline.iter(_MAIN + "t"))
    return value.text if value is not None else None


def _row_cells(row: ET.Element, shared: list[str]) -> dict[int, str | None]:
    return {
        _col_index(cell.attrib["r"]): _clean(_cell_value(cell, shared))
        for cell in row
    }


def parse_b3_sector_xlsx(data: bytes) -> B3SectorDownloadSnapshot:
    """Extrai ``SETOR / SUBSETOR / CÓDIGO`` do primeiro worksheet oficial B3."""
    try:
        zf = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise B3SectorParseError("xlsx_invalido") from exc

    with zf:
        shared = _shared_strings(zf)
        try:
            sheet_raw = zf.read("xl/worksheets/sheet1.xml")
        except KeyError as exc:
            raise B3SectorParseError("worksheet_principal_ausente") from exc
        root = ET.fromstring(sheet_raw)
        sheet_data = root.find(_MAIN + "sheetData")
        if sheet_data is None:
            raise B3SectorParseError("sheetdata_ausente")
        rows = list(sheet_data)
        if len(rows) < 3:
            raise B3SectorParseError("planilha_sem_dados")

        header_indexes: dict[str, int] = {}
        for header_row in rows[:2]:
            for cell in header_row:
                value = _clean(_cell_value(cell, shared))
                if value is None:
                    continue
                normalized = value.casefold()
                if normalized in {"setor", "subsetor", "código", "codigo"}:
                    header_indexes[normalized] = _col_index(cell.attrib["r"])

        sector_index = header_indexes.get("setor")
        subsector_index = header_indexes.get("subsetor")
        code_index = header_indexes.get("código", header_indexes.get("codigo"))
        if sector_index is None:
            raise B3SectorParseError("cabecalho_obrigatorio_ausente:setor")
        if subsector_index is None:
            raise B3SectorParseError("cabecalho_obrigatorio_ausente:subsetor")
        if code_index is None:
            raise B3SectorParseError("cabecalho_obrigatorio_ausente:codigo")

        by_code: dict[str, B3SectorDownloadRecord] = {}
        duplicate_rows = 0
        rows_seen = 0
        for row in rows[2:]:
            cells = _row_cells(row, shared)
            if not any(cells.values()):
                continue
            rows_seen += 1
            sector = cells.get(sector_index)
            subsector = cells.get(subsector_index)
            code = (cells.get(code_index) or "").upper()
            if not _COMPANY_CODE.fullmatch(code):
                raise B3SectorParseError(f"codigo_companhia_invalido:{code or '<vazio>'}")
            if not sector or not subsector:
                raise B3SectorParseError(f"classificacao_incompleta:{code}")
            record = B3SectorDownloadRecord(
                company_code=code,
                economic_sector=sector,
                subsector=subsector,
            )
            previous = by_code.get(code)
            if previous is not None:
                if previous.key != record.key:
                    raise B3SectorParseError(f"codigo_setorial_divergente:{code}")
                duplicate_rows += 1
                continue
            by_code[code] = record

        records = tuple(by_code[code] for code in sorted(by_code))
        if not records:
            raise B3SectorParseError("nenhuma_classificacao_b3_encontrada")
        return B3SectorDownloadSnapshot(
            records=records,
            rows_seen=rows_seen,
            duplicate_rows=duplicate_rows,
        )
