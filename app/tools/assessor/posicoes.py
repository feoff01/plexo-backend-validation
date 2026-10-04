"""Tool da família `planejamento` — a carteira aberta POSIÇÃO A POSIÇÃO.

POR QUE EXISTE, E POR QUE NÃO BASTAVA A COMPOSIÇÃO
    `planejamento.composicao_patrimonio` agrega por CLASSE de ativo (`group by classe`). Com a
    carteira cheia, a resposta à pergunta "devo vender alguma das minhas ações?" seria
    "ações: R$ 319.046" — nunca "ITUB4: 2.400 ações, 12% da carteira, comprada a R$ 31,20".
    Perguntada sobre um ativo, a plataforma respondia sobre uma categoria.

    Esta tool é o detalhe. Ela é a primeira do sistema a cruzar a posição do cliente
    (`wealth.holdings_snapshots`) com o preço de mercado (`market.prices`) e com o custo do
    produto (`market.fund_facts`) — até aqui os dois lados nunca se encontraram: as tools de
    mercado são do Analista e não veem o cliente, e as do Assessor viam o cliente e não o
    mercado.

A FRONTEIRA COM O ANALISTA (T18), QUE NÃO SE ATRAVESSA AQUI
    O Assessor não roda `quant`/`dados`, e isso continua valendo. O que esta tool devolve
    sobre preço é o que qualquer nota de corretagem devolve: quanto o cliente pagou, quanto
    valia no último fechamento publicado, e a diferença entre os dois. É fato sobre a carteira
    DELE, não análise de mercado.

    Retorno anualizado, volatilidade, drawdown, correlação e comparação com benchmark
    continuam sendo `quant.*`/`dados.*`, do Analista. Pergunta que os exija vira `encaminhar`.

DUAS DATAS, E ELAS NUNCA SE MISTURAM
    `posicao_em` é a data do snapshot da carteira. `fechamento_em` é a data do último pregão
    ingerido. São diferentes por construção — a carteira é de hoje, o preço é D-1 por contrato
    do produto (COMMENT de `market.prices`). Fundi-las produziria "sua carteira vale X hoje",
    que é uma afirmação que a plataforma não pode fazer. Os dois campos saem separados, e o
    bloco na tela mostra os dois.

`emite_numero=False`: é DESCRIÇÃO do que está registrado mais o preço publicado, não
simulação. O rodapé "não é projeção de rentabilidade" seria falso — não há projeção nenhuma.

v1 descreve e ordena. NÃO julga concentração, não aponta posição a reduzir e não classifica
ativo como adequado ou inadequado: isso é o Raio-X (`diagnostics.findings`), que tem limiar
versionado em política, e não uma opinião embutida numa consulta.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.hashing import arred2
from app.tools.registry import tool

FONTE = "wealth.holdings_snapshots + market.prices"
CLASSE_SEM_CLASSIFICACAO = "outros"
ROTULO_SEM_CLASSIFICACAO = "Sem classificação"
GRUPO_SEM_CLASSIFICACAO = "alternativos"

# Só estes têm código negociado em bolsa. CDB, LCI, Tesouro, fundo e saldo em conta
# recebem código de catálogo interno, e exibi-lo como se fosse ticker inventaria um mercado
# que não existe — a tela mostra o nome nesses casos.
KINDS_COM_TICKER = ("acao", "etf", "fii", "bdr")

# COBERTURA DO FGC É DO INSTRUMENTO, NÃO DO EMISSOR — e a primeira versão desta tool errou
# nisso: lia `market.issuers.fgc_covered` sozinho e devolvia ITUB4 (uma AÇÃO do Itaú) como
# coberta pelo FGC. O erro não é cosmético: o teto de R$ 250 mil por instituição só conta o
# que é garantido, e somar a ação ao CDB inflaria a exposição coberta, fazendo o alerta
# disparar sobre um número que não existe.
#
# A regra é a do próprio FGC (Resolução CMN 4.222 e alterações): depósitos e letras emitidos
# por instituição associada. Ficam de fora CRI/CRA, debênture, COE, fundos, previdência e
# qualquer papel de renda variável — mesmo quando o emissor é um banco associado. Fica de
# fora também `conta`, que aqui é saldo em corretora, e não depósito bancário.
#
# É fato jurídico, não premissa de mercado: vive em código com a citação, como `KINDS_COM_TICKER`,
# e não em `engine.policy_versions`. O TETO em reais, esse sim, é parâmetro e vai para política.
KINDS_COBERTOS_PELO_FGC = ("cdb", "lci_lca", "poupanca")

NOTA = ("Posições registradas no escopo, avaliadas pelo último fechamento publicado na data "
        "indicada. Preço de fechamento é D-1, não cotação do momento. É descrição do que está "
        "registrado, não avaliação de adequação nem indicação de compra ou venda.")


class PosicoesParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apenas_classe: str | None = Field(
        default=None,
        description=("Filtrar por uma classe de ativo (`acoes_br`, `fii`, `selic`, `ipca`, "
                     "`multimercado`, `caixa`…). Sem isso, devolve a carteira inteira."))
    apenas_grupo: str | None = Field(
        default=None,
        description=("Filtrar por grupo: `renda_variavel`, `renda_fixa`, `caixa` ou "
                     "`alternativos`. Use para responder só sobre ações, por exemplo."))


class PosicaoResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str | None
    nome: str
    tipo: str
    classe: str
    rotulo_classe: str
    grupo: str
    emissor: str | None
    emissor_raiz: str | None
    coberto_pelo_fgc: bool
    conta: str
    quantidade: float | None
    preco_medio: float | None
    preco_fechamento: float | None
    fechamento_em: str | None
    valor_registrado_brl: float
    taxa_adm_aa: float | None
    liquidez_dias: int | None


class PosicoesResolvidas(BaseModel):
    model_config = ConfigDict(extra="forbid")
    posicao_em: str
    posicoes: list[PosicaoResolvida]
    total_da_carteira_brl: float          # antes de qualquer filtro — é o denominador do peso
    contas: int
    filtro_classe: str | None
    filtro_grupo: str | None


class PosicaoCarteira(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str | None                    # None quando não é papel negociado em bolsa
    nome: str
    tipo: str
    classe: str
    rotulo_classe: str
    grupo: str
    emissor: str | None
    coberto_pelo_fgc: bool
    conta: str
    quantidade: float | None
    preco_medio: float | None
    preco_fechamento: float | None
    valor_registrado_brl: float
    valor_no_fechamento_brl: float | None
    variacao_sobre_preco_medio_pct: float | None
    share_pct: float
    taxa_adm_aa: float | None
    liquidez_dias: int | None


class GrupoCarteira(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grupo: str
    valor_brl: float
    share_pct: float
    posicoes: int


class PosicoesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    posicao_em: str
    fechamento_em: str | None
    posicoes: list[PosicaoCarteira]
    por_grupo: list[GrupoCarteira]
    total_da_carteira_brl: float
    total_listado_brl: float
    itens: int
    contas: int
    filtro_classe: str | None
    filtro_grupo: str | None
    maior_posicao: str | None
    maior_posicao_share_pct: float | None
    sem_preco: list[str]
    fonte: str
    avisos: list[str]
    nota: str


async def preparar_posicoes(params: PosicoesParams, ctx: ToolContext) -> PosicoesResolvidas:
    """Lê a carteira mais recente do escopo, item a item, com emissor, custo e último preço.

    `v_latest_holdings` é `security_invoker`: sob `plexo_app` a RLS do escopo vale, e posição
    de outro escopo simplesmente não aparece.

    O último fechamento vem por `distinct on (instrument_id)` sobre `market.prices`, que tem
    índice `(instrument_id, price_date DESC)`. Instrumento sem preço ingerido devolve NULL e
    entra em `sem_preco` — a ausência se DECLARA; estimar preço aqui seria inventar mercado.
    """
    cur = await ctx.conn.execute(
        "with ultimo_preco as ("
        "  select distinct on (p.instrument_id) p.instrument_id, p.value::float as preco, "
        "         p.price_date::text as em "
        "    from market.prices p"
        "   where p.instrument_id in (select instrument_id from wealth.v_latest_holdings"
        "                              where scope_id = %s)"
        "   order by p.instrument_id, p.price_date desc)"
        "select case when i.kind::text = any(%s) then i.ticker end as codigo, "
        "       coalesce(i.name, 'Posição sem cadastro') as nome, "
        "       coalesce(i.kind::text, 'outro') as tipo, "
        "       coalesce(i.asset_class_code, %s) as classe, "
        "       coalesce(ac.display_name, %s) as rotulo_classe, "
        "       coalesce(ac.group_name, %s) as grupo, "
        "       iss.name as emissor, raiz.name as emissor_raiz, "
        # As DUAS condições: emissor associado ao fundo garantidor E instrumento do tipo
        # coberto. Faltando qualquer uma, não há garantia.
        "       (coalesce(raiz.fgc_covered, iss.fgc_covered, false) "
        "        and i.kind::text = any(%s)) as fgc, "
        "       coalesce(ct.label, 'Conta não identificada') as conta, "
        "       h.quantity::float, h.avg_cost::float, up.preco, up.em, "
        "       h.value_brl::float, ff.management_fee::float, i.liquidity_days, "
        "       h.as_of_date::text "
        "  from wealth.v_latest_holdings h "
        "  left join market.instruments i on i.id = h.instrument_id "
        "  left join market.asset_classes ac on ac.code = coalesce(i.asset_class_code, %s) "
        "  left join market.issuers iss on iss.id = i.issuer_id "
        "  left join market.issuers raiz on raiz.id = coalesce(iss.parent_issuer_id, iss.id) "
        "  left join market.fund_facts ff on ff.instrument_id = i.id "
        "  left join wealth.accounts ct on ct.id = h.account_id "
        "  left join ultimo_preco up on up.instrument_id = h.instrument_id "
        " where h.scope_id = %s "
        " order by h.value_brl desc, coalesce(i.name, '')",
        (ctx.scope_id, list(KINDS_COM_TICKER), CLASSE_SEM_CLASSIFICACAO, ROTULO_SEM_CLASSIFICACAO,
         GRUPO_SEM_CLASSIFICACAO, list(KINDS_COBERTOS_PELO_FGC), CLASSE_SEM_CLASSIFICACAO,
         ctx.scope_id))
    linhas = await cur.fetchall()
    ctx.registrar_insumo("wealth.v_latest_holdings", posicoes=len(linhas))

    if not linhas:
        raise ToolInsumoFaltante(
            "carteira desconhecida: não há posição registrada no escopo — pergunte ao cliente onde o "
            "dinheiro está investido, ou peça a importação do extrato, antes de falar das posições")

    # O denominador do peso é a carteira INTEIRA, mesmo quando o cliente pede só as ações:
    # "PETR4 é 9% da sua carteira" e "PETR4 é 23% das suas ações" são frases diferentes, e a
    # que interessa para risco é a primeira. O filtro escolhe o que MOSTRAR, nunca o total.
    total_carteira = arred2(sum(l[14] for l in linhas))
    posicao_em = max(l[17] for l in linhas)

    resolvidas = [
        PosicaoResolvida(
            codigo=l[0], nome=l[1], tipo=l[2], classe=l[3], rotulo_classe=l[4], grupo=l[5],
            emissor=l[7] or l[6], emissor_raiz=l[7], coberto_pelo_fgc=l[8], conta=l[9],
            quantidade=l[10], preco_medio=l[11], preco_fechamento=l[12], fechamento_em=l[13],
            valor_registrado_brl=arred2(l[14]), taxa_adm_aa=l[15], liquidez_dias=l[16])
        for l in linhas
        if (params.apenas_classe is None or l[3] == params.apenas_classe)
        and (params.apenas_grupo is None or l[5] == params.apenas_grupo)
    ]
    if not resolvidas:
        alvo = params.apenas_classe or params.apenas_grupo
        raise ToolInsumoFaltante(
            f"a carteira registrada não tem nenhuma posição em '{alvo}' — as classes presentes "
            f"são: {', '.join(sorted({l[3] for l in linhas}))}")

    cur = await ctx.conn.execute(
        "select count(distinct account_id) from wealth.v_latest_holdings where scope_id = %s",
        (ctx.scope_id,))
    contas = (await cur.fetchone())[0]

    return PosicoesResolvidas(
        posicao_em=posicao_em, posicoes=resolvidas, total_da_carteira_brl=total_carteira,
        contas=contas, filtro_classe=params.apenas_classe, filtro_grupo=params.apenas_grupo)


# 1.0.1: cobertura do FGC passou a exigir o TIPO do instrumento, não só o emissor — ITUB4
# voltava como coberta pelo FGC no primeiro smoke real.
@tool(code="planejamento.posicoes_carteira", family="planejamento", semver="1.0.1",
      display_name="Posições da carteira, uma a uma",
      description=("Abre a carteira do cliente POSIÇÃO A POSIÇÃO: cada ativo com nome, código, "
                   "quantidade, preço médio pago, último preço de fechamento publicado, valor, "
                   "peso na carteira, emissor (consolidado por conglomerado), cobertura do FGC, "
                   "taxa de administração e prazo de liquidez. Aceita filtro por classe ou por "
                   "grupo para responder só sobre ações, por exemplo. Use quando o cliente "
                   "perguntar sobre um ativo específico, sobre 'minhas ações' ou quiser ver onde "
                   "o dinheiro está. Para a visão agregada por classe, use a composição do "
                   "patrimônio; para retorno, volatilidade ou comparação com índice, o assunto "
                   "é do Analista."),
      emite_numero=False, preparar=preparar_posicoes)
def calcular_posicoes(r: PosicoesResolvidas) -> PosicoesOutput:
    total = r.total_da_carteira_brl

    def participacao(valor: float) -> float:
        return arred2(valor / total * 100) if total > 0 else 0.0

    itens: list[PosicaoCarteira] = []
    sem_preco: list[str] = []
    for p in r.posicoes:
        # Reavaliação só existe com os DOIS lados: quantidade e preço. Uma posição declarada
        # em reais (CDB, LCI, saldo) não tem "valor no fechamento" — e devolver o próprio
        # valor registrado nesse campo faria a tela dizer que o CDB foi reavaliado hoje.
        no_fechamento = (arred2(p.quantidade * p.preco_fechamento)
                         if p.quantidade is not None and p.preco_fechamento is not None else None)
        variacao = (arred2((p.preco_fechamento / p.preco_medio - 1) * 100)
                    if p.preco_fechamento is not None and p.preco_medio else None)
        if p.quantidade is not None and p.preco_fechamento is None:
            sem_preco.append(p.codigo or p.nome)
        itens.append(PosicaoCarteira(
            codigo=p.codigo, nome=p.nome, tipo=p.tipo, classe=p.classe,
            rotulo_classe=p.rotulo_classe, grupo=p.grupo, emissor=p.emissor,
            coberto_pelo_fgc=p.coberto_pelo_fgc, conta=p.conta, quantidade=p.quantidade,
            preco_medio=p.preco_medio, preco_fechamento=p.preco_fechamento,
            valor_registrado_brl=p.valor_registrado_brl, valor_no_fechamento_brl=no_fechamento,
            variacao_sobre_preco_medio_pct=variacao, share_pct=participacao(p.valor_registrado_brl),
            taxa_adm_aa=p.taxa_adm_aa, liquidez_dias=p.liquidez_dias))

    itens.sort(key=lambda c: (-c.valor_registrado_brl, c.nome))

    por_grupo_brl: dict[str, float] = {}
    por_grupo_n: dict[str, int] = {}
    for p in r.posicoes:
        por_grupo_brl[p.grupo] = arred2(por_grupo_brl.get(p.grupo, 0.0) + p.valor_registrado_brl)
        por_grupo_n[p.grupo] = por_grupo_n.get(p.grupo, 0) + 1
    grupos = [GrupoCarteira(grupo=g, valor_brl=v, share_pct=participacao(v), posicoes=por_grupo_n[g])
              for g, v in por_grupo_brl.items()]
    grupos.sort(key=lambda g: (-g.valor_brl, g.grupo))

    # A data do preço é a MAIS ANTIGA entre as posições precificadas, não a mais recente:
    # dizer "fechamento de 27/08" quando metade da carteira só tem preço de 12/08 seria
    # datar a carteira pela sua parte mais fresca.
    datas = [p.fechamento_em for p in r.posicoes if p.fechamento_em]
    fechamento_em = min(datas) if datas else None

    listado = arred2(sum(i.valor_registrado_brl for i in itens))
    maior = itens[0] if itens else None

    avisos: list[str] = []
    if sem_preco:
        avisos.append("posicoes_sem_preco_ingerido")
    if any(i.classe == CLASSE_SEM_CLASSIFICACAO for i in itens):
        avisos.append("posicoes_sem_classe_de_ativo")
    if any(i.emissor is None for i in itens):
        avisos.append("posicoes_sem_emissor_cadastrado")
    if datas and len(set(datas)) > 1:
        avisos.append("precos_de_datas_diferentes")
    if r.filtro_classe or r.filtro_grupo:
        avisos.append("recorte_da_carteira")

    return PosicoesOutput(
        posicao_em=r.posicao_em, fechamento_em=fechamento_em, posicoes=itens, por_grupo=grupos,
        total_da_carteira_brl=total, total_listado_brl=listado, itens=len(itens), contas=r.contas,
        filtro_classe=r.filtro_classe, filtro_grupo=r.filtro_grupo,
        maior_posicao=(maior.codigo or maior.nome) if maior else None,
        maior_posicao_share_pct=maior.share_pct if maior else None,
        sem_preco=sem_preco, fonte=FONTE, avisos=avisos, nota=NOTA)
