"""Tool `contexto.perfil_financeiro` — o diagnóstico do cliente como ele deve ser lido.

Devolve TRÊS coisas, e a terceira é a que quase todo produto esconde:
  1. o gate da Fundação (reserva e dívida cara vêm antes de qualquer pontuação — D11);
  2. um score POR FAMÍLIA, com o elo mais fraco entre as críticas marcado;
  3. o que NÃO foi possível medir, com o nome do dado que falta.

Não existe score único aqui, e a ausência é a decisão do produto: média ponderada deixaria
uma falha crítica ser escondida por força em outra família — rotativo aberto com carteira
bem montada sairia "0,72", que soa razoável.

`emite_numero=False`: o score é um índice de diagnóstico já gravado por um run auditável
(`engine.runs`), não uma projeção. O rodapé de simulação seria falso.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.context.catalogo import catalogo, cobertura
from app.engine.perfil import perfil_atual
from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.registry import tool

METODO = "leitura do perfil calculado pelo motor determinístico (engine.runs kind=client_profile)"
NOTA = ("Diagnóstico do seu momento financeiro a partir do que está registrado no seu contexto. "
        "Onde falta dado, o indicador aparece como não medido — nunca como zero.")

# Motivo técnico → frase que o cliente entende. O agente lê a frase, não o slug.
MOTIVOS = {
    "fundacao_critica": "a Fundação está crítica: reserva e dívida cara vêm antes de pontuar o resto",
    "cobertura_insuficiente": "não há dados suficientes para pontuar esta área com honestidade",
    "dados_insuficientes": "ainda não há informação registrada para esta área",
    "motor_ausente": "este indicador ainda não é calculado nesta versão",
    "fato_vencido": "a informação registrada está desatualizada e precisa ser reconfirmada",
}


class PerfilParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incluir_catalogo: bool = Field(
        default=False,
        description="True para receber também a lista de fatos que a plataforma sabe registrar (útil para saber que chave usar em `contexto.verificar_mudanca`).")


class PerfilResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    perfil: dict
    cobertura_do_catalogo: dict
    catalogo: list[dict]


class AreaOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str
    rotulo: str
    score: float | None
    cobertura: float
    confianca: float
    critica: bool
    elo_mais_fraco: bool
    indisponivel: bool
    motivo: str | None


class IndicadorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str
    valor: float | None
    unidade: str | None
    confianca: float
    indisponivel: bool
    motivo: str | None


class PerfilOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calculado_em: str | None
    fundacao_critica: bool
    fundacao_semaforo: str | None
    areas: list[AreaOutput]
    indicadores: list[IndicadorOutput]
    elo_mais_fraco: str | None
    cobertura_do_contexto: float
    fatos_faltando: list[str]
    catalogo: list[dict]
    avisos: list[str]
    metodo: str
    nota: str


async def preparar_perfil(params: PerfilParams, ctx: ToolContext) -> PerfilResolvido:
    perfil = await perfil_atual(ctx.conn, ctx.scope_id)
    ctx.registrar_insumo("diagnostics.v_client_profile", areas=len(perfil["scores"]))

    if not perfil["scores"]:
        raise ToolInsumoFaltante(
            "o perfil ainda não foi calculado para este cliente — não há score gravado. "
            "Responda com o que se sabe do contexto e diga que o diagnóstico completo "
            "aparece assim que houver dados suficientes.")

    cob = await cobertura(ctx.conn, ctx.scope_id)
    ctx.registrar_insumo("context.v_fact_coverage", cobertura=cob["cobertura"])

    lista: list[dict] = []
    if params.incluir_catalogo:
        lista = [{"fact_key": d.fact_key, "rotulo": d.display_name, "familia": d.family,
                  "unidade": d.unit, "tipo": d.value_type}
                 for d in await catalogo(ctx.conn)]

    return PerfilResolvido(perfil=perfil, cobertura_do_catalogo=cob, catalogo=lista)


@tool(code="contexto.perfil_financeiro", family="contexto", semver="1.0.0",
      display_name="Perfil financeiro do cliente",
      description=(
          "Diagnóstico do momento financeiro do cliente por área (fluxo, proteção, estoque, "
          "destino, comportamento), com o gate da Fundação acima de tudo e a área mais frágil "
          "destacada. Diz também o que NÃO foi possível medir e qual dado falta. Use para "
          "situar qualquer conversa sobre a vida financeira do cliente e para descobrir a "
          "próxima pergunta útil."),
      preparar=preparar_perfil, min_plan="free", emite_numero=False)
def calcular_perfil_financeiro(r: PerfilResolvido) -> PerfilOutput:
    p = r.perfil
    areas = [
        AreaOutput(
            area=s["family"], rotulo=s["display_name"], score=s["value"],
            cobertura=s["coverage"] or 0.0, confianca=s["confidence"] or 0.0,
            critica=bool(s["is_critical_family"]), elo_mais_fraco=bool(s["elo_mais_fraco"]),
            indisponivel=bool(s["is_disabled"]),
            motivo=MOTIVOS.get(s["disabled_reason"] or "", s["disabled_reason"]))
        for s in p["scores"]
    ]
    indicadores = [
        IndicadorOutput(
            codigo=i["indicator_code"], valor=i["value"], unidade=i["unit"],
            confianca=i["confidence"] or 0.0, indisponivel=bool(i["is_unavailable"]),
            motivo=MOTIVOS.get(i["unavailable_reason"] or "", i["unavailable_reason"]))
        for i in p["indicadores"]
    ]

    avisos: list[str] = []
    if p["fundacao_critica"]:
        avisos.append(
            "A Fundação está crítica: os scores ficam desativados até reserva e dívida cara "
            "entrarem em ordem. Não é score baixo — é ausência de score, de propósito.")
    faltando = list(r.cobertura_do_catalogo.get("faltando") or [])
    if faltando:
        avisos.append(
            f"{len(faltando)} dado(s) do contexto ainda não registrados — é o que limita "
            "o que dá para medir com honestidade.")
    if r.cobertura_do_catalogo.get("vencendo"):
        avisos.append(
            f"{r.cobertura_do_catalogo['vencendo']} informação(ões) vencendo nos próximos 30 dias: "
            "vale reconfirmar antes que o diagnóstico perca confiança.")
    indisponiveis = [i for i in indicadores if i.indisponivel]
    if indisponiveis:
        avisos.append(
            f"{len(indisponiveis)} indicador(es) não medido(s). Não medido não é zero: "
            "onde não há base, não há número.")

    return PerfilOutput(
        calculado_em=p.get("as_of_date"),
        fundacao_critica=bool(p["fundacao_critica"]),
        fundacao_semaforo=p.get("fundacao_semaforo"),
        areas=areas, indicadores=indicadores, elo_mais_fraco=p.get("elo_mais_fraco"),
        cobertura_do_contexto=float(r.cobertura_do_catalogo.get("cobertura") or 0.0),
        fatos_faltando=faltando[:20], catalogo=r.catalogo,
        avisos=avisos, metodo=METODO, nota=NOTA)
