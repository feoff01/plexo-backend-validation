"""Uma conta de teste COMPLETA, em plano pago, para exercitar o produto pela tela.

POR QUE ELA NÃO É UMA PERSONA DO GOLDEN
    As seis personas de `personas.py` existem para CONGELAR um diagnóstico: cada uma força
    um comportamento do motor e o golden protege o que o produto diz sobre ela. Esta conta
    existe para o oposto — para alguém entrar nela e mexer: mudar a renda pela conversa
    (F14), confirmar proposta, refazer projeção. Se ela fosse um arquétipo do golden, o
    primeiro teste manual quebraria a suíte, e a resposta seria "regrave o golden", que é
    como um golden morre.

    Por isso ela vive fora de `ARQUETIPOS` e reusa o MESMO inseridor. Nada aqui é código
    novo de escrita: é um `Arquetipo` a mais, com plano e senha.

O QUE ELA TEM QUE AS PERSONAS NÃO TÊM
    · **plano pago de verdade** (`billing.subscriptions`), sem o qual `plano_do_escopo`
      devolve 'free' e as tools com `min_plan='essential'` — inclusive
      `planejamento.simulacao_objetivo` — nunca chegam ao modelo;
    · **dois objetivos ativos**, que é o que exercita a regra da F17 "a MENOR probabilidade
      entre os objetivos ativos" — nenhuma persona tinha mais de um;
    · **os fatos que nenhuma persona declara**: idade-alvo de aposentadoria, aporte mensal e
      os dois de comportamento. Sem eles, Destino e Comportamento saem sem nota em TODAS as
      personas, e metade do diagnóstico fica invisível para quem está testando.

    O resultado é a única conta do repositório em que as cinco famílias saem com número — o
    que é justamente o que se quer ver antes de mostrar o produto a alguém.

PLANO: `advanced`, NÃO `wealth`
    `wealth` é `is_purchasable = false` e `requires_cvm_authorization = true` na migration 03:
    é a camada consultiva humana, bloqueada até a autorização da CVM. Criar conta de teste
    nele seria simular um produto que a Plexo não pode vender. `advanced` é o teto legítimo
    hoje — Copiloto ilimitado, objetivos ilimitados, Family Office.

DADOS FICTÍCIOS
    Pessoa inventada, e-mail `@teste.local` (domínio reservado, não roteável). Nenhum dado
    aqui vem de pessoa real.
"""
from __future__ import annotations

from datetime import date

from psycopg import AsyncConnection

from app.seeds.personas import Arquetipo, Divida, Emissor, Posicao, aplicar

# ---------------------------------------------------------------------------------
# A CARTEIRA — e por que estes números, e não outros
#
# Até 2026-08-30 a Helena tinha R$ 780.000 como UM número (`investido`), e mais nada. A
# pergunta "devo vender alguma das minhas ações?" batia na tool de composição, que lê
# `wealth.holdings_snapshots`, achava zero linhas e respondia "não há posição registrada no
# escopo" — enquanto o prompt do agente, no mesmo turno, recebia "investível R$ 780.000"
# vindo do rollup. A conta de demonstração não demonstrava a carteira.
#
# Cada linha abaixo existe para que uma anomalia REAL apareça no Raio-X. Uma carteira
# plausível mas sem defeito nenhum é uma conta de teste que não testa nada:
#
#   · Itaú aparece TRÊS vezes — ação, CDB e LCI da financeira do grupo. Consolidado por
#     `parent_issuer_id`, é ~47% da carteira num único risco de crédito, e os R$ 270.000
#     de CDB + LCI passam do teto de R$ 250.000 do FGC. É o cartão "exposição bancária
#     acima do limite" e o cartão "concentração", que são coisas diferentes;
#   · a LCI é D+90: parcela relevante presa em resgate longo;
#   · o fundo macro cobra 2,3% a.a., acima da referência da classe;
#   · há saldo parado na corretora com a reserva JÁ coberta (R$ 95.000 em conta à parte,
#     que não se toca — é dela que `protecao.reserva_atual` nasce);
#   · não há um centavo em ações internacionais.
#
# As cinco posições de bolsa usam quantidade inteira e são avaliadas pelo ÚLTIMO
# FECHAMENTO ingerido (`market.prices`), com `preco_referencia` de fallback para banco sem
# ingestão. Por isso o total flutua com o mercado, e é assim que tem de ser: o número que
# não se move é que seria mentira. O preço médio mistura ganho e perda de propósito —
# uma carteira em que tudo subiu não faz ninguém perguntar se deve vender.
# ---------------------------------------------------------------------------------
EMISSORES = (
    Emissor("itau", "Itaú Unibanco", "banco", fgc_covered=True),
    # A financeira do grupo: mesmo risco de crédito, mesmo teto de FGC, CNPJ diferente.
    # É este par que faz `v_issuer_concentration` valer a pena.
    Emissor("itau_financeira", "Itaú Financeira", "banco", fgc_covered=True, matriz="itau"),
    Emissor("petrobras", "Petróleo Brasileiro S.A.", "empresa"),
    Emissor("vale", "Vale S.A.", "empresa"),
    Emissor("weg", "WEG S.A.", "empresa"),
    Emissor("tesouro_nacional", "Tesouro Nacional", "governo"),
    Emissor("gestora_indice", "Gestora de índices", "gestora"),
    Emissor("gestora_fii", "Gestora imobiliária", "gestora"),
    Emissor("gestora_macro", "Gestora macro", "gestora"),
)

CARTEIRA = (
    Posicao("ITUB4", "Itaú Unibanco PN", "acao", "acoes_br", emissor="itau",
            quantidade=2400, preco_referencia=39.10, preco_medio=31.20,
            liquidez_dias=2, negociado_em_bolsa=True),
    Posicao("PETR4", "Petrobras PN", "acao", "acoes_br", emissor="petrobras",
            quantidade=1700, preco_referencia=42.70, preco_medio=46.80,
            liquidez_dias=2, negociado_em_bolsa=True),
    Posicao("VALE3", "Vale ON", "acao", "acoes_br", emissor="vale",
            quantidade=700, preco_referencia=79.11, preco_medio=68.40,
            liquidez_dias=2, negociado_em_bolsa=True),
    Posicao("WEGE3", "WEG ON", "acao", "acoes_br", emissor="weg",
            quantidade=700, preco_referencia=50.25, preco_medio=54.10,
            liquidez_dias=2, negociado_em_bolsa=True),
    Posicao("BOVA11", "iShares Ibovespa (ETF)", "etf", "acoes_br", emissor="gestora_indice",
            quantidade=360, preco_referencia=172.40, preco_medio=149.80,
            liquidez_dias=2, negociado_em_bolsa=True),
    Posicao("HGLG11", "FII de logística", "fii", "fii", emissor="gestora_fii",
            quantidade=300, preco_referencia=160.00, preco_medio=168.00,
            liquidez_dias=2, negociado_em_bolsa=True),
    # Daqui para baixo não há ticker de bolsa: o código é do catálogo interno.
    Posicao("CDBITAU108", "CDB Itaú 108% do CDI", "cdb", "selic", emissor="itau",
            valor_brl=180000.0, liquidez_dias=0),
    Posicao("LCIITAU95", "LCI Itaú Financeira 95% do CDI", "lci_lca", "selic",
            emissor="itau_financeira", valor_brl=90000.0, liquidez_dias=90),
    Posicao("TESIPCA2035", "Tesouro IPCA+ 2035", "tesouro", "ipca",
            emissor="tesouro_nacional", valor_brl=90000.0, liquidez_dias=1,
            maturidade=date(2035, 5, 15)),
    # 2,8% a.a. contra a referência de 2,0% de `PRODUTO_REFERENCIAS`. A primeira versão usava
    # 2,3%, que cai dentro da folga de 0,5 p.p. do limiar — e uma conta de demonstração cujo
    # fundo caro não dispara o alerta de fundo caro não demonstra nada. A folga existe para
    # não alertar por diferença de arredondamento, e ela fica; quem muda é o exemplo.
    Posicao("FUNDOMACRO01", "Fundo multimercado macro", "fundo", "multimercado",
            emissor="gestora_macro", valor_brl=30000.0, liquidez_dias=30, taxa_adm_aa=0.028),
    Posicao("SALDOCORRETORA", "Saldo em conta na corretora", "conta", "caixa",
            valor_brl=18000.0, liquidez_dias=0),
)

# ---------------------------------------------------------------------------------
# Helena Ferraz Antunes, 41 anos — cliente "bem conhecida": quase todo o catálogo
# preenchido, Fundação verde, e um objetivo folgado ao lado de um apertado.
#
# Os números foram escolhidos para que o diagnóstico saia INTEIRO e o veredito de risco
# tenha o que dizer:
#   · reserva de 8,3 meses de despesa essencial  → Fundação VERDE (mínimo é 3, alvo 6)
#   · dívida mais cara a 17,9% a.a.              → abaixo de CDI + 6 p.p., então não é "cara"
#   · faculdade em 10 anos, folgada              → o conservador basta
#   · aposentadoria de R$ 7,5 mi em 24 anos      → o conservador NÃO basta; é o caso em que
#                                                  a regra do §4 tem algo a dizer
# ---------------------------------------------------------------------------------
HELENA = Arquetipo(
    nome="helena_completa",
    titulo="Helena Ferraz Antunes",
    forca="conta de demonstração: catálogo quase inteiro, plano pago, dois objetivos ativos",
    idade=41,
    plano="advanced",

    # --- fluxo: CLT sênior com bônus variável
    renda_fixa=24000.0,
    renda_variavel=6000.0,
    renda_p10=2000.0,          # o piso observado do bônus: é ele que julga sustentabilidade
    fontes_de_renda=2,
    despesa_total=16800.0,
    despesa_essencial=11500.0,
    fixo_contratado=9200.0,

    # --- proteção
    reserva=95000.0,           # 8,3 meses de essencial
    dependentes=2,
    seguro_vida=400000.0,      # informado, e abaixo da necessidade: a lacuna aparece

    # --- estoque. `investido` fica como referência histórica do que o agregado dizia; com
    # `carteira` preenchida quem manda é a soma das posições (migration 53).
    investido=780000.0,
    emissores=EMISSORES,
    carteira=CARTEIRA,
    imoveis=1250000.0,
    dividas=(
        Divida("financiamento_imovel", "Financiamento do apartamento",
               420000.0, 0.095, 4300.0),
        Divida("financiamento_veiculo", "Financiamento do carro",
               38000.0, 0.179, 1450.0),
    ),

    # --- destino: dois objetivos, e a probabilidade do escopo é a MENOR entre eles
    objetivos=(
        ("Faculdade da Manuela", 600000.0, 120),
        ("Aposentadoria aos 65", 7500000.0, 288),
    ),

    # --- o que nenhuma persona declara, e sem o que duas famílias ficam mudas
    fatos_declarados=(
        ("destino.idade_aposentadoria", 65),
        ("fluxo.aporte_mensal", 9000.0),
        ("comportamento.aporte_regular", True),
        # `manteve` = 0,5 na escala do motor: nem vendeu na queda, nem aportou mais
        ("comportamento.reacao_queda", "manteve"),
        ("vida.estado_civil", "casado"),
        ("renda.tipo_vinculo", "clt"),
    ),
)

EMAIL = HELENA.email


async def criar(conn: AsyncConnection) -> dict[str, str]:
    """Cria (ou atualiza) a conta. Idempotente pelo mesmo uuid5 das personas."""
    return await aplicar(conn, HELENA)
