"""CLI administrativa — `python -m app.cli ...` (ou `plexo ...` após pip install -e .).

Tudo que mexe em prompt/policy passa por aqui, como serviço, e deixa trilha em audit.activity_log.
Nunca imprime DATABASE_URL nem chaves.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import typer

from app.config.settings import ROOT, get_settings
from app.db.database import PooledDatabase
from app.db.errors import PromptNotApprovable
from app.db.repos import identity as identity_repo
from app.db.repos import policies as policies_repo
from app.db.repos import prompts as prompts_repo
from app.llm.prompts import content_hash_of

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
for _stream in (sys.stdout, sys.stderr):  # console cp1252 não imprime acentos/setas; saída sempre UTF-8
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover — stream substituído (testes/pipes)
        pass

app = typer.Typer(help="Plexo — administração do backend de agentes", no_args_is_help=True)
prompts_app = typer.Typer(help="prompts versionados com aprovação de compliance", no_args_is_help=True)
policy_app = typer.Typer(help="engine.policy_versions (config-first)", no_args_is_help=True)
db_app = typer.Typer(help="checagens de banco", no_args_is_help=True)
seed_app = typer.Typer(help="seeds idempotentes (serviço)", no_args_is_help=True)
auth_app = typer.Typer(help="senha e sessões (F7) — operações de serviço", no_args_is_help=True)
tools_app = typer.Typer(help="registro de tools ↔ espelho auditável no banco", no_args_is_help=True)
perfil_app = typer.Typer(help="motor do perfil: fatos → indicadores → scores por família", no_args_is_help=True)
objetivo_app = typer.Typer(help="projeção de objetivos (F17) — Monte Carlo com premissa versionada", no_args_is_help=True)
context_app = typer.Typer(help="agente de Contexto: fila de conversas encerradas → sinais/asserções/propostas", no_args_is_help=True)
raiox_app = typer.Typer(help="Raio-X da carteira: posições → findings de risco, custo, liquidez e alocação", no_args_is_help=True)
onboarding_app = typer.Typer(help="intake do onboarding (F21b): submissões de texto/arquivo/áudio → extração por IA", no_args_is_help=True)
app.add_typer(prompts_app, name="prompts")
app.add_typer(policy_app, name="policy")
app.add_typer(db_app, name="db")
app.add_typer(seed_app, name="seed")
app.add_typer(tools_app, name="tools")
app.add_typer(auth_app, name="auth")
app.add_typer(context_app, name="context")
app.add_typer(perfil_app, name="perfil")
app.add_typer(objetivo_app, name="objetivo")
app.add_typer(raiox_app, name="raiox")
app.add_typer(onboarding_app, name="onboarding")

PROMPTS_DIR = ROOT / "prompts"


def _run(coro):
    return asyncio.run(coro)


async def _db():
    return await PooledDatabase(get_settings()).open()


async def _resolver_usuario(db, ref: str) -> str:
    async with db.service_session() as conn:
        uid = await identity_repo.resolver_user_id(conn, ref)
    if uid is None:
        raise typer.BadParameter(f"usuário '{ref}' não encontrado (uuid ou e-mail)")
    return uid


# ------------------------------------------------------------------ prompts
@prompts_app.command("push")
def prompts_push(code: str, file: Path | None = typer.Option(None, help="default: prompts/<code>.j2"),
                 by: str | None = typer.Option(None, help="uuid/e-mail de quem publica")):
    """Publica o template do arquivo como rascunho (nova versão se a vigente está aprovada)."""
    path = file or (PROMPTS_DIR / f"{code}.j2")
    template = path.read_text(encoding="utf-8")

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, by) if by else None
            async with db.service_session() as conn:
                row = await prompts_repo.push(conn, code, template, created_by=uid)
            typer.echo(f"{row.code} v{row.version} [{row.compliance_status}] hash={row.content_hash[:12]} vars={row.variables}")
        finally:
            await db.close()
    _run(go())


@prompts_app.command("approve")
def prompts_approve(code: str, version: int = typer.Option(..., "--version", "-v"),
                    by: str = typer.Option(..., "--by", help="uuid/e-mail do aprovador (compliance)")):
    """Aprova a versão (checa [PENDENTE], vocabulário, variables) e aponta o agente para ela. Auditado."""
    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, by)
            async with db.service_session() as conn:
                try:
                    row = await prompts_repo.approve(conn, code, version, approved_by=uid)
                except PromptNotApprovable as e:
                    typer.echo(f"RECUSADO: {e}", err=True)
                    raise typer.Exit(2)
            typer.echo(f"APROVADO {row.code} v{row.version} hash={row.content_hash[:12]}")
        finally:
            await db.close()
    _run(go())


@prompts_app.command("reject")
def prompts_reject(code: str, version: int = typer.Option(..., "--version", "-v"),
                   by: str = typer.Option(..., "--by"), reason: str = typer.Option(..., "--reason")):
    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, by)
            async with db.service_session() as conn:
                row = await prompts_repo.reject(conn, code, version, by=uid, reason=reason)
            typer.echo(f"REJEITADO {row.code} v{row.version}: {reason}")
        finally:
            await db.close()
    _run(go())


@prompts_app.command("list")
def prompts_list():
    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                rows = await prompts_repo.listar(conn)
            for r in rows:
                vigente = "vigente" if r.effective_to is None else "encerrada"
                typer.echo(f"{r.code:<28} v{r.version:<3} {r.compliance_status:<9} {vigente:<9} {r.content_hash[:12]} vars={r.variables}")
        finally:
            await db.close()
    _run(go())


@prompts_app.command("check")
def prompts_check():
    """Drift: hash de cada prompts/*.j2 vs a versão vigente no banco. Sai 1 se houver diferença."""
    async def go():
        db = await _db()
        drift = 0
        try:
            async with db.service_session() as conn:
                for path in sorted(PROMPTS_DIR.glob("*.j2")):
                    code = path.stem
                    row = await prompts_repo.get_current(conn, code)
                    local = content_hash_of(path.read_text(encoding="utf-8"))
                    if row is None:
                        typer.echo(f"{code}: sem versão no banco"); drift += 1
                    elif row.content_hash != local:
                        typer.echo(f"{code}: DRIFT arquivo={local[:12]} banco(v{row.version},{row.compliance_status})={row.content_hash[:12]}"); drift += 1
                    else:
                        typer.echo(f"{code}: ok (v{row.version}, {row.compliance_status})")
        finally:
            await db.close()
        if drift:
            raise typer.Exit(1)
    _run(go())


# ------------------------------------------------------------------ policies
@policy_app.command("set")
def policy_set(code: str, json_payload: str | None = typer.Option(None, "--json"),
               file: Path | None = typer.Option(None, "--file"), by: str | None = typer.Option(None, "--by")):
    """Publica nova versão (draft) da policy. Payload por --json ou --file."""
    if (json_payload is None) == (file is None):
        raise typer.BadParameter("informe exatamente um de --json / --file")
    payload = json.loads(json_payload if json_payload is not None else file.read_text(encoding="utf-8"))

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, by) if by else None
            async with db.service_session() as conn:
                row = await policies_repo.set_policy(conn, code, payload, created_by=uid)
            typer.echo(f"{row.code} v{row.version} [{row.compliance_status}] hash={row.content_hash[:12]}")
        finally:
            await db.close()
    _run(go())


@policy_app.command("show")
def policy_show(code: str):
    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                row = await policies_repo.get_current(conn, code)
            if row is None:
                typer.echo(f"{code}: sem versão vigente"); raise typer.Exit(1)
            typer.echo(f"{row.code} v{row.version} [{row.compliance_status}]")
            typer.echo(policies_repo.payload_json(row))
        finally:
            await db.close()
    _run(go())


@policy_app.command("list")
def policy_list():
    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                rows = await policies_repo.listar(conn)
            for r in rows:
                typer.echo(f"{r.code:<24} v{r.version:<3} {r.compliance_status:<9} {r.content_hash[:12]}")
        finally:
            await db.close()
    _run(go())


@policy_app.command("approve")
def policy_approve(code: str, by: str = typer.Option(..., "--by", help="uuid/e-mail do aprovador (compliance)")):
    """Aprova a versão vigente da policy — pré-requisito de uso client-facing (gates 02/29). Auditado."""
    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, by)
            async with db.service_session() as conn:
                row = await policies_repo.approve_current(conn, code, approved_by=uid)
            typer.echo(f"APROVADA {row.code} v{row.version} hash={row.content_hash[:12]}")
        finally:
            await db.close()
    _run(go())


# ------------------------------------------------------------------ tools
@tools_app.command("sync")
def tools_sync(check: bool = typer.Option(False, "--check", help="só verifica drift (CI); não escreve"),
               allow_dirty: bool = typer.Option(False, "--allow-dirty", help="permite árvore git suja (dev)"),
               desativar_ausentes: bool = typer.Option(True, "--desativar-ausentes/--manter-ausentes")):
    """Sincroniza o registro (@tool) com tools.tools/tool_versions — git_sha + sha256 do fonte."""
    import subprocess

    from app.tools import carregar_tools
    from app.tools.registry import specs_registradas
    from app.tools.sync import SyncConflito, sincronizar

    carregar_tools()
    git_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
    sujo = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                               text=True, check=True).stdout.strip())
    if sujo and not (allow_dirty or check):
        typer.echo("árvore git suja: o git_sha não provaria o fonte publicado. Commit antes, "
                   "ou use --allow-dirty em dev.", err=True)
        raise typer.Exit(2)

    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                try:
                    rel = await sincronizar(conn, specs_registradas(), git_sha=git_sha,
                                            desativar_ausentes=desativar_ausentes,
                                            somente_verificar=check)
                except SyncConflito as e:
                    typer.echo(f"CONFLITO: {e}", err=True)
                    raise typer.Exit(2)
            for rotulo, itens in (("criadas", rel.criadas), ("versionadas", rel.versionadas),
                                  ("desativadas", rel.desativadas), ("inalteradas", rel.inalteradas),
                                  ("sha corrigido (CRLF→LF, mesmo fonte)", rel.corrigidas),
                                  ("DRIFT", rel.drift)):
                if itens:
                    typer.echo(f"{rotulo}: {', '.join(itens)}")
            if check and rel.tem_drift:
                raise typer.Exit(1)
            if sujo and not check:
                typer.echo("(aviso: árvore suja — changelog da versão marcado como ambiente de dev)")
        finally:
            await db.close()
    _run(go())


# ------------------------------------------------------------------ db / seed
@db_app.command("check-roles")
def db_check_roles():
    """Prova que as sessões assumem os papéis certos e que RLS está ativa para a API."""
    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                cur = await conn.execute("select current_user, current_setting('app.role', true), core.is_service()")
                typer.echo(f"service_session: {await cur.fetchone()}")
            async with db.app_session(user_id="00000000-0000-0000-0000-000000000000",
                                      scope_id="00000000-0000-0000-0000-000000000000") as conn:
                cur = await conn.execute("select current_user, current_setting('app.role', true), core.is_service(), "
                                         "(select count(*) from identity.scopes)")
                typer.echo(f"app_session (escopo inexistente): {await cur.fetchone()}  (count deve ser 0)")
        finally:
            await db.close()
    _run(go())


@seed_app.command("dev")
def seed_dev(file: Path = typer.Option(ROOT / "seeds" / "dev.sql", "--file")):
    """Aplica seeds/dev.sql como serviço (idempotente; sem BEGIN/COMMIT no arquivo)."""
    sql = file.read_text(encoding="utf-8")

    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                await conn.execute(sql)
            typer.echo(f"seed aplicado: {file.name}")
        finally:
            await db.close()
    _run(go())


@seed_app.command("personas")
def seed_personas():
    """Aplica as SEIS personas da F16 — cada uma força um comportamento do motor.

    Idempotente por uuid5 do nome; escopos próprios, nenhum teste ou eval existente muda."""
    from app.seeds.personas import ARQUETIPOS, aplicar, confirmar_seguro

    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                for a in ARQUETIPOS:
                    r = await aplicar(conn, a)
                    seguro = await confirmar_seguro(conn, a)
                    marca = " · seguro informado" if seguro else (
                        " · seguro NÃO informado" if a.seguro_vida is None else "")
                    typer.echo(f"  {a.nome:26} {r['scope_id'][:8]}  {a.forca}{marca}")
            typer.echo(f"{len(ARQUETIPOS)} personas aplicadas. "
                       "Rode `perfil derivar --user <nome>@teste.local` em cada uma.")
        finally:
            await db.close()

    _run(go())


@seed_app.command("conta-teste")
def seed_conta_teste(
    pipeline: bool = typer.Option(True, "--pipeline/--sem-pipeline",
                                  help="roda derivar → projetar → calcular no fim"),
):
    """Cria a conta de DEMONSTRAÇÃO: dados fictícios completos, plano pago, dois objetivos.

    Fora das seis personas de propósito — esta é para mexer à mão pela tela, e golden não
    pode depender de dado que alguém vai editar durante um teste.

    A senha NÃO é definida aqui: rode `plexo auth definir-senha <e-mail>`, que pergunta com
    entrada oculta e confirmação.
    """
    from app.context.derivacao import derivar_escopo
    from app.engine.perfil import calcular_perfil
    from app.engine.projecao import projetar_escopo
    from app.seeds.conta_teste import HELENA, criar
    from app.seeds.personas import confirmar_seguro

    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                ids = await criar(conn)
                await confirmar_seguro(conn, HELENA)
                # Sem CDI ingerido, `fundacao.py` mede dívida cara contra o piso do spread e
                # qualquer dívida realista fica cara: a Fundação sai crítica e TODAS as
                # famílias ficam sem nota (D11). Não é bug — é o motor se recusando a
                # concluir "não há dívida cara" por ignorância. Mas quem for testar a tela
                # precisa saber por que a conta apareceu vazia.
                cur = await conn.execute(
                    "select 1 from market.index_values where index_code = 'cdi' limit 1")
                if not await cur.fetchone():
                    typer.echo("  AVISO: sem CDI em market.index_values, a Fundação sai "
                               "CRÍTICA e nenhuma família recebe nota.")
                    typer.echo("         Rode antes: plexo mercado ingerir --fonte sgs "
                               "--indice cdi")
                typer.echo(f"conta: {HELENA.titulo} · {HELENA.email} · plano {HELENA.plano}")
                typer.echo(f"  escopo {ids['scope_id']}")
                if not pipeline:
                    return
                # ORDEM: derivar → projetar → calcular. A projeção LÊ renda/despesa derivadas
                # e ESCREVE a probabilidade que o perfil lê.
                d = await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
                typer.echo(f"  derivação: {len(d.gravados)} fato(s)")
                projecoes = await projetar_escopo(conn, ids["scope_id"])
                for pr in projecoes:
                    if pr.indisponivel:
                        typer.echo(f"  {pr.nome}: sem projeção ({pr.motivo_indisponivel})")
                    else:
                        eleita = next(x for x in pr.distribuicoes
                                      if x.alocacao == pr.veredito.alocacao)
                        typer.echo(f"  {pr.nome}: chega em {eleita.prob_sucesso:.0%} "
                                   f"· carteira {pr.veredito.alocacao}")
                r = await calcular_perfil(conn, ids["scope_id"], client_facing=False)
                com_valor = [x for x in r.scores if x["value"] is not None]
                typer.echo(f"  perfil: {len(com_valor)}/{len(r.scores)} score(s) com valor "
                           f"· cobertura do catálogo {r.cobertura_do_catalogo:.0%}")
                for x in r.scores:
                    if x["value"] is None:
                        typer.echo(f"    {x['display_name']:16} indisponível ({x['disabled_reason']})")
                    else:
                        typer.echo(f"    {x['display_name']:16} {x['value']:.2f} "
                                   f"· cobertura {x['coverage']:.0%}")
            typer.echo(f"\nDefina a senha: plexo auth definir-senha {HELENA.email}")
        finally:
            await db.close()

    _run(go())


@seed_app.command("persona")
def seed_persona(file: Path = typer.Option(ROOT / "seeds" / "persona.sql", "--file")):
    """Aplica seeds/persona.sql: cliente de demonstração com patrimônio completo em plano pago.

    Escopo próprio (`0fe0a000-…`), separado do de dev — os testes e evals existentes não mudam."""
    sql = file.read_text(encoding="utf-8")

    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                await conn.execute(sql)
                cur = await conn.execute(
                    "select investivel_brl::float, patrimonio_liquido_brl::float "
                    "from estate.v_net_worth where scope_id = %s",
                    ("0fe0a000-0000-4000-8000-000000000002",))
                investivel, liquido = await cur.fetchone()
            typer.echo(f"seed aplicado: {file.name} — investível R$ {investivel:,.2f} · "
                       f"patrimônio líquido R$ {liquido:,.2f}")
        finally:
            await db.close()
    _run(go())


# ------------------------------------------------------------------ auth (F7)
@auth_app.command("definir-senha")
def auth_definir_senha(user: str = typer.Argument(..., help="uuid ou e-mail"),
                       senha: str = typer.Option(..., "--senha", prompt=True, hide_input=True, confirmation_prompt=True)):
    """Define (ou troca) a senha de um usuário e revoga as sessões abertas dele."""
    from app.auth import senha as senha_mod
    from app.db.repos import sessoes as sessoes_repo
    if len(senha) < 10:
        raise typer.BadParameter("senha com menos de 10 caracteres")

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, user)
            async with db.service_session() as conn:
                await identity_repo.atualizar_password_hash(conn, uid, senha_mod.gerar(senha))
                await conn.execute(
                    "insert into identity.auth_identities (user_id, provider, provider_uid) values (%s, 'password', %s) "
                    "on conflict (provider, provider_uid) do nothing", (uid, uid))
                n = await sessoes_repo.revogar_todas_do_usuario(conn, uid, "senha_redefinida")
            typer.echo(f"senha definida para {uid}; sessões revogadas: {n}")
        finally:
            await db.close()
    _run(go())


@auth_app.command("revogar-sessoes")
def auth_revogar_sessoes(user: str = typer.Argument(..., help="uuid ou e-mail")):
    """Revoga todas as sessões abertas do usuário (o próximo request dele recebe 401)."""
    from app.db.repos import sessoes as sessoes_repo

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, user)
            async with db.service_session() as conn:
                n = await sessoes_repo.revogar_todas_do_usuario(conn, uid, "revogacao_manual")
            typer.echo(f"sessões revogadas: {n}")
        finally:
            await db.close()
    _run(go())


@app.command("chat")
def chat(pergunta: str = typer.Argument(""),
         agent: str | None = typer.Option(None, "--agent", help="força o agente (assessor|analista|educador)"),
         chip: str | None = typer.Option(None, "--chip"),
         conversa: str | None = typer.Option(None, "--conversa", help="continua uma conversa existente"),
         research: bool = typer.Option(False, "--research", help="análise aprofundada assíncrona (só Analista); rode `analise run` depois"),
         user: str = typer.Option("dev@teste.local", "--user", help="uuid/e-mail (seeds/dev.sql)"),
         scope: str = typer.Option("0de0a000-0000-4000-8000-000000000002", "--scope")):
    """Conversa com o Copiloto pelo terminal (DeepSeek real). Eventos do turno são impressos."""
    from app.agents import eventos as ev
    from app.agents.turn import TurnoCopiloto, TurnoInput
    from app.config.policies import PolicyStore
    from app.llm.deepseek import DeepSeekClient
    from app.tools import carregar_tools

    carregar_tools()

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, user)
            turno = TurnoCopiloto(db=db, llm=DeepSeekClient(get_settings()), policies=PolicyStore(db), streaming=get_settings().llm_stream)
            async for e in turno.executar(TurnoInput(texto=pergunta, user_id=uid, scope_id=scope,
                                                     agent_code=agent, chip_id=chip, conversation_id=conversa,
                                                     mode="research" if research else "standard")):
                if isinstance(e, ev.Delta):
                    typer.echo(e.texto, nl=False)
                elif isinstance(e, ev.Done):
                    typer.echo(f"\n\n[done] conversa={e.conversation_id} msg={e.message_id} refs={len(e.cited_refs)}")
                else:
                    typer.echo(f"[{e.nome}] {e.to_dict()}")
        finally:
            await db.close()
    _run(go())


# ------------------------------------------------------------------ contexto / jobs
def _ctx_direto(db, llm, enfileirados: list[str]) -> dict:
    """ctx das tasks sem Redis: `enfileirar` só anota — a CLI processa em seguida, na mesma passada."""
    from app.config.policies import PolicyStore

    async def enfileirar(conversation_id: str) -> None:
        enfileirados.append(conversation_id)

    async def enfileirar_analise(analysis_id: str) -> None:
        enfileirados.append(analysis_id)

    return {"db": db, "llm": llm, "policies": PolicyStore(db), "enfileirar": enfileirar,
            "enfileirar_analise": enfileirar_analise}


@context_app.command("run")
def context_run(conversa: str | None = typer.Option(None, "--conversa", help="processa só esta conversa (uuid)"),
                sem_manutencao: bool = typer.Option(False, "--sem-manutencao", help="só a fila de extração")):
    """Roda o ciclo do agente de Contexto UMA vez, sem Redis: encerra inativas → extrai a fila
    (DeepSeek real) → expira asserções/propostas → varre execuções travadas. Essencial no dev Windows."""
    from app.context.extractor import ConversaJaProcessada, ConversaNaoEncontrada
    from app.jobs import tasks
    from app.llm.deepseek import DeepSeekClient
    from app.tools import carregar_tools

    carregar_tools()

    async def go():
        db = await _db()
        try:
            fila: list[str] = []
            ctx = _ctx_direto(db, DeepSeekClient(get_settings()), fila)
            if conversa:
                fila.append(conversa)
            else:
                if not sem_manutencao:
                    typer.echo(f"encerradas por inatividade: {await tasks.encerrar_inativas(ctx)}")
                typer.echo(f"na fila de extração: {await tasks.varrer_encerradas(ctx)}")
            for cid in fila:
                try:
                    r = await tasks.extrair_conversa(ctx, cid)
                except ConversaJaProcessada:
                    typer.echo(f"  {cid}: já processada"); continue
                except ConversaNaoEncontrada:
                    typer.echo(f"  {cid}: conversa não encontrada", err=True); continue
                typer.echo(f"  {cid}: {r['status']} run={r['run_id']} sinais={r['signals']} "
                           f"asserções={r['assertions']} propostas={r['proposals']} descartados={r['descartados']}"
                           + (f" erro={r['erro']}" if r.get("erro") else ""))
            if not conversa and not sem_manutencao:
                exp = await tasks.expirar(ctx)
                typer.echo(f"expiradas: asserções={exp['assercoes']} propostas={exp['propostas']}")
                typer.echo(f"execuções travadas → timeout: {await tasks.varrer_execucoes_travadas(ctx)}")
        finally:
            await db.close()
    _run(go())


@onboarding_app.command("processar")
def onboarding_processar(id: str | None = typer.Option(None, "--id", help="processa só esta submissão (uuid)")):
    """Extrai submissões pendentes do intake do onboarding UMA vez, sem Redis (F21b).
    Sem provedor de transcrição/leitura configurado, submissão binária fica em
    'aguardando_provedor' — plugar o serviço é a F21d."""
    from app.config.policies import PolicyStore
    from app.intake import provedores
    from app.intake.extrator import SubmissaoNaoEncontrada, processar_submissao
    from app.llm.deepseek import DeepSeekClient

    async def go():
        db = await _db()
        try:
            llm = DeepSeekClient(get_settings())
            policies = PolicyStore(db)
            fila: list[str] = []
            if id:
                fila.append(id)
            else:
                async with db.service_session() as conn:
                    cur = await conn.execute(
                        "select id::text from context.intake_submissions "
                        " where status in ('recebido', 'aguardando_provedor') order by created_at")
                    fila = [r[0] for r in await cur.fetchall()]
            if not fila:
                typer.echo("nada pendente no intake"); return
            transcritor = provedores.transcritor_configurado(get_settings())
            extrator_arq = provedores.extrator_arquivo_configurado(get_settings())
            for sid in fila:
                try:
                    r = await processar_submissao(db, llm, policies, sid,
                                                  transcritor=transcritor, extrator_arquivo=extrator_arq)
                except SubmissaoNaoEncontrada:
                    typer.echo(f"  {sid}: submissão não encontrada", err=True); continue
                typer.echo(f"  {sid}: {r.status} itens={len(r.itens)} descartados={len(r.descartados)}"
                           + (f" erro={r.erro}" if r.erro else ""))
        finally:
            await db.close()
    _run(go())


@context_app.command("status")
def context_status():
    """Fila e produção do agente de Contexto (como serviço)."""
    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                cur = await conn.execute(
                    """select (select count(*) from agents.conversations where status = 'aberta'),
                              (select count(*) from agents.conversations c where c.status = 'encerrada'
                                 and not exists (select 1 from context.extraction_runs r
                                                  where r.conversation_id = c.id and r.status = 'succeeded')),
                              (select count(*) from agents.conversations where status = 'processada'),
                              (select count(*) from context.extraction_runs where status = 'failed'),
                              (select count(*) from context.signals),
                              (select count(*) from context.assertions where source = 'conversa'),
                              (select count(*) from context.change_proposals where status = 'proposta'),
                              (select count(*) from context.v_open_questions)""")
                abertas, fila, processadas, falhas, sinais, assercoes, pendentes, perguntas = await cur.fetchone()
            typer.echo(f"conversas: abertas={abertas} na fila={fila} processadas={processadas} · runs failed={falhas}")
            typer.echo(f"contexto: sinais={sinais} asserções(conversa)={assercoes} propostas pendentes={pendentes} "
                       f"perguntas abertas={perguntas}")
        finally:
            await db.close()
    _run(go())


@context_app.command("canario")
def context_canario():
    """Canário do card ao vivo (F20): allowlist e limiar da policy + precisão medida por classe."""
    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                policy = await policies_repo.get_current(conn, "CONTEXT_FACT_CATALOG")
                payload = policy.payload if policy else {}
                escopos = payload.get("escopos_canario_card_ao_vivo")
                limiar = payload.get("precisao_minima_publicacao")
                cur = await conn.execute(
                    "select scope_id::text, classe, n_respondidas, n_mesma_classe, "
                    "n_reclassificadas, n_rejeitadas, n_sem_rotulo, precisao "
                    "from context.v_precisao_extrator order by scope_id, classe")
                linhas = await cur.fetchall()
            if isinstance(escopos, list) and escopos:
                typer.echo(f"canário do card ao vivo: {len(escopos)} escopo(s) na allowlist")
                for e in escopos:
                    typer.echo(f"  - {e}")
            else:
                typer.echo("canário do card ao vivo: SEM allowlist na policy vigente "
                           "(fail-closed — o card não nasce para ninguém)")
            typer.echo(f"precisão mínima de publicação: "
                       f"{limiar if limiar is not None else 'não definida na policy'}")
            if not linhas:
                typer.echo("precisão por classe: sem resposta registrada ainda")
            else:
                typer.echo("precisão por classe "
                           "(escopo · classe · respondidas · mesma classe · reclassificadas · "
                           "rejeitadas · sem rótulo · precisão):")
                for scope_id, classe, n_resp, n_mesma, n_reclas, n_rej, n_sem, precisao in linhas:
                    p = f"{float(precisao):.2f}" if precisao is not None else "—"
                    typer.echo(f"  {scope_id} · {classe:<11} resp={n_resp} mesma={n_mesma} "
                               f"reclass={n_reclas} rejeit={n_rej} sem_rotulo={n_sem} precisao={p}")
        finally:
            await db.close()
    _run(go())


@app.command("worker")
def worker():
    """Worker Arq de verdade (REDIS_URL no .env): cron de manutenção + fila de extração."""
    from arq import run_worker

    from app.jobs.worker import WorkerSettings, redis_settings_de

    run_worker(WorkerSettings, redis_settings=redis_settings_de(get_settings()))


# ------------------------------------------------------------------ docs (F13a)
docs_app = typer.Typer(help="camada documental: ingestão de documento oficial e curadoria", no_args_is_help=True)
app.add_typer(docs_app, name="docs")


@docs_app.command("ingerir")
def docs_ingerir(fonte: str = typer.Option("copom", "--fonte", help="copom"),
                 tipo: str = typer.Option("comunicado", "--tipo", help="comunicado | ata"),
                 quantidade: int = typer.Option(6, "--ultimos", help="quantos documentos mais recentes buscar")):
    """Busca documentos na fonte e grava como PENDENTE. Lote idempotente: o mesmo conjunto é no-op.
    Nada nasce citável — aprovar é passo separado (`docs aprovar`)."""
    from app.jobs import tasks

    if fonte != "copom":
        raise typer.BadParameter("fonte desconhecida (use: copom)")

    async def go():
        db = await _db()
        try:
            r = await tasks.ingerir_copom(_ctx_direto(db, None, []), tipo=tipo, quantidade=quantidade)
            typer.echo(f"{r['status']}: lote={r.get('batch_id')} novos={r['rows_ingested']} "
                       f"ja_existentes={r.get('ja_existentes', 0)}")
        finally:
            await db.close()
    _run(go())


@docs_app.command("status")
def docs_status(pendentes: bool = typer.Option(False, "--pendentes", help="lista os que aguardam curadoria")):
    """Quantos documentos há por fonte e status; com --pendentes, o que falta revisar."""
    from app.docs import ingest as docs_ingest

    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                linhas = await docs_ingest.resumo(conn)
                fila = await docs_ingest.pendentes(conn) if pendentes else []
            for linha in linhas:
                typer.echo(f"{linha['fonte']:<16} {linha['status']:<10} {linha['n']:>4}  mais recente: {linha['mais_recente']}")
            if not linhas:
                typer.echo("nenhum documento ingerido — rode `docs ingerir`")
            for d in fila:
                vetado = f"  VOCABULÁRIO VETADO: {', '.join(d['termos'])}" if d["vetados"] else ""
                typer.echo(f"  {d['id']}  {d['publicado_em']}  {d['kind']:<11} {d['titulo'][:60]}{vetado}")
        finally:
            await db.close()
    _run(go())


@docs_app.command("aprovar")
def docs_aprovar(documento: str = typer.Argument(..., help="uuid do documento (veja `docs status --pendentes`)"),
                 by: str = typer.Option(..., "--by", help="uuid/e-mail do revisor (compliance)"),
                 notas: str | None = typer.Option(None, "--notas")):
    """Aprova o documento COM a trilha, na mesma transação. O banco recusa sem revisor, sem trilha
    e com vocabulário vetado (T73–T77) — este comando não contorna nada, só monta a ordem certa."""
    from app.docs import ingest as docs_ingest

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, by)
            async with db.service_session() as conn:
                externo = await docs_ingest.aprovar(conn, documento_id=documento, revisor_id=uid, notas=notas)
            typer.echo(f"APROVADO {externo} ({documento})")
        finally:
            await db.close()
    _run(go())


# ------------------------------------------------------------------ mercado (F5)
mercado_app = typer.Typer(help="dados de mercado: ingestão B3 COTAHIST / BACEN SGS e cobertura", no_args_is_help=True)
app.add_typer(mercado_app, name="mercado")


@mercado_app.command("ingerir")
def mercado_ingerir(fonte: str = typer.Option(..., "--fonte", help="sgs | cotahist | focus"),
                    arquivo: Path | None = typer.Option(None, "--arquivo", help="COTAHIST local (.ZIP ou .TXT) — sem rede"),
                    ano: int | None = typer.Option(None, "--ano", help="COTAHIST anual (COTAHIST_A{ano}.ZIP)"),
                    data: str | None = typer.Option(None, "--data", help="COTAHIST diário (AAAA-MM-DD); padrão: ontem útil"),
                    indice: str | None = typer.Option(None, "--indice", help="SGS: só este índice (cdi, selic_meta, ipca); padrão: todos"),
                    indicador: str | None = typer.Option(None, "--indicador", help="Focus: só este indicador (Selic, IPCA, Câmbio, PIB Total); padrão: todos"),
                    de: str | None = typer.Option(None, "--de", help="SGS: início (AAAA-MM-DD); padrão: último valor + 1 ou backfill_anos"),
                    ate: str | None = typer.Option(None, "--ate", help="SGS: fim (AAAA-MM-DD); padrão: hoje")):
    """Roda a ingestão UMA vez, sem Redis (mesmas tasks do worker). Lote idempotente: o mesmo arquivo
    ou a mesma resposta do provedor é no-op — a regra é do banco (31)."""
    from datetime import date as _date

    from app.jobs import tasks

    async def go():
        db = await _db()
        try:
            ctx = _ctx_direto(db, None, [])
            if fonte == "cotahist":
                r = await tasks.ingerir_cotahist(ctx, arquivo=str(arquivo) if arquivo else None, ano=ano,
                                                 data=_date.fromisoformat(data) if data else None)
                typer.echo(f"{r['status']}: lote={r['batch_id']} linhas={r['rows_ingested']} "
                           f"fora_do_universo={r['ignorados_fora_universo']} conflitos={r['conflitos']}")
            elif fonte == "sgs":
                r = await tasks.ingerir_sgs(ctx, indice=indice, de=_date.fromisoformat(de) if de else None,
                                            ate=_date.fromisoformat(ate) if ate else None)
                for item in (r if isinstance(r, list) else [r]):
                    typer.echo(f"{item['indice']}: {item['status']} lote={item['batch_id']} linhas={item['rows_ingested']}")
            elif fonte == "focus":
                r = await tasks.ingerir_focus(ctx, indicador=indicador)
                typer.echo(f"focus {r.get('indicador') or 'todos'}: {r['status']} lote={r.get('batch_id')} "
                           f"linhas={r['rows_ingested']} lidas={r.get('lidos', 0)}")
            else:
                raise typer.BadParameter("--fonte deve ser sgs ou cotahist")
        finally:
            await db.close()
    _run(go())


@mercado_app.command("status")
def mercado_status():
    """Cobertura: último preço por instrumento do universo, últimos lotes e partições de market.prices."""
    from app.market import ingest

    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                cob = await ingest.cobertura_particoes(conn)
                typer.echo(f"partições de market.prices: {cob.particoes} ({cob.inicio} → {cob.fim})")
                cur = await conn.execute(
                    """select i.ticker, max(p.price_date), count(p.price_date)
                         from market.instruments i left join market.prices p on p.instrument_id = i.id and p.kind = 'close'
                        where i.is_in_universe group by i.ticker order by i.ticker""")
                typer.echo("universo (ticker · último fechamento · nº de pregões):")
                for ticker, ultimo, n in await cur.fetchall():
                    typer.echo(f"  {ticker:<8} {ultimo or '—'}  {n}")
                cur = await conn.execute(
                    "select index_code, max(value_date), count(*) from market.index_values group by 1 order by 1")
                typer.echo("índices (código · último valor · nº de pontos):")
                for code, ultimo, n in await cur.fetchall():
                    typer.echo(f"  {code:<10} {ultimo}  {n}")
                cur = await conn.execute(
                    """select source_code, dataset, status, rows_ingested, started_at::date, left(id::text, 8)
                         from market.ingestion_batches order by started_at desc limit 10""")
                typer.echo("últimos lotes:")
                for src, ds, st, n, dia, bid in await cur.fetchall():
                    typer.echo(f"  {dia} {src:<10} {ds:<14} {st:<9} linhas={n} lote={bid}…")
        finally:
            await db.close()
    _run(go())


# ------------------------------------------------------------------ análise research (F6)
analise_app = typer.Typer(help="Analista research: roda/consulta análises aprofundadas sem Redis", no_args_is_help=True)
app.add_typer(analise_app, name="analise")


@analise_app.command("run")
def analise_run(id: str | None = typer.Option(None, "--id", help="só esta análise; padrão: todas em 'received' + travadas")):
    """Roda o pipeline (planner → DAG → relatório, DeepSeek real) UMA vez, sem worker. Idempotente."""
    from app.jobs import tasks
    from app.llm.deepseek import DeepSeekClient
    from app.tools import carregar_tools

    carregar_tools()

    async def go():
        db = await _db()
        try:
            fila: list[str] = []
            ctx = _ctx_direto(db, DeepSeekClient(get_settings()), fila)
            if id:
                fila.append(id)
            else:
                await tasks.varrer_analises_travadas(ctx)
                await tasks.varrer_analises_pendentes(ctx)
                typer.echo(f"na fila: {len(fila)}")
            for aid in dict.fromkeys(fila):
                r = await tasks.analisar(ctx, aid)
                typer.echo(f"  {aid}: {r['status']}" + (" (já concluída)" if r.get("noop") else "")
                           + f" replans={r['replans']} report={r['report_id']}" + (f" erro={r['erro']}" if r.get("erro") else ""))
        finally:
            await db.close()
    _run(go())


@analise_app.command("status")
def analise_status(id: str | None = typer.Option(None, "--id")):
    """Análises research: status, plano ativo, tasks e relatório."""
    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                if id:
                    cur = await conn.execute(
                        """select a.status::text, a.replan_count, a.max_replans, a.question,
                                  (select count(*) from analysis.evidence_findings f where f.analysis_id = a.id),
                                  (select r.status from analysis.reports r where r.analysis_id = a.id and r.superseded_by is null)
                             from analysis.analyses a where a.id = %s""", (id,))
                    row = await cur.fetchone()
                    if row is None:
                        typer.echo("análise não encontrada", err=True); return
                    typer.echo(f"status={row[0]} replans={row[1]}/{row[2]} findings={row[4]} relatório={row[5]}  · {row[3]}")
                    cur = await conn.execute(
                        """select t.node_id, t.tool_code, t.status::text, t.criticality::text, t.attempt, t.error_code
                             from analysis.tasks t join analysis.plans p on p.id = t.plan_id and p.is_active
                            where t.analysis_id = %s order by t.id""", (id,))
                    for n, tool, st, crit, att, err in await cur.fetchall():
                        typer.echo(f"  {n:<12} {tool:<28} {st:<9} {crit:<9} tentativas={att}" + (f" erro={err}" if err else ""))
                else:
                    cur = await conn.execute(
                        """select id::text, status::text, replan_count, left(question, 60), created_at::timestamp(0)
                             from analysis.analyses where mode = 'research' order by created_at desc limit 20""")
                    for aid, st, rp, q, ts in await cur.fetchall():
                        typer.echo(f"{ts} {st:<20} replans={rp} {aid} · {q}")
        finally:
            await db.close()
    _run(go())

async def _escopo_padrao(conn, user_id: str) -> str:
    """Primeiro escopo do usuário — `escopos_do_usuario` já ordena dono/pessoal primeiro."""
    escopos = await identity_repo.escopos_do_usuario(conn, user_id)
    if not escopos:
        raise typer.BadParameter(f"usuário {user_id} não tem escopo — rode `plexo seed dev`")
    return escopos[0]["id"]

# ---------------------------------------------------------------------------- raio-x (F19)
@raiox_app.command("run")
def raiox_run(
    usuario: str = typer.Option(..., "--user", help="e-mail ou uuid do titular"),
    escopo: str | None = typer.Option(None, "--scope", help="uuid do escopo (padrão: o pessoal do usuário)"),
    client_facing: bool = typer.Option(
        False, "--client-facing/--interno",
        help="client-facing exige RAIOX_LIMIARES aprovada; em rascunho o gate 29a recusa o run"),
):
    """Roda o Raio-X da carteira e grava os findings — o produtor que a taxonomia da
    migration 15 esperava desde sempre."""
    from app.engine.raiox import executar

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, usuario)
            async with db.service_session() as conn:
                sid = escopo or await _escopo_padrao(conn, uid)
                r = await executar(conn, sid, client_facing=client_facing)
            if r["sem_carteira"]:
                typer.echo("nenhuma posição registrada no escopo — nada a diagnosticar.")
                typer.echo("  Registre a carteira (ex.: `plexo seed conta-teste`) e rode de novo.")
                return
            c = r["cobertura"]
            typer.echo(f"run {r['run_id']} · carteira R$ {c['total_value_brl']:,.2f} · "
                       f"cobertura {c['covered_value_brl'] / c['total_value_brl']:.0%}")
            if c["uncovered"]:
                typer.echo(f"  não diagnosticado: {c['uncovered']}")
            typer.echo(f"{len(r['achados'])} ponto(s) de atenção:")
            for a in r["achados"]:
                impacto = f" · R$ {a.impacto_brl_ano:,.2f}/ano" if a.impacto_brl_ano else ""
                typer.echo(f"  [{a.severidade:8}] {a.tipo}{impacto}")
                for k, v in a.quantificacao.items():
                    if not str(k).startswith("_"):
                        typer.echo(f"             {k}: {v}")
        finally:
            await db.close()

    _run(go())


@raiox_app.command("status")
def raiox_status(
    usuario: str = typer.Option(..., "--user", help="e-mail ou uuid do titular"),
    escopo: str | None = typer.Option(None, "--scope"),
):
    """Os findings correntes do escopo, na ordem da fila (prioridade), como a tela lê."""
    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, usuario)
            async with db.service_session() as conn:
                sid = escopo or await _escopo_padrao(conn, uid)
                cur = await conn.execute(
                    "select f.finding_type_code, ft.display_name, ft.family::text, "
                    "       f.severity::text, f.impact_brl_year::float, f.priority_score::float, "
                    "       f.quantification, ft.min_plan::text, f.last_detected_at::date "
                    "  from diagnostics.findings f "
                    "  join diagnostics.finding_types ft on ft.code = f.finding_type_code "
                    " where f.scope_id = %s and f.is_current and not f.permanently_suppressed "
                    # Gravidade primeiro, valor depois — a mesma ordem da tool: achado sem
                    # impacto em reais tem `priority_score` zero e afundaria a lista.
                    " order by case f.severity when 'critica' then 0 when 'alta' then 1 "
                    "            when 'media' then 2 else 3 end, "
                    "          f.priority_score desc, f.finding_type_code", (sid,))
                achados = await cur.fetchall()
                cur = await conn.execute(
                    "select total_value_brl::float, coverage_pct::float, uncovered_breakdown, as_of_date "
                    "  from diagnostics.coverage_reports where scope_id = %s "
                    " order by as_of_date desc limit 1", (sid,))
                cobertura = await cur.fetchone()
            if not achados:
                typer.echo("nenhum ponto de atenção corrente — rode `plexo raiox run` antes.")
                return
            if cobertura:
                total, pct, nao_coberto, data = cobertura
                typer.echo(f"carteira R$ {total:,.2f} · cobertura {pct:.0%} · {data}")
                if nao_coberto:
                    typer.echo(f"  não diagnosticado: {nao_coberto}")
            for tipo, rotulo, familia, sev, impacto, score, quant, plano, visto in achados:
                linha = f"  [{sev:8}] {rotulo} ({familia}, {plano})"
                if impacto:
                    linha += f" · R$ {impacto:,.2f}/ano · prioridade {score:.0f}"
                typer.echo(linha)
                typer.echo(f"             {tipo} · visto em {visto} · {quant}")
        finally:
            await db.close()

    _run(go())


# ---------------------------------------------------------------------------- perfil (F14)
@perfil_app.command("calcular")
def perfil_calcular(
    usuario: str = typer.Option(..., "--user", help="e-mail ou uuid do titular"),
    escopo: str | None = typer.Option(None, "--scope", help="uuid do escopo (padrão: o pessoal do usuário)"),
    client_facing: bool | None = typer.Option(
        None, "--client-facing/--interno",
        help="por padrão, client-facing só quando CLIENT_SCORES está aprovada (o gate C40d recusaria o resto)"),
):
    """Roda o motor do perfil para um escopo e grava indicadores + scores com run auditável."""
    from app.engine.perfil import calcular_perfil

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, usuario)
            async with db.service_session() as conn:
                sid = escopo or await _escopo_padrao(conn, uid)
                r = await calcular_perfil(conn, sid, client_facing=client_facing)
            typer.echo(f"run {r.run_id} · {r.as_of_date} · cobertura do catálogo {r.cobertura_do_catalogo:.0%}")
            if r.fundacao_critica:
                typer.echo("  Fundação CRÍTICA — os scores saem desativados (D11), não baixos.")
            for s in r.scores:
                if s["is_disabled"]:
                    typer.echo(f"  {s['display_name']:16} indisponível ({s['disabled_reason']}) · cobertura {s['coverage']:.0%}")
                else:
                    marca = " ← elo mais fraco" if s.get("is_critical_family") and s["value"] == min(
                        (x["value"] for x in r.scores if x["value"] is not None and x["is_critical_family"]), default=None) else ""
                    typer.echo(f"  {s['display_name']:16} {s['value']:.2f} · cobertura {s['coverage']:.0%} · confiança {s['confidence']:.2f}{marca}")
            faltando = r.indisponiveis
            if faltando:
                typer.echo(f"  não medidos: {', '.join(faltando)}")
        finally:
            await db.close()

    _run(go())


@perfil_app.command("status")
def perfil_status(
    usuario: str = typer.Option(..., "--user", help="e-mail ou uuid do titular"),
    escopo: str | None = typer.Option(None, "--scope"),
):
    """O perfil gravado, como a OPERAÇÃO lê — inclusive o que está em calibração.

    Não usa `perfil_atual`: aquela é a janela do CLIENTE e filtra o que não é publicável
    (run interno, política em rascunho). O operador precisa ver justamente o que a tela
    esconde — foi para isso que a migration 45 manteve a calibração na view."""
    from app.context.catalogo import cobertura as ler_cobertura

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, usuario)
            async with db.service_session() as conn:
                sid = escopo or await _escopo_padrao(conn, uid)
                cur = await conn.execute(
                    "select display_name, value::float, is_disabled, disabled_reason, "
                    "       coverage::float, confidence::float, is_critical_family, elo_mais_fraco, "
                    "       fundacao_critica, fundacao_semaforo::text, as_of_date, "
                    "       (is_client_facing and politica_aprovada) as publicavel "
                    "from diagnostics.v_client_profile where scope_id = %s "
                    "  and as_of_date = (select max(as_of_date) from diagnostics.client_scores "
                    "                    where scope_id = %s) "
                    "order by is_critical_family desc, value nulls last", (sid, sid))
                linhas = await cur.fetchall()
                cob = await ler_cobertura(conn, sid)
            if not linhas:
                typer.echo("perfil ainda não calculado — rode `plexo perfil calcular --user ...`")
                return
            typer.echo(f"perfil de {sid} · {linhas[0][10]}")
            typer.echo(f"  Fundação: {linhas[0][9] or 'sem leitura'}"
                       + (" (CRÍTICA)" if linhas[0][8] else ""))
            for (nome, valor, desativado, motivo, cobertura, confianca,
                 critica, elo, _fc, _fs, _d, publicavel) in linhas:
                txt = f"indisponível ({motivo})" if desativado else f"{valor:.2f}"
                marca = " ←" if elo else ""
                typer.echo(f"  {nome:16} {txt:>34}  {'crítica' if critica else '       '}  "
                           f"cobertura {cobertura:.0%} · confiança {confianca:.2f}{marca}")
            if not any(l[11] for l in linhas):
                typer.echo("  (em CALIBRAÇÃO — nenhum destes números chega ao cliente enquanto "
                           "a política estiver em rascunho)")
            typer.echo(f"  contexto conhecido: {cob['fatos_presentes']}/{cob['fatos_no_catalogo']} fatos "
                       f"({(cob['cobertura'] or 0):.0%})")
            if cob["faltando"]:
                typer.echo(f"  próximas perguntas úteis: {', '.join(cob['faltando'][:5])}")
        finally:
            await db.close()

    _run(go())


@perfil_app.command("derivar")
def perfil_derivar(
    usuario: str = typer.Option(..., "--user", help="e-mail ou uuid do titular"),
    escopo: str | None = typer.Option(None, "--scope"),
    calcular: bool = typer.Option(True, "--calcular/--so-derivar",
                                  help="recalcula o perfil logo depois (padrão: sim)"),
):
    """Lê o que o banco já sabe (orçamento, dívidas, patrimônio, família, objetivos) e grava
    como fato INFERIDO. Não toca no que o cliente confirmou nem regrava valor igual."""
    from app.context.derivacao import derivar_escopo
    from app.context.catalogo import cobertura as ler_cobertura
    from app.engine.perfil import calcular_perfil

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, usuario)
            async with db.service_session() as conn:
                sid = escopo or await _escopo_padrao(conn, uid)
                antes_cob = await ler_cobertura(conn, sid)
                r = await derivar_escopo(conn, sid, uid)
                depois_cob = await ler_cobertura(conn, sid)
                typer.echo(f"{r.resumo}")
                if r.gravados:
                    typer.echo(f"  gravados: {', '.join(sorted(r.gravados))}")
                if r.pulados_confirmados:
                    typer.echo(f"  já confirmados pelo cliente (intocados): {', '.join(sorted(r.pulados_confirmados))}")
                for x in r.recusados:
                    typer.echo(f"  RECUSADO {x['fact_key']}: {x['motivo']}")
                typer.echo(f"  cobertura: {(antes_cob['cobertura'] or 0):.0%} → {(depois_cob['cobertura'] or 0):.0%}"
                           f" ({depois_cob['fatos_presentes']}/{depois_cob['fatos_no_catalogo']})")
                if calcular:
                    res = await calcular_perfil(conn, sid, client_facing=False)
                    com_valor = sum(1 for s in res.scores if not s["is_disabled"])
                    typer.echo(f"  perfil recalculado: {com_valor}/{len(res.scores)} score(s) com valor")
        finally:
            await db.close()

    _run(go())


@perfil_app.command("catalogo")
def perfil_catalogo(familia: str | None = typer.Option(None, "--familia", help="fluxo|protecao|estoque|destino|comportamento|vida")):
    """O vocabulário fechado de fatos (migration 38) — o que a plataforma sabe registrar."""
    from app.context.catalogo import catalogo as ler_catalogo

    async def go():
        db = await _db()
        try:
            async with db.service_session() as conn:
                for d in await ler_catalogo(conn, family=familia):
                    governado = "" if d.allows_conversation_update else f"  [governado por {d.fonte_que_manda}]"
                    meia = f"{d.half_life_days}d" if d.half_life_days else "não vence"
                    typer.echo(f"  {d.family:14} {d.fact_key:34} {d.value_type:10} {meia:>10}{governado}")
        finally:
            await db.close()

    _run(go())


# ---------------------------------------------------------------------------- objetivo (F17)
@objetivo_app.command("projetar")
def objetivo_projetar(
    usuario: str = typer.Option(..., "--user", help="e-mail ou uuid do titular"),
    escopo: str | None = typer.Option(None, "--scope", help="uuid do escopo (padrão: o pessoal do usuário)"),
    semente: int | None = typer.Option(None, "--semente", help="sobrepõe a semente da política — a MESMA semente devolve o MESMO resultado"),
    client_facing: bool | None = typer.Option(
        None, "--client-facing/--interno",
        help="por padrão só é client-facing quando a política E a premissa de mercado estão aprovadas (C48c)"),
):
    """Roda o Monte Carlo dos objetivos do escopo e grava com run auditável.

    Precisa rodar ANTES de `perfil calcular` para que `destino.probabilidade_meta` tenha
    fato — sem projeção o indicador sai indisponível, dizendo qual fato falta.
    """
    from app.engine.projecao import projetar_escopo

    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, usuario)
            async with db.service_session() as conn:
                sid = escopo or await _escopo_padrao(conn, uid)
                resultados = await projetar_escopo(conn, sid, semente=semente,
                                                   client_facing=client_facing)
            if not resultados:
                typer.echo("nenhum objetivo ativo neste escopo.")
                return
            for r in resultados:
                if r.indisponivel:
                    falta = f" (falta: {', '.join(r.faltando)})" if r.faltando else ""
                    typer.echo(f"{r.nome}: sem projeção — {r.motivo_indisponivel}{falta}")
                    continue
                typer.echo(f"\n{r.nome} · alvo R$ {r.valor_alvo:,.0f} em {r.meses} meses · "
                           f"aporte R$ {r.meta.aporte_mensal:,.0f}/mês")
                for d in r.distribuicoes:
                    marca = " ←" if d.alocacao == r.veredito.alocacao else "  "
                    typer.echo(
                        f" {marca} {d.alocacao:14} cenário ruim R$ {d.cenario_ruim:>12,.0f} · "
                        f"mediana R$ {d.mediana:>12,.0f} · chega em {d.prob_sucesso:>5.0%} · "
                        f"abaixo do depositado {d.prob_abaixo_do_depositado:>4.0%}")
                eleita = next(d for d in r.distribuicoes if d.alocacao == r.veredito.alocacao)
                if eleita.aporte_necessario is not None:
                    typer.echo(f"    aporte para 90% de confiança: R$ {eleita.aporte_necessario:,.0f}/mês")
                typer.echo(f"    {r.veredito.motivo}")
            typer.echo("\n  Simulação ilustrativa: log-retornos normais subestimam a cauda — "
                       "crise real é pior que o cenário ruim mostrado.")
        finally:
            await db.close()

    _run(go())


@objetivo_app.command("status")
def objetivo_status(
    usuario: str = typer.Option(..., "--user", help="e-mail ou uuid do titular"),
    escopo: str | None = typer.Option(None, "--scope"),
):
    """Mostra a última projeção gravada de cada objetivo — o que a tela e a tool leem."""
    async def go():
        db = await _db()
        try:
            uid = await _resolver_usuario(db, usuario)
            async with db.service_session() as conn:
                sid = escopo or await _escopo_padrao(conn, uid)
                cur = await conn.execute(
                    """select distinct on (p.goal_id, p.alocacao_code)
                              g.name, p.alocacao_code, p.success_prob::float,
                              p.p5_brl::float, p.p50_brl::float, p.p95_brl::float,
                              (p.assumptions ->> 'eleita')::boolean, p.as_of_date,
                              s.code, s.version, s.compliance_status::text
                         from planning.goal_projections p
                         join planning.goals g on g.id = p.goal_id
                         left join market.assumption_sets s on s.id = p.assumption_set_id
                        where p.scope_id = %s
                        order by p.goal_id, p.alocacao_code, p.as_of_date desc""", (sid,))
                linhas = await cur.fetchall()
            if not linhas:
                typer.echo("nenhuma projeção gravada — rode `objetivo projetar`.")
                return
            for nome, aloc, prob, p5, p50, p95, eleita, dia, code, ver, status in linhas:
                marca = "←" if eleita else " "
                typer.echo(f"{marca} {nome[:28]:28} {aloc:14} p5 R$ {p5:>12,.0f} · "
                           f"p50 R$ {p50:>12,.0f} · p95 R$ {p95:>12,.0f} · chega em {prob:.0%} "
                           f"· {dia} · {code} v{ver} ({status})")
        finally:
            await db.close()

    _run(go())


def main():
    app()


if __name__ == "__main__":
    main()
