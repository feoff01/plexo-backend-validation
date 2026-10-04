"""Tool da família `planejamento` — composição do patrimônio do cliente.

Por que existe: o `context_pack` entrega ao prompt exatamente dois números de patrimônio
(investível e líquido). A CARTEIRA — quanto está em cada classe de ativo — não chega ao agente por
caminho nenhum: nenhuma tool lia `wealth.holdings_snapshots`. Encher o banco sem isto deixaria o
agente cego para o que o cliente cadastrou. A composição vira tool em vez de virar seção de prompt
por três motivos: o LLM continua sem calcular, o número fica auditável em `tool_executions`, e a
tela ganha o gráfico de graça (`blocos.py`).

Família `planejamento` — é insumo de planejamento, e é uma das três que o Assessor pode invocar
(`sql/17_agents.sql:270`); uma família `patrimonio` custaria migration e `ALTER TYPE`.

`emite_numero=False` de propósito: isto é DESCRIÇÃO do que está registrado no escopo, não
simulação. O rodapé "Simulação ilustrativa… não é projeção de rentabilidade" seria falso aqui —
não há projeção nenhuma. Quem projeta é `planejamento.projecao_objetivo`, e essa emite o rodapé.

v1 é descritiva: soma, ordena e mostra participação. NÃO julga concentração nem aponta classe
adequada — limiar seria premissa numérica e exigiria policy própria (`PATRIMONIO_REFERENCIAS`).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.hashing import arred2
from app.tools.registry import tool

FONTE = "wealth.holdings_snapshots"
CLASSE_SEM_CLASSIFICACAO = "outros"
ROTULO_SEM_CLASSIFICACAO = "Sem classificação"
GRUPO_SEM_CLASSIFICACAO = "alternativos"
NOTA = ("Composição declarada pelo cliente e registrada no escopo, na data de referência indicada. "
        "É descrição do que está registrado, não avaliação de adequação nem indicação de investimento.")


class ComposicaoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incluir_nao_financeiro: bool = Field(
        default=True,
        description="Somar imóveis, veículos e demais bens não financeiros ao quadro, além da carteira investida.")


class PosicaoPorClasse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classe: str
    rotulo: str                           # market.asset_classes.display_name — vocabulário do banco
    grupo: str                            # renda_fixa | renda_variavel | alternativos | caixa
    valor_brl: float


class ComposicaoResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of_date: str
    posicoes: list[PosicaoPorClasse]
    total_investido_brl: float
    contas: int
    incluir_nao_financeiro: bool
    nao_financeiro_brl: float
    imoveis_brl: float
    iliquido_brl: float
    passivo_brl: float
    patrimonio_liquido_brl: float


class ClasseComposicao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classe: str
    rotulo: str
    grupo: str
    valor_brl: float
    share_pct: float


class GrupoComposicao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grupo: str
    valor_brl: float
    share_pct: float


class ComposicaoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: str
    total_investido_brl: float
    composicao: list[ClasseComposicao]
    por_grupo: list[GrupoComposicao]
    classes: int
    contas: int
    maior_classe: str | None
    maior_classe_share_pct: float | None
    nao_financeiro_brl: float
    imoveis_brl: float
    # Explícito de propósito: sem este campo o modelo subtrai imóveis do total para chegar nele —
    # e o LLM não calcula (visto no smoke de 2026-08-26, ele derivou os R$ 95.000 do carro).
    outros_bens_brl: float
    iliquido_brl: float
    passivo_brl: float
    patrimonio_liquido_brl: float
    fonte: str
    avisos: list[str]
    nota: str


async def preparar_composicao(params: ComposicaoParams, ctx: ToolContext) -> ComposicaoResolvida:
    """Lê a carteira mais recente do escopo por classe de ativo e o consolidado não financeiro.

    `v_latest_holdings` e `v_net_worth` são `security_invoker`: sob `plexo_app` a RLS do escopo
    vale, e posição de outro escopo simplesmente não aparece."""
    # O rótulo e o grupo vêm de `market.asset_classes` — o vocabulário já é do banco, não se
    # duplica aqui nem no frontend. `group_name` dá a leitura renda fixa × variável de graça.
    cur = await ctx.conn.execute(
        "select coalesce(i.asset_class_code, %s) as classe, "
        "       coalesce(ac.display_name, %s) as rotulo, coalesce(ac.group_name, %s) as grupo, "
        "       sum(h.value_brl)::float as valor, max(h.as_of_date)::text as as_of "
        "  from wealth.v_latest_holdings h "
        "  left join market.instruments i on i.id = h.instrument_id "
        "  left join market.asset_classes ac on ac.code = coalesce(i.asset_class_code, %s) "
        " where h.scope_id = %s "
        " group by 1, 2, 3 order by 4 desc, 1",
        (CLASSE_SEM_CLASSIFICACAO, ROTULO_SEM_CLASSIFICACAO, GRUPO_SEM_CLASSIFICACAO,
         CLASSE_SEM_CLASSIFICACAO, ctx.scope_id))
    linhas = await cur.fetchall()
    ctx.registrar_insumo("wealth.v_latest_holdings", classes=len(linhas))

    if not linhas:
        raise ToolInsumoFaltante(
            "carteira desconhecida: não há posição registrada no escopo — pergunte ao cliente onde o "
            "dinheiro está investido, ou peça a importação do extrato, antes de falar da composição")

    posicoes = [PosicaoPorClasse(classe=classe, rotulo=rotulo, grupo=grupo, valor_brl=arred2(valor))
                for classe, rotulo, grupo, valor, _ in linhas]
    as_of = max(as_of_da_classe for _, _, _, _, as_of_da_classe in linhas)

    # DISTINCT por escopo, não por classe: o mesmo ativo pode estar em duas contas e a mesma conta
    # aparece em várias classes — `max(count por classe)` daria um número menor que o real.
    cur = await ctx.conn.execute(
        "select count(distinct account_id) from wealth.v_latest_holdings where scope_id = %s", (ctx.scope_id,))
    contas = (await cur.fetchone())[0]

    cur = await ctx.conn.execute(
        "select nao_financeiro_brl::float, imoveis_brl::float, iliquido_brl::float, "
        "       passivo_brl::float, patrimonio_liquido_brl::float "
        "  from estate.v_net_worth where scope_id = %s", (ctx.scope_id,))
    consolidado = await cur.fetchone()
    ctx.registrar_insumo("estate.v_net_worth", presente=consolidado is not None)
    nao_fin, imoveis, iliquido, passivo, liquido = consolidado or (0, 0, 0, 0, 0)

    return ComposicaoResolvida(
        as_of_date=as_of, posicoes=posicoes,
        total_investido_brl=arred2(sum(p.valor_brl for p in posicoes)),
        contas=contas, incluir_nao_financeiro=params.incluir_nao_financeiro,
        nao_financeiro_brl=arred2(nao_fin), imoveis_brl=arred2(imoveis),
        iliquido_brl=arred2(iliquido), passivo_brl=arred2(passivo),
        patrimonio_liquido_brl=arred2(liquido),
    )


@tool(code="planejamento.composicao_patrimonio", family="planejamento", semver="1.2.0",
      display_name="Composição do patrimônio",
      description=("Como o patrimônio do cliente está distribuído HOJE: quanto há em cada classe de ativo "
                   "(caixa, selic, ipca, ações, FII, multimercado…), participação de cada uma, em quantas "
                   "contas, mais o consolidado com imóveis, bens e passivo. Descreve o que está registrado "
                   "no escopo; não avalia adequação nem sugere mudança de carteira."),
      emite_numero=False, preparar=preparar_composicao)
def calcular_composicao(r: ComposicaoResolvida) -> ComposicaoOutput:
    total = r.total_investido_brl

    def participacao(valor: float) -> float:
        return arred2(valor / total * 100) if total > 0 else 0.0

    itens = [ClasseComposicao(classe=p.classe, rotulo=p.rotulo, grupo=p.grupo,
                              valor_brl=p.valor_brl, share_pct=participacao(p.valor_brl))
             for p in r.posicoes]
    itens.sort(key=lambda c: (-c.valor_brl, c.classe))
    maior = itens[0] if itens else None

    por_grupo_brl: dict[str, float] = {}
    for p in r.posicoes:
        por_grupo_brl[p.grupo] = arred2(por_grupo_brl.get(p.grupo, 0.0) + p.valor_brl)
    grupos = [GrupoComposicao(grupo=g, valor_brl=v, share_pct=participacao(v))
              for g, v in por_grupo_brl.items()]
    grupos.sort(key=lambda g: (-g.valor_brl, g.grupo))

    avisos: list[str] = []
    if any(c.classe == CLASSE_SEM_CLASSIFICACAO for c in itens):
        avisos.append("posicoes_sem_classe_de_ativo")
    # O consolidado é tudo-ou-nada. Zerar os bens e manter o patrimônio líquido cheio produziria
    # "líquido R$ 1.521.500 · bens não financeiros R$ 0", que o agente leria como carteira de 1,5 mi.
    if r.incluir_nao_financeiro:
        nao_fin, imoveis = r.nao_financeiro_brl, r.imoveis_brl
        outros, iliquido = arred2(r.nao_financeiro_brl - r.imoveis_brl), r.iliquido_brl
        passivo, liquido = r.passivo_brl, r.patrimonio_liquido_brl
        if nao_fin == 0:
            avisos.append("sem_bem_nao_financeiro_registrado")
        if passivo > 0:
            avisos.append("ha_passivo_no_consolidado")
    else:
        nao_fin = imoveis = outros = iliquido = passivo = liquido = 0.0
        avisos.append("consolidado_omitido_a_pedido")

    return ComposicaoOutput(
        as_of=r.as_of_date, total_investido_brl=total, composicao=itens, por_grupo=grupos,
        classes=len(itens), contas=r.contas,
        maior_classe=maior.classe if maior else None,
        maior_classe_share_pct=maior.share_pct if maior else None,
        nao_financeiro_brl=nao_fin, imoveis_brl=imoveis, outros_bens_brl=outros,
        iliquido_brl=iliquido, passivo_brl=passivo, patrimonio_liquido_brl=liquido,
        fonte=FONTE, avisos=avisos, nota=NOTA,
    )
