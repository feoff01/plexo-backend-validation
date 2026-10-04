"""O semáforo da Fundação — reserva e dívida cara, antes de qualquer pontuação.

POR QUE ESTE ARQUIVO EXISTIA COMO BURACO
    `diagnostics.foundation_status` está no banco desde a migration 06. A regra D11 é
    imposta por CHECK em `portfolio_scores`, por trigger em `client_scores` (C40a) e por
    teste de sabotagem em três arquivos SQL. E **nada nunca escreveu uma linha nessa tabela**:
    o único código que a mencionava era `app/engine/perfil.py`, para lê-la.

    O efeito prático: a regra mais importante do produto — "reserva e dívida cara vêm antes
    de qualquer pontuação" — nunca disparava. Um cliente com meio mês de reserva e rotativo
    a 400% ao ano recebia score como se a Fundação estivesse em ordem, porque a Fundação
    simplesmente não era lida. Um gate sem quem o alimente não é gate: é intenção.

    Foi a persona `endividado_rotativo` da F16 que expôs isso, na primeira leitura — ela
    existe exatamente para forçar "Fundação crítica ⇒ todos os scores desativados", e o que
    apareceu na tela foi "Fundação: sem leitura".

O QUE É CRÍTICO, E POR QUE ESTA DEFINIÇÃO
    Reserva abaixo do MÍNIMO da política, **ou** dívida cara em aberto. Não é a média das
    duas nem um score: é disjunção, porque qualquer uma das duas sozinha já torna qualquer
    outro diagnóstico secundário. Quem tem rotativo a 400% não tem um problema de alocação.

    "Dívida cara" é a definição que a 06 já fixou: taxa acima do CDI mais o spread da
    política. Sem CDI ingerido, o motor usa o spread como piso absoluto e diz que fez isso —
    nunca conclui "não há dívida cara" por não saber o CDI.

Config-first: `reserva_meses_min`, `reserva_meses_alvo` e `divida_cara_spread_sobre_cdi` vêm
de `FOUNDATION_THRESHOLDS`. Zero número de negócio neste arquivo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from psycopg import AsyncConnection

log = logging.getLogger(__name__)

POLICY = "FOUNDATION_THRESHOLDS"
CDI_CODE = "cdi"     # `core.slug` é minúsculo por CHECK


@dataclass(frozen=True)
class Fundacao:
    reserva_brl: float | None
    custo_mensal_brl: float | None
    reserva_meses: float | None
    reserva_alvo_meses: float
    reserva_minimo_meses: float
    reserva_luz: str
    divida_cara_brl: float
    divida_cara_taxa_max: float | None
    divida_luz: str
    luz_geral: str
    critica: bool
    superavit_brl: float | None
    avisos: list[str]


def taxa_anual_em_fracao(valor: float | None, unidade: str | None) -> float | None:
    """Converte o valor de um índice para FRAÇÃO ao ano, ou devolve None se não der.

    `market.index_values` guarda taxa em PERCENTUAL (`selic_meta` = 14.0 significa 14% a.a.);
    `budget.debts.annual_rate` é o domain `core.rate_annual`, em FRAÇÃO (0.145 = 14,5% a.a.).
    Comparar os dois direto — que foi o primeiro jeito que este arquivo fez — lia um rotativo
    a 400% ao ano (annual_rate 4.0) como mais barato que o CDI (14.0), e a Fundação nunca
    ficava crítica por dívida com o CDI ingerido. Um gate meio morto é pior que um ausente,
    porque parece funcionar.

    Só `taxa_aa` é conversível: `pontos` é índice, `taxa_am` é mensal e converter mês→ano aqui
    embutiria uma premissa de capitalização que não é deste arquivo.
    """
    if valor is None or unidade != "taxa_aa":
        return None
    return float(valor) / 100.0


def _luz(meses: float | None, minimo: float, alvo: float) -> str:
    """Sem leitura é VERMELHO, não verde.

    A ausência de dado sobre a reserva não pode ser lida como reserva suficiente — é o mesmo
    princípio da lacuna de seguro, e aqui o custo de errar para o lado otimista é maior.
    """
    if meses is None:
        return "vermelho"
    if meses >= alvo:
        return "verde"
    return "amarelo" if meses >= minimo else "vermelho"


async def avaliar(conn: AsyncConnection, scope_id: str, *, as_of: date | None = None) -> Fundacao:
    """Lê fatos e dívidas do escopo e devolve o semáforo. Não grava nada."""
    as_of = as_of or date.today()
    avisos: list[str] = []

    cur = await conn.execute(
        "select payload from engine.policy_versions where code = %s and effective_to is null",
        (POLICY,))
    linha = await cur.fetchone()
    if linha is None:
        raise RuntimeError(f"política {POLICY} não está vigente — o mínimo de reserva não "
                           "tem default no código")
    pol = linha[0]
    minimo = float(pol["reserva_meses_min"])
    alvo = float(pol["reserva_meses_alvo"])
    spread = float(pol["divida_cara_spread_sobre_cdi"])

    # --- reserva e custo: da janela OPERÁVEL, como todo o resto do motor
    cur = await conn.execute(
        "select fact_key, numero::float from context.v_fact_operavel "
        "where scope_id = %s and fact_key = any(%s)",
        (scope_id, ["protecao.reserva_atual", "despesa.essencial_mensal",
                    "renda.mensal_liquida", "despesa.total_mensal"]))
    fatos = dict(await cur.fetchall())
    reserva = fatos.get("protecao.reserva_atual")
    custo = fatos.get("despesa.essencial_mensal")
    renda = fatos.get("renda.mensal_liquida")
    despesa_total = fatos.get("despesa.total_mensal")

    if reserva is None:
        avisos.append("saldo de reserva não informado")
    if custo is None:
        avisos.append("despesa essencial não informada")

    meses = (reserva / custo) if (reserva is not None and custo) else None
    reserva_luz = _luz(meses, minimo, alvo)

    # --- dívida cara: taxa acima de CDI + spread
    cur = await conn.execute(
        "select v.value::float, d.unit from market.index_values v "
        "join market.index_definitions d on d.code = v.index_code "
        "where v.index_code = %s order by v.value_date desc limit 1", (CDI_CODE,))
    linha = await cur.fetchone()
    cdi = taxa_anual_em_fracao(linha[0], linha[1]) if linha else None
    if cdi is not None:
        limite = cdi + spread
    else:
        # Sem CDI ingerido, o piso é o próprio spread. Nunca se conclui "não há dívida cara"
        # por ignorância do CDI — declara-se a limitação e usa-se o piso conservador.
        limite = spread
        avisos.append(f"CDI indisponível em taxa anual: dívida cara avaliada contra o "
                      f"piso de {spread:.1%} a.a.")

    cur = await conn.execute(
        "select coalesce(sum(outstanding_brl) filter (where annual_rate > %s), 0)::float, "
        "       max(annual_rate) filter (where annual_rate > %s)::float, "
        # Dívida ABERTA cuja taxa ninguém capturou. `annual_rate` é nullable (08_budget:100)
        # enquanto `outstanding_brl` é NOT NULL, então o filtro `annual_rate > limite`
        # descartava essas linhas em silêncio: `NULL > 0.06` é NULL, a soma dava zero e a luz
        # saía VERDE. Um cliente com rotativo aberto e taxa não importada recebia Fundação em
        # ordem — e nenhum aviso, ao contrário do ramo do CDI logo acima, que declara a
        # limitação e usa um piso conservador. Achado no /code-review de 2026-08-30.
        "       coalesce(sum(outstanding_brl) filter (where annual_rate is null), 0)::float, "
        "       count(*) filter (where annual_rate is null) "
        "from budget.debts where scope_id = %s and settled_at is null",
        (limite, limite, scope_id))
    divida_cara, taxa_max, divida_sem_taxa, n_sem_taxa = await cur.fetchone()

    if divida_cara:
        divida_luz = "vermelho"
    elif n_sem_taxa:
        # Não é verde (não se sabe que é barata) nem vermelho (não se sabe que é cara). É a
        # mesma disciplina do resto do arquivo: "sem leitura de reserva é VERMELHO, não
        # verde" — aqui, sem leitura de TAXA, é amarelo, e a ignorância vai declarada.
        divida_luz = "amarelo"
        avisos.append(f"{n_sem_taxa} dívida(s) aberta(s) somando R$ {divida_sem_taxa:,.2f} "
                      f"sem taxa registrada: não dá para dizer se são caras")
    else:
        divida_luz = "verde"

    critica = reserva_luz == "vermelho" or divida_luz == "vermelho"
    luz_geral = ("vermelho" if critica
                 else "amarelo" if reserva_luz == "amarelo" or divida_luz == "amarelo"
                 else "verde")

    superavit = (renda - despesa_total) if (renda is not None and despesa_total is not None) else None

    return Fundacao(
        reserva_brl=reserva, custo_mensal_brl=custo, reserva_meses=meses,
        reserva_alvo_meses=alvo, reserva_minimo_meses=minimo, reserva_luz=reserva_luz,
        divida_cara_brl=divida_cara or 0.0, divida_cara_taxa_max=taxa_max,
        divida_luz=divida_luz, luz_geral=luz_geral, critica=critica,
        superavit_brl=superavit, avisos=avisos)


async def gravar(conn: AsyncConnection, scope_id: str, f: Fundacao, *,
                 run_id: str, as_of: date) -> None:
    """Grava o semáforo do dia. Idempotente por (scope, data)."""
    await conn.execute(
        """insert into diagnostics.foundation_status
             (scope_id, as_of_date, run_id, monthly_cost_brl, reserve_amount_brl,
              reserve_months, reserve_target_months, reserve_light, expensive_debt_brl,
              expensive_debt_max_rate, debt_light, investable_surplus_brl, overall_light,
              is_critical)
           values (%s, %s, %s, %s, %s, %s, %s, %s::diagnostics.foundation_light, %s, %s,
                   %s::diagnostics.foundation_light, %s, %s::diagnostics.foundation_light, %s)
           on conflict (scope_id, as_of_date) do update
             set run_id = excluded.run_id, monthly_cost_brl = excluded.monthly_cost_brl,
                 reserve_amount_brl = excluded.reserve_amount_brl,
                 reserve_months = excluded.reserve_months,
                 reserve_light = excluded.reserve_light,
                 expensive_debt_brl = excluded.expensive_debt_brl,
                 expensive_debt_max_rate = excluded.expensive_debt_max_rate,
                 debt_light = excluded.debt_light,
                 investable_surplus_brl = excluded.investable_surplus_brl,
                 overall_light = excluded.overall_light,
                 is_critical = excluded.is_critical, computed_at = now()""",
        (scope_id, as_of, run_id, f.custo_mensal_brl, f.reserva_brl,
         round(f.reserva_meses, 2) if f.reserva_meses is not None else None,
         f.reserva_alvo_meses, f.reserva_luz, f.divida_cara_brl, f.divida_cara_taxa_max,
         f.divida_luz, f.superavit_brl, f.luz_geral, f.critica))
    log.info("fundação (scope=%s): %s · reserva %s meses · dívida cara R$ %.2f",
             scope_id, f.luz_geral, f.reserva_meses, f.divida_cara_brl)
