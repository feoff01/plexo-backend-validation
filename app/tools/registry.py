"""Registro de tools por decorator — o CÓDIGO é a fonte da verdade; o banco é o espelho (sync).

Cada tool tem duas metades, de propósito:
- `preparar(params, ctx)` — assíncrona: resolve insumos (views, RLS) e PREMISSAS (policies).
  Tudo que ela leu entra em `resolved_params` — é o que torna o cache content-addressed.
- `calcular(resolvido)` — PURA e determinística: recebe o resolvido, devolve o output tipado.
  É a metade travada por golden master; nenhum acesso a banco, relógio ou aleatório.

O `param_schema` sai do Pydantic (model_json_schema) e serve duas vezes: validação no serviço e
tool definition do LLM. Nunca manter cópia manual do schema em prompt (COMMENT de 18_tools).
"""
from __future__ import annotations

import inspect
import pathlib
import typing
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from app.tools.hashing import sha256_fontes

_SEMVER_OK = 3  # major.minor.patch


@dataclass(frozen=True)
class ToolSpec:
    code: str
    family: str
    semver: str
    display_name: str
    description: str
    min_plan: str
    requires_market_data: bool
    is_deterministic: bool
    emite_numero: bool                      # False = saída sem cálculo (glossário): sem rodapé de simulação
    exposed_to_llm: bool                     # False = executável/auditável, mas fora do catálogo do modelo/planner
    params_model: type[BaseModel]
    resolvido_model: type[BaseModel]
    output_model: type[BaseModel]
    preparar: Callable[..., Awaitable[BaseModel]]
    calcular: Callable[[BaseModel], BaseModel]
    module_file: str
    source_files: tuple[str, ...]             # closure de implementação declarada para fingerprint/auditoria
    source_sha256: str
    param_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)


_REG: dict[str, ToolSpec] = {}


def _schema_de(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.setdefault("additionalProperties", False)
    return schema


def tool(*, code: str, family: str, semver: str, display_name: str, description: str,
         preparar: Callable[..., Awaitable[BaseModel]], min_plan: str = "free",
         requires_market_data: bool = False, is_deterministic: bool = True, emite_numero: bool = True,
         exposed_to_llm: bool = True, source_dependencies: tuple[str | pathlib.Path, ...] = ()):
    """Registra a tool.

    `source_dependencies` declara helpers/engines externos que podem alterar o input resolvido ou
    o cálculo. O fingerprint da versão cobre esses arquivos junto do módulo da tool e do módulo de
    `preparar` (quando diferente), sem incluir caminhos absolutos no hash. Isso permite engines
    compartilhados sem quebrar cache/auditoria.

    `exposed_to_llm=False` mantém a tool registrada e executável (útil para migração/retomada),
    mas a retira do catálogo oferecido ao turno e ao Research planner.
    """
    if len(semver.split(".")) != _SEMVER_OK:
        raise ValueError(f"{code}: semver inválida '{semver}'")
    if "PENDENTE" in description or not description.strip():
        raise ValueError(f"{code}: description é o que o LLM lê para escolher a tool — escreva-a")

    def deco(calcular: Callable[[BaseModel], BaseModel]):
        hints_prep = typing.get_type_hints(preparar)
        hints_calc = typing.get_type_hints(calcular)
        params_model = next(iter(hints_prep.values()))          # primeiro parâmetro de preparar
        resolvido_model = next(iter(hints_calc.values()))       # primeiro parâmetro de calcular
        output_model = hints_calc["return"]
        module_file = pathlib.Path(inspect.getsourcefile(calcular)).resolve()
        preparar_file = pathlib.Path(inspect.getsourcefile(preparar)).resolve()
        source_files = tuple(dict.fromkeys(
            str(pathlib.Path(c).resolve()) for c in (module_file, preparar_file, *source_dependencies)
        ))
        spec = ToolSpec(
            code=code, family=family, semver=semver, display_name=display_name,
            description=description.strip(), min_plan=min_plan,
            requires_market_data=requires_market_data, is_deterministic=is_deterministic,
            emite_numero=emite_numero, exposed_to_llm=exposed_to_llm,
            params_model=params_model, resolvido_model=resolvido_model, output_model=output_model,
            preparar=preparar, calcular=calcular, module_file=str(module_file), source_files=source_files,
            source_sha256=sha256_fontes(source_files),
            param_schema=_schema_de(params_model), output_schema=_schema_de(output_model),
        )
        anterior = _REG.get(code)
        if anterior is not None and anterior.module_file != spec.module_file:
            raise ValueError(f"tool {code} registrada duas vezes ({anterior.module_file} e {spec.module_file})")
        _REG[code] = spec
        return calcular

    return deco


def spec_de(code: str) -> ToolSpec:
    if code not in _REG:
        raise KeyError(f"tool '{code}' não registrada — faltou carregar_tools()/import do módulo?")
    return _REG[code]


def specs_registradas() -> list[ToolSpec]:
    return sorted(_REG.values(), key=lambda s: s.code)
