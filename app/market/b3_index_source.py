"""Parser determinístico de carteira diária oficial de índice B3.

Contrato observado em 2026-10-02 em ``IBRADia_02-10-26.csv``:
- primeira linha: ``IBRA - Carteira do Dia DD/MM/AA``;
- segunda linha: Código;Ação;Tipo;Qtde. Teórica;Part. (%);
- dados de componentes;
- rodapé com ``Quantidade Teórica Total`` e ``Redutor``.

O módulo não acessa banco, não faz rede e não infere histórico além da data explícita no título.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import StringIO
import re

from app.market import acervo

_TITLE = re.compile(r"^([A-Z0-9]+)\s*-\s*Carteira do Dia\s+(\d{2}/\d{2}/\d{2,4})$", re.IGNORECASE)


class B3IndexPortfolioParseError(ValueError):
    """O arquivo não respeita o contrato de carteira diária observado."""


@dataclass(frozen=True)
class B3IndexPortfolioRecord:
    ticker: str
    name: str
    security_type: str
    theoretical_qty: Decimal
    weight_pct: Decimal


@dataclass(frozen=True)
class B3IndexPortfolioSnapshot:
    index_code: str
    reference_date: date
    records: tuple[B3IndexPortfolioRecord, ...]
    total_theoretical_qty: Decimal
    total_weight_pct: Decimal


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise B3IndexPortfolioParseError("encoding_csv_nao_suportado")


def _decimal_br(value: str, *, field: str) -> Decimal:
    normalized = value.strip().replace(".", "").replace(",", ".")
    if not normalized:
        raise B3IndexPortfolioParseError(f"campo_numerico_vazio:{field}")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise B3IndexPortfolioParseError(f"campo_numerico_invalido:{field}:{value}") from exc


def _parse_reference_date(value: str) -> date:
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(value, fmt).date()
            if parsed.year < 2000:
                raise B3IndexPortfolioParseError(f"data_referencia_invalida:{value}")
            return parsed
        except ValueError:
            continue
    raise B3IndexPortfolioParseError(f"data_referencia_invalida:{value}")


def parse_b3_index_portfolio_csv(
    data: bytes,
    *,
    expected_index_code: str | None = None,
    expected_reference_date: date | None = None,
) -> B3IndexPortfolioSnapshot:
    """Extrai uma carteira diária B3 e valida totais/identidade sem acessar banco."""
    text = _decode(data)
    rows = list(csv.reader(StringIO(text), delimiter=";"))
    if len(rows) < 4:
        raise B3IndexPortfolioParseError("csv_sem_dados")

    title = (rows[0][0] if rows[0] else "").strip()
    match = _TITLE.fullmatch(title)
    if not match:
        raise B3IndexPortfolioParseError("titulo_carteira_invalido")
    index_code = match.group(1).strip().lower()
    reference_date = _parse_reference_date(match.group(2))

    if expected_index_code and index_code != expected_index_code.strip().lower():
        raise B3IndexPortfolioParseError(
            f"indice_inesperado:{index_code}:esperado={expected_index_code.strip().lower()}"
        )
    if expected_reference_date and reference_date != expected_reference_date:
        raise B3IndexPortfolioParseError(
            f"data_inesperada:{reference_date.isoformat()}:esperado={expected_reference_date.isoformat()}"
        )

    header = [cell.strip().casefold() for cell in rows[1] if cell.strip()]
    expected_header = ["código", "ação", "tipo", "qtde. teórica", "part. (%)"]
    if header[:5] != expected_header:
        raise B3IndexPortfolioParseError("cabecalho_carteira_invalido")

    by_ticker: dict[str, B3IndexPortfolioRecord] = {}
    total_qty: Decimal | None = None
    total_weight: Decimal | None = None
    for row in rows[2:]:
        if not row:
            continue
        first = (row[0] or "").strip()
        if not first:
            continue
        if first.casefold() == "quantidade teórica total".casefold():
            if len(row) < 5:
                raise B3IndexPortfolioParseError("rodape_total_incompleto")
            total_qty = _decimal_br(row[3], field="quantidade_teorica_total")
            total_weight = _decimal_br(row[4], field="peso_total")
            continue
        if first.casefold() == "redutor".casefold():
            continue
        if len(row) < 5:
            raise B3IndexPortfolioParseError(f"linha_carteira_incompleta:{first}")

        ticker = first.upper()
        if not acervo.ticker_negociavel(ticker):
            raise B3IndexPortfolioParseError(f"ticker_b3_invalido:{ticker}")
        if ticker in by_ticker:
            raise B3IndexPortfolioParseError(f"ticker_b3_duplicado:{ticker}")

        qty = _decimal_br(row[3], field=f"qtde_teorica:{ticker}")
        weight = _decimal_br(row[4], field=f"peso:{ticker}")
        if qty < 0:
            raise B3IndexPortfolioParseError(f"qtde_teorica_negativa:{ticker}")
        if weight < 0 or weight > 100:
            raise B3IndexPortfolioParseError(f"peso_fora_da_faixa:{ticker}")

        by_ticker[ticker] = B3IndexPortfolioRecord(
            ticker=ticker,
            name=(row[1] or "").strip(),
            security_type=" ".join((row[2] or "").split()),
            theoretical_qty=qty,
            weight_pct=weight,
        )

    if not by_ticker:
        raise B3IndexPortfolioParseError("carteira_sem_componentes")
    if total_qty is None or total_weight is None:
        raise B3IndexPortfolioParseError("rodape_total_ausente")

    records = tuple(by_ticker[ticker] for ticker in sorted(by_ticker))
    qty_sum = sum((record.theoretical_qty for record in records), Decimal("0"))
    weight_sum = sum((record.weight_pct for record in records), Decimal("0"))
    if qty_sum != total_qty:
        raise B3IndexPortfolioParseError(
            f"quantidade_total_divergente:{qty_sum}:{total_qty}"
        )
    if abs(weight_sum - total_weight) > Decimal("0.01"):
        raise B3IndexPortfolioParseError(f"peso_total_divergente:{weight_sum}:{total_weight}")
    if not (Decimal("99.90") <= total_weight <= Decimal("100.10")):
        raise B3IndexPortfolioParseError(f"peso_total_nao_fecha_100:{total_weight}")

    return B3IndexPortfolioSnapshot(
        index_code=index_code,
        reference_date=reference_date,
        records=records,
        total_theoretical_qty=total_qty,
        total_weight_pct=total_weight,
    )
