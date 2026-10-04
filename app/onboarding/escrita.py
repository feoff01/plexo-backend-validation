"""Escrita de fato de formulário — sempre sob app_session do próprio usuário.

O wizard não é uma conversa: o cliente está literalmente digitando o próprio dado, então
declaração e confirmação são o MESMO gesto (ao contrário do card do Copiloto, onde
confirmar é um segundo ato do usuário sobre uma proposta do extrator). Mesmo assim a
asserção nasce 'declarado' (C22a) e só then vira 'confirmado' — nunca pula a régua —, o
mesmo padrão de app/context/aplicador.py e app/seeds/personas.py.

`attribute`/`subject_kind`/`unit` vêm SEMPRE do catálogo (context.fact_definitions):
nunca hardcoded — é a armadilha registrada no app/README.md (`fluxo.aporte_mensal` tem
subject_kind='despesa', não 'renda'; `attribute` não é o sufixo do fact_key).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.onboarding.erros import DadoInvalido

FONTE = "formulario"
# Confiança de fato declarado diretamente pelo cliente no formulário — mesma constante
# usada por app/seeds/personas.py para o mesmo tipo de origem.
CONFIANCA_FORMULARIO = 0.95
# Fato extraído por IA do texto do onboarding e então confirmado pelo cliente (F21b):
# um degrau abaixo do digitado — a leitura é da máquina, o "sim" é do cliente.
CONFIANCA_ONBOARDING = 0.85


class FatoInvalido(DadoInvalido):
    """Fato fora do catálogo ativo ou fora da faixa de sanidade — 422 antes do banco."""


@dataclass(frozen=True)
class _Definicao:
    subject_kind: str
    attribute: str
    value_type: str
    unit: str | None
    min_value: float | None
    max_value: float | None


async def _definicao(conn: AsyncConnection, fact_key: str) -> _Definicao:
    cur = await conn.execute(
        "select subject_kind::text, attribute, value_type::text, unit, "
        "       min_value::float, max_value::float "
        "  from context.fact_definitions where fact_key = %s and is_active", (fact_key,))
    row = await cur.fetchone()
    if row is None:
        raise FatoInvalido(f"fato '{fact_key}' não existe no catálogo ativo")
    return _Definicao(*row)


def _bruto(d: _Definicao, fact_key: str, valor: Any) -> dict[str, Any]:
    if d.value_type in ("money_brl", "numero", "percentual", "meses", "anos"):
        numero = float(valor)
        if d.min_value is not None and numero < d.min_value:
            raise FatoInvalido(f"{fact_key}: {numero} está abaixo do mínimo ({d.min_value})")
        if d.max_value is not None and numero > d.max_value:
            raise FatoInvalido(f"{fact_key}: {numero} está acima do máximo ({d.max_value})")
        return {"amount": numero}
    if d.value_type == "booleano":
        return {"bool": bool(valor)}
    if d.value_type == "texto":
        return {"text": str(valor)}
    if d.value_type == "data":
        bruto = valor.isoformat() if isinstance(valor, (dt.date, dt.datetime)) else str(valor)
        return {"date": bruto}
    raise FatoInvalido(f"{fact_key}: tipo '{d.value_type}' sem escrita conhecida")  # pragma: no cover


async def validar_fato(conn: AsyncConnection, fact_key: str, valor: Any) -> None:
    """Valida chave/tipo/faixa contra o catálogo SEM gravar — levanta FatoInvalido.
    Usada pela extração do intake (F21b) para descartar item inválido com motivo."""
    d = await _definicao(conn, fact_key)
    _bruto(d, fact_key, valor)


async def confirmar_fato(conn: AsyncConnection, *, scope_id: str, user_id: str,
                         fact_key: str, valor: Any, source: str = FONTE,
                         confianca: float = CONFIANCA_FORMULARIO) -> str:
    """Grava o fato DECLARADO e confirma no mesmo ato. Devolve o id da asserção.

    `source` default 'formulario' (wizard); o intake confirma com 'onboarding' (F21b) —
    mais fraco na precedência DECLARADA, de propósito. SAVEPOINT por fato (mesmo padrão
    de app/context/derivacao.py): se o catálogo recusar (faixa, tipo), só este fato
    falha — quem chama decide se o resto segue ou não.
    """
    d = await _definicao(conn, fact_key)
    bruto = _bruto(d, fact_key, valor)
    async with conn.transaction():
        cur = await conn.execute(
            "insert into context.assertions "
            "  (scope_id, user_id, fact_key, subject_kind, attribute, value, unit, "
            "   modality, source, confidence) "
            "values (%s, %s, %s, %s::context.subject_kind, %s, %s, %s, "
            "        'fato', %s, %s) returning id::text",
            (scope_id, user_id, fact_key, d.subject_kind, d.attribute, Jsonb(bruto), d.unit,
             source, confianca))
        assertion_id = (await cur.fetchone())[0]
        await conn.execute(
            "update context.assertions set status = 'confirmado', confirmed_at = now(), "
            "confirmed_by = %s where id = %s", (user_id, assertion_id))
    return assertion_id
