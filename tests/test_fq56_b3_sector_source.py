from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.market.b3_sector_source import B3SectorParseError, parse_b3_sector_xlsx


def _xlsx(rows):
    strings = []
    index = {}

    def s(value):
        if value not in index:
            index[value] = len(strings)
            strings.append(value)
        return index[value]

    def cell(ref, value):
        return f'<c r="{ref}" t="s"><v>{s(value)}</v></c>'

    xml_rows = [
        '<row r="1">' + cell("A1", "SETOR") + cell("B1", "SUBSETOR") + '</row>',
        '<row r="2">' + cell("C2", "CÓDIGO") + '</row>',
    ]
    for rno, (sector, subsector, code) in enumerate(rows, 3):
        xml_rows.append(
            f'<row r="{rno}">'
            + cell(f"A{rno}", sector)
            + cell(f"B{rno}", subsector)
            + cell(f"C{rno}", code)
            + '</row>'
        )

    shared = ''.join(f'<si><t>{value}</t></si>' for value in strings)
    buf = BytesIO()
    with ZipFile(buf, 'w', ZIP_DEFLATED) as zf:
        zf.writestr(
            'xl/sharedStrings.xml',
            '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + shared
            + '</sst>',
        )
        zf.writestr(
            'xl/worksheets/sheet1.xml',
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + ''.join(xml_rows)
            + '</sheetData></worksheet>',
        )
    return buf.getvalue()


def test_parser_reads_two_row_official_contract():
    snapshot = parse_b3_sector_xlsx(
        _xlsx([
            ('Petróleo, Gás e Biocombustíveis', 'Petróleo, Gás e Biocombustíveis', 'PETR'),
            ('Financeiro', 'Intermediários Financeiros', 'B3SA'),
        ])
    )
    assert [r.company_code for r in snapshot.records] == ['B3SA', 'PETR']
    petr = next(r for r in snapshot.records if r.company_code == 'PETR')
    assert petr.economic_sector == 'Petróleo, Gás e Biocombustíveis'
    assert petr.subsector == 'Petróleo, Gás e Biocombustíveis'
    assert snapshot.rows_seen == 2


def test_parser_deduplicates_identical_and_fails_divergent():
    same = _xlsx([
        ('Financeiro', 'Bancos', 'ITUB'),
        ('Financeiro', 'Bancos', 'ITUB'),
    ])
    snapshot = parse_b3_sector_xlsx(same)
    assert len(snapshot.records) == 1
    assert snapshot.duplicate_rows == 1

    divergent = _xlsx([
        ('Financeiro', 'Bancos', 'ITUB'),
        ('Financeiro', 'Serviços', 'ITUB'),
    ])
    with pytest.raises(B3SectorParseError, match='codigo_setorial_divergente:ITUB'):
        parse_b3_sector_xlsx(divergent)


def test_parser_fails_closed_on_invalid_code_or_incomplete_classification():
    with pytest.raises(B3SectorParseError, match='codigo_companhia_invalido'):
        parse_b3_sector_xlsx(_xlsx([('Financeiro', 'Bancos', 'ITUB4')]))
    with pytest.raises(B3SectorParseError, match='classificacao_incompleta'):
        parse_b3_sector_xlsx(_xlsx([('Financeiro', '', 'ITUB')]))
