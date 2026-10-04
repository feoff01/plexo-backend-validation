"""Derivação: o que o banco já sabe sobre o cliente vira fato catalogado.

POR QUE ESTE MÓDULO EXISTE
    A F14 entregou o catálogo, o card e o motor — e a verificação mostrou a persona de
    demonstração com R$ 1,52 milhão em dados estruturados e **0% de cobertura**. Renda,
    orçamento, dívida, patrimônio e família estavam em `budget.*`, `estate.*` e
    `household.*`, e nada os lia como fato. O motor respondia "dados_insuficientes" sobre
    um cliente que o banco conhecia inteiro.

O QUE ELE NÃO FAZ, E É O MAIS IMPORTANTE
    Não transforma dedução em confissão. Toda asserção aqui nasce `inferido` com
    `source='inferencia_motor'` — C22a intacta. Quem lê isso é o MOTOR
    (`context.v_fact_operavel`); o agente continua vendo só `context.v_fact_current`, que
    é o que o cliente confirmou. A confiança grava o desconto de
    `CONTEXT_FACT_CATALOG.fator_confianca_derivado`.

DUAS REGRAS DO JOB, as duas com teste
    1. **Não deriva o que o cliente já confirmou.** Derivar por cima geraria uma asserção
       divergente que o gate C38c marca `conflitante` — ruído, e um conflito que ninguém
       pediu. Se o cliente disse, o cliente manda.
    2. **Não regrava valor igual.** `context.assertions` é append-only: sem esta regra o
       job diário empilharia uma linha por fato por dia, e o histórico do cliente viraria
       log de execução do motor.

A parte que lê banco e a que decide o valor estão separadas, como nas tools: `coletar` é
IO, `derivar` é pura e testável sem Postgres.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.tools.context_pack import (
    dividas_ativas, income_breakdown, media_custo_mensal, reserve_settings,
    ultimo_income_summary,
)

log = logging.getLogger(__name__)

def _mudou(anterior: float, novo: float, mat_abs: float, mat_rel: float) -> bool:
    """O valor mudou o suficiente para virar asserção nova?

    O limiar vem do CATÁLOGO — `materiality_abs` e `materiality_rel`, o maior dos dois, a
    mesma regra que o banco aplica às propostas (T83a). Antes era um `0.005` cravado no
    código, e ele produzia um defeito silencioso e progressivo:

        `objetivo.prazo_meses` é uma contagem regressiva. Derivado em dias/30,4375, ele muda
        TODO DIA (23,10 → 23,06 → 23,03). Cada derivação passava do 0,005, gravava asserção
        nova, e o gate C38c marcava a nova e a anterior como `conflitante` — as duas fora da
        janela operável. Duas execuções bastavam para o fato SUMIR para sempre, levando junto
        o `destino.esforco_requerido`, sem erro nenhum em lugar nenhum.

    O catálogo já dizia que mudança menor que 3 meses não é material nesse fato. Ninguém lia.
    Número mágico contra config-first não é questão de estilo: aqui ele apagava um indicador.
    """
    limiar = max(float(mat_abs or 0), abs(anterior) * float(mat_rel or 0))
    return abs(anterior - novo) > limiar


FONTE = "inferencia_motor"
POLICY = "CONTEXT_FACT_CATALOG"
MESES_POR_ANO = 12          # unidade de calendário, não premissa de negócio


@dataclass
class Bruto:
    """O que as views e tabelas do escopo devolvem, antes de virar fato."""
    income_summary: dict[str, Any] | None = None
    income_breakdown: dict[str, Any] | None = None
    fontes_de_renda: int = 0
    custo_medio_mensal: float | None = None
    meses_de_orcamento: int = 0
    essencial_mensal: float | None = None
    fixo_contratado: float | None = None
    # `None` = nunca consultado; `[]` = consultado e não há dívida ativa. A distinção não é
    # preciosismo: com `[]` como default, um Bruto não populado afirmaria "saldo devedor zero"
    # — mesma falha da lacuna de seguro, que a migration 44 corrigiu.
    dividas: list[dict[str, Any]] | None = None
    patrimonio: dict[str, Any] | None = None
    familia: dict[str, Any] | None = None
    objetivo: dict[str, Any] | None = None
    reserva: float | None = None
    # `identity.users.birth_date` do dono do escopo. Sem ele,
    # `destino.horizonte_aposentadoria` não calcula e a família Destino fica
    # indisponível para todo cliente — foi assim que as seis personas saíram.
    nascimento: Any = None


@dataclass(frozen=True)
class FatoDerivado:
    fact_key: str
    valor: float | None
    origem: str          # que tabela/view sustentou o número — vai para source_ref
    # Fato não numérico (data, texto, booleano) traz o jsonb pronto: o catálogo valida a
    # forma no INSERT (C38a), e `valor` fica None porque não há número a comparar.
    bruto: dict[str, Any] | None = None


# =============================================================================
# IO
# =============================================================================
async def coletar(conn: AsyncConnection, scope_id: str) -> Bruto:
    b = Bruto()
    b.income_summary = await ultimo_income_summary(conn, scope_id)
    b.income_breakdown = await income_breakdown(conn, scope_id)
    b.custo_medio_mensal, b.meses_de_orcamento = await media_custo_mensal(conn, scope_id)
    b.dividas = await dividas_ativas(conn, scope_id)

    cur = await conn.execute(
        "select count(*)::int from budget.income_sources "
        "where scope_id = %s and is_active and ended_at is null", (scope_id,))
    b.fontes_de_renda = (await cur.fetchone())[0]

    # despesa ESSENCIAL: a base da reserva de emergência. Média dos meses que a registraram.
    cur = await conn.execute(
        "select avg(essential_expense_brl)::float from ("
        "  select essential_expense_brl from budget.monthly_summaries "
        "  where scope_id = %s and essential_expense_brl is not null "
        "  order by month desc limit %s) m", (scope_id, MESES_POR_ANO))
    b.essencial_mensal = (await cur.fetchone())[0]

    cur = await conn.execute(
        "select sum(amount_brl)::float from budget.recurring_items "
        "where scope_id = %s and is_active and flow = 'saida' "
        "  and (ends_on is null or ends_on >= current_date)", (scope_id,))
    b.fixo_contratado = (await cur.fetchone())[0]

    cur = await conn.execute(
        "select investivel_brl::float, nao_financeiro_brl::float, patrimonio_liquido_brl::float "
        "from estate.v_net_worth where scope_id = %s", (scope_id,))
    row = await cur.fetchone()
    if row:
        b.patrimonio = {"investivel": row[0], "nao_financeiro": row[1], "liquido": row[2]}

    cur = await conn.execute(
        "select dependents_count::int, members_count::int from household.v_summary "
        "where scope_id = %s", (scope_id,))
    row = await cur.fetchone()
    if row:
        b.familia = {"dependentes": row[0], "membros": row[1]}

    # o objetivo de maior prioridade — o catálogo guarda UM objetivo por escopo (v1)
    cur = await conn.execute(
        "select target_amount_brl::float, priority::int, "
        # MESES INTEIROS, e a diferença não é cosmética: em dias/30,4375 o prazo muda todo
        # dia (23,10 → 23,06 → 23,03), cada derivação diverge da anterior acima do limiar de
        # materialidade, e o gate C38c marca as duas asserções como `conflitante`. Duas
        # execuções bastavam para o fato SUMIR da janela operável para sempre — e com ele o
        # `destino.esforco_requerido`, em silêncio. Contagem regressiva não é fato instável:
        # é fato de granularidade mensal, e é assim que ele tem que ser gravado.
        "       greatest(0, (date_part('year', age(target_date, current_date)) * 12 "
        "                    + date_part('month', age(target_date, current_date))))::float "
        "         as prazo_meses "
        "from planning.goals where scope_id = %s and status = 'ativa' "
        "order by priority, target_date limit 1", (scope_id,))
    row = await cur.fetchone()
    if row:
        b.objetivo = {"valor": row[0], "prioridade": row[1], "prazo_meses": row[2]}

    cur = await conn.execute(
        "select u.birth_date from identity.users u "
        "join identity.scopes s on s.owner_user_id = u.id where s.id = %s", (scope_id,))
    linha = await cur.fetchone()
    b.nascimento = linha[0] if linha else None

    ajustes = await reserve_settings(conn, scope_id)
    if ajustes and ajustes.get("reserve_account_ids"):
        # ÚLTIMO SNAPSHOT DE CADA CONTA, não o último snapshot do conjunto. A versão
        # anterior usava um `max(as_of_date)` GLOBAL: com duas contas de reserva de datas
        # diferentes — conta corrente atualizada ontem, CDB de liquidez atualizado há dois
        # meses —, só a mais recente casava o filtro e a outra sumia do total. Reserva
        # subestimada acende VERMELHO em `fundacao.avaliar`, `critica` vira True e a D11
        # DESATIVA todos os scores: o cliente com reserva saudável recebe "Fundação
        # crítica" e o diagnóstico apagado, sem erro em lugar nenhum.
        #
        # `app/engine/projecao.py:_saldo_carimbado` já fazia certo, com `group by
        # account_id` — a assimetria entre os dois é que era o defeito. O `scope_id`
        # explícito é defesa em profundidade: esta função roda sob serviço, onde a RLS não
        # morde, e o filtro era só por `account_id`.
        cur = await conn.execute(
            "select coalesce(sum(b.balance_brl), 0)::float "
            "  from wealth.account_balances b "
            "  join (select account_id, max(as_of_date) as d from wealth.account_balances "
            "         where scope_id = %s and account_id = any(%s) group by account_id) u "
            "    on u.account_id = b.account_id and u.d = b.as_of_date "
            " where b.scope_id = %s",
            (scope_id, list(ajustes["reserve_account_ids"]), scope_id))
        linha = await cur.fetchone()
        b.reserva = linha[0] if linha else None

    return b


# =============================================================================
# Parte pura — sem banco, travável por teste
# =============================================================================
def derivar(b: Bruto) -> list[FatoDerivado]:
    """Do bruto para a lista de fatos. Insumo ausente não vira zero: vira ausência."""
    fatos: list[FatoDerivado] = []

    def por(fact_key: str, valor: float | None, origem: str) -> None:
        if valor is not None:
            fatos.append(FatoDerivado(fact_key, float(valor), origem))

    # ---------------------------------------------------------------- fluxo
    if b.income_summary:
        # `total_brl` é gerado; aqui reconstruo a partir do que o repo devolve.
        fixo = b.income_summary.get("fixed_brl") or 0.0
        variavel = b.income_summary.get("variable_brl") or 0.0
        por("renda.mensal_liquida", fixo + variavel if (fixo or variavel) else None,
            "budget.income_summaries")
    if b.income_summary:
        # `committable_brl` é fixo + piso p10 do variável, com CHECK no banco desde a 24:
        # "não se compromete o que só aparece nos bons meses". É este o número que julga
        # sustentabilidade — a média serve para dizer quanto se poupou, não quanto se aguenta.
        por("renda.comprometivel", b.income_summary.get("committable_brl"),
            "budget.income_summaries.committable_brl")
    if b.income_breakdown:
        por("renda.mensal_bruta", b.income_breakdown.get("monthly_gross_brl"),
            "budget.v_income_breakdown")
    if b.fontes_de_renda:
        por("renda.fontes_ativas", b.fontes_de_renda, "budget.income_sources")

    if b.meses_de_orcamento:
        por("despesa.total_mensal", b.custo_medio_mensal, "budget.monthly_summaries")
    por("despesa.essencial_mensal", b.essencial_mensal, "budget.monthly_summaries")
    por("despesa.fixa_contratada", b.fixo_contratado, "budget.recurring_items")

    # `fluxo.aporte_mensal` NÃO é derivado, de propósito. O superávit do orçamento é
    # CAPACIDADE ("quanto caberia"); o aporte é COMPORTAMENTO ("quanto de fato vai"). São
    # números diferentes, e é justamente por `fluxo.aporte_mensal` que
    # `destino.esforco_requerido` divide o aporte necessário — derivar capacidade ali faria
    # todo plano parecer mais fácil do que é, que é o oposto do que este produto existe para
    # fazer. Enquanto não houver série de aportes efetivos, ele é PERGUNTA:
    # "Quanto você consegue guardar por mês hoje?"

    # ---------------------------------------------------------------- proteção
    por("protecao.reserva_atual", b.reserva, "budget.reserve_settings + wealth.account_balances")
    if b.familia:
        por("protecao.dependentes_financeiros", b.familia.get("dependentes"), "household.v_summary")

    # ---------------------------------------------------------------- estoque
    if b.patrimonio:
        por("patrimonio.investido", b.patrimonio.get("investivel"), "estate.v_net_worth")
        por("patrimonio.imobilizado", b.patrimonio.get("nao_financeiro"), "estate.v_net_worth")
        por("patrimonio.liquido", b.patrimonio.get("liquido"), "estate.v_net_worth")

    if b.dividas:
        saldo = sum(d.get("outstanding_brl") or 0.0 for d in b.dividas)
        por("divida.saldo_total", saldo, "budget.debts")
        # Parcela só nasce se ALGUMA dívida informou a sua: somar zeros de dívidas sem
        # parcela declarada afirmaria "não paga nada por mês", que é outra coisa.
        com_parcela = [d for d in b.dividas if d.get("monthly_payment_brl") is not None]
        if com_parcela:
            por("divida.parcela_mensal",
                sum(d["monthly_payment_brl"] for d in com_parcela), "budget.debts")
        # custo MÉDIO PONDERADO pelo saldo: é o spread contra o retorno esperado que
        # decide quitar vs. investir, e média simples esconderia o rotativo pequeno e caro.
        com_taxa = [(d["outstanding_brl"], d["annual_rate"]) for d in b.dividas
                    if d.get("annual_rate") is not None and d.get("outstanding_brl")]
        base = sum(s for s, _ in com_taxa)
        if base:
            por("divida.custo_medio", sum(s * t for s, t in com_taxa) / base, "budget.debts")
    elif b.dividas is not None:
        # Consultado e não há dívida: zero é a melhor notícia possível — e é um FATO, não
        # ausência. Os TRÊS precisam nascer, não só o saldo: sem `custo_medio` e
        # `parcela_mensal`, a cobertura de Estoque cai para 40% e o cliente SEM DÍVIDA fica
        # sem score, enquanto o endividado ganha um. Foi assim que a persona
        # `patrimonio_alto_sem_fluxo` apareceu com "Estoque indisponível" tendo R$ 3,4 mi.
        por("divida.saldo_total", 0.0, "budget.debts (sem dívida ativa)")
        por("divida.custo_medio", 0.0, "budget.debts (sem dívida ativa)")
        por("divida.parcela_mensal", 0.0, "budget.debts (sem dívida ativa)")

    # ---------------------------------------------------------------- vida
    if b.nascimento is not None:
        # A data de nascimento estava em `identity.users` desde a 01 e nunca era derivada —
        # e sem ela `destino.horizonte_aposentadoria` não calcula, o que deixava a família
        # DESTINO indisponível para todo cliente. Apareceu ao ler as seis personas.
        fatos.append(FatoDerivado("vida.data_nascimento", None, "identity.users.birth_date",
                                  {"date": b.nascimento.isoformat()}))

    # ---------------------------------------------------------------- destino
    if b.objetivo:
        por("objetivo.valor_alvo", b.objetivo.get("valor"), "planning.goals")
        por("objetivo.prazo_meses", b.objetivo.get("prazo_meses"), "planning.goals")
        por("objetivo.prioridade", b.objetivo.get("prioridade"), "planning.goals")

    return fatos


# =============================================================================
# Escrita
# =============================================================================
@dataclass
class ResultadoDerivacao:
    gravados: list[str] = field(default_factory=list)
    pulados_confirmados: list[str] = field(default_factory=list)
    pulados_iguais: list[str] = field(default_factory=list)
    recusados: list[dict[str, str]] = field(default_factory=list)

    @property
    def resumo(self) -> str:
        return (f"{len(self.gravados)} gravado(s) · {len(self.pulados_confirmados)} já confirmado(s) "
                f"· {len(self.pulados_iguais)} sem mudança · {len(self.recusados)} recusado(s)")


async def derivar_escopo(conn: AsyncConnection, scope_id: str, user_id: str) -> ResultadoDerivacao:
    """Coleta, deriva e grava. Idempotente: rodar duas vezes seguidas não cria linha nova."""
    r = ResultadoDerivacao()

    cur = await conn.execute(
        "select payload from engine.policy_versions "
        "where code = %s and effective_to is null", (POLICY,))
    linha = await cur.fetchone()
    if linha is None:
        raise RuntimeError(f"política {POLICY} não está vigente — o fator de confiança não tem "
                           "default no código")
    fator = float(linha[0].get("fator_confianca_derivado", 0.0))
    if fator <= 0:
        raise RuntimeError(f"{POLICY}.fator_confianca_derivado ausente ou inválido")

    bruto = await coletar(conn, scope_id)
    fatos = derivar(bruto)
    if not fatos:
        return r

    chaves = [f.fact_key for f in fatos]

    # o que o cliente já confirmou não se deriva por cima (regra 1)
    cur = await conn.execute(
        "select fact_key from context.v_fact_current "
        "where scope_id = %s and fact_key = any(%s)", (scope_id, chaves))
    confirmados = {c[0] for c in await cur.fetchall()}

    # o que já foi derivado com o MESMO valor não se regrava (regra 2)
    cur = await conn.execute(
        "select fact_key, numero::float from context.v_fact_operavel "
        "where scope_id = %s and fact_key = any(%s) and source = %s",
        (scope_id, chaves, FONTE))
    linhas_ja = await cur.fetchall()
    ja_derivados = {c[0]: c[1] for c in linhas_ja}
    ja_presentes = {c[0] for c in linhas_ja}

    cur = await conn.execute(
        "select fact_key, subject_kind::text, attribute, unit, "
        "       coalesce(materiality_abs, 0)::float, coalesce(materiality_rel, 0)::float "
        "  from context.fact_definitions where fact_key = any(%s) and is_active", (chaves,))
    catalogo = {c[0]: c[1:] for c in await cur.fetchall()}

    for f in fatos:
        if f.fact_key in confirmados:
            r.pulados_confirmados.append(f.fact_key)
            continue
        definicao = catalogo.get(f.fact_key)
        if definicao is None:
            r.recusados.append({"fact_key": f.fact_key, "motivo": "fora do catálogo ativo"})
            continue
        subject_kind, attribute, unit, mat_abs, mat_rel = definicao

        anterior = ja_derivados.get(f.fact_key)
        if f.valor is not None and anterior is not None and not _mudou(anterior, f.valor,
                                                                      mat_abs, mat_rel):
            r.pulados_iguais.append(f.fact_key)
            continue
        if f.valor is None and f.fact_key in ja_presentes:
            r.pulados_iguais.append(f.fact_key)      # não numérico já derivado
            continue
        try:
            # SAVEPOINT por fato: o gate do catálogo (faixa de sanidade, tipo) recusa um
            # sem derrubar os outros — mesmo padrão do extrator.
            async with conn.transaction():
                await conn.execute(
                    """insert into context.assertions
                         (scope_id, user_id, fact_key, subject_kind, attribute, value, unit,
                          modality, status, confidence, source, source_ref)
                       values (%s, %s, %s, %s::context.subject_kind, %s, %s, %s,
                               'fato', 'inferido', %s, 'inferencia_motor', %s)""",
                    (scope_id, user_id, f.fact_key, subject_kind, attribute,
                     Jsonb(f.bruto if f.bruto is not None else {"amount": round(f.valor, 2)}),
                     unit, fator,
                     Jsonb({"derivado_de": f.origem})))
            r.gravados.append(f.fact_key)
        except Exception as e:                       # noqa: BLE001 — o motivo é o dado
            r.recusados.append({"fact_key": f.fact_key,
                                "motivo": str(e).strip().splitlines()[0]})

    log.info("derivação (scope=%s): %s", scope_id, r.resumo)
    return r
