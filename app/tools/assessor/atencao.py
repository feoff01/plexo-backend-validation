"""Tool da família `planejamento` — os pontos de atenção da carteira (Raio-X).

POR QUE A FRASE NÃO É ESCRITA PELO MODELO
    Esta é a zona de risco de compliance de toda a F19, e vale dizer por quê em vez de
    confiar que dê certo. A lista de vocabulário proibido tem doze termos, e **"vender",
    "venda" e "melhor" isolados não estão nela** — o que está é `venda já`, `melhor fundo`,
    `melhor investimento`, `melhor opção`. Quem barra "esta posição você deveria reduzir" é a
    regra 4/5 do prompt do Assessor, que é qualitativa e não tem detector automático.

    Um alerta é exatamente o texto que puxa o modelo para o imperativo: "concentração alta em
    X" pede, gramaticalmente, um "então faça Y". Por isso a frase de cada achado sai de um
    DICIONÁRIO na fronteira, alimentado pela `quantification` que o motor gravou — o mesmo
    padrão de `AVISOS_CLIENTE` da F18. O modelo lê o achado e o interpreta; não o redige.

O QUE ELA DEVOLVE, E O QUE ESCONDE
    Findings correntes do escopo, com o gate de plano do próprio tipo (`min_plan`), mais a
    REVELAÇÃO ESTRUTURAL do que ficou de fora: quantos são e quanto valem, sem dizer quais.
    É a regra da migration 06 — "mostra O QUE foi encontrado e QUANTO vale; esconde por que e
    como resolver. Sem blur".

`emite_numero=False`: descreve o que foi medido sobre a carteira registrada. Não simula nada.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.db.repos.identity import plano_do_escopo
from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.hashing import arred2
from app.tools.registry import tool

FONTE = "diagnostics.findings"
POLICY = "RAIOX_LIMIARES"

ORDEM_PLANO = {"free": 0, "essential": 1, "advanced": 2, "wealth": 3}

SEVERIDADE_ROTULO = {"critica": "crítico", "alta": "alto", "media": "médio", "baixa": "baixo"}

# ---------------------------------------------------------------------------------
# A FRASE DO CLIENTE — dicionário na fronteira, nunca redação do modelo.
#
# Cada função recebe a `quantification` que o motor gravou e devolve UMA frase que
# descreve o que foi medido. Nenhuma delas diz o que fazer: a que mais chega perto é o
# FGC, e mesmo ela para em "fora dessa cobertura", sem completar a instrução.
# Achado sem frase aqui NÃO é renderizado — meia tradução é pior que nenhuma.
# ---------------------------------------------------------------------------------
def _brl(v: float | int | None) -> str:
    if v is None:
        return "—"
    return f"R$ {float(v):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _pct(v: float | int | None) -> str:
    return "—" if v is None else f"{float(v):.1f}%".replace(".", ",")


FRASES = {
    "risco.concentracao_emissor": lambda q: (
        f"{_pct(q.get('share_pct'))} da carteira está em {q.get('emissor')}, somando ações, "
        f"títulos e fundos do mesmo grupo — {_brl(q.get('exposicao_brl'))}. A referência de "
        f"diversificação usada aqui é {_pct(q.get('limiar_pct'))} por emissor."),
    "risco.exposicao_acima_do_fgc": lambda q: (
        f"{_brl(q.get('coberto_brl'))} em produtos cobertos pelo FGC no {q.get('emissor')}, "
        f"contra um teto de {_brl(q.get('teto_brl'))} por instituição. "
        f"{_brl(q.get('excedente_brl'))} ficam fora dessa cobertura."),
    "risco.concentracao_classe": lambda q: (
        f"{_pct(q.get('share_pct'))} da carteira está em uma única classe de ativo "
        f"({q.get('classe')}), {_brl(q.get('valor_brl'))}. A referência usada é "
        f"{_pct(q.get('limiar_pct'))}."),
    "alocacao.caixa_parado_excessivo": lambda q: (
        f"{_brl(q.get('caixa_total_brl'))} em caixa, contra {_brl(q.get('reserva_requerida_brl'))} "
        f"de reserva de emergência calculada para o seu custo de vida — "
        f"{_brl(q.get('excedente_brl'))} além dela."),
    "liquidez.resgate_longo_excessivo": lambda q: (
        f"{_pct(q.get('share_pct'))} da carteira ({_brl(q.get('valor_brl'))}) só pode ser "
        f"resgatada em D+{q.get('a_partir_de_dias')} ou mais. A referência usada é "
        f"{_pct(q.get('limiar_pct'))}."),
    "custo.taxa_fundo_alta": lambda q: (
        f"{q.get('produto')} cobra {_pct((q.get('taxa_aa') or 0) * 100)} ao ano de "
        f"administração, contra {_pct((q.get('referencia_aa') or 0) * 100)} de referência para "
        f"a classe — {_brl(q.get('custo_ano_brl'))} por ano sobre "
        f"{_brl(q.get('valor_aplicado_brl'))} aplicados."),
    "alocacao.sem_exposicao_internacional": lambda q: (
        "Não há posição em ativos internacionais na carteira registrada."),
}

NOTA = ("Diagnóstico sobre as posições registradas no escopo, medido contra as referências "
        "versionadas da plataforma na data indicada. Aponta o que foi medido, não o que fazer "
        "com o dinheiro — a decisão é sua.")


class AtencaoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apenas_familia: str | None = Field(
        default=None,
        description=("Filtrar por família: `risco`, `custo`, `liquidez`, `alocacao`, "
                     "`tributacao`, `estrutura`, `fundacao` ou `planejamento`."))


class AchadoResolvido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: str
    titulo: str
    familia: str
    severidade: str
    impacto_brl_ano: float | None
    unidade_do_impacto: str | None
    prioridade: float
    quantificacao: dict
    visto_em: str
    visivel: bool
    min_plan: str


class AtencaoResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: str | None
    achados: list[AchadoResolvido]
    plano: str
    total_carteira_brl: float | None
    cobertura_pct: float | None
    nao_diagnosticado: dict
    filtro_familia: str | None


class PontoDeAtencao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: str
    titulo: str
    familia: str
    severidade: str
    gravidade: str
    leitura: str
    impacto_brl_ano: float | None
    unidade_do_impacto: str | None
    quantificacao: dict


class AtencaoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: str | None
    pontos: list[PontoDeAtencao]
    total: int
    por_gravidade: dict[str, int]
    # Revelação estrutural do paywall (migration 06): quantos e quanto, nunca quais.
    ocultos: int
    ocultos_familias: list[str]
    plano: str
    total_carteira_brl: float | None
    cobertura_pct: float | None
    nao_diagnosticado: dict
    filtro_familia: str | None
    fonte: str
    avisos: list[str]
    nota: str


async def preparar_atencao(params: AtencaoParams, ctx: ToolContext) -> AtencaoResolvida:
    """Lê os findings correntes do escopo, respeitando cooldown e supressão.

    `diagnostics.findings` é `security_invoker` por RLS de escopo: finding de outro cliente
    não aparece. O gate de plano é aplicado depois, na metade pura, para que a REVELAÇÃO do
    que ficou oculto seja calculável — esconder na consulta tornaria impossível dizer quantos
    são, que é justamente o que a migration 06 exige que se diga.
    """
    await ctx.policy(POLICY)   # registra o uso: os limiares são premissa do que se afirma

    # `plano_do_escopo`, e não uma consulta própria. A primeira versão desta tool escreveu
    # `status = 'active'` à mão, enquanto o helper canônico aceita
    # `('trialing','active','past_due')` — e `status` tem DEFAULT `'trialing'` (03_billing:90).
    # O efeito era um cliente em teste receber `plano='free'` aqui e o paywall esconder
    # metade do diagnóstico, enquanto o MESMO cliente, no mesmo turno de conversa, era
    # admitido como `advanced` por `turn.py` — que usa o helper. Duas respostas para
    # "qual é o plano deste escopo" na mesma sessão.
    plano = await plano_do_escopo(ctx.conn, ctx.scope_id)

    cur = await ctx.conn.execute(
        "select f.finding_type_code, ft.display_name, ft.family::text, f.severity::text, "
        "       f.impact_brl_year::float, f.priority_score::float, f.quantification, "
        "       f.evidence, ft.min_plan::text, f.last_detected_at::date::text "
        "  from diagnostics.findings f "
        "  join diagnostics.finding_types ft on ft.code = f.finding_type_code "
        " where f.scope_id = %s and f.is_current and not f.permanently_suppressed "
        "   and (f.cooldown_until is null or f.cooldown_until <= current_date) "
        # GRAVIDADE PRIMEIRO, valor depois — e a razão é um defeito que a primeira execução
        # mostrou. `priority_score` é gerado pelo banco como (impacto × confiança) / atrito, e
        # concentração de emissor não tem impacto em reais por ano: o que ela muda é a
        # dispersão do resultado, não a despesa. Com `impact_brl_year` nulo o score cai a
        # zero, e o achado CRÍTICO — 45% da carteira num emissor só — aparecia depois de um
        # fundo caro de R$ 240 por ano.
        #
        # O score continua sendo o desempate certo entre achados de mesma gravidade: é ele
        # que põe R$ 44.000 parados na frente de R$ 240 de taxa. O que ele não pode é ordenar
        # sozinho uma lista em que metade dos itens não tem preço.
        " order by case f.severity when 'critica' then 0 when 'alta' then 1 "
        "            when 'media' then 2 else 3 end, "
        "          f.priority_score desc, f.finding_type_code", (ctx.scope_id,))
    linhas = await cur.fetchall()
    ctx.registrar_insumo("diagnostics.findings", achados=len(linhas))

    if not linhas:
        raise ToolInsumoFaltante(
            "não há diagnóstico de carteira para este escopo — o Raio-X ainda não foi "
            "executado, ou não há posição registrada para diagnosticar")

    achados = [
        AchadoResolvido(
            tipo=t, titulo=titulo, familia=familia, severidade=sev, impacto_brl_ano=impacto,
            unidade_do_impacto=(evidencia or {}).get("unidade_do_impacto"),
            prioridade=score or 0.0, quantificacao=quant or {}, visto_em=visto,
            visivel=ORDEM_PLANO.get(min_plan, 9) <= ORDEM_PLANO.get(plano, 0),
            min_plan=min_plan)
        for t, titulo, familia, sev, impacto, score, quant, evidencia, min_plan, visto in linhas
        if params.apenas_familia is None or familia == params.apenas_familia
    ]
    if not achados:
        raise ToolInsumoFaltante(
            f"nenhum ponto de atenção na família '{params.apenas_familia}' — as famílias com "
            f"achado hoje são: {', '.join(sorted({l[2] for l in linhas}))}")

    cur = await ctx.conn.execute(
        "select total_value_brl::float, coverage_pct::float, uncovered_breakdown, as_of_date::text "
        "  from diagnostics.coverage_reports where scope_id = %s "
        " order by as_of_date desc limit 1", (ctx.scope_id,))
    cob = await cur.fetchone()
    ctx.registrar_insumo("diagnostics.coverage_reports", presente=cob is not None)

    return AtencaoResolvida(
        as_of=cob[3] if cob else None, achados=achados, plano=plano,
        total_carteira_brl=arred2(cob[0]) if cob else None,
        cobertura_pct=round(cob[1] * 100, 2) if cob else None,
        nao_diagnosticado=dict(cob[2] or {}) if cob else {},
        filtro_familia=params.apenas_familia)


# 1.0.1: a copy do FGC deixou de usar o radical que o detector de vocabulario barra no
# singular. O plural escapava da lista por casamento de palavra inteira, e e justamente
# por escapar que nao devia ficar: "cobertura do FGC" e o termo corrente do mercado.
@tool(code="planejamento.pontos_de_atencao", family="planejamento", semver="1.1.0",
      display_name="Pontos de atenção da carteira",
      description=("O que o diagnóstico da carteira encontrou: concentração em um emissor "
                   "(consolidando conglomerado), exposição acima do teto coberto pelo FGC, "
                   "concentração em uma classe, caixa parado além da reserva, parcela travada "
                   "em resgate longo e produto com taxa acima da referência da classe. Cada "
                   "ponto vem com o número que o produziu e a referência contra a qual foi "
                   "medido. Use quando o cliente perguntar se há algo errado, arriscado ou fora "
                   "do lugar na carteira. Descreve o que foi medido; não indica o que comprar, "
                   "manter ou desfazer."),
      emite_numero=False, preparar=preparar_atencao)
def calcular_atencao(r: AtencaoResolvida) -> AtencaoOutput:
    pontos: list[PontoDeAtencao] = []
    avisos: list[str] = []
    sem_frase = False

    for a in r.achados:
        if not a.visivel:
            continue
        frase = FRASES.get(a.tipo)
        if frase is None:
            # Achado novo sem frase escrita é bug de quem acrescentou o achado. O cliente não
            # vê slug; quem mantém vê o aviso.
            sem_frase = True
            continue
        pontos.append(PontoDeAtencao(
            tipo=a.tipo, titulo=a.titulo, familia=a.familia, severidade=a.severidade,
            gravidade=SEVERIDADE_ROTULO.get(a.severidade, a.severidade),
            leitura=frase(a.quantificacao), impacto_brl_ano=a.impacto_brl_ano,
            unidade_do_impacto=a.unidade_do_impacto, quantificacao=a.quantificacao))

    por_gravidade: dict[str, int] = {}
    for p in pontos:
        por_gravidade[p.gravidade] = por_gravidade.get(p.gravidade, 0) + 1

    ocultos = [a for a in r.achados if not a.visivel]
    if sem_frase:
        avisos.append("achado_sem_leitura_para_o_cliente")
    if ocultos:
        avisos.append("ha_pontos_fora_do_plano")
    if r.nao_diagnosticado:
        avisos.append("parte_da_carteira_nao_diagnosticada")
    if r.filtro_familia:
        avisos.append("recorte_por_familia")

    return AtencaoOutput(
        as_of=r.as_of, pontos=pontos, total=len(pontos), por_gravidade=por_gravidade,
        # Quantos e de que famílias — nunca quais. É a revelação estrutural da migration 06:
        # o Free vê que existe algo e quanto pesa, sem receber o diagnóstico de graça.
        ocultos=len(ocultos), ocultos_familias=sorted({a.familia for a in ocultos}),
        plano=r.plano, total_carteira_brl=r.total_carteira_brl, cobertura_pct=r.cobertura_pct,
        nao_diagnosticado=r.nao_diagnosticado, filtro_familia=r.filtro_familia,
        fonte=FONTE, avisos=avisos, nota=NOTA)
