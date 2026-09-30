"""Prompts versionados: renderização Jinja2 ESTRITA e carga do prompt aprovado vigente de um agente.

- Variável faltando é erro (StrictUndefined), nunca string vazia silenciosa.
- content_hash_of() reproduz core.canonical_hash(jsonb_build_object('template', t)) do banco
  (19_llm.sql: llm.prompt_hash) — é o que permite detectar drift entre prompts/*.j2 e a versão aprovada.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from jinja2 import Environment, StrictUndefined, meta
from psycopg import AsyncConnection

from app.db.errors import PromptNotApproved

_ENV = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True,
                   trim_blocks=False, lstrip_blocks=False)


def variaveis_do_template(template: str) -> list[str]:
    return sorted(meta.find_undeclared_variables(_ENV.parse(template)))


def content_hash_of(template: str) -> str:
    """sha256 do texto jsonb de {"template": t} como o PostgreSQL o serializa ({"key": "value"})."""
    payload = json.dumps({"template": template}, ensure_ascii=False, separators=(", ", ": "))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Prompt:
    id: str
    code: str
    version: int
    template: str
    variables: tuple[str, ...]
    content_hash: str
    compliance_status: str

    def render(self, **variaveis) -> str:
        return _ENV.from_string(self.template).render(**variaveis)


class PromptLoader:
    def __init__(self, conn: AsyncConnection, require_approved: bool = True):
        self._conn = conn
        self._require = require_approved

    async def carregar_por_code(self, code: str) -> Prompt:
        """Prompt vigente por code (ex.: 'copiloto.router') — mesmo gate de aprovação."""
        cur = await self._conn.execute(
            "select id::text, code, version, template, variables, content_hash, compliance_status::text "
            "from llm.prompt_versions where code = %s and effective_to is null", (code,))
        row = await cur.fetchone()
        if row is None:
            raise PromptNotApproved(f"Prompt {code} inexistente")
        prompt = Prompt(id=row[0], code=row[1], version=row[2], template=row[3], variables=tuple(row[4] or ()),
                        content_hash=row[5], compliance_status=row[6])
        if self._require and prompt.compliance_status != "approved":
            raise PromptNotApproved(f"Prompt {code} v{prompt.version} não aprovado (status: {prompt.compliance_status})")
        return prompt

    async def carregar_para_agente(self, agent_code: str) -> Prompt:
        cur = await self._conn.execute(
            """select p.id::text, p.code, p.version, p.template, p.variables, p.content_hash, p.compliance_status::text
                 from agents.agent_definitions d
                 left join llm.prompt_versions p on p.id = d.active_prompt_version_id
                where d.code = %s::agents.agent_code""", (agent_code,))
        row = await cur.fetchone()
        if row is None or row[0] is None:
            raise PromptNotApproved(f"Agente {agent_code} sem prompt ativo")
        prompt = Prompt(id=row[0], code=row[1], version=row[2], template=row[3], variables=tuple(row[4] or ()),
                        content_hash=row[5], compliance_status=row[6])
        if self._require and prompt.compliance_status != "approved":
            raise PromptNotApproved(
                f"Agente {agent_code} com prompt {prompt.code} v{prompt.version} não aprovado (status: {prompt.compliance_status})")
        return prompt
