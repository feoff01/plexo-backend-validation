"""Tool `dados.resolver_instrumento` — de um termo (ticker, código antigo, nome) ao instrumento do
universo analisável. Sem número: `emite_numero=False`. Ambíguo ou fora da cobertura ⇒ `encontrado=false`
com o motivo em `evidencia.avisos` — o Analista pergunta, não chuta."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.tools.analista._comum import (FORA_DA_COBERTURA, INSTRUMENTO_AMBIGUO, INSTRUMENTO_DESCONHECIDO, Evidencia,
                                       data_referencia, resolver_candidatos, resolver_cutoff)
from app.tools.executor import ToolContext
from app.tools.registry import tool


class ResolverParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    termo: str = Field(min_length=1, description="Como o cliente chamou o ativo: ticker (PETR4), código antigo ou parte do nome.")
    data_referencia: date | None = Field(default=None, description="Data de referência (point-in-time); padrão: a da análise.")


class Candidato(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_id: str
    ticker: str | None
    name: str
    kind: str
    is_in_universe: bool
    prioridade: int                      # 0 ticker exato · 1 alias · 2 nome contém
    ultimo_preco_em: date | None


class ResolverResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    termo: str
    cutoff_date: date
    candidatos: list[Candidato]


class ResolverOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encontrado: bool
    termo: str
    instrument_id: str | None
    ticker: str | None
    name: str | None
    kind: str | None
    is_in_universe: bool | None
    ultimo_preco_em: date | None
    ambiguos: list[Candidato]
    nota: str
    evidencia: Evidencia


async def preparar_resolver(params: ResolverParams, ctx: ToolContext) -> ResolverResolvido:
    cutoff = resolver_cutoff(params.data_referencia, ctx.cutoff_date, await data_referencia(ctx.conn))
    cands = await resolver_candidatos(ctx.conn, params.termo, cutoff=cutoff)
    ctx.registrar_insumo("market.instruments", termo=params.termo, candidatos=len(cands))
    return ResolverResolvido(termo=params.termo, cutoff_date=cutoff, candidatos=[Candidato(**c) for c in cands])


@tool(code="dados.resolver_instrumento", family="dados", semver="1.0.0",
      display_name="Resolver instrumento",
      description=("Identifica o ativo que o cliente citou (ticker, código antigo da B3 ou parte do nome) e diz se "
                   "ele está na cobertura de análise e até quando há preço. Use antes das métricas quando o "
                   "termo não for um ticker inequívoco. Se voltar encontrado=false, pergunte ao cliente qual "
                   "ativo é (lista em `ambiguos`) ou diga que o ativo não está na cobertura."),
      preparar=preparar_resolver, requires_market_data=True, emite_numero=False)
def resolver(r: ResolverResolvido) -> ResolverOutput:
    exatos = [c for c in r.candidatos if c.prioridade < 2]
    escolhido = exatos[0] if len(exatos) == 1 else (r.candidatos[0] if len(r.candidatos) == 1 else None)
    avisos: list[str] = []
    if escolhido is None:
        avisos.append(INSTRUMENTO_AMBIGUO if r.candidatos else INSTRUMENTO_DESCONHECIDO)
    elif not escolhido.is_in_universe:
        avisos.append(FORA_DA_COBERTURA)
    encontrado = escolhido is not None and escolhido.is_in_universe
    nota = ("Instrumento identificado; use o ticker nas demais ferramentas." if encontrado else
            "Não identifiquei um único instrumento na cobertura: pergunte ao cliente ou informe que o ativo não está coberto.")
    ev = Evidencia(fonte="b3", instrument_ids=[escolhido.instrument_id] if escolhido else [],
                   tickers=[escolhido.ticker] if escolhido and escolhido.ticker else [],
                   cutoff_date=r.cutoff_date, as_of=escolhido.ultimo_preco_em if escolhido else None,
                   n_observacoes=len(r.candidatos), metodo="resolucao_de_entidade",
                   nota_metodo="Casamento exato por ticker/alias; senão único por nome. Sem inferência.",
                   suficiente=encontrado, avisos=avisos)
    return ResolverOutput(encontrado=encontrado, termo=r.termo,
                          instrument_id=escolhido.instrument_id if escolhido else None,
                          ticker=escolhido.ticker if escolhido else None, name=escolhido.name if escolhido else None,
                          kind=escolhido.kind if escolhido else None,
                          is_in_universe=escolhido.is_in_universe if escolhido else None,
                          ultimo_preco_em=escolhido.ultimo_preco_em if escolhido else None,
                          ambiguos=[] if escolhido else r.candidatos, nota=nota, evidencia=ev)
