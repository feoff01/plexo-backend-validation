"""Registro da análise do Analista (F5, modo standard): toda pergunta vira `analysis.analyses`
(com cutoff pela data de observação em `cutoff_date`) e cada tool executada vira `analysis.evidence_findings` com
proveniência (`tool_execution_id`, preços/índices `as_of`, lotes). Dado insuficiente vira evidência
`missing` — o banco exige proveniência só do que é material (CHECK material_needs_provenance).
Plans/tasks/reports (modo research) ficam para a F6."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

STATUS_FINAL = "final"
STATUS_COM_AVISOS = "final_with_warnings"
STATUS_CANCELADA = "cancelled"
STATUS_BLOQUEADA = "blocked"
STATUS_FALHOU = "failed"
TERMINAIS = (STATUS_FINAL, STATUS_COM_AVISOS, STATUS_CANCELADA, STATUS_BLOQUEADA, STATUS_FALHOU)


class TransicaoInvalida(RuntimeError):
    """A análise não estava em nenhum dos estados de origem esperados (outro executor avançou, ou terminal)."""


@dataclass(frozen=True)
class AnaliseRow:
    id: str
    scope_id: str
    user_id: str
    conversation_id: str | None
    question: str
    mode: str
    cutoff_date: date | None
    status: str
    replan_count: int
    max_replans: int
    budget: dict[str, Any]
    intent: dict[str, Any] | None


_COLS = "id::text, scope_id::text, user_id::text, conversation_id::text, question, mode, cutoff_date, status::text, replan_count, max_replans, budget, intent"


async def carregar(conn: AsyncConnection, analysis_id: str) -> AnaliseRow | None:
    cur = await conn.execute(f"select {_COLS} from analysis.analyses where id = %s", (analysis_id,))
    row = await cur.fetchone()
    return AnaliseRow(*row) if row else None


async def carregar_service(db, analysis_id: str) -> AnaliseRow | None:
    async with db.service_session() as conn:
        return await carregar(conn, analysis_id)


async def listar_findings(conn: AsyncConnection, analysis_id: str) -> list[dict[str, Any]]:
    """Findings da análise em ordem estável (kind, id) — a base do evidence_hash."""
    cur = await conn.execute(
        "select id::text, kind, finding, provenance from analysis.evidence_findings where analysis_id = %s order by kind, id",
        (analysis_id,))
    return [{"id": i, "kind": k, "finding": f, "provenance": p} for i, k, f, p in await cur.fetchall()]


def evidence_hash_de(findings: list[dict[str, Any]]) -> str:
    """sha256 do bundle canônico (kind, finding, provenance) — o que fundamentou o texto do relatório."""
    from app.tools.hashing import canonical_json, sha256_hex

    return sha256_hex(canonical_json([{k: f[k] for k in ("kind", "finding", "provenance")} for f in findings]))


async def avancar_status(conn: AsyncConnection, analysis_id: str, *, de: tuple[str, ...], para: str) -> None:
    """Transição guardada: só avança se a análise está em um dos estados `de` (CAS); terminal carimba finished_at no banco."""
    cur = await conn.execute(
        "update analysis.analyses set status = %s::analysis.analysis_status where id = %s and status = any(%s::analysis.analysis_status[]) returning id",
        (para, analysis_id, list(de)))
    if await cur.fetchone() is None:
        raise TransicaoInvalida(f"análise {analysis_id}: transição para {para} exige estado em {de}")


async def criar(conn: AsyncConnection, *, scope_id: str, user_id: str, conversation_id: str | None, question: str,
                budget: dict[str, Any] | None = None, mode: str = "standard", max_replans: int | None = None) -> tuple[str, date]:
    """Abre a análise (status 'received') com cutoff = data do banco. Devolve (id, cutoff_date).
    `max_replans` vem de LLM_BUDGETS.max_replans_por_analise vigente no início da análise; None = default do banco."""
    cur = await conn.execute(
        """insert into analysis.analyses (scope_id, user_id, conversation_id, question, mode, cutoff_date, budget, max_replans)
           values (%s, %s, %s, %s, %s, current_date, %s, coalesce(%s, 2)) returning id::text, cutoff_date""",
        (scope_id, user_id, conversation_id, question, mode, Jsonb(budget or {}), max_replans))
    aid, cutoff = await cur.fetchone()
    return aid, cutoff


def cited_refs_de(evidencia: Any) -> list[dict[str, Any]]:
    """cited_refs de preço/índice as-of a partir de `output.evidencia` (duck-typing, como `slugs` do Educador)."""
    if evidencia is None:
        return []
    refs = [{"kind": "price_asof", "instrument_id": iid, "as_of": evidencia.as_of.isoformat() if evidencia.as_of else None,
             "source": evidencia.fonte} for iid in evidencia.instrument_ids]
    refs += [{"kind": "index_asof", "index_code": code, "as_of": evidencia.as_of.isoformat() if evidencia.as_of else None,
              "source": evidencia.fonte} for code in evidencia.index_codes]
    return refs


def cited_refs_documentais(evidencia: Any) -> list[dict[str, Any]]:
    """cited_refs de documento a partir de `output.evidencia_documental` (F13a).

    Kind `document` — o primeiro ref do projeto que aponta para FORA: leva url, data e emissor, para
    o cliente poder abrir a fonte e conferir o trecho citado."""
    if evidencia is None:
        return []
    return [{"kind": "document", "id": d.id, "titulo": d.titulo, "as_of": d.publicado_em,
             "url": d.url, "source": d.fonte, "publisher": d.publisher}
            for d in evidencia.documentos]


def _provenance_documental(code: str, execution_id: str, ev: Any) -> list[dict[str, Any]]:
    """`documentary` é evidência MATERIAL: o CHECK material_needs_provenance (20) recusa lista vazia."""
    return [{"tool_execution_id": execution_id, "tool": code, "fonte": ev.fonte,
             "documents": [{"id": d.id, "titulo": d.titulo, "publicado_em": d.publicado_em,
                            "url": d.url, "publisher": d.publisher} for d in ev.documentos],
             "as_of": ev.as_of}]


def _provenance(code: str, execution_id: str, ev: Any) -> list[dict[str, Any]]:
    return [{"tool_execution_id": execution_id, "tool": code,
             "price_asof": [{"instrument_id": i, "as_of": ev.as_of.isoformat() if ev.as_of else None} for i in ev.instrument_ids],
             "index_asof": [{"index_code": c, "as_of": ev.as_of.isoformat() if ev.as_of else None} for c in ev.index_codes],
             "ingestion_batch_ids": list(ev.ingestion_batch_ids), "cutoff_date": ev.cutoff_date.isoformat()}]


async def _inserir(conn: AsyncConnection, analysis_id: str, kind: str, finding: dict[str, Any],
                   provenance: list[dict[str, Any]]) -> str:
    cur = await conn.execute(
        "insert into analysis.evidence_findings (analysis_id, kind, finding, provenance) values (%s, %s, %s, %s) returning id::text",
        (analysis_id, kind, Jsonb(finding), Jsonb(provenance)))
    return (await cur.fetchone())[0]


def _finding_quantitativo(base: dict[str, Any], ev: Any) -> dict[str, Any]:
    """Serializa finding quantitativo sem alargar o contrato legacy de Evidencia.

    Tools descritivas continuam gravando somente ``metricas``. Tools inferenciais podem fornecer
    ``estimativas`` tipadas; o campo só entra no finding quando existe e não está vazio.
    """
    finding = {**base, "metricas": ev.metricas, "tickers": ev.tickers, "index_codes": ev.index_codes}
    estimativas = getattr(ev, "estimativas", None)
    if estimativas:
        finding["estimativas"] = {
            code: estimate.model_dump(mode="json") if hasattr(estimate, "model_dump") else estimate
            for code, estimate in estimativas.items()
        }
    return finding


async def registrar_findings(conn: AsyncConnection, analysis_id: str, executadas: list[tuple[str, Any]],
                             node_id: str | None = None) -> tuple[list[str], bool]:
    """Uma rodada de findings por execução com `evidencia`. Devolve (ids, houve_missing_ou_aviso)."""
    ids: list[str] = []
    com_avisos = False
    for code, r in executadas:
        # Evidência DOCUMENTAL (F13a): trecho de documento aprovado. Preenche o kind `documentary`,
        # que existe no schema desde a 20 e nunca tinha sido escrito por linha de código nenhuma.
        ed = getattr(r.output, "evidencia_documental", None)
        if ed is not None:
            ids.append(await _inserir(
                conn, analysis_id, "documentary",
                {"tool": code, "as_of": ed.as_of, "n_documentos": ed.n_documentos,
                 "fonte": ed.fonte, "metodo": ed.metodo,
                 "documentos": [{"id": d.id, "titulo": d.titulo, "publicado_em": d.publicado_em}
                                for d in ed.documentos],
                 **({"node_id": node_id} if node_id else {})},
                _provenance_documental(code, r.execution_id, ed)))
            for aviso in ed.avisos:
                com_avisos = True

        ev = getattr(r.output, "evidencia", None)
        if ev is None:
            continue
        prov = _provenance(code, r.execution_id, ev)
        base = {"tool": code, "as_of": ev.as_of.isoformat() if ev.as_of else None, "n_observacoes": ev.n_observacoes,
                "cutoff_date": ev.cutoff_date.isoformat(), **({"node_id": node_id} if node_id else {})}
        if ev.suficiente:
            ids.append(await _inserir(conn, analysis_id, "quantitative",
                                      _finding_quantitativo(base, ev), prov))
        else:
            com_avisos = True
            ids.append(await _inserir(conn, analysis_id, "missing",
                                      {**base, "motivos": ev.avisos, "tickers": ev.tickers, "index_codes": ev.index_codes}, prov))
        ids.append(await _inserir(conn, analysis_id, "methodology",
                                  {**base, "metodo": ev.metodo, "nota_metodo": ev.nota_metodo,
                                   "policies": [{"code": m["code"], "version": m["version"]} for m in r.politicas_meta]}, prov))
        for aviso in (ev.avisos if ev.suficiente else []):
            com_avisos = True
            ids.append(await _inserir(conn, analysis_id, "warning", {**base, "aviso": aviso, "lacunas": [d.isoformat() for d in ev.lacunas]}, prov))
    return ids, com_avisos


async def finalizar(conn: AsyncConnection, analysis_id: str, status: str) -> None:
    await conn.execute(
        "update analysis.analyses set status = %s::analysis.analysis_status, finished_at = clock_timestamp() where id = %s",
        (status, analysis_id))
