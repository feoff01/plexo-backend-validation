"""Parser determinístico do CSV oficial público ANBIMA de ETTJ.

Contrato físico observado em 2026-10-03 no download first-party
``https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp``:
- ``Content-Type: text/csv``;
- arquivo ``CurvaZero_.csv`` em encoding compatível com cp1252/ISO-8859;
- data econômica na primeira célula, formato ``DD/MM/AAAA``;
- seção ``ETTJ Inflação Implicita (IPCA)``;
- cabeçalho ``Vertices;ETTJ IPCA;ETTJ PREF;Inflação Implícita``;
- decimal brasileiro com vírgula e separador de milhar ``.`` nos vértices;
- PRE e inflação implícita podem terminar antes da ETTJ IPCA.

O módulo não faz rede, não acessa banco, não interpola e ignora deliberadamente
parâmetros Svensson e a seção de erro título-a-título, fora da tranche FQ5.7.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import StringIO


class AnbimaYieldCurveCsvParseError(ValueError):
    """O CSV ANBIMA não respeita o contrato físico observado."""


@dataclass(frozen=True)
class AnbimaYieldCurveCsvPoint:
    business_days: int
    ipca_rate_pct: Decimal
    pre_rate_pct: Decimal | None
    implied_inflation_pct: Decimal | None


@dataclass(frozen=True)
class AnbimaYieldCurveCsvSnapshot:
    reference_date: date
    points: tuple[AnbimaYieldCurveCsvPoint, ...]

    @property
    def ipca_vertices(self) -> int:
        return len(self.points)

    @property
    def pre_vertices(self) -> int:
        return sum(point.pre_rate_pct is not None for point in self.points)

    @property
    def implied_vertices(self) -> int:
        return sum(point.implied_inflation_pct is not None for point in self.points)


def _decode(data: bytes) -> str:
    if not data:
        raise AnbimaYieldCurveCsvParseError("csv_ettj_vazio")
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise AnbimaYieldCurveCsvParseError("encoding_ettj_invalido") from exc


def _reference_date(value: str) -> date:
    try:
        parsed = datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError as exc:
        raise AnbimaYieldCurveCsvParseError(f"data_referencia_ettj_invalida:{value}") from exc
    if parsed.year < 2000:
        raise AnbimaYieldCurveCsvParseError(f"data_referencia_ettj_invalida:{value}")
    return parsed


def _decimal_br(value: str, *, field: str) -> Decimal:
    normalized = value.strip().replace(".", "").replace(",", ".")
    if not normalized:
        raise AnbimaYieldCurveCsvParseError(f"campo_ettj_vazio:{field}")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise AnbimaYieldCurveCsvParseError(
            f"campo_ettj_invalido:{field}:{value}"
        ) from exc


def _optional_decimal_br(value: str, *, field: str) -> Decimal | None:
    if not value.strip():
        return None
    return _decimal_br(value, field=field)


def _business_days(value: str) -> int:
    normalized = value.strip().replace(".", "")
    if not normalized.isdigit():
        raise AnbimaYieldCurveCsvParseError(f"vertice_ettj_invalido:{value}")
    result = int(normalized)
    if result <= 0:
        raise AnbimaYieldCurveCsvParseError(f"vertice_ettj_invalido:{value}")
    return result


def parse_anbima_yield_curve_csv(data: bytes) -> AnbimaYieldCurveCsvSnapshot:
    """Extrai apenas os vértices oficiais ETTJ do CSV público ANBIMA."""
    rows = list(csv.reader(StringIO(_decode(data)), delimiter=";"))
    if len(rows) < 8 or not rows[0]:
        raise AnbimaYieldCurveCsvParseError("csv_ettj_sem_dados")

    reference_date = _reference_date(rows[0][0])
    section_title = "ETTJ Inflação Implicita (IPCA)"
    try:
        section_index = next(
            index for index, row in enumerate(rows)
            if row and row[0].strip() == section_title
        )
    except StopIteration as exc:
        raise AnbimaYieldCurveCsvParseError("secao_ettj_ausente") from exc

    if section_index + 1 >= len(rows):
        raise AnbimaYieldCurveCsvParseError("cabecalho_ettj_ausente")
    header = [cell.strip() for cell in rows[section_index + 1]][:4]
    expected_header = ["Vertices", "ETTJ IPCA", "ETTJ PREF", "Inflação Implícita"]
    if header != expected_header:
        raise AnbimaYieldCurveCsvParseError("cabecalho_ettj_invalido")

    points: list[AnbimaYieldCurveCsvPoint] = []
    seen: set[int] = set()
    previous_vertex = 0
    for row in rows[section_index + 2:]:
        if not row or not any(cell.strip() for cell in row):
            break
        cells = (row + ["", "", "", ""])[:4]
        vertex = _business_days(cells[0])
        if vertex in seen:
            raise AnbimaYieldCurveCsvParseError(f"vertice_ettj_duplicado:{vertex}")
        if vertex <= previous_vertex:
            raise AnbimaYieldCurveCsvParseError(f"vertices_ettj_fora_de_ordem:{vertex}")
        seen.add(vertex)
        previous_vertex = vertex

        ipca = _decimal_br(cells[1], field=f"ipca:{vertex}")
        pre = _optional_decimal_br(cells[2], field=f"pre:{vertex}")
        implied = _optional_decimal_br(cells[3], field=f"implicita:{vertex}")
        if (pre is None) != (implied is None):
            raise AnbimaYieldCurveCsvParseError(
                f"pre_implicita_desalinhados:{vertex}"
            )
        points.append(
            AnbimaYieldCurveCsvPoint(
                business_days=vertex,
                ipca_rate_pct=ipca,
                pre_rate_pct=pre,
                implied_inflation_pct=implied,
            )
        )

    if not points:
        raise AnbimaYieldCurveCsvParseError("ettj_sem_vertices")
    if not any(point.pre_rate_pct is not None for point in points):
        raise AnbimaYieldCurveCsvParseError("ettj_pre_ausente")
    return AnbimaYieldCurveCsvSnapshot(
        reference_date=reference_date,
        points=tuple(points),
    )
