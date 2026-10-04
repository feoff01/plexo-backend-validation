"""Tasks do agente de Contexto e de manutenção. Todas rodam como plexo_service (core.is_service()).

- extrair_conversa(ctx, id)      → app.context.extractor.processar_conversa
- varrer_encerradas(ctx)         → fila = conversations_pending_context_idx sem run 'succeeded'; enfileira
- encerrar_inativas(ctx)         → AGENT_CONVERSATIONS.inatividade_minutos; 'aberta' → 'encerrada'
- expirar(ctx)                   → context.expire_stale_assertions() + propostas vencidas → 'expirada'
- varrer_execucoes_travadas(ctx) → JOBS_MANUTENCAO.execucao_travada_minutos; tool_executions 'running' → 'timeout'

Números vêm de policy (config-first); cada job com efeito deixa trilha em audit.activity_log.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from app.context.extractor import processar_conversa
from app.db.repos import audit


async def extrair_conversa(ctx: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    r = await processar_conversa(ctx["db"], ctx["llm"], ctx["policies"], conversation_id)
    return r.resumo()


async def varrer_encerradas(ctx: dict[str, Any]) -> int:
    """Conversas 'encerrada' sem extração bem-sucedida, da mais antiga para a mais nova."""
    async with ctx["db"].service_session() as conn:
        cur = await conn.execute(
            """select c.id::text from agents.conversations c
                where c.status = 'encerrada'
                  and not exists (select 1 from context.extraction_runs r
                                   where r.conversation_id = c.id and r.status = 'succeeded')
                order by c.ended_at""")
        ids = [r[0] for r in await cur.fetchall()]
    for cid in ids:
        await ctx["enfileirar"](cid)
    return len(ids)


async def encerrar_inativas(ctx: dict[str, Any]) -> int:
    minutos = int((await ctx["policies"].payload("AGENT_CONVERSATIONS"))["inatividade_minutos"])
    async with ctx["db"].service_session() as conn:
        cur = await conn.execute(
            """update agents.conversations set status = 'encerrada', ended_at = now()
                where status = 'aberta'
                  and coalesce(last_message_at, started_at) < now() - make_interval(mins => %s)
                returning id::text, scope_id::text""", (minutos,))
        linhas = await cur.fetchall()
        for cid, scope_id in linhas:
            await audit.registrar(conn, actor_kind="job", action="conversation.closed_inactive",
                                  object_kind="conversation", object_id=cid, scope_id=scope_id,
                                  details={"inatividade_minutos": minutos})
    return len(linhas)


async def expirar(ctx: dict[str, Any]) -> dict[str, int]:
    async with ctx["db"].service_session() as conn:
        cur = await conn.execute("select context.expire_stale_assertions()")
        assercoes = (await cur.fetchone())[0]
        cur = await conn.execute(
            """update context.change_proposals set status = 'expirada'
                where status = 'proposta' and expires_at is not null and expires_at < current_date
                returning id::text, scope_id::text""")
        propostas = await cur.fetchall()
        for pid, scope_id in propostas:
            await audit.registrar(conn, actor_kind="job", action="proposal.expired", object_kind="proposal",
                                  object_id=pid, scope_id=scope_id)
        if assercoes:
            await audit.registrar(conn, actor_kind="job", action="assertions.expired", details={"n": assercoes})
    return {"assercoes": assercoes, "propostas": len(propostas)}


async def varrer_execucoes_travadas(ctx: dict[str, Any]) -> int:
    minutos = int((await ctx["policies"].payload("JOBS_MANUTENCAO"))["execucao_travada_minutos"])
    async with ctx["db"].service_session() as conn:
        cur = await conn.execute(
            """update tools.tool_executions
                  set status = 'timeout', finished_at = now(), error_code = 'timeout',
                      error_detail = 'execução em running além de JOBS_MANUTENCAO.execucao_travada_minutos',
                      duration_ms = (extract(epoch from now() - started_at) * 1000)::int
                where status = 'running' and started_at < now() - make_interval(mins => %s)
                returning id::text, scope_id::text""", (minutos,))
        linhas = await cur.fetchall()
        for eid, scope_id in linhas:
            await audit.registrar(conn, actor_kind="job", action="tool_execution.timeout", object_kind="tool_execution",
                                  object_id=eid, scope_id=scope_id, details={"execucao_travada_minutos": minutos})
    return len(linhas)


# ------------------------------------------------------------------ mercado (F5)
# Ingestão de preços oficiais. URLs, cadência e tamanho de lote vêm da policy MERCADO_INGESTAO;
# as regras (append-only, um arquivo = um lote succeeded, sem data futura) são do banco (31).
async def _baixar(url: str, *, timeout_s: float) -> str:
    """Baixa para arquivo temporário (o COTAHIST anual tem centenas de MB — nunca em memória)."""
    import tempfile

    import httpx

    fd, caminho = tempfile.mkstemp(prefix="plexo_market_", suffix=".bin")
    with open(fd, "wb") as f:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                async for parte in r.aiter_bytes():
                    f.write(parte)
    return caminho


def _ontem_util(hoje: date) -> date:
    d = hoje - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


async def ingerir_cotahist(ctx: dict[str, Any], *, arquivo: str | None = None, ano: int | None = None,
                           data: date | None = None) -> dict[str, Any]:
    """COTAHIST (B3) → market.prices (fechamento, só do universo). Sem argumentos: o diário de ontem."""
    from app.market import cotahist, ingest

    cfg = await ctx["policies"].payload("MERCADO_INGESTAO")
    temporario = url = None
    if arquivo is None:
        if ano is None and data is None:
            data = _ontem_util(date.today())
        url = (cfg["cotahist_url_anual"].format(ano=ano) if ano
               else cfg["cotahist_url_diario"].format(ddmmaaaa=data.strftime("%d%m%Y")))
        temporario = arquivo = await _baixar(url, timeout_s=float(cfg["timeout_s"]))
    try:
        file_hash = cotahist.hash_arquivo(arquivo)
        async with ctx["db"].service_session() as conn:
            batch = await ingest.abrir_lote(conn, source_code="b3", dataset=cotahist.DATASET,
                                            file_hash=file_hash, reference_date=data)
            if batch is None:
                existente = await ingest.lote_existente(conn, source_code="b3", dataset=cotahist.DATASET, file_hash=file_hash)
                return {"status": "noop", "batch_id": existente, "file_hash": file_hash, "rows_ingested": 0,
                        "ignorados_fora_universo": 0, "conflitos": 0}
            mapa = await ingest.mapa_universo(conn, somente_universo=bool(cfg.get("somente_universo", True)))
        try:
            async with ctx["db"].service_session() as conn:
                res = await ingest.gravar_precos(
                    conn, batch, cotahist.iter_registros(cotahist.abrir_linhas(arquivo)), mapa,
                    source_code="b3", lote_linhas=int(cfg["lote_insert_linhas"]))
        except Exception as exc:
            async with ctx["db"].service_session() as conn:
                await ingest.fechar_lote(conn, batch, status="failed", rows=None,
                                         error=f"{type(exc).__name__}: {exc}"[:500])
            raise
        detalhes = {"ignorados_fora_universo": res.ignorados_fora_universo, "conflitos": res.conflitos,
                    "origem": url or os.path.basename(arquivo)}
        async with ctx["db"].service_session() as conn:
            await ingest.fechar_lote(conn, batch, status="succeeded", rows=res.inseridos, details=detalhes,
                                     reference_date=data)
        return {"status": "succeeded", "batch_id": batch, "file_hash": file_hash, "rows_ingested": res.inseridos,
                "ignorados_fora_universo": res.ignorados_fora_universo, "conflitos": res.conflitos}
    finally:
        if temporario:
            os.unlink(temporario)


async def ingerir_copom(ctx: dict[str, Any], *, tipo: str = "comunicado", quantidade: int = 6,
                        respostas: dict[str, str] | None = None) -> Any:
    """Copom (Bacen) → docs.documents. `tipo` = comunicado | ata.

    `respostas` injeta o JSON do provedor por URL (testes sem rede), como `texto_json` faz no SGS.
    Nada é aprovado aqui: o documento nasce `pendente` e a curadoria é passo separado."""
    import httpx

    from app.docs import copom, ingest as docs_ingest
    from app.market import ingest

    cfg = await ctx["policies"].payload("MERCADO_INGESTAO")
    timeout = float(cfg["timeout_s"])

    async def buscar(url: str) -> str:
        if respostas is not None:
            return respostas[url]
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text

    itens = copom.parse_lista(await buscar(copom.url_lista(tipo, quantidade)))
    documentos = []
    for item in itens:
        texto = copom.parse_detalhe(tipo, await buscar(copom.url_detalhe(tipo, item["nro_reuniao"])))
        doc = copom.montar(tipo, item, texto)
        if doc is not None:
            documentos.append(doc)
    if not documentos:
        return {"tipo": tipo, "status": "vazio", "rows_ingested": 0}

    # O hash do LOTE é o do conjunto: rodar de novo sem documento novo é no-op, como no COTAHIST.
    file_hash = copom.hash_texto("|".join(f"{d.external_id}:{d.sha256}" for d in documentos))
    referencia = max(d.publicado_em for d in documentos)
    dataset = f"{copom.DATASET}/{tipo}"
    async with ctx["db"].service_session() as conn:
        batch = await ingest.abrir_lote(conn, source_code="bacen_copom", dataset=dataset,
                                        file_hash=file_hash, reference_date=referencia)
        if batch is None:
            existente = await ingest.lote_existente(conn, source_code="bacen_copom", dataset=dataset,
                                                    file_hash=file_hash)
            return {"tipo": tipo, "status": "noop", "batch_id": existente, "rows_ingested": 0}
    try:
        async with ctx["db"].service_session() as conn:
            inseridos, ja_existentes = await docs_ingest.gravar_documentos(
                conn, documentos, source_code="bacen_copom", batch_id=batch)
    except Exception as exc:
        async with ctx["db"].service_session() as conn:
            await ingest.fechar_lote(conn, batch, status="failed", rows=None,
                                     error=f"{type(exc).__name__}: {exc}"[:500])
        raise
    async with ctx["db"].service_session() as conn:
        await ingest.fechar_lote(conn, batch, status="succeeded", rows=inseridos,
                                 details={"tipo": tipo, "ja_existentes": ja_existentes,
                                          "referencia": referencia.isoformat()})
    return {"tipo": tipo, "status": "succeeded", "batch_id": batch, "file_hash": file_hash,
            "rows_ingested": inseridos, "ja_existentes": ja_existentes}


async def ingerir_focus(ctx: dict[str, Any], *, indicador: str | None = None, top: int = 200,
                        texto_json: str | None = None) -> Any:
    """Focus (Bacen) → market.market_expectations. `texto_json` injeta a resposta (testes sem rede)."""
    import httpx

    from app.market import focus, ingest

    cfg = await ctx["policies"].payload("MERCADO_INGESTAO")
    url = focus.url(indicador, top)
    if texto_json is not None:
        texto = texto_json
    else:
        async with httpx.AsyncClient(timeout=float(cfg["timeout_s"])) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            texto = resp.text

    itens = focus.parse(texto)
    if not itens:
        return {"indicador": indicador, "status": "vazio", "rows_ingested": 0}
    file_hash = focus.hash_texto(texto)
    referencia = max(e.data_coleta for e in itens)
    dataset = f"{focus.DATASET}/{indicador or 'todos'}"
    async with ctx["db"].service_session() as conn:
        batch = await ingest.abrir_lote(conn, source_code="bacen_focus", dataset=dataset,
                                        file_hash=file_hash, reference_date=referencia)
        if batch is None:
            existente = await ingest.lote_existente(conn, source_code="bacen_focus", dataset=dataset,
                                                    file_hash=file_hash)
            return {"indicador": indicador, "status": "noop", "batch_id": existente, "rows_ingested": 0}
    try:
        async with ctx["db"].service_session() as conn:
            inseridos = await ingest.gravar_expectativas(conn, batch, itens)
    except Exception as exc:
        async with ctx["db"].service_session() as conn:
            await ingest.fechar_lote(conn, batch, status="failed", rows=None,
                                     error=f"{type(exc).__name__}: {exc}"[:500])
        raise
    async with ctx["db"].service_session() as conn:
        await ingest.fechar_lote(conn, batch, status="succeeded", rows=inseridos,
                                 details={"indicador": indicador, "lidos": len(itens),
                                          "referencia": referencia.isoformat()})
    return {"indicador": indicador, "status": "succeeded", "batch_id": batch, "file_hash": file_hash,
            "rows_ingested": inseridos, "lidos": len(itens)}


async def ingerir_sgs(ctx: dict[str, Any], *, indice: str | None = None, de: date | None = None,
                      ate: date | None = None, texto_json: str | None = None) -> Any:
    """SGS (Bacen) → market.index_values. Sem `indice`: todos com sgs_series_id (lista de resultados).
    `texto_json` injeta a resposta do provedor (testes sem rede)."""
    import httpx

    from app.market import ingest, sgs

    cfg = await ctx["policies"].payload("MERCADO_INGESTAO")
    async with ctx["db"].service_session() as conn:
        todos = await ingest.indices_sgs(conn)
    alvos = [(c, s) for c, s in todos if indice is None or c == indice]
    if indice is not None and not alvos:
        raise ValueError(f"índice {indice!r} não tem sgs_series_id em market.index_definitions")
    saidas = []
    for code, serie in alvos:
        async with ctx["db"].service_session() as conn:
            ultimo = await ingest.ultimo_valor_indice(conn, code)
        de_i = de or (ultimo + timedelta(days=1) if ultimo
                      else date.today() - timedelta(days=365 * int(cfg["backfill_anos"])))
        ate_i = ate or date.today()
        if texto_json is not None:
            texto = texto_json
        else:
            async with httpx.AsyncClient(timeout=float(cfg["timeout_s"])) as client:
                texto = await sgs.buscar_texto(client, cfg["sgs_base_url"], serie, de_i, ate_i,
                                               max_dias=int(cfg["sgs_janela_max_dias"]))
        file_hash = sgs.hash_texto(texto)
        dataset = f"sgs_{code}"
        async with ctx["db"].service_session() as conn:
            batch = await ingest.abrir_lote(conn, source_code="bacen_sgs", dataset=dataset,
                                            file_hash=file_hash, reference_date=ate_i)
            if batch is None:
                existente = await ingest.lote_existente(conn, source_code="bacen_sgs", dataset=dataset, file_hash=file_hash)
                saidas.append({"indice": code, "status": "noop", "batch_id": existente, "rows_ingested": 0})
                continue
        try:
            async with ctx["db"].service_session() as conn:
                res = await ingest.gravar_indice(conn, batch, code, sgs.parse_sgs(texto))
        except Exception as exc:
            async with ctx["db"].service_session() as conn:
                await ingest.fechar_lote(conn, batch, status="failed", rows=None,
                                         error=f"{type(exc).__name__}: {exc}"[:500])
            raise
        async with ctx["db"].service_session() as conn:
            await ingest.fechar_lote(conn, batch, status="succeeded", rows=res.inseridos,
                                     details={"conflitos": res.conflitos, "de": de_i.isoformat(), "ate": ate_i.isoformat()})
        saidas.append({"indice": code, "status": "succeeded", "batch_id": batch, "file_hash": file_hash,
                       "rows_ingested": res.inseridos, "conflitos": res.conflitos})
    return saidas[0] if indice is not None else saidas


# ------------------------------------------------------------------ análise research (F6)
async def analisar(ctx: dict[str, Any], analysis_id: str) -> dict[str, Any]:
    """Roda o pipeline de uma análise research (idempotente: terminal ⇒ no-op)."""
    from app.analysis.pipeline import executar_analise

    r = await executar_analise(ctx["db"], ctx["llm"], ctx["policies"], analysis_id)
    return r.resumo()


async def varrer_analises_pendentes(ctx: dict[str, Any]) -> list[str]:
    """Análises research ainda em `received` (turno enfileirou e o job não pegou): reenfileira."""
    async with ctx["db"].service_session() as conn:
        cur = await conn.execute(
            "select id::text from analysis.analyses where mode = 'research' and status = 'received' order by created_at")
        ids = [r[0] for r in await cur.fetchall()]
    enfileirar = ctx.get("enfileirar_analise")
    if enfileirar is not None:
        for aid in ids:
            await enfileirar(aid)
    return ids


async def varrer_analises_travadas(ctx: dict[str, Any]) -> int:
    """Análise não terminal parada há mais de ANALISE_RESEARCH.analise_travada_minutos: tasks `running`
    órfãs voltam a `pending` (o claim é por CAS) e a análise é reenfileirada. Trilha em audit."""
    from app.analysis.pipeline import NAO_TERMINAIS

    minutos = int((await ctx["policies"].payload("ANALISE_RESEARCH"))["analise_travada_minutos"])
    async with ctx["db"].service_session() as conn:
        cur = await conn.execute(
            """select id::text, scope_id::text from analysis.analyses
                where mode = 'research' and status = any(%s::analysis.analysis_status[])
                  and updated_at < clock_timestamp() - make_interval(mins => %s)""", (list(NAO_TERMINAIS), minutos))
        linhas = await cur.fetchall()
        for aid, sid in linhas:
            await conn.execute("update analysis.tasks set status = 'pending' where analysis_id = %s and status = 'running'", (aid,))
            await audit.registrar(conn, actor_kind="job", action="analysis.requeued", object_kind="analysis", object_id=aid,
                                  scope_id=sid, details={"travada_minutos": minutos})
    enfileirar = ctx.get("enfileirar_analise")
    if enfileirar is not None:
        for aid, _ in linhas:
            await enfileirar(aid)
    return len(linhas)


async def processar_intake(ctx: dict[str, Any], submission_id: str) -> dict[str, Any]:
    """F21b — extrai UMA submissão do intake do onboarding (texto pronto ou transcrito
    pelos provedores configurados; sem provedor, fica em 'aguardando_provedor')."""
    from app.intake import provedores
    from app.intake.extrator import processar_submissao

    resultado = await processar_submissao(
        ctx["db"], ctx["llm"], ctx["policies"], submission_id,
        transcritor=provedores.transcritor_configurado(None),
        extrator_arquivo=provedores.extrator_arquivo_configurado(None))
    return resultado.resumo()
