"""Compiler: do AnalysisPlan validado ao DAG em `analysis.plans` + `analysis.tasks`.

Cada nó é conferido contra o registry (tool existe), o catálogo do banco (ativa), a família permitida ao
agente, o plano mínimo da tool vs. o plano congelado da conversa e o `params_model` da tool; nó reprovado
vai para `validation_report.descartados` com motivo (e derruba quem dependia dele). Kahn dá a ordem de
inserção — e o banco, por sua vez, recusa dependência de nó ainda inexistente (T65): ciclo é impossível.
Um plano novo supersede o anterior e conta replan no banco (T66); o excedente é recusado (23514)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app.agents import analysis as an
from app.agents.turn import _ORDEM_PLANOS
from app.analysis.config import ConfigResearch
from app.analysis.dsl import AnalysisPlan, NodeSpec
from app.tools.registry import spec_de


class CicloNoPlano(ValueError):
    """Dependências circulares entre nós válidos — o plano não é um DAG."""


class PlanoInvalido(ValueError):
    """Nenhum nó executável (ou limite excedido); carrega o validation_report para o replan."""

    def __init__(self, motivo: str, validation_report: dict[str, Any]):
        super().__init__(motivo)
        self.validation_report = validation_report


@dataclass(frozen=True)
class Compilado:
    plan_id: str
    version: int
    ordem: list[str]
    validation_report: dict[str, Any] = field(default_factory=dict)


def _ordenar(nos: list[NodeSpec]) -> list[str]:
    """Kahn: ordem topológica; sobra ⇒ ciclo."""
    grau = {n.node_id: len(n.depends_on) for n in nos}
    dependentes: dict[str, list[str]] = {n.node_id: [] for n in nos}
    for n in nos:
        for d in n.depends_on:
            dependentes[d].append(n.node_id)
    fila = sorted(k for k, g in grau.items() if g == 0)
    ordem: list[str] = []
    while fila:
        atual = fila.pop(0)
        ordem.append(atual)
        for dep in sorted(dependentes[atual]):
            grau[dep] -= 1
            if grau[dep] == 0:
                fila.append(dep)
    if len(ordem) != len(nos):
        raise CicloNoPlano("ciclo entre: " + ", ".join(sorted(k for k, g in grau.items() if g > 0)))
    return ordem


async def _catalogo(conn: AsyncConnection) -> dict[str, dict[str, Any]]:
    cur = await conn.execute("select code, family::text, min_plan::text, is_active from tools.tools")
    return {c: {"family": f, "min_plan": m, "is_active": a} for c, f, m, a in await cur.fetchall()}


def _validar_no(no: NodeSpec, catalogo: dict[str, dict[str, Any]], familias: tuple[str, ...], plano_conta: str
                ) -> tuple[dict[str, Any] | None, str | None]:
    """(params validados, None) ou (None, motivo)."""
    try:
        spec = spec_de(no.tool_code)
    except KeyError:
        return None, f"tool {no.tool_code} não registrada"
    if not spec.exposed_to_llm:
        return None, f"tool {no.tool_code} não é exposta a novos planos do Analista"
    meta = catalogo.get(no.tool_code)
    if meta is None or not meta["is_active"]:
        return None, f"tool {no.tool_code} inativa ou ausente do catálogo (rode tools sync)"
    if meta["family"] not in familias:
        return None, f"tool {no.tool_code} é da família {meta['family']}, fora das permitidas ao agente ({', '.join(familias)})"
    if _ORDEM_PLANOS[plano_conta] < _ORDEM_PLANOS[meta["min_plan"]]:
        return None, f"tool {no.tool_code} exige plano {meta['min_plan']}; a conversa é {plano_conta}"
    try:
        params = spec.params_model.model_validate(no.params)
    except ValidationError as err:
        detalhes = "; ".join(".".join(str(x) for x in e.get("loc", ())) + ": " + str(e.get("msg")) for e in err.errors(include_url=False))
        return None, f"parâmetros inválidos para {no.tool_code}: {detalhes}"
    return params.model_dump(mode="json", exclude_none=True), None


async def compilar(conn: AsyncConnection, analise: an.AnaliseRow, plano: AnalysisPlan, *, familias: tuple[str, ...] | list[str],
                   plano_conta: str, cfg: ConfigResearch, planner_model_call_id: str | None = None,
                   descartados: list[dict[str, Any]] | None = None) -> Compilado:
    familias = tuple(familias)
    descartes: list[dict[str, Any]] = list(descartados or [])
    catalogo = await _catalogo(conn)
    validos: list[tuple[NodeSpec, dict[str, Any]]] = []
    for no in plano.nodes:
        params, motivo = _validar_no(no, catalogo, familias, plano_conta)
        if motivo is not None:
            descartes.append({"indice": None, "node_id": no.node_id, "motivo": motivo})
        else:
            validos.append((no, params))
    # propagação: quem dependia de nó reprovado cai também
    mudou = True
    while mudou:
        mudou = False
        presentes = {n.node_id for n, _ in validos}
        for item in list(validos):
            faltam = [d for d in item[0].depends_on if d not in presentes]
            if faltam:
                validos.remove(item)
                descartes.append({"indice": None, "node_id": item[0].node_id,
                                  "motivo": f"depende de nó reprovado: {', '.join(faltam)}"})
                mudou = True
    report: dict[str, Any] = {"descartados": descartes, "avisos": [], "ordem": []}

    async def gravar_plano(plano_json: dict[str, Any]) -> tuple[str, int]:
        # Plano inválido TAMBÉM vira versão (com o validation_report): é trilha do que o planner devolveu e é o
        # INSERT que faz o banco contar o replan (T66) e recusar o excedente.
        cur = await conn.execute(
            """insert into analysis.plans (analysis_id, dsl_version, plan, planner_model_call_id, validation_report)
               values (%s, %s, %s, %s, %s) returning id::text, version""",
            (analise.id, cfg.dsl_version, Jsonb(plano_json), planner_model_call_id, Jsonb(report)))
        pid, ver = await cur.fetchone()
        return pid, int(ver)

    if not validos:
        await gravar_plano(plano.model_dump(mode="json"))
        raise PlanoInvalido("nenhum nó executável no plano", report)
    if len(validos) > cfg.max_tasks:
        report["avisos"].append(f"plano com {len(validos)} nós excede max_tasks={cfg.max_tasks}")
        await gravar_plano(plano.model_dump(mode="json"))
        raise PlanoInvalido(f"plano excede max_tasks ({len(validos)} > {cfg.max_tasks})", report)
    try:
        ordem = _ordenar([n for n, _ in validos])
    except CicloNoPlano as exc:
        report["avisos"].append(str(exc))
        await gravar_plano(plano.model_dump(mode="json"))
        raise
    report["ordem"] = ordem
    por_id = {n.node_id: (n, p) for n, p in validos}

    plano_json = plano.model_dump(mode="json")
    plano_json["nodes"] = [{**por_id[k][0].model_dump(mode="json"), "params": por_id[k][1]} for k in ordem]
    plan_id, version = await gravar_plano(plano_json)
    for k in ordem:                      # ordem topológica: o banco exige que as dependências já existam (T65)
        no, params = por_id[k]
        await conn.execute(
            """insert into analysis.tasks (analysis_id, plan_id, node_id, tool_code, params, depends_on, criticality)
               values (%s, %s, %s, %s, %s, %s, %s::analysis.task_criticality)""",
            (analise.id, plan_id, no.node_id, no.tool_code, Jsonb(params), no.depends_on, no.criticality))
    await an.avancar_status(conn, analise.id, de=("received", "normalized", "planned", "plan_validated", "needs_replan", "compiled"),
                            para="compiled")
    return Compilado(plan_id=plan_id, version=int(version), ordem=ordem, validation_report=report)
