"""A metade IMPURA do Monte Carlo: lê premissa e meta, roda, grava, audita.

O QUE DECIDE ESTE ARQUIVO, E O QUE ELE SE RECUSA A DECIDIR
    Decide: de onde vem cada insumo, o que fazer quando um deles falta, e o que fica gravado
    para alguém conferir depois. Não decide nada de matemática — isso é `simulacao.py`, que
    não conhece banco — nem de julgamento de risco, que é `elegibilidade.py`.

UM RUN POR ALOCAÇÃO, E O MOTIVO
    `planning.goal_projections` tem UNIQUE (goal_id, run_id) desde a migration 07: uma linha
    por meta por execução. Como cada meta é simulada sob TRÊS alocações candidatas, cada
    alocação recebe seu próprio `engine.runs` — e isso é mais certo do que parece
    conveniente: a alocação É um insumo da simulação, então duas alocações são duas
    execuções com `input_hash` diferente. Um run por alocação é o que torna cada número
    rastreável até a entrada exata que o produziu.

O QUE FALTA VIRA AUSÊNCIA DECLARADA, NUNCA ZERO
    Sem aporte conhecido não há projeção — e a resposta é dizer isso, com o nome do que
    falta, não simular com aporte zero e devolver uma probabilidade de 3%. É a mesma regra
    que governa indicador sem fato (F14) e score sem cobertura (C40b): imputar zero diria ao
    cliente que ele vai mal onde, na verdade, ninguém mediu.

SALDO INICIAL: SÓ O QUE ESTÁ CARIMBADO PARA A META
    `planning.goals.linked_account_ids` é o carimbo. Sem ele o saldo inicial é ZERO, e isso
    é deliberado: usar o patrimônio inteiro como ponto de partida de cada meta atribuiria o
    mesmo dinheiro a três objetivos ao mesmo tempo, e a soma das probabilidades seria uma
    ficção otimista. Zero aqui não é ausência mal tratada — é a leitura conservadora de um
    dinheiro que ninguém reservou.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.engine.elegibilidade import Veredito, avaliar
from app.engine.simulacao import (
    Distribuicao, Meta, Premissas, simular, volatilidade_da_carteira,
)
from app.tools.hashing import canonical_json, sha256_hex

log = logging.getLogger(__name__)

POLICY = "SIMULACAO_METAS"
SEMVER = "1.0.0"
MESES_POR_ANO = 12

# COMPROMETÍVEL, não a média: "não se compromete o que só aparece nos bons meses" é regra
# explícita da migration 24, e aporte mensal é exatamente um compromisso recorrente. Usar a
# renda média dava R$ 13.200 de sobra onde a tool de capacidade dizia R$ 9.200 — duas
# respostas para a mesma pergunta, na mesma tela, e a mais otimista era a que virava projeção.
FATO_RENDA = "renda.comprometivel"
FATO_RENDA_FALLBACK = "renda.mensal_liquida"
FATO_DESPESA = "despesa.total_mensal"
FATO_PROBABILIDADE = "objetivo.probabilidade_sucesso"


@dataclass
class ResultadoProjecao:
    goal_id: str
    nome: str
    meses: int
    valor_alvo: float
    indisponivel: bool = False
    motivo_indisponivel: str | None = None
    faltando: list[str] | None = None
    meta: Meta | None = None
    origem_do_aporte: str | None = None      # declarado | rateio_por_prioridade | unico_objetivo
    fatia_do_aporte: float | None = None     # fração da sobra destinada a este objetivo
    distribuicoes: list[Distribuicao] | None = None
    veredito: Veredito | None = None
    run_ids: dict[str, str] | None = None


async def _politica(conn: AsyncConnection) -> tuple[str, dict[str, Any], str]:
    cur = await conn.execute(
        "select id::text, payload, compliance_status::text from engine.policy_versions "
        "where code = %s and effective_to is null", (POLICY,))
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"política {POLICY} não está vigente — premissa numérica não tem default no código")
    return row


async def carregar_premissas(conn: AsyncConnection, code: str) -> tuple[str, Premissas, str]:
    """Lê o conjunto VIGENTE de premissas de mercado, com seu status de compliance."""
    cur = await conn.execute(
        "select id::text, compliance_status::text from market.assumption_sets "
        "where code = %s and effective_to is null", (code,))
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"conjunto de premissas '{code}' não está vigente — a simulação não inventa "
            "retorno esperado, e não há default no código (migration 48)")
    set_id, status = row

    cur = await conn.execute(
        "select asset_class_code, retorno_real_aa::float, volatilidade_aa::float "
        "from market.class_assumptions where assumption_set_id = %s", (set_id,))
    linhas = await cur.fetchall()
    if not linhas:
        raise RuntimeError(f"conjunto '{code}' sem nenhuma classe de ativo")

    cur = await conn.execute(
        "select classe_a, classe_b, correlacao::float from market.class_correlations "
        "where assumption_set_id = %s", (set_id,))
    pares = await cur.fetchall()

    return set_id, Premissas(
        retornos={c: r for c, r, _ in linhas},
        volatilidades={c: v for c, _, v in linhas},
        correlacoes={(a, b): p for a, b, p in pares}), status


def repartir_aporte(metas: list[tuple[str, int, float | None]],
                    sobra: float | None) -> dict[str, dict[str, Any]]:
    """Divide o dinheiro disponível entre os objetivos ativos. PURA, e testável sem banco.

    O DEFEITO QUE ISTO CORRIGE
        Cada objetivo era projetado com a sobra INTEIRA. Uma cliente com R$ 9.200 por mês e
        dois objetivos via a faculdade (alvo de R$ 600 mil) com mediana de R$ 1,96 milhão —
        porque a simulação deu a ela todo o dinheiro, e deu o mesmo dinheiro à aposentadoria.
        As duas probabilidades eram verdadeiras isoladamente e impossíveis juntas: o plano
        prometia o mesmo real duas vezes.

    A REGRA
        1. Objetivo com aporte DECLARADO usa o declarado. O cliente sabe da vida dele.
        2. O que sobra é repartido entre os demais por PRIORIDADE, com peso 1/prioridade
           normalizado — prioridade 1 recebe o dobro da 2, o triplo da 3. É uma regra que
           qualquer pessoa confere de cabeça, e conferível é metade de justo.
        3. Um objetivo só: recebe tudo, e a origem diz isso — não há divisão a explicar.

    Devolve, por objetivo, o aporte E DE ONDE ELE VEIO. A origem não é enfeite: sem ela a
    tela não consegue dizer "dividi assim", e uma divisão que o cliente não vê é uma premissa
    escondida.
    """
    saida: dict[str, dict[str, Any]] = {}
    declarados = {gid: float(v) for gid, _p, v in metas if v is not None}
    sem_declaracao = [(gid, max(1, int(prio))) for gid, prio, v in metas if v is None]

    for gid, valor in declarados.items():
        saida[gid] = {"aporte": valor, "origem": "declarado", "fatia": None}

    if not sem_declaracao:
        return saida
    if sobra is None:
        for gid, _prio in sem_declaracao:
            saida[gid] = {"aporte": None, "origem": None, "fatia": None}
        return saida

    restante = max(0.0, float(sobra) - sum(declarados.values()))
    if len(sem_declaracao) == 1 and not declarados:
        gid = sem_declaracao[0][0]
        saida[gid] = {"aporte": restante, "origem": "unico_objetivo", "fatia": 1.0}
        return saida

    pesos = {gid: 1.0 / prio for gid, prio in sem_declaracao}
    total = sum(pesos.values())
    for gid, peso in pesos.items():
        fatia = peso / total
        saida[gid] = {"aporte": round(restante * fatia, 2),
                      "origem": "rateio_por_prioridade", "fatia": round(fatia, 4)}
    return saida


def ordem_de_risco(alocacoes: dict[str, dict[str, float]],
                   premissas: Premissas) -> list[str]:
    """Do menos ao mais exposto a risco, medido pela VOLATILIDADE da carteira.

    A primeira versão disto lia a ordem das chaves do `payload` — e ficou verde por 20
    minutos enquanto fazia a coisa exatamente ao contrário. `jsonb` NÃO preserva a ordem de
    inserção: o Postgres reordena as chaves por tamanho e depois por bytes, então
    `{"conservadora":…, "balanceada":…, "arrojada":…}` volta do banco como
    `arrojada, balanceada, conservadora`. A caminhada da elegibilidade partia da carteira
    mais arrojada como BASE e comparava as outras contra ela — a regra do §4 invertida, sem
    erro nenhum aparecendo.

    A correção não é declarar a ordem numa lista, que poderia discordar dos pesos sem que
    ninguém percebesse: é DERIVÁ-LA do próprio insumo. σ_p é exatamente o eixo sobre o qual
    a regra caminha — o p5 piora porque a volatilidade cresce —, então ordenar por ele torna
    a ordem impossível de divergir da carteira que ela ordena.
    """
    return sorted(alocacoes, key=lambda nome: volatilidade_da_carteira(alocacoes[nome],
                                                                      premissas))


async def _fato(conn: AsyncConnection, scope_id: str, fact_key: str) -> float | None:
    """Janela OPERÁVEL (confirmado + inferido), que é a do motor — `v_fact_current` é a do
    agente e só devolve o confirmado (migration 43)."""
    cur = await conn.execute(
        "select numero::float from context.v_fact_operavel "
        "where scope_id = %s and fact_key = %s", (scope_id, fact_key))
    row = await cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


async def _saldo_carimbado(conn: AsyncConnection, scope_id: str,
                           contas: list[str] | None) -> float:
    if not contas:
        return 0.0
    cur = await conn.execute(
        """select coalesce(sum(b.balance_brl), 0)::float
             from wealth.account_balances b
             join (select account_id, max(as_of_date) as d from wealth.account_balances
                    where scope_id = %s and account_id = any(%s) group by account_id) u
               on u.account_id = b.account_id and u.d = b.as_of_date
            where b.scope_id = %s""", (scope_id, contas, scope_id))
    row = await cur.fetchone()
    return float(row[0]) if row else 0.0


async def _meses_ate(conn: AsyncConnection, alvo: date, hoje: date) -> int:
    return max(0, (alvo.year - hoje.year) * MESES_POR_ANO + (alvo.month - hoje.month))


async def projetar_escopo(conn: AsyncConnection, scope_id: str, *,
                          goal_id: str | None = None,
                          as_of: date | None = None,
                          semente: int | None = None,
                          client_facing: bool | None = None) -> list[ResultadoProjecao]:
    """Projeta todas as metas ativas do escopo (ou uma), grava e devolve o diagnóstico."""
    as_of = as_of or date.today()
    policy_id, payload, policy_status = await _politica(conn)

    alocacoes: dict[str, dict[str, float]] = payload["alocacoes"]
    caminhos = int(payload.get("n_caminhos", 10_000))
    semente = int(semente if semente is not None else payload.get("semente", 20260823))
    confianca = float(payload.get("nivel_confianca_padrao", 0.90))
    regra = payload.get("elegibilidade_de_risco") or {}
    limiar = float(regra.get("limiar_materialidade_prob", 0.10))
    piora_max = float(regra.get("piora_maxima_do_p5", 0.10))

    set_id, premissas, premissa_status = await carregar_premissas(
        conn, payload.get("conjunto_de_premissas", "PLEXO_BASE"))

    ordem = ordem_de_risco(alocacoes, premissas)

    # client_facing só quando as DUAS opiniões passaram por compliance: a curva de decisão
    # (política) e o retorno esperado (premissa de mercado). O C48c recusaria, e com razão.
    if client_facing is None:
        client_facing = policy_status == "approved" and premissa_status == "approved"

    sql = ("select id::text, name, target_amount_brl::float, target_date, "
           "       monthly_contribution_brl::float, linked_account_ids "
           "  from planning.goals where scope_id = %s and status = 'ativa'")
    params: list[Any] = [scope_id]
    if goal_id:
        sql += " and id = %s"
        params.append(goal_id)
    cur = await conn.execute(sql + " order by priority, created_at", params)
    metas = await cur.fetchall()

    cur = await conn.execute(
        "select id::text, priority::int, monthly_contribution_brl::float "
        "  from planning.goals where scope_id = %s and status = 'ativa'", (scope_id,))
    ativas = await cur.fetchall()

    renda = await _fato(conn, scope_id, FATO_RENDA)
    if renda is None:
        # Sem piso derivado, a líquida é o que há — e é melhor que não projetar. O aviso de
        # que a conta usou a média fica no resultado.
        renda = await _fato(conn, scope_id, FATO_RENDA_FALLBACK)
    despesa = await _fato(conn, scope_id, FATO_DESPESA)
    sobra = (renda - despesa) if (renda is not None and despesa is not None) else None

    reparticao = repartir_aporte(ativas, sobra)

    engine_version_id = await _engine_version_id(conn)
    resultados: list[ResultadoProjecao] = []

    for gid, nome, alvo, data_alvo, aporte_declarado, contas in metas:
        meses = await _meses_ate(conn, data_alvo, as_of)
        r = ResultadoProjecao(goal_id=gid, nome=nome, meses=meses, valor_alvo=float(alvo))

        if meses <= 0:
            r.indisponivel = True
            r.motivo_indisponivel = "prazo_vencido"
            resultados.append(r)
            continue

        aporte = reparticao.get(gid, {}).get("aporte")
        if aporte is None:
            # Sem aporte não há projeção — e dizer isso, com o nome do que falta, vale mais
            # que uma probabilidade calculada sobre aporte zero.
            r.indisponivel = True
            r.motivo_indisponivel = "aporte_desconhecido"
            r.faltando = [k for k, v in ((FATO_RENDA, renda), (FATO_DESPESA, despesa))
                          if v is None]
            resultados.append(r)
            continue

        if aporte <= 0:
            # Simular com aporte zero devolveria "0% de chance", e isso soaria como um
            # diagnóstico sobre o objetivo quando é um diagnóstico sobre o ORÇAMENTO. A
            # persona autônoma é o caso: o piso da renda dela não cobre a própria despesa,
            # então não há o que aportar — e dizer isso vale mais que uma probabilidade.
            r.indisponivel = True
            r.motivo_indisponivel = "sem_sobra_para_aportar"
            resultados.append(r)
            continue

        meta = Meta(valor_alvo=float(alvo), meses=meses, aporte_mensal=aporte,
                    saldo_inicial=await _saldo_carimbado(conn, scope_id, contas))
        r.meta = meta
        r.origem_do_aporte = reparticao[gid]["origem"]
        r.fatia_do_aporte = reparticao[gid]["fatia"]

        distribuicoes = [
            simular(pesos, premissas, meta, caminhos=caminhos, semente=semente,
                    alocacao=alocacao, confianca_do_aporte=confianca)
            for alocacao, pesos in alocacoes.items()]
        veredito = avaliar(distribuicoes, ordem=ordem, limiar_materialidade_prob=limiar,
                           piora_maxima_do_p5=piora_max, meses=meses)
        r.distribuicoes = distribuicoes
        r.veredito = veredito
        r.run_ids = {}

        for d in distribuicoes:
            eleita = d.alocacao == veredito.alocacao
            entrada = {"scope_id": scope_id, "goal_id": gid, "as_of": as_of.isoformat(),
                       "alocacao": d.alocacao, "pesos": alocacoes[d.alocacao],
                       "meta": {"alvo": meta.valor_alvo, "meses": meta.meses,
                                "aporte": meta.aporte_mensal, "inicial": meta.saldo_inicial},
                       "premissas": set_id, "policy": policy_id,
                       "semente": semente, "caminhos": caminhos, "semver": SEMVER}
            cur = await conn.execute(
                """insert into engine.runs (scope_id, kind, engine_version_id,
                                            policy_version_ids, params, input_hash, status,
                                            is_client_facing, as_of_date, triggered_by)
                   values (%s, 'projection', %s, %s, %s, %s, 'running', %s, %s, 'job')
                   returning id::text""",
                (scope_id, engine_version_id, [policy_id],
                 # a semente vai para `params`, que entra no input_hash e portanto na
                 # identidade do run — é o que o C48e exige para a projeção ser refazível
                 Jsonb({"semente": semente, "n_caminhos": caminhos, "alocacao": d.alocacao,
                        "semver": SEMVER, "policy_status": policy_status,
                        "premissa_status": premissa_status}),
                 sha256_hex(canonical_json(entrada)),
                 client_facing and eleita, as_of))
            run_id = (await cur.fetchone())[0]
            r.run_ids[d.alocacao] = run_id

            await conn.execute(
                """insert into planning.goal_projections
                     (goal_id, scope_id, run_id, as_of_date, assumption_set_id, alocacao_code,
                      success_prob, prob_abaixo_do_depositado, required_monthly_brl,
                      p5_brl, p10_brl, p25_brl, p50_brl, p75_brl, p90_brl, p95_brl,
                      assumptions)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (gid, scope_id, run_id, as_of, set_id, d.alocacao,
                 round(d.prob_sucesso, 4), round(d.prob_abaixo_do_depositado, 4),
                 _brl(d.aporte_necessario),
                 _brl(d.percentis[5]), _brl(d.percentis[10]), _brl(d.percentis[25]),
                 _brl(d.percentis[50]), _brl(d.percentis[75]), _brl(d.percentis[90]),
                 _brl(d.percentis[95]),
                 Jsonb({"alocacao": d.alocacao, "pesos": alocacoes[d.alocacao],
                        "eleita": eleita, "veredito": veredito.motivo if eleita else None,
                        "retorno_aa": round(d.retorno_aa, 4),
                        "volatilidade_aa": round(d.volatilidade_aa, 4),
                        "total_depositado": round(d.total_depositado, 2),
                        "metodo": "log-retornos normais, aporte no fim do mês, "
                                  "volatilidade da carteira por raiz de wᵀΣw",
                        "limitacao": "a normal subestima a cauda: crise real é pior que o p5"})))

            saida = {"percentis": {q: round(v, 2) for q, v in d.percentis.items()},
                     "prob": round(d.prob_sucesso, 4)}
            await conn.execute(
                "update engine.runs set status = 'succeeded', output_hash = %s, "
                "finished_at = now() where id = %s",
                (sha256_hex(canonical_json(saida)), run_id))

        resultados.append(r)

    await _derivar_probabilidade(conn, scope_id, resultados)
    return resultados


async def _derivar_probabilidade(conn: AsyncConnection, scope_id: str,
                                 resultados: list[ResultadoProjecao]) -> str | None:
    """Grava `objetivo.probabilidade_sucesso` — quem escreve o fato que o Destino lê.

    A F16 custou meia sessão para descobrir que `diagnostics.foundation_status` não tinha
    produtor: o gate existia, era testado por sabotagem em três arquivos, e nunca disparava.
    O indicador `destino.probabilidade_meta` nasce na migration 50 já com quem o alimenta,
    e é esta função.

    A MENOR probabilidade entre os objetivos ativos, não a média: o Destino de alguém é tão
    firme quanto o objetivo que ele tem menos chance de alcançar. A média deixaria um
    objetivo inalcançável desaparecer atrás de dois fáceis — o mesmo motivo pelo qual o
    produto recusou ter score único.

    As duas regras do job de derivação valem aqui igual (`app/context/derivacao.py`): não se
    deriva por cima do que o cliente confirmou, e não se regrava valor igual — senão o
    histórico do cliente vira log de execução do motor, e `context.assertions` é append-only.
    """
    eleitas = [r for r in resultados
               if not r.indisponivel and r.veredito is not None and r.distribuicoes]
    if not eleitas:
        return None

    menor = min(
        next(d for d in r.distribuicoes if d.alocacao == r.veredito.alocacao).prob_sucesso
        for r in eleitas)

    cur = await conn.execute(
        "select 1 from context.assertions where scope_id = %s and fact_key = %s "
        "and status = 'confirmado' and superseded_at is null limit 1",
        (scope_id, FATO_PROBABILIDADE))
    if await cur.fetchone():
        return None

    cur = await conn.execute(
        "select numero::float from context.v_fact_operavel "
        "where scope_id = %s and fact_key = %s", (scope_id, FATO_PROBABILIDADE))
    row = await cur.fetchone()
    if row and row[0] is not None and abs(float(row[0]) - menor) < 0.005:
        return None

    cur = await conn.execute(
        "select owner_user_id::text from identity.scopes where id = %s", (scope_id,))
    dono = await cur.fetchone()

    try:
        async with conn.transaction():
            cur = await conn.execute(
                """insert into context.assertions
                     (scope_id, user_id, fact_key, subject_kind, attribute, value, unit,
                      modality, status, confidence, source, source_ref)
                   values (%s, %s, %s, 'objetivo', 'objetivo_probabilidade_sucesso',
                           %s, 'fracao', 'fato', 'inferido', %s, 'inferencia_motor', %s)
                   returning id::text""",
                (scope_id, dono[0] if dono else None, FATO_PROBABILIDADE,
                 Jsonb({"amount": round(menor, 4)}), 0.9,
                 Jsonb({"derivado_de": "engine.runs kind=projection",
                        "criterio": "menor probabilidade entre os objetivos ativos",
                        "objetivos": len(eleitas)})))
            return (await cur.fetchone())[0]
    except Exception as e:                            # noqa: BLE001 — o motivo é o dado
        log.warning("probabilidade não derivada (scope=%s): %s",
                    scope_id, str(e).strip().splitlines()[0])
        return None


async def _engine_version_id(conn: AsyncConnection) -> str:
    """Mesma resolução usada pelo perfil (F14): a versão do motor é parte da auditoria."""
    from app.engine.perfil import _engine_version_id as resolver
    return await resolver(conn)


def _brl(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)
