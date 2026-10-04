"""Tool `planejamento.simulacao_objetivo` — a distribuição do valor final de um objetivo.

O QUE ELA DEVOLVE, E POR QUE NESSA ORDEM
    O p5 vem ANTES da mediana na estrutura de saída, e não é detalhe de arrumação: é o
    guardrail do §8 do `META_PROBABILIDADE_DE_SUCESSO.md`. Um fan chart lido de cima para
    baixo vira promessa de retorno; lido a partir do cenário ruim, vira planejamento. O
    agente escreve na ordem em que recebe.

    Junto vem o ARREPENDIMENTO — a chance de terminar com menos do que foi depositado —, que
    é o risco que o cliente sente e que percentil nenhum comunica. Sem ele, "a arrojada tem
    mediana maior" parece um argumento.

POR QUE ELA LÊ EM VEZ DE SIMULAR
    O executor de tools tem cache endereçado por conteúdo: mesma entrada devolve a saída
    guardada SEM executar. Uma tool que rodasse o Monte Carlo devolveria, na segunda
    chamada, números que ninguém calculou naquele momento — e, pior, sem `engine.runs` para
    auditar. Então simular é trabalho de job (`plexo meta projetar`), que grava com run,
    semente e hash; a tool LÊ o que ficou gravado. É a mesma separação de
    `contexto.perfil_financeiro`.

`emite_numero=True`: aqui há projeção de futuro, e o rodapé de simulação é obrigatório.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.tools.executor import ToolContext, ToolInsumoFaltante
from app.tools.registry import tool

METODO = ("leitura da projeção gravada por run determinístico (engine.runs kind=projection): "
          "Monte Carlo com log-retornos normais, aporte no fim do mês e volatilidade da "
          "carteira derivada da matriz de covariância das premissas de mercado vigentes")
NOTA = ("Simulação ilustrativa a partir de premissas de mercado versionadas, não previsão. "
        "Os valores mudam se as premissas, o aporte ou o prazo mudarem.")
LIMITACAO = ("A simulação assume oscilações com distribuição normal, o que SUBESTIMA a "
             "cauda: uma crise real tende a ser pior que o cenário ruim mostrado aqui.")


class SimulacaoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objetivo: str | None = Field(
        default=None,
        description="Nome (ou parte do nome) do objetivo. Omita para receber todos os objetivos ativos com projeção.")


class Projecao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objetivo: str
    prazo_meses: int
    valor_alvo: float
    aporte_mensal: float
    total_a_depositar: float
    carteira: str
    # a ordem importa: cenário ruim primeiro, mediana depois (guardrail do §8)
    cenario_ruim_p5: float
    p25: float
    mediana_p50: float
    p75: float
    cenario_bom_p95: float
    chance_de_atingir: float
    chance_de_ficar_abaixo_do_depositado: float
    aporte_para_90_por_cento: float | None
    veredito_de_risco: str | None
    carteiras_comparadas: list[dict]
    # SLUGS, nunca prosa: o bloco os traduz (`AVISOS_CLIENTE` em `app/agents/blocos.py`).
    # Por objetivo, e não da execução inteira — senão o aviso de uma meta aparece embaixo
    # da outra, que foi exatamente o que aconteceu na tela.
    avisos: list[str] = []


class SimulacaoResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projecoes: list[dict]
    premissas: dict


class SimulacaoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projecoes: list[Projecao]
    premissas_de_mercado: dict
    avisos: list[str]
    metodo: str
    nota: str
    limitacao: str
    # Orientação DIRIGIDA AO MODELO. Chega ao LLM (o turno serializa a saída inteira) e
    # NUNCA ao bloco: `blocos.py` só copia `avisos`. Antes esse texto morava em `avisos`, e
    # o cliente lia "é o número a discutir, não o alvo · diga isso ao cliente" em vermelho.
    orientacao_ao_modelo: list[str]


async def preparar_simulacao(params: SimulacaoParams, ctx: ToolContext) -> SimulacaoResolvida:
    filtro = ""
    args: list[object] = [ctx.scope_id]
    if params.objetivo:
        filtro = " and g.name ilike %s"
        args.append(f"%{params.objetivo}%")

    # A projeção mais recente de cada meta, com as três alocações lado a lado. `distinct on`
    # por (meta, alocação) porque cada alocação tem run próprio — ver `projecao.py`.
    cur = await ctx.conn.execute(
        f"""select distinct on (p.goal_id, p.alocacao_code)
                   g.name, g.target_amount_brl::float, g.target_date, p.alocacao_code,
                   p.success_prob::float, p.prob_abaixo_do_depositado::float,
                   p.required_monthly_brl::float,
                   p.p5_brl::float, p.p25_brl::float, p.p50_brl::float,
                   p.p75_brl::float, p.p95_brl::float,
                   p.assumptions, p.as_of_date
              from planning.goal_projections p
              join planning.goals g on g.id = p.goal_id
             where p.scope_id = %s and g.status = 'ativa'{filtro}
             order by p.goal_id, p.alocacao_code, p.as_of_date desc, p.computed_at desc""",
        args)
    linhas = await cur.fetchall()
    ctx.registrar_insumo("planning.goal_projections", linhas=len(linhas))

    if not linhas:
        raise ToolInsumoFaltante(
            "ainda não há projeção calculada para os objetivos deste cliente. Diga que a "
            "simulação aparece assim que o objetivo tiver prazo, valor e um aporte mensal "
            "conhecido — e pergunte o que falta em vez de estimar.")

    cur = await ctx.conn.execute(
        "select code, version, metodologia, compliance_status::text, horizonte_anos "
        "from market.assumption_sets where effective_to is null order by code limit 1")
    row = await cur.fetchone()
    premissas = ({"conjunto": row[0], "versao": row[1], "metodologia": row[2],
                  "status": row[3], "horizonte_anos": row[4]} if row else {})
    ctx.registrar_insumo("market.assumption_sets", conjunto=premissas.get("conjunto"))

    return SimulacaoResolvida(
        projecoes=[{"objetivo": n, "alvo": a, "data": d.isoformat(), "carteira": c,
                    "prob": pr, "arrep": ab, "necessario": req,
                    "p5": p5, "p25": p25, "p50": p50, "p75": p75, "p95": p95,
                    "extra": ex or {}, "as_of": ao.isoformat()}
                   for n, a, d, c, pr, ab, req, p5, p25, p50, p75, p95, ex, ao in linhas],
        premissas=premissas)


@tool(code="planejamento.simulacao_objetivo", family="planejamento", semver="1.2.0",
      display_name="Simulação de objetivo com probabilidade",
      description=(
          "A CHANCE de o cliente alcançar um objetivo que ele já cadastrou. Responde "
          "diretamente 'qual a probabilidade de eu conseguir', 'eu vou conseguir me "
          "aposentar', 'dá para chegar lá': simula dez mil cenários e devolve a "
          "probabilidade, o cenário ruim, o valor mais provável, o cenário bom, a chance de "
          "terminar abaixo do que foi depositado e quanto o aporte precisaria ser para chegar "
          "a 90% de confiança. Traz ainda o veredito de risco — se correr mais risco aumenta "
          "ou não a chance NESTE prazo, com o número que decidiu. Use SEMPRE que a pergunta "
          "envolver chance, probabilidade ou 'vou conseguir'. Para um objetivo hipotético que "
          "o cliente ainda não cadastrou, use `planejamento.projecao_objetivo`."),
      preparar=preparar_simulacao, min_plan="essential", emite_numero=True)
def simular_objetivo(r: SimulacaoResolvida) -> SimulacaoOutput:
    por_meta: dict[str, list[dict]] = {}
    for p in r.projecoes:
        por_meta.setdefault(p["objetivo"], []).append(p)

    projecoes: list[Projecao] = []
    avisos: list[str] = []          # slugs da execução — o bloco traduz
    orientacao: list[str] = []      # prosa para o MODELO — nunca chega à tela

    for nome, linhas in por_meta.items():
        eleita = next((l for l in linhas if (l["extra"] or {}).get("eleita")), linhas[0])
        extra = eleita["extra"] or {}
        total = float(extra.get("total_depositado") or 0.0)
        meses = _meses(linhas[0]["data"], linhas[0]["as_of"])
        aporte = (total / meses) if meses else 0.0

        projecoes.append(Projecao(
            objetivo=nome, prazo_meses=meses, valor_alvo=eleita["alvo"],
            aporte_mensal=round(aporte, 2), total_a_depositar=round(total, 2),
            carteira=eleita["carteira"],
            cenario_ruim_p5=eleita["p5"], p25=eleita["p25"], mediana_p50=eleita["p50"],
            p75=eleita["p75"], cenario_bom_p95=eleita["p95"],
            chance_de_atingir=eleita["prob"],
            chance_de_ficar_abaixo_do_depositado=eleita["arrep"],
            aporte_para_90_por_cento=eleita["necessario"],
            veredito_de_risco=extra.get("veredito"),
            carteiras_comparadas=[
                {"carteira": l["carteira"], "cenario_ruim_p5": l["p5"],
                 "mediana_p50": l["p50"], "chance_de_atingir": l["prob"],
                 "chance_de_ficar_abaixo_do_depositado": l["arrep"]}
                for l in sorted(linhas, key=lambda x: x["p5"], reverse=True)]))

        if eleita["prob"] < 0.5:
            projecoes[-1].avisos.append("objetivo_dificil_com_aporte_atual")
            orientacao.append(
                f"'{nome}': a chance está abaixo de 50%. O número acionável é o aporte para "
                f"90% de confiança, não o alvo — traga-o na resposta.")
        if eleita["arrep"] > 0.10:
            projecoes[-1].avisos.append("pode_terminar_abaixo_do_depositado")

    if r.premissas.get("status") != "approved":
        avisos.append("premissas_em_revisao")
        orientacao.append(
            "As premissas de mercado estão em revisão interna: apresente os números como "
            "ordem de grandeza.")

    return SimulacaoOutput(projecoes=projecoes, premissas_de_mercado=r.premissas,
                           avisos=avisos, metodo=METODO, nota=NOTA, limitacao=LIMITACAO,
                           orientacao_ao_modelo=orientacao)


def _meses(data_alvo: str, as_of: str) -> int:
    a, m = int(data_alvo[:4]), int(data_alvo[5:7])
    b, n = int(as_of[:4]), int(as_of[5:7])
    return max(0, (a - b) * 12 + (m - n))
