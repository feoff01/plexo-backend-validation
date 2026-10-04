"""Leitura do catálogo de fatos (migration 38) e as regras que dependem dele.

Este módulo é a metade Python do que o banco já garante em SQL. A duplicação é deliberada e
tem uma direção só: o banco é o executor (C38a–C38h), e aqui a gente **antecipa** a recusa
para que o agente possa explicar em vez de estourar. Nada aqui afrouxa nada — o que passa
por este módulo ainda passa pelos gates da 38/39 ao ser gravado.

O que mora aqui:
  · leitura do catálogo e do fato vigente (`context.v_fact_current`);
  · o teste de materialidade, com o mesmo limiar do banco (o MAIOR entre absoluto e relativo);
  · a classificação de natureza que o card precisa fazer ("passou a valer" × "foi de uma vez").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

# Chaves aceitas dentro de `context.assertions.value` para o número — espelha
# context.fact_number() da 38. Mudar aqui sem mudar lá quebra a simetria.
CHAVES_NUMERICAS = ("amount", "valor")
TIPOS_NUMERICOS = frozenset({"money_brl", "numero", "percentual", "meses", "anos"})


def numero_do_valor(value: dict[str, Any] | None) -> float | None:
    """Número dentro do jsonb de um fato. Espelha context.fact_number() da migration 38."""
    if not isinstance(value, dict):
        return None
    for chave in CHAVES_NUMERICAS:
        bruto = value.get(chave)
        if isinstance(bruto, bool):        # bool é int em Python; aqui seria erro de leitura
            continue
        if isinstance(bruto, (int, float)):
            return float(bruto)
    return None


@dataclass(frozen=True)
class DefinicaoFato:
    """Uma linha de context.fact_definitions, já tipada."""
    fact_key: str
    subject_kind: str
    attribute: str
    family: str
    display_name: str
    value_type: str
    unit: str | None
    source_precedence: list[str]
    allows_conversation_update: bool
    half_life_days: int | None
    materiality_abs: float | None
    materiality_rel: float | None
    min_value: float | None
    max_value: float | None
    is_recurring_by_nature: bool
    requires_nature_check: bool

    @property
    def e_numerico(self) -> bool:
        return self.value_type in TIPOS_NUMERICOS

    @property
    def fonte_que_manda(self) -> str:
        return self.source_precedence[0]

    def limiar_de_materialidade(self, valor_atual: float) -> float:
        """O MAIOR entre o absoluto e o relativo — mesma conta de C38d.

        "±5% ou ±R$ 500, o que for maior" é o que impede tanto o spam em valores pequenos
        quanto a cegueira em valores grandes.
        """
        return max((self.materiality_abs or 0.0),
                   (self.materiality_rel or 0.0) * abs(valor_atual))

    def dentro_da_faixa(self, valor: float) -> bool:
        if self.min_value is not None and valor < self.min_value:
            return False
        return not (self.max_value is not None and valor > self.max_value)


_COLUNAS = ("fact_key, subject_kind::text, attribute, family::text, display_name, "
            "value_type::text, unit, source_precedence::text[], allows_conversation_update, "
            "half_life_days, materiality_abs::float, materiality_rel::float, "
            "min_value::float, max_value::float, is_recurring_by_nature, requires_nature_check")


def _para_definicao(row: tuple) -> DefinicaoFato:
    return DefinicaoFato(*row)


async def definicao(conn: AsyncConnection, fact_key: str) -> DefinicaoFato | None:
    cur = await conn.execute(
        f"select {_COLUNAS} from context.fact_definitions where fact_key = %s and is_active",
        (fact_key,))
    row = await cur.fetchone()
    return _para_definicao(row) if row else None


async def catalogo(conn: AsyncConnection, *, family: str | None = None) -> list[DefinicaoFato]:
    cur = await conn.execute(
        f"select {_COLUNAS} from context.fact_definitions "
        "where is_active and (%s::text is null or family::text = %s) order by family, fact_key",
        (family, family))
    return [_para_definicao(r) for r in await cur.fetchall()]


async def resolver_por_atributo(conn: AsyncConnection, atributo: str) -> DefinicaoFato | None:
    """Aceita tanto `fact_key` quanto o `attribute` — o modelo escreve um dos dois."""
    cur = await conn.execute(
        f"select {_COLUNAS} from context.fact_definitions "
        "where is_active and (fact_key = %s or attribute = %s) order by (fact_key = %s) desc limit 1",
        (atributo, atributo, atributo))
    row = await cur.fetchone()
    return _para_definicao(row) if row else None


async def fato_vigente(conn: AsyncConnection, scope_id: str, fact_key: str) -> dict[str, Any] | None:
    """O fato que vale hoje: um por chave, resolvido por precedência e depois por recência."""
    cur = await conn.execute(
        "select value, numero::float, source::text, observed_at, valid_until, confidence::float, "
        "       vence_em_breve "
        "from context.v_fact_current where scope_id = %s and fact_key = %s",
        (scope_id, fact_key))
    row = await cur.fetchone()
    if row is None:
        return None
    chaves = ("value", "numero", "source", "observed_at", "valid_until", "confidence", "vence_em_breve")
    return dict(zip(chaves, row))


async def cobertura(conn: AsyncConnection, scope_id: str) -> dict[str, Any]:
    """Quanto do catálogo já se sabe sobre este escopo — e o que falta."""
    cur = await conn.execute(
        # `faltando` é core.slug[] (array de DOMÍNIO): sem o cast, o psycopg não conhece o OID
        # e devolve a representação textual '{a,b}', que `list()` quebraria em caracteres.
        "select fatos_no_catalogo, fatos_presentes, cobertura::float, vencendo, faltando::text[] "
        "from context.v_fact_coverage where scope_id = %s", (scope_id,))
    row = await cur.fetchone()
    if row is None:
        return {"fatos_no_catalogo": 0, "fatos_presentes": 0, "cobertura": 0.0,
                "vencendo": 0, "faltando": []}
    chaves = ("fatos_no_catalogo", "fatos_presentes", "cobertura", "vencendo", "faltando")
    d = dict(zip(chaves, row))
    d["faltando"] = list(d["faltando"] or [])
    return d


# ---------------------------------------------------------------------------- comparação
@dataclass(frozen=True)
class Comparacao:
    """O que a tool `contexto.verificar_mudanca` devolve ao modelo."""
    fact_key: str
    display_name: str
    unit: str | None
    valor_atual: float | None
    valor_novo: float
    delta: float | None
    delta_relativo: float | None
    limiar: float | None
    e_material: bool
    e_fato_novo: bool
    dentro_da_faixa: bool
    exige_natureza: bool
    aceita_atualizacao_por_conversa: bool
    fonte_que_manda: str
    fonte_atual: str | None
    motivo: str

    def para_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        return d


def comparar(d: DefinicaoFato, valor_novo: float, atual: dict[str, Any] | None) -> Comparacao:
    """Compara o número que o cliente acabou de dizer com o que está no contexto.

    Não grava nada e não decide nada sozinha: devolve o veredito e o MOTIVO, que é o que
    o agente lê para explicar. Toda recusa possível é dita em português.
    """
    valor_atual = atual.get("numero") if atual else None
    fonte_atual = atual.get("source") if atual else None
    dentro = d.dentro_da_faixa(valor_novo)

    if not dentro:
        return Comparacao(
            fact_key=d.fact_key, display_name=d.display_name, unit=d.unit,
            valor_atual=valor_atual, valor_novo=valor_novo, delta=None, delta_relativo=None,
            limiar=None, e_material=False, e_fato_novo=valor_atual is None, dentro_da_faixa=False,
            exige_natureza=d.requires_nature_check,
            aceita_atualizacao_por_conversa=d.allows_conversation_update,
            fonte_que_manda=d.fonte_que_manda, fonte_atual=fonte_atual,
            motivo=f"valor fora da faixa esperada para {d.display_name.lower()}")

    if not d.allows_conversation_update:
        return Comparacao(
            fact_key=d.fact_key, display_name=d.display_name, unit=d.unit,
            valor_atual=valor_atual, valor_novo=valor_novo, delta=None, delta_relativo=None,
            limiar=None, e_material=False, e_fato_novo=valor_atual is None, dentro_da_faixa=True,
            exige_natureza=d.requires_nature_check, aceita_atualizacao_por_conversa=False,
            fonte_que_manda=d.fonte_que_manda, fonte_atual=fonte_atual,
            motivo=(f"{d.display_name.lower()} é atualizado por {d.fonte_que_manda} e não por "
                    "conversa; a divergência fica registrada como pergunta em aberto"))

    if valor_atual is None:
        return Comparacao(
            fact_key=d.fact_key, display_name=d.display_name, unit=d.unit,
            valor_atual=None, valor_novo=valor_novo, delta=None, delta_relativo=None,
            limiar=None, e_material=True, e_fato_novo=True, dentro_da_faixa=True,
            exige_natureza=d.requires_nature_check, aceita_atualizacao_por_conversa=True,
            fonte_que_manda=d.fonte_que_manda, fonte_atual=None,
            motivo=f"{d.display_name.lower()} ainda não constava no contexto")

    delta = abs(valor_novo - valor_atual)
    limiar = d.limiar_de_materialidade(valor_atual)
    relativo = (delta / abs(valor_atual)) if valor_atual else None
    material = limiar <= 0 or delta >= limiar

    motivo = (f"variação de {delta:.2f} em {d.display_name.lower()}"
              if material else
              f"variação de {delta:.2f} está abaixo do limiar de {limiar:.2f} — não é mudança material")
    return Comparacao(
        fact_key=d.fact_key, display_name=d.display_name, unit=d.unit,
        valor_atual=valor_atual, valor_novo=valor_novo, delta=delta, delta_relativo=relativo,
        limiar=limiar, e_material=material, e_fato_novo=False, dentro_da_faixa=True,
        exige_natureza=d.requires_nature_check, aceita_atualizacao_por_conversa=True,
        fonte_que_manda=d.fonte_que_manda, fonte_atual=fonte_atual, motivo=motivo)
