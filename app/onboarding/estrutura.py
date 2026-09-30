"""Escrita estruturada compartilhada — objetivos, dívidas e bens.

Extraída de jornada.py na F21b para que o wizard (F21a) e a confirmação do intake (F21b)
escrevam pelo MESMO caminho — duas rotas para a mesma linha é o padrão de bug que a
migration 53 corrigiu na carteira. Taxa de dívida entra em % a.a. e vive como FRAÇÃO
(`core.rate_annual`); `prazo_meses → target_date` usa a constante de calendário de 30
dias/mês (como MESES_POR_ANO em derivacao.py), não aritmética de mês real.
"""
from __future__ import annotations

import datetime as dt

from psycopg import AsyncConnection

DIAS_POR_MES_CALENDARIO = 30

LIQUIDEZ_POR_TIPO_BEM = {
    "imovel_residencial": "acima_12m", "imovel_comercial": "acima_12m",
    "terreno": "acima_12m", "imovel_rural": "acima_12m",
    "veiculo": "ate_30d", "equipamento_profissional": "ate_30d",
    "direito_a_receber": "ate_12m",
    "cripto_autocustodia": "imediata",
    "participacao_empresa": "iliquido", "previdencia_fechada": "iliquido",
    "obra_arte_colecionavel": "iliquido", "outro": "iliquido",
}


def daqui_a_meses(base: dt.date, meses: int) -> dt.date:
    return base + dt.timedelta(days=meses * DIAS_POR_MES_CALENDARIO)


async def criar_divida(conn: AsyncConnection, *, scope_id: str, tipo: str, saldo: float,
                       taxa_aa_percentual: float, parcela: float,
                       parcelas_restantes: int | None = None) -> str:
    cur = await conn.execute(
        "insert into budget.debts "
        "  (scope_id, kind, outstanding_brl, annual_rate, monthly_payment_brl, "
        "   remaining_installments) "
        "values (%s, %s::budget.debt_kind, %s, %s, %s, %s) returning id::text",
        (scope_id, tipo, saldo, taxa_aa_percentual / 100, parcela, parcelas_restantes))
    return (await cur.fetchone())[0]


async def criar_bem(conn: AsyncConnection, *, scope_id: str, tipo: str, rotulo: str,
                    valor: float, residencia_principal: bool = False, onerado: bool = False,
                    divida_id: str | None = None) -> str:
    liquidez = LIQUIDEZ_POR_TIPO_BEM.get(tipo, "iliquido")
    cur = await conn.execute(
        "insert into estate.assets "
        "  (scope_id, kind, label, liquidity, is_encumbered, linked_debt_id, "
        "   is_primary_residence, origin) "
        "values (%s, %s::estate.asset_kind, %s, %s::estate.liquidity_tier, %s, %s, %s, "
        "        'onboarding') returning id::text",
        (scope_id, tipo, rotulo, liquidez, onerado, divida_id, residencia_principal))
    asset_id = (await cur.fetchone())[0]
    await conn.execute(
        "insert into estate.valuations (asset_id, scope_id, as_of_date, value_brl, method) "
        "values (%s, %s, current_date, %s, 'declarado')",
        (asset_id, scope_id, valor))
    return asset_id


async def criar_objetivo(conn: AsyncConnection, *, scope_id: str, user_id: str, nome: str,
                         tipo: str, valor: float, prazo_meses: int, prioridade: int) -> str:
    alvo = daqui_a_meses(dt.date.today(), prazo_meses)
    cur = await conn.execute(
        "insert into planning.goals "
        "  (scope_id, created_by, name, kind, target_amount_brl, target_date, priority) "
        "values (%s, %s, %s, %s, %s, %s, %s) returning id::text",
        (scope_id, user_id, nome, tipo, valor, alvo, prioridade))
    return (await cur.fetchone())[0]
