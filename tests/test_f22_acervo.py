"""F22 — acervo de mercado: o que a migration 61 mudou do lado do Python.

O grosso dos invariantes da 61 é do banco e está em `test_regras_invioláveis_market.sql`
(T146–T150). Aqui fica o que o SQL não alcança: a leitura de nome de partição, que passou a
conviver com duas granularidades, a cobertura que ela alimenta, e as regras de projeção do acervo
(`app/market/acervo.py`) — as decisões que, se erradas, produzem número errado em SILÊNCIO.
"""
from datetime import date
from decimal import Decimal

from app.market import acervo
from app.market.ingest import _faixa_da_particao


# ---------------------------------------------------------------- puro (sem banco)
def test_faixa_da_particao_reconhece_anual_e_mensal():
    """A 61 criou `prices_AAAA` para 1995–2015 ao lado das `prices_AAAAMM` que já existiam.

    O regex anterior exigia os seis dígitos: as anuais seriam ignoradas em silêncio e a cobertura
    diria que a base começa em 2016 mesmo com trinta anos de pregão carregados.
    """
    assert _faixa_da_particao("prices_1995") == (date(1995, 1, 1), date(1995, 12, 31))
    assert _faixa_da_particao("prices_2015") == (date(2015, 1, 1), date(2015, 12, 31))
    assert _faixa_da_particao("prices_201601") == (date(2016, 1, 1), date(2016, 1, 31))
    assert _faixa_da_particao("prices_202402") == (date(2024, 2, 1), date(2024, 2, 29))  # bissexto
    assert _faixa_da_particao("prices_202712") == (date(2027, 12, 1), date(2027, 12, 31))  # vira o ano


def test_faixa_da_particao_ignora_o_que_nao_e_faixa():
    """A DEFAULT é válvula de escape, não cobertura: contá-la faria a base parecer completa."""
    assert _faixa_da_particao("prices_default") is None
    assert _faixa_da_particao("prices") is None
    assert _faixa_da_particao("prices_19951") is None


# ---------------------------------------------------------------- banco real
async def test_cobertura_particoes_alcanca_o_acervo(db):
    """A 61 estendeu market.prices para trás; a cobertura precisa dizer isso."""
    from app.market import ingest

    async with db.service_session() as conn:
        cob = await ingest.cobertura_particoes(conn)
    assert cob.inicio <= date(1995, 1, 1), "as partições anuais do acervo não foram enxergadas"
    assert cob.fim >= date.today()
    assert cob.particoes >= 148  # 21 anuais (1995–2015) + as mensais de 2016-01 em diante


async def test_precos_ajustados_esta_disponivel_para_a_api(db):
    """A view é o caminho oficial de retorno; sob plexo_app ela precisa responder.

    `market` é referência global e não tem RLS — mas a view nasceu com `security_invoker = true`,
    e um GRANT esquecido só apareceria aqui, sob o papel que a tool usa de verdade.
    """
    async with db.app_session(user_id=None, scope_id=None) as conn:
        cur = await conn.execute(
            "select count(*) from market.v_precos_ajustados where price_date > current_date")
        assert (await cur.fetchone())[0] == 0
        cur = await conn.execute("select count(*) from market.v_fatores_ajuste")
        assert (await cur.fetchone())[0] >= 0


# ---------------------------------------------------------------- projeção do acervo (puro)
def test_fatcot_divide_o_preco_das_series_antigas():
    """O erro mais caro e mais silencioso da projeção.

    O COTAHIST cota por LOTE de `quote_factor` títulos: séries antigas e alguns BDRs vinham por
    lote de 1.000. Os Parquet do acervo NÃO trazem `layout_version`, então (pelo `adapt_b3_price`
    do coletor) a divisão ainda não foi aplicada na origem — sem ela o preço fica 1.000× errado e
    nada acusa: o gráfico só sai com escala absurda vinte anos atrás.
    """
    assert acervo.preco_com_fatcot(Decimal("12500.00"), 1000) == Decimal("12.50")
    assert acervo.preco_com_fatcot(Decimal("31.45"), 1) == Decimal("31.45")
    # Fator ausente, zero ou negativo é tratado como 1 — nunca divide por zero, nunca inverte sinal.
    assert acervo.preco_com_fatcot(Decimal("31.45"), None) == Decimal("31.45")
    assert acervo.preco_com_fatcot(Decimal("31.45"), 0) == Decimal("31.45")
    assert acervo.preco_com_fatcot(None, 1000) is None


def test_kind_vem_do_bdi_e_o_bdr_do_sufixo():
    """FII é CODBDI 12. O 14 é "investimento coletivo" e NÃO separa ETF de FIAGRO/FIP/FIDC.

    Medido no COTAHIST de 2026: `BOVA11` (ISHARES BOVA), `IVVB11` (ISHARE SP500), `AAGR11`
    (FIAGRO AAGR) e `AATH11` (FIP ATHON) têm todos `specification = 'CI'`. Sem fonte que os
    separe, o kind honesto é `fundo` — ETF é fundo, e chamar um FIAGRO de ETF seria chute. A
    distinção vem depois, do cadastro CVM de fundos (`fund_type`), que ainda não foi coletado.
    """
    assert acervo.kind_do_instrumento("02", "PETR4") == "acao"
    assert acervo.kind_do_instrumento("02", "TAEE11") == "acao"      # unit continua sendo ação
    assert acervo.kind_do_instrumento("02", "B3SA3") == "acao"       # dígito DENTRO da raiz
    assert acervo.kind_do_instrumento("08", "AMER3") == "acao"       # recuperação judicial
    assert acervo.kind_do_instrumento("07", "TXRX4") == "acao"
    assert acervo.kind_do_instrumento("12", "KNRI11") == "fii"
    assert acervo.kind_do_instrumento("14", "BOVA11") == "fundo"
    assert acervo.kind_do_instrumento("14", "AAGR11") == "fundo"
    assert acervo.kind_do_instrumento("34", "GOGL34") == "bdr"       # DRN, não patrocinado
    assert acervo.kind_do_instrumento("35", "JBSS32") == "bdr"       # DR2, patrocinado nível II
    assert acervo.kind_do_instrumento("36", "BLQD39") == "bdr"       # DRE, BDR de ETF
    assert acervo.kind_do_instrumento("96", "QQQQ1") == "outro"


def test_a_vista_recusa_termo_opcao_e_fracionario():
    """83% do COTAHIST não é mercado à vista; carregar tudo seria 24 mi de linhas em vez de 4,1 mi.

    `market_type` entra na conta porque o MESMO código aparece no mesmo pregão à vista (010) e a
    termo (030) — foi assim que o coletor perdeu a linha de maior volume antes da V9.

    Os CODBDI aceitos saíram do arquivo de 2026, não de suposição. Duas descobertas custaram
    releitura: **BDR não está no 02** (vive em 34/35/36 — 89 mil linhas por ano que o filtro inicial
    descartava), e **07/08 trazem 20 a 30 ações por ano que NÃO têm linha no 02** — são papéis em
    situação especial, `AMER3` e `AMBP3` entre eles. Excluí-los apagaria esses tickers da base.
    Ficam de fora, de propósito, o 10 (DIR, direito de subscrição) e o 22 (BNS, bônus): são direitos
    sobre um papel, não o papel.
    """
    assert acervo.eh_mercado_a_vista("010", "02") is True
    assert acervo.eh_mercado_a_vista("010", "12") is True     # FII
    assert acervo.eh_mercado_a_vista("010", "14") is True     # ETF/FIAGRO/FIP
    assert acervo.eh_mercado_a_vista("010", "34") is True     # BDR não patrocinado
    assert acervo.eh_mercado_a_vista("010", "08") is True     # ação em recuperação judicial
    assert acervo.eh_mercado_a_vista("030", "02") is False    # termo
    assert acervo.eh_mercado_a_vista("070", "02") is False    # opção de compra
    assert acervo.eh_mercado_a_vista("020", "02") is False    # fracionário
    assert acervo.eh_mercado_a_vista("010", "10") is False    # DIR — direito de subscrição
    assert acervo.eh_mercado_a_vista("010", "22") is False    # BNS — bônus de subscrição
    assert acervo.eh_mercado_a_vista("010", "96") is False
    assert acervo.eh_mercado_a_vista("10", "2") is True       # zeros à esquerda perdidos no parquet


def test_nome_do_instrumento_junta_emissor_e_especificacao():
    assert acervo.nome_do_instrumento("PETROBRAS", "PN      N2") == "PETROBRAS PN N2"
    assert acervo.nome_do_instrumento("ALLIAR", "ON      NM") == "ALLIAR ON NM"
    assert acervo.nome_do_instrumento("  VALE  ", None) == "VALE"
    assert acervo.nome_do_instrumento(None, None) == ""


def test_ticker_negociavel_aceita_raiz_alfanumerica_e_serie_especial():
    """Escrevi este teste com PETR4 e BOVA11 e ele passou — mas o arquivo real derrubou a regra.

    Código da B3 é 4 caracteres ALFANUMÉRICOS + 1 ou 2 dígitos, com letra final opcional para
    série especial. Exigir quatro LETRAS recusava dez papéis do COTAHIST de 2026, entre eles
    `B3SA3` — a própria B3, que está no IBrX-100. Os casos abaixo saíram do arquivo, não da minha
    cabeça.
    """
    assert acervo.ticker_negociavel("PETR4") is True
    assert acervo.ticker_negociavel("BOVA11") is True
    assert acervo.ticker_negociavel("B3SA3") is True      # dígito na raiz
    assert acervo.ticker_negociavel("B3BR11") is True
    assert acervo.ticker_negociavel("SPG211") is True
    assert acervo.ticker_negociavel("WEB311") is True
    assert acervo.ticker_negociavel("MRSA3B") is True     # série especial com letra final
    assert acervo.ticker_negociavel("petr4") is False
    assert acervo.ticker_negociavel("PETR") is False
    assert acervo.ticker_negociavel("PETR4XY") is False
    assert acervo.ticker_negociavel("") is False
    assert acervo.ticker_negociavel(None) is False


def test_classe_de_ativo_nao_chuta_o_que_nao_sabe():
    """ETF da B3 tanto pode ser bolsa local quanto S&P 500 (IVVB11). Sem o dado, NULL.

    `posicoes_carteira` já trata classe ausente com `coalesce`; inventar 'acoes_br' para IVVB11
    faria o Raio-X medir concentração em Brasil onde há exposição internacional.
    """
    assert acervo.classe_de_ativo("acao") == "acoes_br"
    assert acervo.classe_de_ativo("fii") == "fii"
    assert acervo.classe_de_ativo("bdr") == "acoes_int"
    assert acervo.classe_de_ativo("fundo") is None
    assert acervo.classe_de_ativo("etf") is None
    assert acervo.classe_de_ativo("outro") is None


# ---------------------------------------------------------------- cobertura no prompt
async def test_cobertura_mercado_nao_cresce_com_o_universo(db):
    """O texto vai para o prompt do Analista em TODA chamada ao modelo, duas por turno.

    Antes da F22 ele era uma linha por instrumento do universo — irrelevante com 5 ativos,
    ~7.500 tokens com os 4.100 papéis do acervo, e isso multiplicado por cada chamada, para sempre.
    O que o agente precisa saber é o TAMANHO e a FAIXA da cobertura; se um papel específico está
    coberto é pergunta para `dados.resolver_instrumento`, que já existe e não custa prompt.
    """
    from app.tools import context_pack

    async with db.service_session() as conn:
        texto = await context_pack.cobertura_mercado(conn)

    linhas = [l for l in texto.splitlines() if l.strip()]
    assert len(linhas) <= 12, f"cobertura voltou a listar papel a papel ({len(linhas)} linhas)"
    assert len(texto) < 1200, f"cobertura com {len(texto)} caracteres — teto de prompt estourado"
    assert "resolver_instrumento" in texto, "o agente precisa saber como checar um papel específico"


def test_raiz_b3_do_ticker_usa_os_quatro_caracteres_do_contrato():
    assert acervo.raiz_b3_do_ticker("PETR4") == "PETR"
    assert acervo.raiz_b3_do_ticker("B3SA3") == "B3SA"
    assert acervo.raiz_b3_do_ticker("G2DI33") == "G2DI"
    assert acervo.raiz_b3_do_ticker("MRSA3B") == "MRSA"
    assert acervo.raiz_b3_do_ticker("PETR") is None


def test_acoes_correntes_por_raiz_exclui_ticker_historico():
    from datetime import date

    ano, por_raiz = acervo.acoes_correntes_por_raiz([
        ("PETR3", "acao", date(2026, 9, 30)),
        ("PETR4", "acao", date(2026, 9, 30)),
        ("BIDI11", "acao", date(2021, 12, 31)),
        ("BOVA11", "etf", date(2026, 9, 30)),
    ])
    assert ano == 2026
    assert por_raiz == {"PETR": ["PETR3", "PETR4"]}
