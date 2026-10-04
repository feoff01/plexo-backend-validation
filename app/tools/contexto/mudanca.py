"""Tool `contexto.verificar_mudanca` — o cliente disse um número; ele mudou de verdade?

POR QUE ESTA TOOL É **READ-ONLY**
    O executor tem cache content-addressed: mesma versão + mesmo resolvido devolve o output
    gravado sem executar a função. Uma tool que ESCREVESSE a proposta seria silenciosamente
    pulada na segunda vez que o cliente repetisse o mesmo número — e o card sumiria sem
    explicação. Então a divisão é: a tool COMPARA (puro, cacheável, golden-testável) e quem
    grava é o orquestrador do turno, em Tx B, idempotente por `proposal_hash` (C38e).

    É a mesma divisão que o projeto já usa na 2ª opinião do Assessor: a tool avalia, o turno
    registra em `decisions.records`.

O QUE ELA DEVOLVE
    O veredito e o MOTIVO em português — inclusive quando a resposta é "não vou perguntar isso".
    Uma variação de R$ 50 na renda não vira card, e o agente precisa saber disso para não
    prometer ao cliente uma atualização que o banco vai recusar (C38d).

`emite_numero=False`: a tool não projeta nem simula nada. Ela compara dois números que já
existem — o rodapé de simulação seria falso.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.context.catalogo import (
    Comparacao, comparar, cobertura, definicao, fato_vigente, resolver_por_atributo,
)
from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.registry import tool

METODO = "comparação do valor informado com o fato vigente, contra o catálogo de fatos"
NOTA = ("Comparação com o que já está registrado no seu contexto. Nada é alterado sem a sua "
        "confirmação explícita.")


class VerificarMudancaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atributo: str = Field(
        description=("O que mudou, na chave do catálogo (ex.: 'renda.mensal_liquida', "
                     "'despesa.essencial_mensal', 'protecao.reserva_atual'). Use `contexto.perfil_financeiro` "
                     "para ver as chaves disponíveis."))
    valor: float = Field(description="O número que o cliente acabou de informar, na unidade do fato (BRL, meses, anos, fração).")
    natureza: str | None = Field(
        default=None,
        description=("'recorrente' se passou a valer daqui em diante, 'pontual' se foi de uma vez só, "
                     "'incerto' se o cliente não deixou claro. Na dúvida, deixe vazio: a tela pergunta."))


class MudancaResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encontrou_no_catalogo: bool
    comparacao: dict | None
    natureza_informada: str | None
    cobertura_do_escopo: float
    atributo_pedido: str


class MudancaOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_key: str
    rotulo: str
    unidade: str | None
    valor_atual: float | None
    valor_informado: float
    variacao: float | None
    variacao_relativa: float | None
    e_mudanca_material: bool
    e_fato_novo: bool
    pode_virar_proposta: bool
    precisa_classificar_natureza: bool
    natureza: str | None
    fonte_que_manda: str
    motivo: str
    avisos: list[str]
    metodo: str
    nota: str


NATUREZAS = ("pontual", "recorrente", "incerto")


async def preparar_verificar_mudanca(params: VerificarMudancaParams, ctx: ToolContext) -> MudancaResolvida:
    d = await resolver_por_atributo(ctx.conn, params.atributo)
    if d is None:
        # Não é erro do cliente nem alucinação a ser escondida: é vocabulário fechado.
        # O agente recebe a lista do que existe e refaz a chamada.
        catalogo_txt = await _chaves_proximas(ctx, params.atributo)
        raise ToolInsumoFaltante(
            f"'{params.atributo}' não está no catálogo de fatos. Chaves parecidas: {catalogo_txt}. "
            "Use uma delas ou chame `contexto.perfil_financeiro` para ver o catálogo.")

    ctx.registrar_insumo("context.fact_definitions", fact_key=d.fact_key)
    atual = await fato_vigente(ctx.conn, ctx.scope_id, d.fact_key)
    ctx.registrar_insumo("context.v_fact_current", fact_key=d.fact_key, presente=atual is not None)

    if not d.e_numerico:
        raise ToolInsumoFaltante(
            f"'{d.display_name}' não é um fato numérico ({d.value_type}) — esta tool compara números. "
            "Mudanças qualitativas entram pela extração de fim de conversa.")

    cob = await cobertura(ctx.conn, ctx.scope_id)
    ctx.registrar_insumo("context.v_fact_coverage", cobertura=cob["cobertura"])

    comp: Comparacao = comparar(d, params.valor, atual)
    natureza = params.natureza if params.natureza in NATUREZAS else None
    return MudancaResolvida(
        encontrou_no_catalogo=True, comparacao=comp.para_dict(), natureza_informada=natureza,
        cobertura_do_escopo=cob["cobertura"] or 0.0, atributo_pedido=params.atributo)


async def _chaves_proximas(ctx: ToolContext, pedido: str) -> str:
    """Sugestão simples por prefixo/substring — o agente não adivinha o vocabulário sozinho."""
    from app.context.catalogo import catalogo as ler_catalogo
    todas = await ler_catalogo(ctx.conn)
    alvo = pedido.lower().replace("-", "_")
    perto = [d.fact_key for d in todas
             if alvo.split(".")[-1] in d.fact_key or d.fact_key.split(".")[0] in alvo]
    return ", ".join(perto[:5]) if perto else ", ".join(d.fact_key for d in todas[:5])


@tool(code="contexto.verificar_mudanca", family="contexto", semver="1.0.0",
      display_name="Verificar mudança no contexto",
      description=(
          "Compara um número que o cliente acabou de informar (renda, despesa, reserva, dívida, "
          "objetivo) com o que já está registrado no contexto dele, e diz se a mudança é material "
          "o bastante para virar uma confirmação. Use SEMPRE que o cliente mencionar um valor novo "
          "sobre a própria vida financeira — inclusive de passagem. Não altera nada: quem confirma "
          "é o cliente, num cartão na tela."),
      preparar=preparar_verificar_mudanca, min_plan="free", emite_numero=False)
def calcular_verificar_mudanca(r: MudancaResolvida) -> MudancaOutput:
    c = r.comparacao or {}
    avisos: list[str] = []

    material = bool(c.get("e_material"))
    aceita = bool(c.get("aceita_atualizacao_por_conversa"))
    dentro = bool(c.get("dentro_da_faixa"))
    exige_natureza = bool(c.get("exige_natureza"))
    natureza = r.natureza_informada

    if not dentro:
        avisos.append("O valor está fora da faixa esperada para este fato — confirme se entendi certo.")
    if not aceita:
        avisos.append(
            f"Este dado é atualizado por {c.get('fonte_que_manda')}, não por conversa. "
            "A divergência fica registrada como pergunta em aberto.")
    if material and aceita and dentro and exige_natureza and natureza in (None, "incerto"):
        avisos.append(
            "Falta saber se isso passou a valer daqui em diante ou foi de uma vez só — "
            "é o que a tela vai perguntar.")
    if not material and not c.get("e_fato_novo") and aceita and dentro:
        avisos.append("A variação está abaixo do limiar: não vale interromper o cliente por isso.")

    # A proposta só pode nascer quando TODAS as portas do banco estão abertas (C38b/C38d/C39d).
    # Antecipar isso aqui é o que permite o agente explicar em vez de o turno estourar.
    pode = material and aceita and dentro and (not exige_natureza or natureza == "recorrente"
                                               or natureza == "pontual")

    return MudancaOutput(
        fact_key=str(c.get("fact_key")),
        rotulo=str(c.get("display_name")),
        unidade=c.get("unit"),
        valor_atual=c.get("valor_atual"),
        valor_informado=float(c.get("valor_novo", 0.0)),
        variacao=c.get("delta"),
        variacao_relativa=c.get("delta_relativo"),
        e_mudanca_material=material,
        e_fato_novo=bool(c.get("e_fato_novo")),
        pode_virar_proposta=pode,
        precisa_classificar_natureza=exige_natureza and natureza is None,
        natureza=natureza,
        fonte_que_manda=str(c.get("fonte_que_manda")),
        motivo=str(c.get("motivo")),
        avisos=avisos,
        metodo=METODO,
        nota=NOTA,
    )
