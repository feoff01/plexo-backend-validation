"""Gravação de documentos em `docs.*` — como plexo_service, dentro de um lote de ingestão.

Reusa `app/market/ingest.py` para o lote (imutável, idempotente por `file_hash`, audit no fecho):
documento é dado externo datado, e o mecanismo já existe desde a 31. Nada aqui aprova nada — a
curadoria é passo separado, e o banco recusa aprovar sem revisor, sem trilha e com vocabulário
vetado (34, T73–T77).
"""
from __future__ import annotations

from typing import Iterable

from psycopg import AsyncConnection

from app.db.repos.prompts import encontrar_vocabulario_proibido
from app.docs.copom import DocumentoCopom


def achados_de_vocabulario(texto: str) -> list[str]:
    """Termos vetados (RCVM 19) no texto de TERCEIRO. Achado ⇒ o banco não deixa aprovar.

    O mesmo matcher do guardrail de saída (`app/db/repos/prompts.py:57`), aplicado na entrada —
    é o único ponto do sistema em que texto externo é inspecionado antes de virar citável."""
    return encontrar_vocabulario_proibido(texto)


async def gravar_documentos(conn: AsyncConnection, documentos: Iterable[DocumentoCopom], *,
                            source_code: str, batch_id: str) -> tuple[int, int]:
    """Insere o que ainda não existe. Devolve (inseridos, ja_existentes).

    `ON CONFLICT DO NOTHING` na chave natural (fonte, tipo, id externo): documento já ingerido é o
    que vale — corrigir texto de documento aprovado exige reabrir a revisão, nunca UPDATE cego."""
    inseridos = ja_existentes = 0
    for doc in documentos:
        cur = await conn.execute(
            "insert into docs.documents (source_code, kind, external_id, title, published_on, url, "
            "                            body_text, body_sha256, ingestion_batch_id, vocabulario_achados) "
            "values (%s, %s::docs.document_kind, %s, %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (source_code, kind, external_id) do nothing returning id::text",
            (source_code, doc.kind, doc.external_id, doc.titulo, doc.publicado_em, doc.url,
             doc.texto, doc.sha256, batch_id, achados_de_vocabulario(doc.texto)))
        if await cur.fetchone():
            inseridos += 1
        else:
            ja_existentes += 1
    return inseridos, ja_existentes


async def aprovar(conn: AsyncConnection, *, documento_id: str, revisor_id: str, notas: str | None = None) -> str:
    """Aprova um documento COM a trilha, na mesma transação — a ordem que o gate da 34 exige."""
    await conn.execute(
        "insert into docs.document_reviews (document_id, decision, reviewer_id, notes) "
        "values (%s, 'aprovado', %s, %s)", (documento_id, revisor_id, notas))
    cur = await conn.execute(
        "update docs.documents set review_status = 'aprovado', reviewed_by = %s, reviewed_at = now(), "
        "       updated_at = now() where id = %s returning external_id",
        (revisor_id, documento_id))
    row = await cur.fetchone()
    if row is None:
        raise LookupError(f"documento {documento_id} não encontrado")
    return row[0]


async def pendentes(conn: AsyncConnection, *, source_code: str | None = None, limite: int = 50) -> list[dict]:
    filtro = "and source_code = %s" if source_code else ""
    args: tuple = (limite,) if not source_code else (source_code, limite)
    cur = await conn.execute(
        f"select id::text, source_code, kind::text, external_id, title, published_on::text, "
        f"       cardinality(vocabulario_achados), vocabulario_achados "
        f"  from docs.documents where review_status = 'pendente' {filtro} "
        f" order by published_on desc limit %s", args)
    return [{"id": i, "fonte": f, "kind": k, "external_id": e, "titulo": t, "publicado_em": p,
             "vetados": n, "termos": list(termos)}
            for i, f, k, e, t, p, n, termos in await cur.fetchall()]


async def resumo(conn: AsyncConnection) -> list[dict]:
    cur = await conn.execute(
        "select source_code, review_status::text, count(*), max(published_on)::text "
        "  from docs.documents group by 1, 2 order by 1, 2")
    return [{"fonte": f, "status": s, "n": n, "mais_recente": d} for f, s, n, d in await cur.fetchall()]
