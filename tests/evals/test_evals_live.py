"""
Evals do Copiloto com o provedor REAL — opt-in (`PLEXO_LIVE=1`), fora da suíte padrão.

O que mede (por caso de `casos.yaml`): roteamento, tool escolhida, texto do modelo vs. texto fixo,
citação de fonte, vocabulário/rótulos, números fora de tool, custo e latência (de `llm.model_calls`).
Cada caso é um teste parametrizado: roda no banco de dev dentro da transação do conftest (rollback
no fim — a cota do plano free zera a cada caso). Um caso NÃO falha o teste: o relatório JSON
(`tests/evals/relatorios/<data>.json`) é o produto; a rodada só falha se a taxa global de acerto
ficar abaixo de `EVALS_MIN_ACERTO` (default 0). Serve para comparar ANTES/DEPOIS de mudanças no
turno e nos prompts (varredura de 2026-08-25).
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import time
from datetime import datetime, timezone
from typing import Any

import pytest
import yaml

from app.agents import eventos as ev
from app.agents.turn import TurnoCopiloto, TurnoInput
from app.config.policies import PolicyStore
from app.tools import carregar_tools

pytestmark = [pytest.mark.evals,
              pytest.mark.skipif(not os.getenv("PLEXO_LIVE"), reason="evals com provedor real: PLEXO_LIVE=1")]

AQUI = pathlib.Path(__file__).parent
CASOS = yaml.safe_load((AQUI / "casos.yaml").read_text(encoding="utf-8"))["casos"]
RELATORIOS = AQUI / "relatorios"

# Textos fixos do turno/guardrails: resposta que começa assim NÃO foi redigida pelo modelo.
_PREFIXOS_FIXOS = (
    "Não consegui montar os parâmetros", "Antes de calcular, preciso de um dado seu",
    "Ainda não tenho conteúdo aprovado", "Isso é assunto para outro agente",
    "Não consegui redigir", "Medi o que coube neste turno", "Os números da simulação estão registrados",
    "Não consegui concluir este turno", "Não tenho certeza de qual agente atende melhor",
    "Análise aprofundada registrada",
)
_NUMERO = re.compile(r"(R\$\s?\d|\d+(?:[.,]\d+)?\s?%)")

carregar_tools()


@pytest.fixture(scope="session")
def relatorio():
    """Acumula os resultados da sessão e grava o JSON no fim."""
    dados: dict[str, Any] = {"iniciado_em": datetime.now(timezone.utc).isoformat(), "casos": []}
    yield dados
    if not dados["casos"]:
        return
    checks = [c for caso in dados["casos"] for c in caso["checagens"]]
    ok = sum(1 for c in checks if c["ok"])
    dados["resumo"] = {
        "casos": len(dados["casos"]),
        "casos_ok": sum(1 for caso in dados["casos"] if caso["ok"]),
        "checagens": len(checks), "checagens_ok": ok,
        "taxa_checagens": round(ok / len(checks), 4) if checks else None,
        "custo_usd": round(sum(caso["custo_usd"] or 0 for caso in dados["casos"]), 4),
        "latencia_media_ms": int(sum(caso["latencia_ms"] for caso in dados["casos"]) / len(dados["casos"])),
        "por_agente": _por_agente(dados["casos"]),
    }
    RELATORIOS.mkdir(exist_ok=True)
    destino = RELATORIOS / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[evals] relatório: {destino}\n[evals] resumo: {json.dumps(dados['resumo'], ensure_ascii=False)}")
    minimo = float(os.getenv("EVALS_MIN_ACERTO", "0"))
    assert (dados["resumo"]["taxa_checagens"] or 0) >= minimo, f"taxa de acerto abaixo de EVALS_MIN_ACERTO={minimo}"


def _por_agente(casos: list[dict]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for caso in casos:
        chave = caso["agente"] or "roteador"
        d = out.setdefault(chave, {"casos": 0, "ok": 0})
        d["casos"] += 1
        d["ok"] += int(caso["ok"])
    return out


PERSONA_USER = "0fe0a000-0000-4000-8000-000000000001"
PERSONA_SCOPE = "0fe0a000-0000-4000-8000-000000000002"


@pytest.fixture
async def escopo_persona(db, escopos):
    """A persona de `seeds/persona.sql` — patrimônio completo, plano `essential`, vetos declarados.

    É dado COMMITADO (não da transação do teste): os casos `pers_*` medem o Assessor sobre um
    cliente de verdade, não sobre dois números sintéticos. Sem o seed, pulam — medir um escopo
    vazio e chamar de eval seria pior que não medir."""
    async with db.service_session() as conn:
        cur = await conn.execute("select 1 from identity.scopes where id = %s", (PERSONA_SCOPE,))
        if await cur.fetchone() is None:
            pytest.skip("persona não semeada — rode `python -m app.cli seed persona`")
    return dataclasses.replace(escopos, u1=PERSONA_USER, s1=PERSONA_SCOPE)


@pytest.fixture
async def escopo_eval(db, escopos):
    """Escopo com renda e orçamento registrados (o Assessor mede sobre eles). Mercado vem do dev."""
    async with db.service_session() as conn:
        await conn.execute(
            "insert into budget.income_summaries (scope_id, month, fixed_brl, variable_brl, "
            " variable_p10_brl, committable_brl, variable_share, months_observed) "
            "values (%s, date_trunc('month', current_date)::date, 12000, 8000, 2000, 14000, 0.4, 12)",
            (escopos.s1,))
        for i in range(1, 7):
            await conn.execute(
                "insert into budget.monthly_summaries (scope_id, month, income_brl, expense_brl) "
                "values (%s, (date_trunc('month', current_date) - (%s || ' month')::interval)::date, 20000, 9000)",
                (escopos.s1, i))
    return escopos


def _texto(eventos: list[ev.Evento]) -> str:
    return "".join(e.texto for e in eventos if isinstance(e, ev.Delta)).strip()


def _checar(espera: dict[str, Any], eventos: list[ev.Evento], texto: str, cited: list[dict]) -> list[dict[str, Any]]:
    baixo = texto.lower()
    tools = [e.code for e in eventos if isinstance(e, ev.ToolDone)]
    routed = next((e for e in eventos if isinstance(e, ev.Routed)), None)
    handoff = next((e for e in eventos if isinstance(e, ev.HandoffSuggested)), None)
    clarify = next((e for e in eventos if isinstance(e, ev.Clarify)), None)
    out: list[dict[str, Any]] = []

    def add(nome: str, ok: bool, detalhe: str = ""):
        out.append({"criterio": nome, "ok": bool(ok), "detalhe": detalhe})

    for nome, valor in espera.items():
        if nome == "roteado_para":
            add(nome, routed is not None and routed.agent_code == valor, f"routed={routed.agent_code if routed else None}")
        elif nome == "clarify":
            add(nome, (clarify is not None) == bool(valor), f"clarify={clarify.mensagem[:80] if clarify else None}")
        elif nome == "handoff_para":
            add(nome, handoff is not None and handoff.para == valor, f"handoff={handoff.para if handoff else None}")
        elif nome == "tool":
            add(nome, valor in tools, f"tools={tools}")
        elif nome == "sem_tool":
            add(nome, (not tools) == bool(valor), f"tools={tools}")
        elif nome == "contem":
            faltam = [s for s in valor if s.lower() not in baixo]
            add(nome, not faltam, f"faltam={faltam}")
        elif nome == "contem_algum":
            add(nome, any(s.lower() in baixo for s in valor), f"nenhum de {valor}")
        elif nome == "nao_contem":
            achados = [s for s in valor if s.lower() in baixo]
            add(nome, not achados, f"achados={achados}")
        elif nome == "cita_fonte":
            tem = any(r.get("kind") == "education_content" for r in cited)
            add(nome, tem == bool(valor), f"cited={[r.get('kind') for r in cited]}")
        elif nome == "ilustrativo":
            add(nome, ("ilustrativ" in baixo) == bool(valor))
        elif nome == "sem_numero":
            m = _NUMERO.search(texto)
            add(nome, (m is None) == bool(valor), f"numero={m.group(0) if m else None}")
        elif nome == "resposta_do_modelo":
            fonte = clarify.mensagem if clarify else texto
            fixo = not fonte or any(fonte.startswith(p) for p in _PREFIXOS_FIXOS)
            add(nome, (not fixo) == bool(valor), f"inicio={fonte[:60]!r}")
        else:
            add(nome, False, "critério desconhecido")
    return out


@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
async def test_eval(db, settings, escopo_eval, escopo_persona, relatorio, caso):
    from app.llm.deepseek import DeepSeekClient   # só com PLEXO_LIVE (exige chave)

    # Caso `pers_*` roda sobre a persona commitada; o resto segue no escopo sintético.
    e = escopo_persona if caso["id"].startswith("pers_") else escopo_eval
    turno = TurnoCopiloto(db=db, llm=DeepSeekClient(settings), policies=PolicyStore(db, ttl_s=0))
    registro: dict[str, Any] = {"id": caso["id"], "agente": caso.get("agente"), "turnos": [], "checagens": []}
    conversation_id = None
    t0 = time.perf_counter()
    for turno_caso in caso["turnos"]:
        eventos: list[ev.Evento] = []
        try:
            async for evento in turno.executar(TurnoInput(texto=turno_caso["pergunta"], user_id=e.u1, scope_id=e.s1,
                                                          agent_code=caso.get("agente"), conversation_id=conversation_id)):
                eventos.append(evento)
        except Exception as exc:  # noqa: BLE001 — o relatório registra a falha; o eval segue
            eventos.append(ev.Erro(tipo="excecao", mensagem=f"{type(exc).__name__}: {exc}"[:300]))
        done = next((x for x in eventos if isinstance(x, ev.Done)), None)
        if done is not None:
            conversation_id = done.conversation_id
        texto = _texto(eventos)
        checagens = _checar(turno_caso.get("espera", {}), eventos, texto, list(done.cited_refs) if done else [])
        registro["turnos"].append({
            "pergunta": turno_caso["pergunta"], "resposta": texto,
            "eventos": [x.nome for x in eventos],
            "erro": next((x.to_dict() for x in eventos if isinstance(x, ev.Erro)), None),
            "checagens": checagens,
        })
        registro["checagens"].extend(checagens)
        if done is None:
            break
    registro["latencia_ms"] = int((time.perf_counter() - t0) * 1000)
    registro["custo_usd"] = None
    registro["chamadas"] = 0
    if conversation_id:
        async with db.service_session() as conn:
            cur = await conn.execute(
                "select count(*), coalesce(sum(cost_usd), 0)::float, coalesce(sum(input_tokens), 0), coalesce(sum(output_tokens), 0) "
                "from llm.model_calls where conversation_id = %s", (conversation_id,))
            n, custo, tin, tout = await cur.fetchone()
            registro.update(chamadas=n, custo_usd=custo, input_tokens=tin, output_tokens=tout)
    registro["ok"] = all(c["ok"] for c in registro["checagens"])
    relatorio["casos"].append(registro)
