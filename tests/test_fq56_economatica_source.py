from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from app.market.economatica_sector_source import (
    EconomaticaSectorParseError,
    parse_economatica_sector_xlsx,
)


def _xlsx(headers, rows):
    strings=[]; index={}
    def s(v):
        if v not in index:
            index[v]=len(strings); strings.append(v)
        return index[v]
    def col(n):
        out=''
        while n:
            n,rem=divmod(n-1,26); out=chr(65+rem)+out
        return out
    xml_rows=[]
    all_rows=[headers]+rows
    for rno,row in enumerate(all_rows,1):
        cells=[]
        for cno,value in enumerate(row,1):
            if value is None: continue
            cells.append(f'<c r="{col(cno)}{rno}" t="s"><v>{s(str(value))}</v></c>')
        xml_rows.append(f'<row r="{rno}">{"".join(cells)}</row>')
    shared=''.join(f'<si><t>{v}</t></si>' for v in strings)
    buf=BytesIO()
    with ZipFile(buf,'w',ZIP_DEFLATED) as z:
        z.writestr('xl/sharedStrings.xml',f'<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{shared}</sst>')
        z.writestr('xl/worksheets/sheet1.xml',f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    return buf.getvalue()


def test_parser_accepts_modern_and_filters_cancelled_non_b3():
    headers=['Nome','Classe','Bolsa / Fonte','Tipo de Ativo','Ativo / Cancelado','Código','Setor Econômico Bovespa','Subsetor Bovespa','Setor Economatica']
    data=_xlsx(headers,[
        ['Petrobras','PN','Bovespa','Ação','ativo','PETR4','Petróleo gás e biocombustíveis','Petróleo gás e biocombustíveis','Petróleo'],
        ['Velha','ON','Bovespa','Ação','cancelado','OLD3-old','Outros','Outros','Outros'],
        ['US','Com','NASDAQ','Ação','ativo','ABC','-','-','Tech'],
    ])
    snap=parse_economatica_sector_xlsx(data)
    assert [r.ticker for r in snap.records]==['PETR4']
    assert snap.records[0].economic_sector=='Petróleo gás e biocombustíveis'
    assert snap.rows_seen==3
    assert snap.rows_filtered==2


def test_parser_accepts_legacy_without_tipo_de_ativo():
    headers=['Bolsa / Fonte','Ativo / Cancelado','Código','Setor Econômico Bovespa','Subsetor Bovespa','Setor Economatica']
    data=_xlsx(headers,[['Bovespa','ativo','VALE3','Materiais básicos','Mineração','Mineração']])
    snap=parse_economatica_sector_xlsx(data)
    assert snap.records[0].ticker=='VALE3'
    assert snap.records[0].subsector=='Mineração'


def test_parser_fails_closed_on_missing_header_and_divergent_duplicate():
    headers=['Bolsa / Fonte','Ativo / Cancelado','Código','Setor Econômico Bovespa']
    with pytest.raises(EconomaticaSectorParseError, match='cabecalho_obrigatorio_ausente'):
        parse_economatica_sector_xlsx(_xlsx(headers,[['Bovespa','ativo','PETR4','Energia']]))
    headers2=['Bolsa / Fonte','Ativo / Cancelado','Código','Setor Econômico Bovespa','Subsetor Bovespa']
    with pytest.raises(EconomaticaSectorParseError, match='ticker_setorial_divergente'):
        parse_economatica_sector_xlsx(_xlsx(headers2,[
            ['Bovespa','ativo','PETR4','Energia','Petróleo'],
            ['Bovespa','ativo','PETR4','Financeiro','Bancos'],
        ]))
