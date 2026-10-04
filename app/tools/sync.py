"""Sincroniza o registro de tools com o espelho auditável do banco (deploy-time).

Regras (18_tools + RCVM 19 art. 17):
- tools.tools: upsert do catálogo (o que o planner/LLM enxerga);
- tools.tool_versions: git_sha + sha256 do fonte provam qual código exato produziu qual número;
  uma versão corrente por tool (índice tool_versions_one_current);
- mesma semver com fonte diferente = ERRO ("bump a semver") — nunca reescrever versão publicada;
- EXCEÇÃO (legado, 2026-08-26): sha gravado na forma CRLF pelo mesmo fonte. Até esta data o
  `source_sha256` saía dos bytes crus do arquivo, então um `tools sync` rodado em checkout Windows
  (`core.autocrlf`) gravava um sha que o runner Linux nunca reproduzia. Não é código diferente —
  é a MESMA fonte com outra quebra de linha, e o `sync` corrige a impressão digital no lugar
  (sem versão nova, sem tocar no git_sha). O casamento com a forma CRLF do arquivo ATUAL é a
  prova de que nada mudou; qualquer outra diferença continua sendo `SyncConflito`;
- tool sumida do registro: desativada (is_active=false) e versão corrente depreciada.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.tools.hashing import sha256_fonte_crlf
from app.tools.registry import ToolSpec


class SyncConflito(RuntimeError):
    pass


@dataclass
class RelatorioSync:
    criadas: list[str] = field(default_factory=list)
    atualizadas: list[str] = field(default_factory=list)
    versionadas: list[str] = field(default_factory=list)
    desativadas: list[str] = field(default_factory=list)
    inalteradas: list[str] = field(default_factory=list)
    corrigidas: list[str] = field(default_factory=list)   # sha legado CRLF → LF, mesmo fonte
    drift: list[str] = field(default_factory=list)

    @property
    def tem_drift(self) -> bool:
        return bool(self.drift)


def _e_sha_legado_crlf(spec: ToolSpec, sha_no_banco: str) -> bool:
    """Reconhece somente o legado de arquivo único gravado em CRLF até 2026-08-26.

    Fingerprints compostos nasceram depois dessa correção e nunca tiveram representação CRLF
    publicada no banco; tentar "corrigi-los" como legado poderia mascarar mudança real de engine.
    """
    if len(spec.source_files) != 1:
        return False
    try:
        return sha_no_banco == sha256_fonte_crlf(spec.module_file)
    except OSError:                                  # spec sintética de teste sem arquivo em disco
        return False


async def sincronizar(conn: AsyncConnection, specs: list[ToolSpec], *, git_sha: str,
                      desativar_ausentes: bool = False, source_uri: str | None = None,
                      somente_verificar: bool = False) -> RelatorioSync:
    rel = RelatorioSync()
    for spec in specs:
        cur = await conn.execute("select 1 from tools.tools where code = %s", (spec.code,))
        existe = await cur.fetchone() is not None
        cur = await conn.execute(
            "select semver, source_sha256 from tools.tool_versions "
            "where tool_code = %s and deprecated_at is null", (spec.code,))
        corrente = await cur.fetchone()

        if somente_verificar:
            if not existe or corrente is None:
                rel.drift.append(f"{spec.code}: ausente do banco")
            elif corrente == (spec.semver, spec.source_sha256):
                rel.inalteradas.append(spec.code)
            elif corrente[0] == spec.semver and _e_sha_legado_crlf(spec, corrente[1]):
                rel.drift.append(
                    f"{spec.code}: o sha do banco ({corrente[1][:12]}) é a forma CRLF do MESMO fonte "
                    f"(gravado por um sync em checkout Windows) — rode `tools sync` uma vez para corrigir "
                    f"a impressão digital; NÃO bumpe a semver")
            else:
                rel.drift.append(f"{spec.code}: banco={corrente[0]}/{corrente[1][:12]} código={spec.semver}/{spec.source_sha256[:12]}")
            continue

        await conn.execute(
            """insert into tools.tools (code, family, display_name, description, param_schema, output_schema,
                                        is_deterministic, requires_market_data, min_plan, is_active)
               values (%s, %s::tools.tool_family, %s, %s, %s, %s, %s, %s, %s::billing.plan_code, true)
               on conflict (code) do update set
                 family = excluded.family, display_name = excluded.display_name,
                 description = excluded.description, param_schema = excluded.param_schema,
                 output_schema = excluded.output_schema, is_deterministic = excluded.is_deterministic,
                 requires_market_data = excluded.requires_market_data, min_plan = excluded.min_plan,
                 is_active = true""",
            (spec.code, spec.family, spec.display_name, spec.description, Jsonb(spec.param_schema),
             Jsonb(spec.output_schema), spec.is_deterministic, spec.requires_market_data, spec.min_plan))

        if corrente is None:
            await conn.execute(
                "insert into tools.tool_versions (tool_code, semver, git_sha, source_sha256, source_uri) "
                "values (%s, %s, %s, %s, %s)",
                (spec.code, spec.semver, git_sha, spec.source_sha256, source_uri))
            (rel.criadas if not existe else rel.versionadas).append(
                spec.code if not existe else f"{spec.code}@{spec.semver}")
        elif corrente == (spec.semver, spec.source_sha256):
            rel.inalteradas.append(spec.code)
        elif corrente[0] == spec.semver and _e_sha_legado_crlf(spec, corrente[1]):
            # Mesmo fonte, outra quebra de linha: corrige a impressão digital da versão corrente.
            # Não é reescrever versão publicada — é desfazer um artefato de checkout (ver docstring).
            await conn.execute(
                "update tools.tool_versions set source_sha256 = %s "
                "where tool_code = %s and deprecated_at is null",
                (spec.source_sha256, spec.code))
            rel.corrigidas.append(f"{spec.code}@{spec.semver}")
        elif corrente[0] == spec.semver:
            raise SyncConflito(
                f"{spec.code}: o fonte mudou (sha {corrente[1][:12]} → {spec.source_sha256[:12]}) "
                f"mas a semver continua {spec.semver} — versão publicada não se reescreve; faça o bump")
        else:
            await conn.execute(
                "update tools.tool_versions set deprecated_at = clock_timestamp() "
                "where tool_code = %s and deprecated_at is null", (spec.code,))
            await conn.execute(
                "insert into tools.tool_versions (tool_code, semver, git_sha, source_sha256, source_uri) "
                "values (%s, %s, %s, %s, %s)",
                (spec.code, spec.semver, git_sha, spec.source_sha256, source_uri))
            rel.versionadas.append(f"{spec.code}@{spec.semver}")

    if desativar_ausentes and not somente_verificar:
        codigos = [s.code for s in specs]
        cur = await conn.execute(
            "update tools.tools set is_active = false where is_active and not (code = any(%s)) returning code",
            (codigos,))
        for (code,) in await cur.fetchall():
            await conn.execute(
                "update tools.tool_versions set deprecated_at = clock_timestamp() "
                "where tool_code = %s and deprecated_at is null", (code,))
            rel.desativadas.append(code)
    return rel
