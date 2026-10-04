from datetime import date
from decimal import Decimal

import pytest

from app.market.b3_index_source import B3IndexPortfolioParseError, parse_b3_index_portfolio_csv


def _csv(rows, *, title="IBRA - Carteira do Dia 02/10/26") -> bytes:
    lines = [
        title,
        "Código;Ação;Tipo;Qtde. Teórica;Part. (%)",
        *rows,
    ]
    return ("\n".join(lines) + "\n").encode("latin-1")


def test_parse_daily_ibra_contract_and_totals():
    data = _csv([
        "PETR4;PETROBRAS;PN N2;1.000;60,000;",
        "VALE3;VALE;ON NM;2.000;40,000;",
        "Quantidade Teórica Total;;;3.000;100,000",
        "Redutor;;;1,2345",
    ])
    snapshot = parse_b3_index_portfolio_csv(
        data,
        expected_index_code="ibra",
        expected_reference_date=date(2026, 10, 2),
    )
    assert snapshot.index_code == "ibra"
    assert snapshot.reference_date == date(2026, 10, 2)
    assert [r.ticker for r in snapshot.records] == ["PETR4", "VALE3"]
    assert snapshot.total_theoretical_qty == Decimal("3000")
    assert snapshot.total_weight_pct == Decimal("100.000")


def test_parser_fails_closed_on_wrong_index_duplicate_or_bad_total():
    good_rows = [
        "PETR4;PETROBRAS;PN N2;1.000;100,000;",
        "Quantidade Teórica Total;;;1.000;100,000",
    ]
    with pytest.raises(B3IndexPortfolioParseError, match="indice_inesperado"):
        parse_b3_index_portfolio_csv(_csv(good_rows), expected_index_code="ibov")

    with pytest.raises(B3IndexPortfolioParseError, match="ticker_b3_duplicado"):
        parse_b3_index_portfolio_csv(_csv([
            "PETR4;PETROBRAS;PN N2;1.000;50,000;",
            "PETR4;PETROBRAS;PN N2;1.000;50,000;",
            "Quantidade Teórica Total;;;2.000;100,000",
        ]))

    with pytest.raises(B3IndexPortfolioParseError, match="peso_total_divergente"):
        parse_b3_index_portfolio_csv(_csv([
            "PETR4;PETROBRAS;PN N2;1.000;90,000;",
            "Quantidade Teórica Total;;;1.000;100,000",
        ]))
