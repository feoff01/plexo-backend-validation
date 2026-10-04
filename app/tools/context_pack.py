"""Leituras do contexto do escopo que as tools consomem — sempre pela conexão da SESSÃO (RLS).

Cada função devolve dados prontos para entrar em `resolved_params` (tipos primitivos).
A janela de 12 meses é unidade de calendário (meses/ano), não premissa de negócio.
"""
from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

MESES_JANELA = 12


async def media_custo_mensal(conn: AsyncConnection, scope_id: str) -> tuple[float | None, int]:
    """Média de expense_brl dos últimos meses fechados (budget.monthly_summaries)."""
    cur = await conn.execute(
        "select avg(expense_brl)::float, count(*)::int from ("
        "  select expense_brl from budget.monthly_summaries"
        "  where scope_id = %s order by month desc limit %s) m",
        (scope_id, MESES_JANELA))
    media, n = await cur.fetchone()
    return (media, n) if n else (None, 0)


async def despesas_mensais(conn: AsyncConnection, scope_id: str) -> tuple[float | None, float | None, int]:
    """Média de despesa TOTAL e ESSENCIAL dos últimos meses fechados.

    Existe porque `capacidade de aporte` respondia com a renda comprometível — R$ 26.000 para
    uma cliente que gasta R$ 16.800 por mês. O número estava certo como "renda com que dá para
    contar" e completamente errado como "quanto dá para investir", que é o que a pergunta quer
    dizer. Sem despesa não existe sobra, e sobra é a resposta.
    """
    cur = await conn.execute(
        "select avg(expense_brl)::float, avg(essential_expense_brl)::float, count(*)::int from ("
        "  select expense_brl, essential_expense_brl from budget.monthly_summaries"
        "  where scope_id = %s order by month desc limit %s) m",
        (scope_id, MESES_JANELA))
    total, essencial, n = await cur.fetchone()
    return (total, essencial, n) if n else (None, None, 0)


async def sobra_mensal(conn: AsyncConnection, scope_id: str,
                       committable: float) -> dict[str, Any]:
    """A FAIXA de aporte: o que sobra hoje, e o teto se o não essencial for cortado.

    Duas respostas para a mesma pergunta, e as duas verdadeiras. A primeira é o que dá para
    comprometer sem mudar de vida; a segunda é o quanto a vida atual custa em objetivo adiado.
    Dar só a primeira esconde a alavanca; dar só a segunda é otimismo.
    """
    total, essencial, meses = await despesas_mensais(conn, scope_id)
    if total is None:
        return {"sobra_brl": None, "teto_brl": None, "despesa_total_brl": None,
                "despesa_essencial_brl": None, "meses_observados": 0}
    return {"sobra_brl": round(max(committable - total, 0.0), 2),
            "teto_brl": round(max(committable - (essencial if essencial is not None else total), 0.0), 2),
            "despesa_total_brl": round(total, 2),
            "despesa_essencial_brl": round(essencial, 2) if essencial is not None else None,
            "meses_observados": meses}


async def reserve_settings(conn: AsyncConnection, scope_id: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select target_months::float, monthly_cost_override_brl::float, reserve_account_ids "
        "from budget.reserve_settings where scope_id = %s", (scope_id,))
    row = await cur.fetchone()
    if row is None:
        return None
    return {"target_months": row[0], "monthly_cost_override_brl": row[1], "reserve_account_ids": row[2]}


async def ultimo_income_summary(conn: AsyncConnection, scope_id: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select fixed_brl::float, variable_brl::float, variable_p10_brl::float, committable_brl::float, "
        "       months_observed::int, variable_share::float "
        "from budget.income_summaries where scope_id = %s order by month desc limit 1", (scope_id,))
    row = await cur.fetchone()
    if row is None:
        return None
    chaves = ("fixed_brl", "variable_brl", "variable_p10_brl", "committable_brl", "months_observed", "variable_share")
    return dict(zip(chaves, row))


async def income_breakdown(conn: AsyncConnection, scope_id: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select monthly_gross_brl::float, fixed_brl::float, variable_brl::float, variable_share::float "
        "from budget.v_income_breakdown where scope_id = %s", (scope_id,))
    row = await cur.fetchone()
    if row is None:
        return None
    return dict(zip(("monthly_gross_brl", "fixed_brl", "variable_brl", "variable_share"), row))


async def savings_rate_recente(conn: AsyncConnection, scope_id: str) -> float | None:
    cur = await conn.execute(
        "select savings_rate::float from budget.monthly_summaries "
        "where scope_id = %s and savings_rate is not null order by month desc limit 1", (scope_id,))
    row = await cur.fetchone()
    return row[0] if row else None


async def pacote_do_escopo(conn: AsyncConnection, scope_id: str) -> str:
    """Contexto do escopo para o prompt do agente — MINIMIZADO (LGPD): números e slugs,
    nunca nome/e-mail/documento. Entra no prompt como DADO delimitado, não instrução."""
    linhas: list[str] = []

    async def secao(titulo: str, corpo: list[str]) -> None:
        if corpo:
            linhas.append(f"### {titulo}")
            linhas.extend(corpo)

    try:
        resumo = await ultimo_income_summary(conn, scope_id)
        if resumo:
            await secao("Renda mensal (resumo)", [
                f"- fixa: R$ {resumo['fixed_brl']:.2f} · variável (média): R$ {resumo['variable_brl']:.2f} "
                f"· piso variável (p10): R$ {resumo['variable_p10_brl']:.2f}",
                f"- comprometível sem depender de mês bom: R$ {resumo['committable_brl']:.2f} "
                f"({resumo['months_observed']} meses observados)"])
    except Exception:  # pragma: no cover — view/dado ausente não derruba o turno
        pass
    try:
        # F15: o que falta saber, ordenado por quanto cada fato DESTRAVA de diagnóstico. Sem
        # isto o agente pergunta o que lhe vem à cabeça; com isto ele pergunta o que muda o
        # diagnóstico — que é a diferença entre onboarding e formulário.
        from app.agents.perguntas import proximas
        faltando = await proximas(conn, scope_id)
        if faltando:
            await secao("Dados que faltam para o diagnóstico", [
                "- pergunte no máximo UM por resposta, o primeiro da lista, e só quando couber na conversa:",
                *[f"  · {p.pergunta}" + (f" (destrava {p.destrava} indicador(es))" if p.destrava else "")
                  for p in faltando]])
    except Exception:  # pragma: no cover — perfil sem cobertura calculada não derruba o turno
        pass
    try:
        # F8: sem isto o Assessor perguntava o custo de vida em vez de medir a reserva (a tool resolve pelo escopo)
        media, n = await media_custo_mensal(conn, scope_id)
        if n:
            await secao("Orçamento (meses fechados)", [
                f"- custo de vida médio: R$ {media:.2f} ({n} meses observados) — a ferramenta de reserva usa isto "
                "quando o cliente não informa outro valor"])
    except Exception:
        pass
    try:
        cur = await conn.execute(
            "select investivel_brl::float, patrimonio_liquido_brl::float from estate.v_net_worth "
            "where scope_id = %s", (scope_id,))
        row = await cur.fetchone()
        if row:
            await secao("Patrimônio", [f"- líquido: R$ {row[1]:.2f} · investível: R$ {row[0]:.2f}"])
    except Exception:
        pass
    try:
        cur = await conn.execute(
            "select kind::text, coalesce(asset_class_code, sector_code, country_code, ''), threshold::float "
            "from preferences.v_active_constraints where scope_id = %s limit 20", (scope_id,))
        vetos = [f"- {r[0]} {r[1]}" + (f" (limite {r[2]})" if r[2] is not None else "") for r in await cur.fetchall()]
        await secao("Restrições do cliente (invioláveis)", vetos)
    except Exception:
        pass
    try:
        cur = await conn.execute(
            "select attribute, value from context.v_current_facts where scope_id = %s "
            "order by observed_at desc limit 15", (scope_id,))
        fatos = [f"- {r[0]}: {r[1]}" for r in await cur.fetchall()]
        await secao("Fatos confirmados pelo cliente", fatos)
    except Exception:
        pass
    if not linhas:
        return "(sem dados registrados para este escopo — pergunte antes de assumir)"
    return "\n".join(linhas)


async def nivel_conhecimento(conn: AsyncConnection, scope_id: str) -> str | None:
    """Nível de conhecimento CONFIRMADO pelo cliente (asserção `nivel_conhecimento`, value {"text": ...}),
    lido pela sessão (RLS). None quando não há fato confirmado — a tool cai para a policy."""
    cur = await conn.execute(
        "select value->>'text' from context.v_current_facts "
        "where scope_id = %s and attribute = 'nivel_conhecimento' order by observed_at desc limit 1",
        (scope_id,))
    row = await cur.fetchone()
    return row[0] if row else None


async def dividas_ativas(conn: AsyncConnection, scope_id: str) -> list[dict[str, Any]]:
    cur = await conn.execute(
        "select coalesce(description, kind::text), outstanding_brl::float, annual_rate::float, "
        "       monthly_payment_brl::float, is_expensive "
        "from budget.debts where scope_id = %s and settled_at is null order by outstanding_brl desc",
        (scope_id,))
    chaves = ("descricao", "outstanding_brl", "annual_rate", "monthly_payment_brl", "is_expensive")
    return [dict(zip(chaves, r)) for r in await cur.fetchall()]


async def cobertura_mercado(conn: AsyncConnection) -> str:
    """Cobertura de mercado para o prompt do Analista — TAMANHO e FAIXA, nunca a lista.

    Este texto entra no prompt do sistema a CADA chamada ao modelo, duas por turno. Até a F22 ele
    era uma linha por instrumento do universo: irrelevante com os 5 ativos do dev, ~7.500 tokens
    com os 4.100 papéis do acervo — em toda chamada, para sempre — e, pior, calculado por um
    `count(*)` agrupado sobre `market.prices` INTEIRA a cada turno, num nó de 1 GB de RAM.

    Agora custa ~120 tokens e duas consultas baratas: contagem em `market.instruments` (milhares de
    linhas) e `min/max` em `market.prices`, que usa o índice da PK — `price_date` é a coluna líder,
    então é uma leitura por partição, não uma varredura. Saber se um papel ESPECÍFICO está coberto
    virou trabalho de `dados.resolver_instrumento`, que já existe, é barato e não ocupa prompt.

    Entra no prompt como DADO delimitado: o agente diz de cara o que consegue medir, em vez de
    tentar e cair em `sem_dados`.
    """
    rotulo = {"acao": "ações", "fii": "FIIs", "bdr": "BDRs", "etf": "ETFs",
              "fundo": "fundos listados", "tesouro": "títulos públicos"}
    linhas: list[str] = []
    try:
        cur = await conn.execute(
            "select kind::text, count(*) from market.instruments "
            "where is_in_universe group by 1 order by 2 desc")
        por_kind = await cur.fetchall()
        total = sum(n for _, n in por_kind)
        if total:
            detalhe = ", ".join(f"{n} {rotulo.get(k, k)}" for k, n in por_kind)
            cur = await conn.execute("select min(price_date), max(price_date) from market.prices")
            ini, fim = await cur.fetchone()
            faixa = f"; fechamentos de {ini} a {fim}" if ini else "; ainda sem fechamento ingerido"
            linhas += [
                "### Cobertura de mercado (B3, fechamento oficial D-1)",
                f"- {total} ativos na cobertura: {detalhe}{faixa}.",
                "- Para saber se um papel específico está coberto, chame "
                "`dados.resolver_instrumento`. A lista não está aqui, e ausência nesta seção NÃO "
                "significa fora da cobertura.",
            ]
        cur = await conn.execute(
            "select index_code, min(value_date), max(value_date), count(*) "
            "from market.index_values group by 1 order by 1")
        indices = [f"{c} ({ini} a {fim}, {q} pontos)" for c, ini, fim, q in await cur.fetchall()]
        if indices:
            linhas.append("- Índices e taxas: " + "; ".join(indices) + ".")
    except Exception:  # pragma: no cover — sem tabelas de mercado o turno segue
        pass
    if not linhas:
        return "(nenhum ativo ou índice ingerido — diga que não há base de dados para medir)"
    return "\n".join(linhas)
