"""Tool `contexto.documento_oficial` — o que o emissor oficial disse, com data, trecho e link.

Por que existe: o agente sabia dizer QUE a Selic mudou (série do SGS) e nunca POR QUÊ. O comunicado
do Copom é o motivo, escrito por quem decidiu. Esta é a primeira tool do projeto que devolve texto
de TERCEIRO ao cliente — e por isso lê **exclusivamente** `docs.v_documentos_citaveis`, que só expõe
documento aprovado por compliance, exatamente como `educacao.glossario` lê só a view de conteúdo
aprovado (`glossario.py:90-91`). Sem material aprovado, `ToolConteudoIndisponivel`: o agente diz que
não há, nunca improvisa.

`evidencia_documental` é o campo que o turno e o pipeline leem por convenção de nome (como `slugs` no
glossário e `evidencia` no Analista) para gerar o finding `documentary` e o `cited_refs kind=document`.

`emite_numero=False`: é citação datada, não simulação — o rodapé de projeção seria falso.
Config-first: tamanho do trecho e teto de documentos vêm da policy `CONTEXTO_DOCUMENTAL`.
"""
from __future__ import annotations

import unicodedata

from pydantic import BaseModel, ConfigDict, Field

from app.tools.executor import ToolContext, ToolConteudoIndisponivel
from app.tools.registry import tool

METODO = "trecho literal de documento aprovado, recortado em torno do termo procurado"
NOTA = ("Trecho literal do documento oficial citado, na data indicada. É o que o emissor publicou — "
        "não é análise da Plexo nem indicação de investimento.")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


class DocumentoOficialParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    termo: str | None = Field(default=None, description="Assunto procurado no documento (ex.: 'Selic', 'inflação', 'câmbio'). Sem termo, devolve os mais recentes.")
    fonte: str | None = Field(default=None, description="Código da fonte, se o cliente pedir uma específica (ex.: 'bacen_copom').")


class RefDocumento(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    fonte: str
    publisher: str
    titulo: str
    publicado_em: str
    url: str | None


class DocumentoCitado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    fonte: str
    publisher: str
    titulo: str
    publicado_em: str
    url: str | None
    trecho: str


class EvidenciaDocumental(BaseModel):
    """Proveniência do que a tool citou — vira `evidence_findings` (documentary) e `cited_refs`."""
    model_config = ConfigDict(extra="forbid")
    fonte: str
    documentos: list[RefDocumento]
    as_of: str                       # data do documento mais recente citado
    n_documentos: int
    metodo: str
    nota: str
    suficiente: bool
    avisos: list[str]


class DocumentoOficialResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    termo: str | None
    fonte: str | None
    encontrados: list[DocumentoCitado]
    trecho_chars: int
    max_documentos: int


class DocumentoOficialOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    termo: str | None
    documentos: list[DocumentoCitado]
    evidencia_documental: EvidenciaDocumental
    nota: str


def _recorte(texto: str, termo: str | None, largura: int) -> str:
    """Janela em torno da primeira ocorrência do termo; sem termo (ou sem achar), o começo.

    O corte é do TEXTO APROVADO, sem reescrita: o cliente lê o que o emissor escreveu."""
    corpo = " ".join((texto or "").split())
    if not corpo:
        return ""
    inicio = 0
    if termo:
        posicao = _sem_acento(corpo).find(_sem_acento(termo))
        if posicao > 0:
            inicio = max(posicao - largura // 2, 0)
    fim = inicio + largura
    trecho = corpo[inicio:fim]
    return ("…" if inicio > 0 else "") + trecho.strip() + ("…" if fim < len(corpo) else "")


async def preparar_documento_oficial(params: DocumentoOficialParams, ctx: ToolContext) -> DocumentoOficialResolvido:
    cfg = await ctx.policy("CONTEXTO_DOCUMENTAL")
    max_documentos, trecho_chars = int(cfg["max_documentos"]), int(cfg["trecho_chars"])

    condicoes, args = [], []
    if params.fonte:
        condicoes.append("source_code = %s")
        args.append(params.fonte)
    filtro = ("where " + " and ".join(condicoes)) if condicoes else ""
    cur = await ctx.conn.execute(
        "select id::text, source_code, fonte, publisher, title, published_on::text, url, body_text "
        f"  from docs.v_documentos_citaveis {filtro} order by published_on desc", args)
    achados = [{"id": doc_id, "fonte": source_code, "publisher": publisher, "titulo": titulo,
                "publicado_em": publicado, "url": url, "corpo": corpo or ""}
               for doc_id, source_code, _nome, publisher, titulo, publicado, url, corpo in await cur.fetchall()]
    ctx.registrar_insumo("docs.v_documentos_citaveis", disponiveis=len(achados))

    # Filtro por termo em Python: não há `unaccent` no banco (mesma razão do glossário, :88-89).
    if params.termo:
        alvo = _sem_acento(params.termo)
        achados = [d for d in achados if alvo in _sem_acento(f"{d['titulo']} {d['corpo']}")]

    if not achados:
        raise ToolConteudoIndisponivel(
            f"não há documento oficial aprovado sobre {params.termo!r} — diga ao cliente que não há "
            f"material aprovado para citar, sem substituir por conhecimento próprio")

    encontrados = [
        DocumentoCitado(id=d["id"], fonte=d["fonte"], publisher=d["publisher"], titulo=d["titulo"],
                        publicado_em=d["publicado_em"], url=d["url"],
                        trecho=_recorte(d["corpo"], params.termo, trecho_chars))
        for d in achados[:max_documentos]
    ]
    return DocumentoOficialResolvido(termo=params.termo, fonte=params.fonte, encontrados=encontrados,
                                     trecho_chars=trecho_chars, max_documentos=max_documentos)


@tool(code="contexto.documento_oficial", family="contexto", semver="1.0.1",
      display_name="Documento oficial (contexto)",
      description=("O que o emissor OFICIAL publicou sobre um assunto, com data, trecho literal e link — "
                   "comunicados e atas do Copom (Banco Central). Use para explicar POR QUE algo mudou "
                   "(decisão de juros, cenário declarado) ou para situar uma decisão do cliente. "
                   "Devolve só documento aprovado por compliance; não opina nem projeta."),
      emite_numero=False, preparar=preparar_documento_oficial)
def calcular_documento_oficial(r: DocumentoOficialResolvido) -> DocumentoOficialOutput:
    refs = [RefDocumento(id=d.id, fonte=d.fonte, publisher=d.publisher, titulo=d.titulo,
                         publicado_em=d.publicado_em, url=d.url) for d in r.encontrados]
    avisos: list[str] = []
    if len(r.encontrados) == r.max_documentos:
        avisos.append("limite_de_documentos_atingido")
    if r.termo is None:
        avisos.append("sem_termo_devolvidos_os_mais_recentes")

    evidencia = EvidenciaDocumental(
        fonte=refs[0].fonte, documentos=refs, as_of=max(d.publicado_em for d in r.encontrados),
        n_documentos=len(refs), metodo=METODO, nota=NOTA, suficiente=True, avisos=avisos)
    return DocumentoOficialOutput(termo=r.termo, documentos=r.encontrados,
                                  evidencia_documental=evidencia, nota=NOTA)
