"""Tools da família `produto` — decomposição de custo e comparação de alternativas.

Fronteira RCVM: comparação e referência, nunca escolha. Não existe campo "melhor" nem ranking.
Veto do cliente (preferences, C26) marca incompatibilidade visível — a alternativa não some,
ela aparece marcada. Referências de custo por classe vêm de PRODUTO_REFERENCIAS (policy).
Custo estimado por aproximação LINEAR declarada (taxa × valor × anos, sem rendimento) — o
cálculo com rendimento composto é do motor.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.hashing import arred2
from app.tools.registry import tool

METODO = "aproximacao_linear_sem_rendimento"


async def _classes_vetadas(ctx: ToolContext) -> list[str]:
    cur = await ctx.conn.execute(
        "select distinct asset_class_code from preferences.v_active_constraints "
        "where scope_id = %s and enforcement = 'bloqueante' and asset_class_code is not null",
        (ctx.scope_id,))
    vetadas = [r[0] for r in await cur.fetchall()]
    ctx.registrar_insumo("preferences.v_active_constraints", classes_vetadas=vetadas)
    return vetadas


# =============================================================================
# produto.custo_fundo
# =============================================================================
class CustoFundoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identificador: str | None = Field(default=None, description="Ticker ou CNPJ do fundo, para buscar taxas no catálogo.")
    descricao: str | None = Field(default=None, description="Nome do produto como o cliente o chamou.")
    taxa_adm_aa: float | None = Field(default=None, ge=0, description="Taxa de administração ao ano (0.02 = 2%), se o cliente informar.")
    come_cotas: bool | None = Field(default=None, description="O produto sofre come-cotas?")
    classe: str | None = Field(default=None, description="Classe do produto (ex.: renda_fixa, multimercado, acoes) para comparação com a referência.")
    valor_aplicado_brl: float = Field(gt=0, description="Valor aplicado ou a aplicar.")
    horizonte_anos: float = Field(gt=0, description="Horizonte de permanência, em anos.")
    indicado_por_terceiro: bool = Field(default=False, description="True quando o produto foi indicado por assessor/gerente/terceiro — habilita o registro de segunda opinião.")


class CustoFundoResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descricao: str
    fonte: str                       # fund_facts | parametros
    taxa_adm_aa: float
    come_cotas: bool | None
    classe: str | None
    valor_aplicado_brl: float
    horizonte_anos: float
    referencia_classe_aa: float | None
    indicado_por_terceiro: bool
    premissas: dict


class CustoFundoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descricao: str
    fonte: str
    taxa_adm_aa: float
    custo_adm_total_estimado_brl: float
    metodo: str
    referencia_classe_aa: float | None
    acima_da_referencia: bool | None
    come_cotas: bool | None
    classe: str | None
    indicado_por_terceiro: bool
    avisos: list[str]
    premissas_usadas: dict


async def preparar_custo_fundo(params: CustoFundoParams, ctx: ToolContext) -> CustoFundoResolvido:
    refs = await ctx.policy("PRODUTO_REFERENCIAS")
    taxa, come_cotas, classe, fonte = params.taxa_adm_aa, params.come_cotas, params.classe, "parametros"
    descricao = params.descricao or params.identificador or "produto"
    if params.identificador:
        cnpj = re.sub(r"\D", "", params.identificador)
        cur = await ctx.conn.execute(
            "select i.name, f.management_fee::float, f.admin_fee::float, f.come_cotas, i.asset_class_code "
            "from market.instruments i left join market.fund_facts f on f.instrument_id = i.id "
            "where i.ticker = %s or (i.cnpj_fundo is not null and i.cnpj_fundo = %s) limit 1",
            (params.identificador, cnpj))
        row = await cur.fetchone()
        ctx.registrar_insumo("market.fund_facts", identificador=params.identificador, encontrado=row is not None)
        if row is not None:
            nome, mgmt, adm, cc, ac = row
            taxa_catalogo = mgmt if mgmt is not None else adm
            if taxa_catalogo is not None:
                taxa, fonte = taxa_catalogo, "fund_facts"
                descricao = params.descricao or nome
                come_cotas = cc if come_cotas is None else come_cotas
                classe = classe or ac
    if taxa is None:
        raise ToolInsumoFaltante(
            f"taxa de administração de '{descricao}' desconhecida (não está no catálogo) — "
            "pergunte a taxa ao cliente (taxa_adm_aa) ou peça o ticker/CNPJ")
    return CustoFundoResolvido(
        descricao=descricao, fonte=fonte, taxa_adm_aa=float(taxa), come_cotas=come_cotas,
        classe=classe, valor_aplicado_brl=params.valor_aplicado_brl,
        horizonte_anos=params.horizonte_anos,
        referencia_classe_aa=(refs.get("referencia_taxa_adm_aa") or {}).get(classe) if classe else None,
        indicado_por_terceiro=params.indicado_por_terceiro,
        premissas={"PRODUTO_REFERENCIAS": refs},
    )


@tool(code="produto.custo_fundo", family="produto", semver="1.0.0",
      display_name="Custo de produto",
      description=("Decompõe o custo estimado de um fundo/produto no horizonte informado (taxa de "
                   "administração, come-cotas) e compara com a REFERÊNCIA de custo da classe — "
                   "diagnóstico de caro vs. barato, sem indicar compra ou venda. Busca taxas no "
                   "catálogo por ticker/CNPJ ou usa as informadas pelo cliente."),
      preparar=preparar_custo_fundo)
def calcular_custo_fundo(r: CustoFundoResolvido) -> CustoFundoOutput:
    custo = arred2(r.valor_aplicado_brl * r.taxa_adm_aa * r.horizonte_anos)
    acima = (r.taxa_adm_aa > r.referencia_classe_aa) if r.referencia_classe_aa is not None else None
    avisos: list[str] = []
    if r.referencia_classe_aa is None:
        avisos.append("sem_referencia_de_classe")
    if r.come_cotas:
        avisos.append("come_cotas_incide_no_horizonte")
    return CustoFundoOutput(
        descricao=r.descricao, fonte=r.fonte, taxa_adm_aa=r.taxa_adm_aa,
        custo_adm_total_estimado_brl=custo, metodo=METODO,
        referencia_classe_aa=r.referencia_classe_aa, acima_da_referencia=acima,
        come_cotas=r.come_cotas, classe=r.classe,
        indicado_por_terceiro=r.indicado_por_terceiro, avisos=avisos,
        premissas_usadas={"referencia_taxa_adm_aa": r.referencia_classe_aa},
    )


# =============================================================================
# produto.comparar_alternativas
# =============================================================================
class ProdutoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descricao: str
    taxa_adm_aa: float = Field(ge=0)
    classe: str | None = None
    liquidez_dias: int | None = Field(default=None, ge=0)
    come_cotas: bool | None = None


class CompararParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_aplicado_brl: float = Field(gt=0)
    horizonte_anos: float = Field(gt=0)
    produtos: list[ProdutoItem] = Field(min_length=2, description="Produtos a comparar lado a lado (o indicado e as alternativas).")


class ProdutoResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descricao: str
    taxa_adm_aa: float
    classe: str | None
    liquidez_dias: int | None
    come_cotas: bool | None
    referencia_classe_aa: float | None
    vetado_pelo_cliente: bool


class CompararResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_aplicado_brl: float
    horizonte_anos: float
    produtos: list[ProdutoResolvido]
    classes_vetadas: list[str]
    premissas: dict


class ProdutoComparado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descricao: str
    classe: str | None
    taxa_adm_aa: float
    custo_adm_total_estimado_brl: float
    referencia_classe_aa: float | None
    acima_da_referencia: bool | None
    liquidez_dias: int | None
    come_cotas: bool | None
    compativel_com_vetos: bool


class CompararOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valor_aplicado_brl: float
    horizonte_anos: float
    produtos: list[ProdutoComparado]
    metodo: str
    avisos: list[str]
    premissas_usadas: dict


async def preparar_comparar(params: CompararParams, ctx: ToolContext) -> CompararResolvido:
    refs = await ctx.policy("PRODUTO_REFERENCIAS")
    vetadas = await _classes_vetadas(ctx)
    tabela = refs.get("referencia_taxa_adm_aa") or {}
    produtos = [ProdutoResolvido(
        descricao=p.descricao, taxa_adm_aa=p.taxa_adm_aa, classe=p.classe,
        liquidez_dias=p.liquidez_dias, come_cotas=p.come_cotas,
        referencia_classe_aa=tabela.get(p.classe) if p.classe else None,
        vetado_pelo_cliente=(p.classe in vetadas) if p.classe else False,
    ) for p in params.produtos]
    return CompararResolvido(valor_aplicado_brl=params.valor_aplicado_brl,
                             horizonte_anos=params.horizonte_anos, produtos=produtos,
                             classes_vetadas=vetadas, premissas={"PRODUTO_REFERENCIAS": refs})


@tool(code="produto.comparar_alternativas", family="produto", semver="1.0.0",
      display_name="Comparação de alternativas",
      description=("Compara produtos lado a lado no mesmo valor e horizonte: custo estimado, "
                   "referência de classe, liquidez, come-cotas e compatibilidade com os vetos do "
                   "cliente. Devolve a tabela — sem ranking e sem escolher; a decisão é do cliente."),
      preparar=preparar_comparar)
def calcular_comparar(r: CompararResolvido) -> CompararOutput:
    produtos = [ProdutoComparado(
        descricao=p.descricao, classe=p.classe, taxa_adm_aa=p.taxa_adm_aa,
        custo_adm_total_estimado_brl=arred2(r.valor_aplicado_brl * p.taxa_adm_aa * r.horizonte_anos),
        referencia_classe_aa=p.referencia_classe_aa,
        acima_da_referencia=(p.taxa_adm_aa > p.referencia_classe_aa) if p.referencia_classe_aa is not None else None,
        liquidez_dias=p.liquidez_dias, come_cotas=p.come_cotas,
        compativel_com_vetos=not p.vetado_pelo_cliente,
    ) for p in r.produtos]
    avisos: list[str] = []
    if any(not p.compativel_com_vetos for p in produtos):
        avisos.append("ha_produto_incompativel_com_veto_do_cliente")
    return CompararOutput(valor_aplicado_brl=r.valor_aplicado_brl, horizonte_anos=r.horizonte_anos,
                          produtos=produtos, metodo=METODO, avisos=avisos, premissas_usadas={})
