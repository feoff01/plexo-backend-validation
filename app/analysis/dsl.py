"""DSL do plano de análise (AnalysisPlan). Pydantic estrito no molde de `app/context/schemas.py`:
item inválido é DESCARTADO com motivo, nunca derruba o plano inteiro; quem dependia de nó descartado cai
junto (ponto fixo). Plano sem nó válido ⇒ `PlanoVazio`. Aqui não há banco nem registry — é pura."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DSL_VERSION = "1"
Criticidade = Literal["required", "important", "optional"]
_NODE_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class PlanoVazio(ValueError):
    """Nenhum nó válido sobrou — o planner precisa tentar de novo (replan) ou a análise falha."""


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    node_id: str = Field(pattern=_NODE_ID.pattern)
    tool_code: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    criticality: Criticidade = "required"
    motivo: str = ""                       # por que o planner incluiu este nó (auditoria, não instrução)


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dsl_version: str = DSL_VERSION
    objetivo: str = ""
    nodes: list[NodeSpec] = Field(min_length=1)


def _motivo(err: ValidationError) -> str:
    partes = []
    for e in err.errors(include_url=False):
        loc = ".".join(str(x) for x in e.get("loc", ())) or "item"
        partes.append(f"{loc}: {e.get('msg')}")
    return "; ".join(partes)


def validar_plano(obj: Any) -> tuple[AnalysisPlan, list[dict[str, Any]]]:
    """Devolve (plano só com nós válidos, descartados [{indice, node_id, motivo}])."""
    if not isinstance(obj, dict) or not isinstance(obj.get("nodes"), list):
        raise PlanoVazio("plano sem lista `nodes`")
    validos: list[NodeSpec] = []
    descartados: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for i, bruto in enumerate(obj["nodes"]):
        try:
            no = NodeSpec.model_validate(bruto)
        except ValidationError as err:
            descartados.append({"indice": i, "node_id": (bruto or {}).get("node_id") if isinstance(bruto, dict) else None,
                                "motivo": _motivo(err)})
            continue
        if no.node_id in vistos:
            descartados.append({"indice": i, "node_id": no.node_id, "motivo": "node_id duplicado no plano"})
            continue
        vistos.add(no.node_id)
        validos.append(no)

    # ponto fixo: nó que depende de nó ausente (inválido, duplicado ou inexistente) também cai
    mudou = True
    while mudou:
        mudou = False
        presentes = {n.node_id for n in validos}
        for no in list(validos):
            faltam = [d for d in no.depends_on if d not in presentes or d == no.node_id]
            if faltam:
                validos.remove(no)
                descartados.append({"indice": None, "node_id": no.node_id,
                                    "motivo": f"depende de nó ausente ou de si mesmo: {', '.join(faltam)}"})
                mudou = True
    if not validos:
        raise PlanoVazio("nenhum nó válido após a validação: " + "; ".join(d["motivo"] for d in descartados))
    plano = AnalysisPlan(dsl_version=str(obj.get("dsl_version") or DSL_VERSION), objetivo=str(obj.get("objetivo") or ""),
                         nodes=validos)
    return plano, descartados
