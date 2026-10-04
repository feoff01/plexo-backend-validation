"""Tool `educacao.exemplo_didatico` — exemplo numérico de um conceito, ancorado em conteúdo aprovado.

Conceitos v1: come_cotas, taxa_administracao, ir_regressivo. Os números do exemplo (alíquotas,
rendimento didático, valor base) vêm de `EDUCACAO_EXEMPLOS`; o verbete de apoio vem de
`content.v_education_approved` pelo slug mapeado na policy — sem verbete aprovado a tool levanta
`ToolConteudoIndisponivel` (o Educador diz que não há material, não improvisa). `calcular_exemplo`
é pura (golden). Literais no código: 0/1 (identidade), 100 (percentual).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.executor import ToolConteudoIndisponivel, ToolContext
from app.tools.hashing import arred2
from app.tools.registry import tool

PERCENTUAL = 100
Conceito = Literal["come_cotas", "taxa_administracao", "ir_regressivo"]


class ExemploParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conceito: Conceito = Field(description="Conceito a exemplificar: come_cotas, taxa_administracao ou ir_regressivo.")
    valor_brl: float | None = Field(default=None, gt=0, description="Valor base do exemplo; se ausente, uso o valor didático da política.")
    prazo_meses: int | None = Field(default=None, gt=0, description="Só para ir_regressivo: prazo da aplicação em meses.")


class ExemploResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conceito: Conceito
    slug: str
    titulo_conteudo: str
    valor_brl: float
    fonte_valor: str                      # parametro | policy
    prazo_meses: int | None
    parametros: dict[str, Any]            # bloco do conceito em EDUCACAO_EXEMPLOS


class LinhaExemplo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotulo: str
    valor_brl: float
    detalhe: str = ""


class ExemploOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conceito: Conceito
    slug: str
    titulo_conteudo: str
    valor_base_brl: float
    linhas: list[LinhaExemplo]
    leitura: str
    premissas_usadas: dict[str, Any]


async def preparar_exemplo(params: ExemploParams, ctx: ToolContext) -> ExemploResolvido:
    cfg = await ctx.policy("EDUCACAO_EXEMPLOS")
    slug = cfg["conteudo_slug"][params.conceito]
    cur = await ctx.conn.execute(
        "select slug, title from content.v_education_approved where slug = %s", (slug,))
    row = await cur.fetchone()
    ctx.registrar_insumo("content.v_education_approved", slug=slug, presente=row is not None)
    if row is None:
        raise ToolConteudoIndisponivel(f"conceito '{params.conceito}' sem verbete aprovado ('{slug}')")
    valor = params.valor_brl if params.valor_brl is not None else float(cfg["valor_base_brl"])
    prazo = None
    if params.conceito == "ir_regressivo":
        prazo = params.prazo_meses if params.prazo_meses is not None else int(cfg["ir_regressivo"]["prazo_meses_padrao"])
    return ExemploResolvido(conceito=params.conceito, slug=row[0], titulo_conteudo=row[1], valor_brl=valor,
                            fonte_valor="parametro" if params.valor_brl is not None else "policy",
                            prazo_meses=prazo, parametros=dict(cfg[params.conceito]))


def _come_cotas(r: ExemploResolvido) -> tuple[list[LinhaExemplo], str]:
    p = r.parametros
    rendimento = r.valor_brl * float(p["rendimento_semestre_pct"]) / PERCENTUAL
    ir_curto = rendimento * float(p["aliquota_curto_pct"]) / PERCENTUAL
    ir_longo = rendimento * float(p["aliquota_longo_pct"]) / PERCENTUAL
    linhas = [
        LinhaExemplo(rotulo="valor aplicado", valor_brl=arred2(r.valor_brl)),
        LinhaExemplo(rotulo="rendimento no semestre", valor_brl=arred2(rendimento),
                     detalhe=f"{p['rendimento_semestre_pct']}% (didático)"),
        LinhaExemplo(rotulo="come-cotas em fundo de curto prazo", valor_brl=arred2(ir_curto),
                     detalhe=f"{p['aliquota_curto_pct']}% sobre o rendimento"),
        LinhaExemplo(rotulo="come-cotas em fundo de longo prazo", valor_brl=arred2(ir_longo),
                     detalhe=f"{p['aliquota_longo_pct']}% sobre o rendimento"),
        LinhaExemplo(rotulo="saldo após o come-cotas (longo prazo)", valor_brl=arred2(r.valor_brl + rendimento - ir_longo)),
    ]
    leitura = ("O come-cotas antecipa, a cada semestre, o imposto sobre o rendimento — reduzindo o número de "
               "cotas; a diferença para a alíquota final é acertada no resgate.")
    return linhas, leitura


def _taxa_administracao(r: ExemploResolvido) -> tuple[list[LinhaExemplo], str]:
    p = r.parametros
    anos = int(p["anos"])
    bruto = float(p["rendimento_bruto_aa_pct"]) / PERCENTUAL
    taxa = float(p["taxa_aa_pct"]) / PERCENTUAL
    montante_sem = r.valor_brl * (1 + bruto) ** anos
    montante_com = r.valor_brl * (1 + bruto - taxa) ** anos
    linhas = [
        LinhaExemplo(rotulo="valor aplicado", valor_brl=arred2(r.valor_brl)),
        LinhaExemplo(rotulo=f"montante em {anos} anos sem taxa", valor_brl=arred2(montante_sem),
                     detalhe=f"{p['rendimento_bruto_aa_pct']}% a.a. (didático)"),
        LinhaExemplo(rotulo=f"montante em {anos} anos com taxa de {p['taxa_aa_pct']}% a.a.",
                     valor_brl=arred2(montante_com), detalhe="rendimento líquido = bruto − taxa"),
        LinhaExemplo(rotulo="diferença atribuível à taxa", valor_brl=arred2(montante_sem - montante_com)),
    ]
    leitura = ("A taxa de administração é cobrada todo ano sobre o patrimônio, esteja o fundo subindo ou "
               "não; ao longo do tempo a diferença cresce por juros compostos.")
    return linhas, leitura


def _ir_regressivo(r: ExemploResolvido) -> tuple[list[LinhaExemplo], str]:
    p = r.parametros
    prazo_meses = int(r.prazo_meses or 0)
    dias = prazo_meses * int(p["dias_por_mes"])
    rendimento = r.valor_brl * (float(p["rendimento_aa_pct"]) / PERCENTUAL) * (prazo_meses / int(p.get("meses_por_ano", 12)))
    linhas = [LinhaExemplo(rotulo="valor aplicado", valor_brl=arred2(r.valor_brl)),
              LinhaExemplo(rotulo=f"rendimento em {prazo_meses} meses", valor_brl=arred2(rendimento),
                           detalhe=f"{p['rendimento_aa_pct']}% a.a. simples (didático)")]
    faixa_aplicada = None
    for faixa in p["faixas"]:
        ate = faixa.get("ate_dias")
        aliq = float(faixa["aliquota_pct"])
        rotulo = f"até {ate} dias" if ate is not None else "acima do último limite"
        linhas.append(LinhaExemplo(rotulo=f"imposto se resgatado {rotulo}", valor_brl=arred2(rendimento * aliq / PERCENTUAL),
                                   detalhe=f"{aliq}%"))
        if faixa_aplicada is None and (ate is None or dias <= int(ate)):
            faixa_aplicada = aliq
    linhas.append(LinhaExemplo(rotulo=f"imposto neste prazo ({dias} dias)",
                               valor_brl=arred2(rendimento * (faixa_aplicada or 0) / PERCENTUAL),
                               detalhe=f"{faixa_aplicada}%"))
    leitura = "Quanto mais tempo a aplicação fica, menor a alíquota sobre o rendimento — é a tabela regressiva."
    return linhas, leitura


_CALCULOS = {"come_cotas": _come_cotas, "taxa_administracao": _taxa_administracao, "ir_regressivo": _ir_regressivo}


@tool(code="educacao.exemplo_didatico", family="educacao", semver="1.0.0",
      display_name="Exemplo didático com números",
      description=("Monta um exemplo numérico DIDÁTICO de um conceito já explicado na base aprovada: come_cotas, "
                   "taxa_administracao ou ir_regressivo. Usa valores de exemplo da política (ou o valor que o "
                   "cliente der) e devolve linhas rotuladas + o slug do verbete para citar. Não avalia produto real."),
      preparar=preparar_exemplo)
def calcular_exemplo(r: ExemploResolvido) -> ExemploOutput:
    linhas, leitura = _CALCULOS[r.conceito](r)
    return ExemploOutput(conceito=r.conceito, slug=r.slug, titulo_conteudo=r.titulo_conteudo,
                         valor_base_brl=arred2(r.valor_brl), linhas=linhas, leitura=leitura,
                         premissas_usadas={"EDUCACAO_EXEMPLOS": {r.conceito: r.parametros,
                                                                 "fonte_valor": r.fonte_valor}})
