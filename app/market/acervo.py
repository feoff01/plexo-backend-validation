"""Regras de leitura do acervo do mercado brasileiro (F22) — puras, sem banco e sem rede.

Este módulo existe separado por dois motivos. O primeiro é testabilidade: são as decisões que, se
erradas, produzem número errado em SILÊNCIO, e cada uma tem asserção em `tests/test_f22_acervo.py`.
O segundo é operacional: `tools/projetar_acervo.py` roda no Python do SISTEMA (é ele que tem pandas
e pyarrow), enquanto o backend roda na `.venv` — só o que é stdlib puro pode ser compartilhado
pelos dois, e é isto aqui.

O acervo vem do Mercado Brasil Collector, em Parquet já normalizado. O que este módulo encapsula é
o que o Parquet NÃO resolveu, e que o `postgres_loader.py` do coletor resolveria se estivéssemos
usando o schema dele (não estamos — ver `sql/61_acervo_de_mercado.sql`).
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

# TPMERC 010 = à vista. Os outros tipos (020 fracionário, 030 termo, 070/080 opções, 012/013
# exercício, 017 leilão) são 83% do arquivo e nenhum é lido pelo produto.
MERCADO_A_VISTA = "010"

# CODBDI, medidos no COTAHIST de 2026 — não supostos. Duas leituras erradas custaram releitura:
#   · BDR NÃO está no 02. Vive em 34 (DRN, não patrocinado), 35 (DR1/DR2/DR3, patrocinado) e
#     36 (DRE, BDR de ETF) — cerca de 89 mil linhas por ano que um filtro só com {02,12,14}
#     descarta inteiras, e com elas toda a exposição internacional do cliente.
#   · 07 e 08 trazem 20 a 30 ações por ano SEM linha no 02 (`AMER3`, `AMBP3`, `ETER3`): são papéis
#     em situação especial. Excluí-los apagaria esses tickers da base.
# Ficam de fora, de propósito: 10 (DIR, direito de subscrição) e 22 (BNS, bônus) — são direitos
# SOBRE um papel, não o papel; e 13/58, resíduos de poucas linhas sem leitura clara.
BDI_ACAO = frozenset({"02", "07", "08"})
BDI_FII = "12"
BDI_COLETIVO = "14"          # ETF, FIAGRO, FIP e FIDC juntos — ver kind_do_instrumento
BDI_BDR = frozenset({"34", "35", "36"})
BDI_A_VISTA = BDI_ACAO | {BDI_FII, BDI_COLETIVO} | BDI_BDR

# `market.instrument_kind` → `market.asset_classes.code`. `fundo`/`etf` ficam de fora de propósito.
CLASSE_POR_KIND = {"acao": "acoes_br", "fii": "fii", "bdr": "acoes_int"}

# Código de negociação da B3: 4 caracteres ALFANUMÉRICOS (a raiz pode ter dígito — `B3SA3`, `SPG211`,
# `WEB311`), 1 ou 2 dígitos de tipo, e uma letra final opcional de série especial (`MRSA3B`).
# Exigir quatro LETRAS, como esta linha fazia antes, recusava dez papéis do COTAHIST de 2026 — a
# própria B3 entre eles, que está no IBrX-100.
PADRAO_TICKER = r"^[A-Z0-9]{4}\d{1,2}[A-Z]?$"
_TICKER = re.compile(PADRAO_TICKER)
_ESPACOS = re.compile(r"\s+")
_CENTAVO_DE_CENTAVO = Decimal("0.00000001")   # market.prices.value é numeric(20,8)


def _codigo(valor: object, largura: int) -> str:
    """Código numérico do COTAHIST com os zeros à esquerda de volta.

    O Parquet guarda `bdi_code` e `market_type` como texto, mas passar por CSV ou por um cast
    numérico em qualquer ponto da cadeia come o zero: '02' vira '2' e '010' vira '10'. Comparar
    sem normalizar faria o filtro de mercado à vista devolver zero linha, silenciosamente.
    """
    if valor is None:
        return ""
    return str(valor).strip().zfill(largura)


def preco_com_fatcot(valor: Decimal | float | int | None,
                     quote_factor: Decimal | float | int | None) -> Decimal | None:
    """Preço unitário a partir do preço por LOTE de cotação (FATCOT).

    O COTAHIST cota por lote de `quote_factor` títulos — séries antigas e alguns BDRs vêm por lote
    de 1.000. O parser V9 do coletor passou a dividir na origem e a marcar `layout_version=v9`,
    mas os Parquet deste acervo NÃO trazem a marca: pelo `adapt_b3_price` do próprio coletor, isso
    significa que a divisão ainda não foi aplicada. Sem ela o preço fica 1.000× errado, e nada
    acusa — o retorno continua certo porque o fator é constante, e só a escala do gráfico denuncia.
    """
    if valor is None:
        return None
    v = Decimal(str(valor))
    f = Decimal(str(quote_factor)) if quote_factor is not None else Decimal(1)
    if f <= 0:                      # fator ausente, zero ou negativo: trata como 1, nunca inverte
        f = Decimal(1)
    return (v / f).quantize(_CENTAVO_DE_CENTAVO, rounding=ROUND_HALF_UP)


def eh_mercado_a_vista(market_type: object, bdi_code: object) -> bool:
    """Só o pregão à vista de ação, FII, fundo listado e BDR entra em `market.prices`."""
    return _codigo(market_type, 3) == MERCADO_A_VISTA and _codigo(bdi_code, 2) in BDI_A_VISTA


def raiz_b3_do_ticker(ticker: object) -> str | None:
    """Raiz oficial B3 de quatro caracteres para um ticker negociável."""
    if not ticker_negociavel(ticker):
        return None
    return str(ticker).strip().upper()[:4]


def acoes_correntes_por_raiz(
    registros: list[tuple[str, str, object]],
) -> tuple[int | None, dict[str, list[str]]]:
    """Agrupa somente ações observadas no ano mais recente por raiz B3.

    ``registros`` contém ``(ticker, kind, ultima_data)``. A regra evita ligar
    automaticamente tickers históricos/delistados a uma companhia atual só porque
    reutilizam a mesma raiz de quatro caracteres.
    """
    anos = [getattr(data, "year", None) for _ticker, kind, data in registros if kind == "acao"]
    anos = [ano for ano in anos if isinstance(ano, int)]
    if not anos:
        return None, {}
    ano_corrente = max(anos)
    por_raiz: dict[str, list[str]] = {}
    for ticker, kind, data in registros:
        if kind != "acao" or getattr(data, "year", None) != ano_corrente:
            continue
        raiz = raiz_b3_do_ticker(ticker)
        if raiz is not None:
            por_raiz.setdefault(raiz, []).append(str(ticker).strip().upper())
    for raiz in por_raiz:
        por_raiz[raiz] = sorted(set(por_raiz[raiz]))
    return ano_corrente, dict(sorted(por_raiz.items()))


def ticker_negociavel(ticker: object) -> bool:
    """Código de negociação válido da B3 (ver `_TICKER`). Fora do padrão, não é papel.

    O que for recusado é CONTADO e reportado pelo projetor, nunca descartado em silêncio — é a
    regra do próprio coletor ("nunca descarte linha em silêncio").

    `PADRAO_TICKER` é público porque o projetor precisa da MESMA regra na forma vetorizada, sobre
    24 milhões de linhas: uma cópia do regex ali seria uma segunda fonte da verdade.
    """
    return bool(ticker) and bool(_TICKER.match(str(ticker)))


def kind_do_instrumento(bdi_code: object, ticker: object) -> str:
    """Valor de `market.instrument_kind` para uma linha do COTAHIST.

    Quem decide é o CODBDI, que é o que o arquivo afirma — não o sufixo do ticker, que é convenção
    e falha em série especial. Unit (sufixo 11 sob BDI de ação) continua sendo `acao`, porque é
    participação na companhia, não fundo.

    **BDI 14 vira `fundo`, não `etf`.** Medido no arquivo de 2026: `BOVA11` (ISHARES BOVA),
    `IVVB11` (ISHARE SP500), `AAGR11` (FIAGRO AAGR) e `AATH11` (FIP ATHON) têm todos
    `specification = 'CI'` — o COTAHIST não distingue ETF de FIAGRO, FIP ou FIDC. `fundo` é
    verdadeiro para os quatro; `etf` seria chute para metade deles. A separação sai do cadastro
    CVM de fundos (`fund_type`), que ainda não foi coletado — e até lá o upsert do projetor
    PRESERVA o kind de quem já existe, então BOVA11 continua `etf` no dev.
    """
    bdi = _codigo(bdi_code, 2)
    if bdi == BDI_FII:
        return "fii"
    if bdi == BDI_COLETIVO:
        return "fundo"
    if bdi in BDI_BDR:
        return "bdr"
    if bdi in BDI_ACAO:
        return "acao"
    return "outro"


def classe_de_ativo(kind: str) -> str | None:
    """`market.asset_classes.code` do kind, ou None quando o dado não permite afirmar.

    `fundo` e `etf` ficam NULL de propósito: sob o BDI 14 convivem bolsa local (BOVA11), S&P 500
    (IVVB11), FIAGRO e FIP, e o COTAHIST não diz qual é qual. `posicoes_carteira` já trata classe
    ausente com `coalesce`; chutar 'acoes_br' faria o Raio-X medir concentração em Brasil onde há
    exposição internacional — um número errado com cara de certo, que é o que este projeto evita
    por regra.
    """
    return CLASSE_POR_KIND.get(kind)


def nome_do_instrumento(issuer_name: object, specification: object) -> str:
    """Nome legível: emissor + especificação, com o espaçamento fixo do arquivo colapsado.

    O COTAHIST alinha em colunas ('PN      N2'), e o nome vai para a tela do cliente.
    """
    bruto = f"{issuer_name or ''} {specification or ''}"
    return _ESPACOS.sub(" ", bruto).strip()
