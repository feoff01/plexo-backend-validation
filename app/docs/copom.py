"""Leitura dos comunicados e atas do Copom — API de dados abertos do Banco Central.

Nada aqui toca o banco nem a rede: recebe o JSON já baixado e devolve estrutura. É o que permite
testar o parser sem provedor, como `app/market/sgs.py` faz (`sgs.py:5-6`).

Contrato observado (verificado em 2026-08-27):
    GET /api/servico/sitebcb/copom/comunicados?quantidade=N&filtro=
        {"conteudo": [{"nro_reuniao": 280, "dataReferencia": "2026-08-05", "titulo": "280ª reunião …"}]}
    GET /api/servico/sitebcb/copom/comunicados_detalhes?nro_reuniao=280
        acrescenta {"textoComunicado": "<html…>"}
    O mesmo par existe para `atas` / `atas_detalhes`, com `textoAta`.

`LAYOUT_VERSAO` versiona o CONTRATO DE LEITURA, não o dado: mudar o que se extrai muda a versão,
senão o mesmo documento (mesmo hash) já é lote `succeeded` e a reingestão vira no-op — a mesma
armadilha que `cotahist.LAYOUT_VERSAO` documenta (`cotahist.py:26-28`).
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import date

BASE = "https://www.bcb.gov.br/api/servico/sitebcb/copom"
LAYOUT_VERSAO = "1"
DATASET = f"copom@{LAYOUT_VERSAO}"

# tipo de documento → (recurso na API, campo do texto no detalhe, kind em docs.document_kind)
RECURSOS = {
    "comunicado": ("comunicados", "textoComunicado"),
    "ata": ("atas", "textoAta"),
}

_TAGS_INVISIVEIS = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
_QUEBRAS = re.compile(r"</(p|div|tr|h[1-6]|li)\s*>|<br\s*/?>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"[ \t]+")
_LINHAS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class DocumentoCopom:
    kind: str                 # comunicado | ata
    external_id: str          # número da reunião
    titulo: str
    publicado_em: date
    url: str
    texto: str
    sha256: str


def url_lista(tipo: str, quantidade: int) -> str:
    recurso, _ = RECURSOS[tipo]
    return f"{BASE}/{recurso}?quantidade={quantidade}&filtro="


def url_detalhe(tipo: str, nro_reuniao: str | int) -> str:
    recurso, _ = RECURSOS[tipo]
    return f"{BASE}/{recurso}_detalhes?nro_reuniao={nro_reuniao}"


def url_publica(tipo: str, nro_reuniao: str | int) -> str:
    """Endereço que vai para o cliente na citação — a página, não o endpoint da API."""
    pagina = "comunicados" if tipo == "comunicado" else "atas"
    return f"https://www.bcb.gov.br/publicacoes/{'notascopom' if tipo == 'ata' else pagina}/{nro_reuniao}"


def html_para_texto(bruto: str) -> str:
    """HTML do BCB → texto corrido. Sem dependência externa: o que se guarda é o que se cita."""
    sem_invisivel = _TAGS_INVISIVEIS.sub(" ", bruto or "")
    com_quebras = _QUEBRAS.sub("\n", sem_invisivel)
    texto = html.unescape(_TAGS.sub(" ", com_quebras))
    texto = _ESPACOS.sub(" ", texto.replace("\xa0", " "))
    return _LINHAS.sub("\n\n", "\n".join(linha.strip() for linha in texto.splitlines())).strip()


def hash_texto(texto: str) -> str:
    """sha256 do texto normalizado — prova de que o que se cita hoje é o que foi aprovado."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def parse_lista(json_texto: str) -> list[dict]:
    """Itens do índice: nro_reuniao, dataReferencia e titulo. Item sem os três é descartado."""
    conteudo = (json.loads(json_texto) or {}).get("conteudo") or []
    itens = []
    for item in conteudo:
        nro, data, titulo = item.get("nro_reuniao"), item.get("dataReferencia"), item.get("titulo")
        if nro is None or not data or not titulo:
            continue
        itens.append({"nro_reuniao": str(nro), "data": str(data)[:10], "titulo": str(titulo).strip()})
    return itens


def parse_detalhe(tipo: str, json_texto: str) -> str:
    """Texto integral do documento, já sem HTML. Ausente ⇒ string vazia (o chamador descarta)."""
    _, campo = RECURSOS[tipo]
    dados = json.loads(json_texto) or {}
    conteudo = dados.get("conteudo")
    if isinstance(conteudo, list) and conteudo:
        dados = conteudo[0]
    return html_para_texto(dados.get(campo) or "")


def montar(tipo: str, item: dict, texto: str) -> DocumentoCopom | None:
    """Item do índice + texto do detalhe → documento pronto para gravar. Sem texto, não há evidência."""
    if not texto:
        return None
    return DocumentoCopom(
        kind=tipo, external_id=item["nro_reuniao"], titulo=item["titulo"],
        publicado_em=date.fromisoformat(item["data"]),
        url=url_publica(tipo, item["nro_reuniao"]), texto=texto, sha256=hash_texto(texto),
    )
