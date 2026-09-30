"""Execução do motor do perfil: fatos vigentes → indicadores → scores → gates.

É o primeiro consumidor de `engine.runs` do projeto (§3.4 do ESTADO: "engine quant não
existe ainda"). O contrato do run é o que a 02 já fixou e o que a CVM inspeciona:
`{input_hash, engine_version, params, output_hash}` mais as `policy_version_ids` usadas.

A ordem das decisões espelha a do banco, de propósito — o Python antecipa a recusa para
poder EXPLICAR, e o banco recusa de novo para garantir:

    Fundação crítica ────────► score DESATIVADO      (C40a / D11)
    cobertura < mínimo ──────► indisponível, com o que falta   (C40b)
    política em rascunho ────► só run interno         (C40d)

Nada aqui imputa valor ausente. Indicador sem insumo sai `is_unavailable` dizendo o motivo,
e é esse motivo que vira a próxima pergunta do Copiloto.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.engine import indicadores as formulas
from app.engine.fundacao import avaliar as avaliar_fundacao, gravar as gravar_fundacao
from app.engine.scores import compor, confianca_por_frescor
from app.tools.hashing import canonical_json, sha256_hex

log = logging.getLogger(__name__)

PACOTE = "plexo-engine-perfil"
SEMVER = "1.0.0"
POLICY_SCORES = "CLIENT_SCORES"

# Fatos qualitativos que viram número para o motor. A tradução é EXPLÍCITA e versionada
# aqui porque é uma escolha de modelagem, não um detalhe: dizer que "manteve" vale 0,5 é
# uma opinião sobre disciplina, e ela precisa estar escrita em algum lugar legível.
ESCALAS_TEXTO = {
    "comportamento.reacao_queda": {"vendeu": 0.0, "nao_observado": None, "manteve": 0.5, "aportou": 1.0},
}


@dataclass
class ResultadoPerfil:
    run_id: str
    as_of_date: date
    indicadores: list[dict[str, Any]] = field(default_factory=list)
    scores: list[dict[str, Any]] = field(default_factory=list)
    fundacao_critica: bool = False
    cobertura_do_catalogo: float = 0.0

    @property
    def indisponiveis(self) -> list[str]:
        return [i["indicator_code"] for i in self.indicadores if i["is_unavailable"]]


async def _engine_version_id(conn: AsyncConnection) -> str:
    cur = await conn.execute(
        "select id::text from engine.engine_versions where package = %s and semver = %s",
        (PACOTE, SEMVER))
    row = await cur.fetchone()
    if row:
        return row[0]
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             check=False).stdout.strip()
    except OSError:
        sha = ""
    sha = sha if len(sha) == 40 else "0" * 40
    fonte = sha256_hex(canonical_json({"pacote": PACOTE, "semver": SEMVER,
                                       "formulas": sorted(formulas._FORMULAS)}))
    cur = await conn.execute(
        "insert into engine.engine_versions (package, semver, git_sha, source_sha256, notes) "
        "values (%s, %s, %s, %s, %s) returning id::text",
        (PACOTE, SEMVER, sha, fonte, "Motor do perfil do cliente (F14c)."))
    return (await cur.fetchone())[0]


async def _fatos(conn: AsyncConnection, scope_id: str) -> tuple[dict[str, float], dict[str, float]]:
    """Fatos vigentes como números, e a confiança de cada um pelo frescor."""
    cur = await conn.execute(
        "select f.fact_key, f.value, f.numero::float, f.value_type::text, f.confidence::float, "
        "       (current_date - f.observed_at::date) as dias, d.half_life_days "
        # F15: o motor lê a janela OPERÁVEL (confirmado + derivado da estrutura), não a do
        # agente. `confidence` já vem descontada pelo fator de CONTEXT_FACT_CATALOG quando o
        # fato foi deduzido — é assim que um perfil derivado sai com confiança menor.
        "from context.v_fact_operavel f "
        "join context.fact_definitions d on d.fact_key = f.fact_key "
        "where f.scope_id = %s", (scope_id,))
    valores: dict[str, float] = {}
    confiancas: dict[str, float] = {}
    for fact_key, value, numero, value_type, confianca, dias, meia_vida in await cur.fetchall():
        n = _para_numero(fact_key, value, numero, value_type)
        if n is None:
            continue
        valores[fact_key] = n
        frescor = confianca_por_frescor(int(dias or 0), int(meia_vida)) if meia_vida else 1.0
        confiancas[fact_key] = round(float(confianca or 1.0) * frescor, 3)
    return valores, confiancas


def _para_numero(fact_key: str, value: Any, numero: float | None, value_type: str) -> float | None:
    if numero is not None:
        return float(numero)
    if not isinstance(value, dict):
        return None
    if value_type == "booleano" and isinstance(value.get("bool"), bool):
        return 1.0 if value["bool"] else 0.0
    if value_type == "texto":
        escala = ESCALAS_TEXTO.get(fact_key)
        if escala:
            return escala.get(str(value.get("text", "")).lower())
    if value_type == "data" and fact_key == "vida.data_nascimento":
        # o motor quer IDADE, não data: converter aqui mantém a fórmula pura
        try:
            nasc = date.fromisoformat(str(value.get("date")))
        except (TypeError, ValueError):
            return None
        hoje = date.today()
        return float(hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day)))
    return None


async def _politica(conn: AsyncConnection) -> tuple[str, dict[str, Any], str]:
    cur = await conn.execute(
        "select id::text, payload, compliance_status::text from engine.policy_versions "
        "where code = %s and effective_to is null", (POLICY_SCORES,))
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"política {POLICY_SCORES} não está vigente — premissa numérica não tem default no código")
    return row


async def calcular_perfil(conn: AsyncConnection, scope_id: str, *,
                          as_of: date | None = None,
                          client_facing: bool | None = None) -> ResultadoPerfil:
    """Calcula e grava indicadores e scores do escopo.

    `client_facing` default: True apenas se a política estiver aprovada. Assim o motor roda
    em dev sobre rascunho (calibração) sem nunca marcar como client-facing um número que
    compliance ainda não viu — o gate C40d recusaria, e com razão.
    """
    as_of = as_of or date.today()
    policy_id, payload, status = await _politica(conn)
    if client_facing is None:
        client_facing = status == "approved"

    normalizacao = payload.get("normalizacao") or {}
    pesos_por_score = payload.get("pesos") or {}
    premissas = payload.get("premissas_indicadores") or {}

    valores, confiancas = await _fatos(conn, scope_id)

    cur = await conn.execute(
        "select coalesce(cobertura, 0)::float from context.v_fact_coverage where scope_id = %s",
        (scope_id,))
    row = await cur.fetchone()
    cobertura_catalogo = float(row[0]) if row else 0.0

    engine_version_id = await _engine_version_id(conn)
    entrada = {"scope_id": scope_id, "as_of": as_of.isoformat(), "fatos": valores,
               "policy": policy_id, "semver": SEMVER}
    cur = await conn.execute(
        """insert into engine.runs (scope_id, kind, engine_version_id, policy_version_ids,
                                    params, input_hash, status, is_client_facing, as_of_date,
                                    triggered_by)
           values (%s, 'client_profile', %s, %s, %s, %s, 'running', %s, %s, 'job')
           returning id::text""",
        (scope_id, engine_version_id, [policy_id],
         Jsonb({"semver": SEMVER, "policy_status": status}),
         sha256_hex(canonical_json(entrada)), client_facing, as_of))
    run_id = (await cur.fetchone())[0]

    # [F16] A Fundação é avaliada e GRAVADA aqui, antes de qualquer score. Até a F16 nada
    # escrevia `diagnostics.foundation_status`: o gate D11 existia no banco, era testado, e
    # nunca disparava por falta de quem o alimentasse. Um gate sem produtor é intenção.
    fundacao = await avaliar_fundacao(conn, scope_id, as_of=as_of)
    await gravar_fundacao(conn, scope_id, fundacao, run_id=run_id, as_of=as_of)
    fundacao_critica = fundacao.critica

    resultado = ResultadoPerfil(run_id=run_id, as_of_date=as_of,
                                fundacao_critica=fundacao_critica,
                                cobertura_do_catalogo=cobertura_catalogo)

    # ---------------------------------------------------------------- indicadores
    cur = await conn.execute(
        # `::text[]` obrigatório: required/optional são core.slug[] (array de DOMÍNIO) e o
        # psycopg, sem conhecer o OID, devolveria a representação textual '{a,b}' — que
        # `list()` quebra em caracteres e faz a cobertura dar zero em silêncio.
        "select code, unit, required_fact_keys::text[], optional_fact_keys::text[], formula_ref "
        "from diagnostics.indicator_definitions where is_active order by code")
    definicoes = await cur.fetchall()

    valores_indicador: dict[str, float] = {}
    confianca_indicador: dict[str, float] = {}

    for code, unidade, requeridos, opcionais, formula_ref in definicoes:
        requeridos = list(requeridos or [])
        presentes = [k for k in requeridos if k in valores]
        cobertura = len(presentes) / len(requeridos) if requeridos else 0.0
        insumos = {k: {"valor": valores[k], "confianca": confiancas.get(k)}
                   for k in requeridos + list(opcionais or []) if k in valores}

        motivo: str | None = None
        valor: float | None = None
        if not formulas.formula_existe(formula_ref):
            motivo = "motor_ausente"
        elif cobertura < 1.0:
            motivo = "dados_insuficientes"
        else:
            valor = formulas.calcular(formula_ref, valores, premissas)
            if valor is None:
                motivo = "dados_insuficientes"

        conf = 0.0
        if presentes:
            conf = round(sum(confiancas.get(k, 0.0) for k in presentes) / len(presentes), 3)

        if valor is not None:
            valores_indicador[code] = valor
            confianca_indicador[code] = conf

        await conn.execute(
            """insert into diagnostics.client_indicators
                 (scope_id, as_of_date, indicator_code, run_id, value, unit, coverage,
                  confidence, inputs, is_unavailable, unavailable_reason)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (scope_id, as_of_date, indicator_code) do update
                 set run_id = excluded.run_id, value = excluded.value, coverage = excluded.coverage,
                     confidence = excluded.confidence, inputs = excluded.inputs,
                     is_unavailable = excluded.is_unavailable,
                     unavailable_reason = excluded.unavailable_reason, computed_at = now()""",
            (scope_id, as_of, code, run_id, valor, unidade, round(cobertura, 4), conf,
             Jsonb(insumos), valor is None, motivo))
        resultado.indicadores.append({
            "indicator_code": code, "value": valor, "unit": unidade,
            "coverage": round(cobertura, 4), "confidence": conf,
            "is_unavailable": valor is None, "unavailable_reason": motivo,
            "faltando": [k for k in requeridos if k not in valores]})

    # ---------------------------------------------------------------- scores
    cur = await conn.execute(
        "select code, indicator_codes::text[], min_coverage::float, is_critical_family, display_name "
        "from diagnostics.score_definitions where is_active order by code")
    for code, indicator_codes, min_cobertura, critica, rotulo in await cur.fetchall():
        s = compor(
            indicator_codes=list(indicator_codes or []),
            valores=valores_indicador, confiancas=confianca_indicador,
            normalizacao=normalizacao, pesos=pesos_por_score.get(code, {}),
            min_coverage=float(min_cobertura), fundacao_critica=fundacao_critica)

        await conn.execute(
            """insert into diagnostics.client_scores
                 (scope_id, as_of_date, score_code, run_id, value, coverage, confidence,
                  is_disabled, disabled_reason, components, policy_version_id)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (scope_id, as_of_date, score_code) do update
                 set run_id = excluded.run_id, value = excluded.value, coverage = excluded.coverage,
                     confidence = excluded.confidence, is_disabled = excluded.is_disabled,
                     disabled_reason = excluded.disabled_reason, components = excluded.components,
                     policy_version_id = excluded.policy_version_id, computed_at = now()""",
            (scope_id, as_of, code, run_id, s.valor, s.cobertura, s.confianca,
             s.indisponivel, s.motivo, Jsonb(s.componentes), policy_id))
        resultado.scores.append({
            "score_code": code, "display_name": rotulo, "value": s.valor,
            "coverage": s.cobertura, "confidence": s.confianca,
            "is_disabled": s.indisponivel, "disabled_reason": s.motivo,
            "is_critical_family": critica})

    saida = {"indicadores": resultado.indicadores, "scores": resultado.scores}
    await conn.execute(
        "update engine.runs set status = 'succeeded', output_hash = %s, finished_at = now() "
        "where id = %s", (sha256_hex(canonical_json(saida)), run_id))
    return resultado


async def perfil_atual(conn: AsyncConnection, scope_id: str) -> dict[str, Any]:
    """O perfil como a tela lê: gate da Fundação, score por família, elo mais fraco."""
    cur = await conn.execute(
        "select score_code, family::text, display_name, is_critical_family, value::float, "
        "       coverage::float, confidence::float, is_disabled, disabled_reason, "
        "       fundacao_critica, fundacao_semaforo::text, elo_mais_fraco, as_of_date, "
        "       (is_client_facing and politica_aprovada) as publicavel "
        "from diagnostics.v_client_profile where scope_id = %s "
        "  and as_of_date = (select max(as_of_date) from diagnostics.client_scores where scope_id = %s) "
        "order by is_critical_family desc, value nulls last", (scope_id, scope_id))
    chaves = ("score_code", "family", "display_name", "is_critical_family", "value", "coverage",
              "confidence", "is_disabled", "disabled_reason", "fundacao_critica",
              "fundacao_semaforo", "elo_mais_fraco", "as_of_date", "publicavel")
    linhas = [dict(zip(chaves, r)) for r in await cur.fetchall()]

    cur = await conn.execute(
        "select indicator_code, value::float, unit, coverage::float, confidence::float, "
        "       is_unavailable, unavailable_reason "
        "from diagnostics.client_indicators where scope_id = %s "
        "  and as_of_date = (select max(as_of_date) from diagnostics.client_indicators where scope_id = %s) "
        "order by indicator_code", (scope_id, scope_id))
    ind_chaves = ("indicator_code", "value", "unit", "coverage", "confidence",
                  "is_unavailable", "unavailable_reason")
    indicadores = [dict(zip(ind_chaves, r)) for r in await cur.fetchall()]

    # [45] O gate C40d na LEITURA: número que o cliente lê sai de run client-facing sobre
    # política aprovada. Score de calibração continua existindo — só não vai à tela.
    publicaveis = [l for l in linhas if l["publicavel"]]
    em_calibracao = bool(linhas) and not publicaveis
    linhas = publicaveis

    # A FUNDAÇÃO não passa por este filtro, e a distinção importa: ela não é score, vem de
    # `diagnostics.foundation_status` (outro motor) e não depende de curva de normalização
    # nenhuma. "A sua reserva não cobre um mês de despesa" é justamente o que o cliente mais
    # precisa saber — suprimir isso porque uma política de score está em rascunho seria
    # esconder o aviso e manter o enfeite.
    cur = await conn.execute(
        "select is_critical, overall_light::text from diagnostics.foundation_status "
        "where scope_id = %s order by as_of_date desc limit 1", (scope_id,))
    fundacao = await cur.fetchone()

    elo = next((l for l in linhas if l["elo_mais_fraco"]), None)
    return {
        "em_calibracao": em_calibracao,
        "as_of_date": linhas[0]["as_of_date"].isoformat() if linhas else None,
        "fundacao_critica": bool(fundacao[0]) if fundacao else False,
        "fundacao_semaforo": fundacao[1] if fundacao else None,
        "scores": linhas,
        "indicadores": indicadores,
        "elo_mais_fraco": elo["score_code"] if elo else None,
    }
