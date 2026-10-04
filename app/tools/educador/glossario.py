"""Tool `educacao.glossario` — busca conteúdo educativo APROVADO por termo, no nível do cliente.

Busca (nesta ordem, união): slug exato → título contém → tag igual (normalizados: minúsculas, sem
acentos). Nível de linguagem: parâmetro → asserção confirmada `nivel_conhecimento` do escopo (RLS)
→ `EDUCACAO_PARAMS.nivel_padrao`. A parte `montar_glossario` é pura (golden): corta o trecho em
`trecho_chars` e limita a `max_itens`. Sem resultado ⇒ `encontrado=false` — o prompt manda o
Educador dizer que não há conteúdo aprovado, nunca improvisar.
"""
from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.context_pack import nivel_conhecimento
from app.tools.executor import ToolContext
from app.tools.registry import tool

Nivel = Literal["basico", "intermediario", "avancado"]


def _normalizar(s: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.lower().split())


class GlossarioParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    termo: str = Field(min_length=1, description="Conceito que o cliente quer entender (ex.: 'come-cotas', 'CDI').")
    nivel: Nivel | None = Field(default=None, description="Nível de linguagem pedido; se ausente, uso o nível registrado do cliente ou o padrão.")


class ItemConteudo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    title: str
    level: str
    tags: list[str]
    body_md: str


class GlossarioResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    termo: str
    termo_normalizado: str
    nivel_usado: Nivel
    fonte_nivel: str                      # parametro | assercao_confirmada | policy
    itens: list[ItemConteudo]             # já filtrados pela view (aprovados+publicados)
    max_itens: int
    trecho_chars: int


class ItemGlossario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    title: str
    level: str
    tags: list[str]
    trecho: str


class GlossarioOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encontrado: bool
    termo: str
    nivel_usado: Nivel
    fonte_nivel: str
    itens: list[ItemGlossario]
    slugs: list[str]                      # → cited_refs (kind education_content)
    nota: str


async def preparar_glossario(params: GlossarioParams, ctx: ToolContext) -> GlossarioResolvido:
    cfg = await ctx.policy("EDUCACAO_PARAMS")
    if params.nivel is not None:
        nivel, fonte = params.nivel, "parametro"
    else:
        registrado = await nivel_conhecimento(ctx.conn, ctx.scope_id)
        ctx.registrar_insumo("context.v_current_facts.nivel_conhecimento", presente=registrado is not None)
        if registrado in ("basico", "intermediario", "avancado"):
            nivel, fonte = registrado, "assercao_confirmada"
        else:
            nivel, fonte = cfg["nivel_padrao"], "policy"

    termo_n = _normalizar(params.termo)
    termo_slug = termo_n.replace(" ", "-")
    # A view é referência global e pequena: filtra-se em Python para casar sem acentos/maiúsculas
    # (o banco não tem unaccent; o que importa — só aprovado+publicado — é a VIEW que garante).
    cur = await ctx.conn.execute(
        "select slug, title, level, tags, body_md from content.v_education_approved order by slug")
    candidatos = [ItemConteudo(slug=slug, title=title, level=level, tags=list(tags), body_md=body)
                  for slug, title, level, tags, body in await cur.fetchall()]

    def casa(it: ItemConteudo) -> int | None:      # menor = melhor
        if it.slug == termo_slug:
            return 0
        if termo_n in _normalizar(it.title):
            return 1
        if termo_n in {_normalizar(t) for t in it.tags} or termo_slug in it.tags:
            return 2
        return None

    ranqueados = sorted(((casa(it), it) for it in candidatos if casa(it) is not None),
                        key=lambda par: (par[0], par[1].level != nivel, par[1].slug))
    itens = [it for _, it in ranqueados]
    ctx.registrar_insumo("content.v_education_approved", encontrados=len(itens))
    return GlossarioResolvido(termo=params.termo, termo_normalizado=termo_n, nivel_usado=nivel, fonte_nivel=fonte,
                              itens=itens, max_itens=int(cfg["max_itens"]), trecho_chars=int(cfg["trecho_chars"]))


@tool(code="educacao.glossario", family="educacao", semver="1.0.1",
      display_name="Glossário (conteúdo aprovado)",
      description=("Busca na base de conteúdo educativo APROVADO por compliance o verbete de um conceito "
                   "(ex.: come-cotas, CDI, juros compostos, reserva de emergência) no nível de linguagem do "
                   "cliente. Devolve título, trecho e slug para citar. Se não encontrar, devolve encontrado=false "
                   "— e então a resposta é dizer que ainda não há material aprovado, sem explicar de cabeça."),
      preparar=preparar_glossario, emite_numero=False)
def montar_glossario(r: GlossarioResolvido) -> GlossarioOutput:
    itens = []
    for it in r.itens[: r.max_itens]:
        corpo = " ".join(it.body_md.split())
        trecho = corpo if len(corpo) <= r.trecho_chars else corpo[: r.trecho_chars].rstrip() + "…"
        itens.append(ItemGlossario(slug=it.slug, title=it.title, level=it.level, tags=it.tags, trecho=trecho))
    encontrado = bool(itens)
    nota = ("Explique com base APENAS nos trechos acima e cite o slug de cada um." if encontrado else
            "Não há conteúdo aprovado sobre este termo: diga isso ao cliente e não explique por conta própria.")
    return GlossarioOutput(encontrado=encontrado, termo=r.termo, nivel_usado=r.nivel_usado,
                           fonte_nivel=r.fonte_nivel, itens=itens, slugs=[i.slug for i in itens], nota=nota)
