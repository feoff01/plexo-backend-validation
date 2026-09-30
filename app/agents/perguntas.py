"""De "o que falta saber" para "o que perguntar agora".

`context.v_fact_coverage.faltando` já sabe quais fatos do catálogo o escopo não tem. Isso é uma
lista, não uma conversa. Este módulo decide a ORDEM — e a ordem é o produto inteiro aqui, porque
a diferença entre onboarding e formulário é só essa.

A REGRA DE ORDENAÇÃO
    Primeiro o fato que DESTRAVA MAIS: quantos indicadores hoje indisponíveis passariam a ser
    calculáveis se o cliente respondesse aquela pergunta. Desempate pelas famílias CRÍTICAS
    (fluxo, proteção), que são as que nenhuma força alheia compensa.

    É a mesma lógica lexicográfica do elo mais fraco: não perguntar tudo, perguntar o que muda
    o diagnóstico. Um fato que destrava três indicadores vale três vezes mais a atenção do
    cliente que um que não destrava nenhum.

O QUE ELE NÃO FAZ
    Não pergunta o que outra fonte governa (`allows_conversation_update = false`): patrimônio
    investido vem do Open Finance e tolerância a risco vem do suitability. Perguntar isso seria
    pedir ao cliente um dado que o sistema não pode aceitar da boca dele.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

POLICY = "CONTEXT_FACT_CATALOG"
FAMILIAS_CRITICAS = ("fluxo", "protecao")


@dataclass(frozen=True)
class Pergunta:
    fact_key: str
    pergunta: str
    rotulo: str
    familia: str
    destrava: int          # indicadores hoje indisponíveis que passariam a ser calculáveis
    critica: bool

    def para_chip(self) -> dict[str, Any]:
        """No formato dos chips do YAML — a tela não precisa saber que este é dinâmico."""
        return {"id": f"falta:{self.fact_key}", "rotulo": self.rotulo,
                "agente": "assessor", "texto": self.pergunta}


_SQL = """
with faltando as (
    select unnest(f.faltando)::text as fact_key
      from context.v_fact_coverage f
     where f.scope_id = %s
),
-- quantos indicadores ATIVOS dependem de cada fato que falta, contando só os que hoje
-- estão indisponíveis: destravar um indicador que já sai não é destravar nada.
destrava as (
    select fl.fact_key, count(*)::int as n
      from faltando fl
      join diagnostics.indicator_definitions i
        on fl.fact_key = any(i.required_fact_keys)
     where i.is_active
       and exists (
             select 1 from diagnostics.client_indicators ci
              where ci.scope_id = %s and ci.indicator_code = i.code and ci.is_unavailable
           )
     group by fl.fact_key
)
select d.fact_key, d.pergunta, d.display_name, d.family::text,
       coalesce(x.n, 0) as destrava,
       (d.family::text = any(%s)) as critica
  from faltando fl
  join context.fact_definitions d on d.fact_key = fl.fact_key
  left join destrava x on x.fact_key = fl.fact_key
 where d.is_active
   and d.allows_conversation_update      -- não se pergunta o que outra fonte governa
   and d.pergunta is not null
 order by coalesce(x.n, 0) desc,
          (d.family::text = any(%s)) desc,
          d.fact_key
 limit %s
"""


async def proximas(conn: AsyncConnection, scope_id: str, *, teto: int | None = None) -> list[Pergunta]:
    """As perguntas mais úteis agora, na ordem. Teto vem da política — atenção é governada."""
    if teto is None:
        cur = await conn.execute(
            "select payload from engine.policy_versions "
            "where code = %s and effective_to is null", (POLICY,))
        linha = await cur.fetchone()
        if linha is None:
            raise RuntimeError(f"política {POLICY} não está vigente")
        teto = int(linha[0].get("max_perguntas_sugeridas", 0))
        if teto <= 0:
            raise RuntimeError(f"{POLICY}.max_perguntas_sugeridas ausente ou inválido")

    cur = await conn.execute(_SQL, (scope_id, scope_id, list(FAMILIAS_CRITICAS),
                                    list(FAMILIAS_CRITICAS), teto))
    return [Pergunta(fact_key=r[0], pergunta=r[1], rotulo=r[2], familia=r[3],
                     destrava=r[4], critica=bool(r[5]))
            for r in await cur.fetchall()]


async def linha_para_prompt(conn: AsyncConnection, scope_id: str) -> str:
    """O bloco que entra no contexto do Assessor: o que falta e o que isso custa em diagnóstico.

    Entra como DADO delimitado, no mesmo espírito de `cobertura_mercado` do Analista: o agente
    diz de cara o que consegue medir, em vez de tentar e cair em `insumo_faltante`.
    """
    perguntas = await proximas(conn, scope_id)
    if not perguntas:
        return "Nenhum dado essencial em falta."
    linhas = ["Dados que faltam para o diagnóstico (pergunte no máximo UM por resposta, "
              "o primeiro da lista, e só quando fizer sentido na conversa):"]
    for p in perguntas:
        destrava = (f" — destrava {p.destrava} indicador(es)" if p.destrava else "")
        linhas.append(f"- {p.pergunta} ({p.rotulo}{destrava})")
    return "\n".join(linhas)
