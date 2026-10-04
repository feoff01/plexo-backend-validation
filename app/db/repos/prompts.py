"""llm.prompt_versions — ciclo de vida dos prompts com aprovação de compliance.

- push: rascunho é editável; aprovada nunca muda → fecha effective_to e abre version+1 em draft
  (índice prompt_one_current exige uma vigente por code). O ponteiro
  agents.agent_definitions.active_prompt_version_id só muda na aprovação.
- approve: checagens da APLICAÇÃO antes do banco — template sem [PENDENTE], sem vocabulário
  proibido, variables[] coerente com o template; depois UPDATE + ponteiro do agente + trilha em
  audit.activity_log. O gate do banco (19_llm) continua sendo quem bloqueia conversa sem prompt.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml
from psycopg import AsyncConnection

from app.db.errors import PromptNotApprovable
from app.db.repos import audit
from app.llm.prompts import variaveis_do_template

_VOCAB_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "vocabulario_proibido.yaml"


@dataclass(frozen=True)
class PromptRow:
    id: str
    code: str
    version: int
    template: str
    variables: list[str]
    compliance_status: str
    content_hash: str
    effective_to: object | None


_COLS = "id::text, code, version, template, variables, compliance_status::text, content_hash, effective_to"


def termos_proibidos() -> list[str]:
    data = yaml.safe_load(_VOCAB_PATH.read_text(encoding="utf-8")) or {}
    return [str(t) for t in data.get("termos", [])]


def vocabulario_excecoes() -> list[str]:
    """Expressões técnicas neutras que contêm um termo vetado (ex.: 'custo de oportunidade') — config, não código."""
    data = yaml.safe_load(_VOCAB_PATH.read_text(encoding="utf-8")) or {}
    return [str(t) for t in data.get("excecoes", [])]


def _sem_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def encontrar_vocabulario_proibido(texto: str, termos: list[str] | None = None) -> list[str]:
    """Casamento por palavra inteira, sem acentos/maiúsculas; ignora tags Jinja e as exceções do YAML."""
    corpo = _sem_acentos(re.sub(r"\{[{%#].*?[}%#]\}", " ", texto, flags=re.S))
    for excecao in vocabulario_excecoes():
        corpo = re.sub(r"(?<![\w])" + re.escape(_sem_acentos(excecao)) + r"(?![\w])", " ", corpo)
    achados = []
    for termo in termos if termos is not None else termos_proibidos():
        padrao = r"(?<![\w])" + re.escape(_sem_acentos(termo)) + r"(?![\w])"
        if re.search(padrao, corpo):
            achados.append(termo)
    return achados


async def get_current(conn: AsyncConnection, code: str) -> PromptRow | None:
    cur = await conn.execute(f"select {_COLS} from llm.prompt_versions where code = %s and effective_to is null", (code,))
    row = await cur.fetchone()
    return PromptRow(*row) if row else None


async def get_version(conn: AsyncConnection, code: str, version: int) -> PromptRow | None:
    cur = await conn.execute(f"select {_COLS} from llm.prompt_versions where code = %s and version = %s", (code, version))
    row = await cur.fetchone()
    return PromptRow(*row) if row else None


async def push(conn: AsyncConnection, code: str, template: str, created_by: str | None = None) -> PromptRow:
    variaveis = variaveis_do_template(template)
    atual = await get_current(conn, code)
    if atual is None:
        cur = await conn.execute(
            "insert into llm.prompt_versions (code, version, template, variables, compliance_status, created_by) "
            f"values (%s, 1, %s, %s, 'draft', %s) returning {_COLS}", (code, template, variaveis, created_by))
        return PromptRow(*(await cur.fetchone()))
    if atual.compliance_status == "draft":
        cur = await conn.execute(
            f"update llm.prompt_versions set template = %s, variables = %s where id = %s returning {_COLS}",
            (template, variaveis, atual.id))
        return PromptRow(*(await cur.fetchone()))
    # aprovada/rejeitada/revogada: nunca editar → fecha a vigente e abre a próxima em draft
    await conn.execute(
        "update llm.prompt_versions set effective_to = greatest(clock_timestamp(), effective_from + interval '1 microsecond') "
        "where id = %s", (atual.id,))
    cur = await conn.execute(
        "insert into llm.prompt_versions (code, version, template, variables, compliance_status, created_by) "
        f"values (%s, %s, %s, %s, 'draft', %s) returning {_COLS}",
        (code, atual.version + 1, template, variaveis, created_by))
    return PromptRow(*(await cur.fetchone()))


def _agent_code_de(prompt_code: str) -> str | None:
    m = re.fullmatch(r"agent\.([a-z_]+)\.system", prompt_code)
    if m:
        return m.group(1)
    if prompt_code == "context.extractor":
        return "contexto"
    return None


async def approve(conn: AsyncConnection, code: str, version: int, approved_by: str) -> PromptRow:
    row = await get_version(conn, code, version)
    if row is None:
        raise PromptNotApprovable(f"{code} v{version} não existe")
    if row.compliance_status == "approved":
        raise PromptNotApprovable(f"{code} v{version} já está aprovado")
    if "[PENDENTE" in row.template:
        raise PromptNotApprovable(f"{code} v{version}: template contém [PENDENTE] — escreva o prompt antes de aprovar")
    achados = encontrar_vocabulario_proibido(row.template)
    if achados:
        raise PromptNotApprovable(f"{code} v{version}: vocabulário proibido no template: {', '.join(achados)}")
    esperadas = variaveis_do_template(row.template)
    if sorted(row.variables) != esperadas:
        raise PromptNotApprovable(
            f"{code} v{version}: variables[] {sorted(row.variables)} difere das variáveis do template {esperadas}")
    cur = await conn.execute(
        "update llm.prompt_versions set compliance_status = 'approved', approved_at = clock_timestamp(), "
        f"approved_by = %s, rejection_reason = null where id = %s returning {_COLS}", (approved_by, row.id))
    aprovado = PromptRow(*(await cur.fetchone()))
    agent_code = _agent_code_de(code)
    if agent_code:
        # code::text evita erro de cast quando o prompt não corresponde a um agente existente
        await conn.execute(
            "update agents.agent_definitions set active_prompt_version_id = %s where code::text = %s",
            (aprovado.id, agent_code))
    await audit.registrar(conn, actor_kind="admin", actor_user_id=approved_by, action="prompt.approved",
                          object_kind="prompt_version", object_id=aprovado.id,
                          details={"code": code, "version": version, "content_hash": aprovado.content_hash,
                                   "agent_code": agent_code})
    return aprovado


async def reject(conn: AsyncConnection, code: str, version: int, by: str, reason: str) -> PromptRow:
    row = await get_version(conn, code, version)
    if row is None:
        raise PromptNotApprovable(f"{code} v{version} não existe")
    cur = await conn.execute(
        "update llm.prompt_versions set compliance_status = 'rejected', rejection_reason = %s, approved_at = null, "
        f"approved_by = null where id = %s returning {_COLS}", (reason, row.id))
    rejeitado = PromptRow(*(await cur.fetchone()))
    await audit.registrar(conn, actor_kind="admin", actor_user_id=by, action="prompt.rejected",
                          object_kind="prompt_version", object_id=rejeitado.id,
                          details={"code": code, "version": version, "reason": reason})
    return rejeitado


async def reabrir_rascunho(conn: AsyncConnection, code: str, template: str = "[PENDENTE — rascunho]") -> PromptRow:
    """Fecha a vigente (qualquer status) e abre version+1 em DRAFT, apontando o agente para ela.

    Uso: testes (estado conhecido dentro da transação) e operação ("voltar o agente para rascunho"
    de propósito — bloqueia conversas até nova aprovação, pelo gate de 19_llm)."""
    atual = await get_current(conn, code)
    versao = 1
    if atual is not None:
        await conn.execute(
            "update llm.prompt_versions set effective_to = greatest(clock_timestamp(), effective_from + interval '1 microsecond') "
            "where id = %s", (atual.id,))
        versao = atual.version + 1
    cur = await conn.execute(
        "insert into llm.prompt_versions (code, version, template, variables, compliance_status) "
        f"values (%s, %s, %s, %s, 'draft') returning {_COLS}",
        (code, versao, template, variaveis_do_template(template)))
    novo = PromptRow(*(await cur.fetchone()))
    agent_code = _agent_code_de(code)
    if agent_code:
        await conn.execute(
            "update agents.agent_definitions set active_prompt_version_id = %s where code::text = %s",
            (novo.id, agent_code))
    return novo


async def listar(conn: AsyncConnection) -> list[PromptRow]:
    cur = await conn.execute(f"select {_COLS} from llm.prompt_versions order by code, version")
    return [PromptRow(*r) for r in await cur.fetchall()]
