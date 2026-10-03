"""Blocos ricos (F11): tradução DETERMINÍSTICA do output de uma tool em descritores de representação
(`serie` | `barras` | `indicadores` | `progresso` | `tabela`) que a tela desenha em SVG próprio.

Regras:
- Nenhum número é criado aqui: tudo vem do `output_payload` (model_dump json) da execução. O LLM não participa.
- Todo bloco carrega `proveniencia` (fonte, as_of, n, método, premissas, avisos) e uma `nota` de compliance.
- Evidência insuficiente (`evidencia.suficiente=false`) ⇒ nenhum bloco numérico.
- Chave ausente ⇒ o bloco é omitido, nunca exceção (outputs `dict` do Assessor não têm modelo).
- Comparações preservam a ordem de entrada — sem ranking, sem "melhor"; veto do cliente é marcado, não escondido.
- Tetos (config-first): `max_blocos` e `max_pontos` vêm de AGENT_CONVERSATIONS; a amostragem preserva as pontas.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from psycopg import AsyncConnection

log = logging.getLogger(__name__)

# `faixa` (F18): a distribuição de um resultado — cenário ruim, meio e bom — contra um alvo.
# Nasceu porque o bloco de indicadores despejava cinco valores do mesmo tamanho e o leitor não
# conseguia ver o que importa: se a mediana está acima ou abaixo do alvo. Cinco números que o
# olho precisa comparar são cinco números que ninguém compara.
# `carteira` (F19): a carteira aberta posição a posição, agrupada pelos grupos que o banco já
# nomeia (`market.asset_classes.group_name`). Não é `tabela` genérica porque o que faz esta
# leitura funcionar é a hierarquia — grupo, depois ativo — com o peso visível na linha. Uma
# tabela plana de onze linhas com uma coluna de porcentagem é o formato em que a concentração
# desaparece: ninguém soma três linhas de olho para descobrir que 47% está num emissor só.
TIPOS = ("serie", "barras", "indicadores", "progresso", "tabela", "citacao", "faixa", "carteira", "atencao")

# ---------------------------------------------------------------------------------
# AVISOS: a fronteira entre o que a tool sabe e o que o cliente lê
#
# As tools emitem SLUG — que é o formato certo para uma máquina: estável, comparável,
# testável. O que estava errado era o slug atravessar até a tela. O cliente lia
# "aporte necessario acima da capacidade" em vermelho, sem acento, e entendia erro.
#
# A tradução vive AQUI, e não no frontend, por dois motivos: o texto é conteúdo de
# produto (passa pelo mesmo cuidado de vocabulário que o resto), e o mesmo bloco é
# gravado em `agents.messages.content_json` — quem reabrir a conversa daqui a um ano
# tem que ler a frase, não o slug.
#
# REGRA: slug fora deste mapa NÃO é renderizado. Nada de `replace("_", " ")` — meia
# tradução é pior que nenhuma, porque parece intencional.
# ---------------------------------------------------------------------------------
AVISOS_CLIENTE: dict[str, str] = {
    # --- séries e dados de mercado
    "serie_curta": "A série tem poucos pontos para o período pedido, então o número perde precisão.",
    "serie_defasada": "O dado mais recente disponível é anterior à data pedida.",
    "serie_amostrada": "O gráfico mostra uma amostra dos pontos, para caber na tela.",
    "serie_constante": "A série não variou no período.",
    "sem_dados": "Não há dado disponível para o período pedido.",
    "instrumento_desconhecido": "Não encontrei esse ativo no que a plataforma cobre hoje.",
    "instrumento_ambiguo": "Mais de um ativo corresponde a esse nome.",
    "indice_desconhecido": "Não encontrei esse índice ou taxa na cobertura de mercado atual.",
    "composicao_indice_indisponivel": "Não há snapshot oficial de composição disponível para a data pedida.",
    "composicao_indice_truncada": "A tabela mostra apenas parte dos componentes do snapshot; o total da carteira foi preservado.",
    "sem_eventos_condicao": "Não encontrei períodos na direção pedida dentro da janela analisada.",
    "driver_constante": "O driver não variou no período usado, então não existe sensibilidade linear identificável.",
    "sem_graus_liberdade_inferencia": "Há pares suficientes para traçar a reta, mas não para estimar a incerteza dela.",
    "amostra_insuficiente_regressao": "Há observações demais poucas para estimar uma regressão linear.",
    "regime_sem_duas_amostras": "Um dos regimes não teve observações suficientes para formar a comparação.",
    "regime_amostra_insuficiente": "Pelo menos um dos regimes tem poucas observações; trate a comparação como descritiva e frágil.",
    "fora_da_cobertura": "Esse ativo está fora do que a plataforma cobre hoje.",
    "janela_pos_truncada": "A janela depois do evento ficou incompleta.",
    "janela_pre_truncada": "A janela antes do evento ficou incompleta.",
    "sem_retorno_alinhado_no_evento": "Não havia retorno comum do ativo e do benchmark na data do evento ou depois dela.",
    "amostra_insuficiente_event_study": "A janela de estimação tem poucas observações para estimar o modelo de mercado.",
    "benchmark_constante_event_study": "O benchmark não variou na janela de estimação, então beta não é identificável.",
    "event_study_inferencia_indisponivel": "O CAR pôde ser descrito, mas a amostra não permite estimar sua incerteza pelo método solicitado.",
    "event_study_inferencia_hipoteses_fortes": "O intervalo de confiança usa hipóteses clássicas fortes (resíduos iid/homoscedásticos e variância estável no evento).",
    "evento_ajustado": "A data do evento foi ajustada para o pregão mais próximo.",
    "calendar_fallback_from_prices": "O calendário oficial não cobria toda a janela; foram usadas datas observadas nos preços como fallback.",
    "adjusted_close_retrospective": "Os preços ajustados usam eventos corporativos conhecidos hoje; não representam um vintage histórico do cutoff.",
    "benchmark_indisponivel": "Não havia referência de mercado disponível para comparar.",
    "sem_datas_comuns": "As séries não têm datas em comum suficientes para comparar.",
    "sem_horizonte_na_coleta": "A pesquisa de mercado não trouxe esse horizonte.",
    "horizonte_sem_mediana": "A pesquisa de mercado não trouxe mediana para esse horizonte.",
    "fundamental_unit_raw": "Há fundamento preservado sem unidade canônica; ele não entra nas contas de valuation.",
    "fundamental_unit_incompativel": "Há fundamento com unidade incompatível com a conta pedida; ele foi excluído do cálculo.",
    "historico_fundamental_insuficiente": "Há menos de dois períodos anuais válidos para formar uma tendência fundamental.",
    "crescimento_percentual_base_nao_positiva": "O crescimento percentual foi omitido quando a base anterior era zero ou negativa; a variação absoluta foi preservada.",
    "margem_receita_nao_positiva": "A margem foi omitida nos períodos em que a receita não era positiva.",
    "fundamental_metrica_classe_nao_suportada": "Esta versão de tendências fundamentais analisa métricas da companhia, não séries específicas por classe de ação.",
    "shares_outstanding_indisponivel": "Faltam ações em circulação de pelo menos uma classe, então o valor de mercado total não foi estimado.",
    "preco_bruto_indisponivel": "Falta preço de fechamento bruto válido para pelo menos uma classe.",
    "market_cap_cobertura_incompleta": "O valor de mercado total exige preço e ações de todas as classes identificadas; a cobertura está incompleta.",
    "market_cap_indisponivel": "Não foi possível calcular o valor de mercado total com segurança.",
    "divida_liquida_indisponivel": "Não há dívida líquida, nem dívida bruta e caixa suficientes para derivá-la.",
    "lucro_liquido_nao_positivo": "O lucro líquido não é positivo; P/L não é exibido para evitar um múltiplo enganoso.",
    "ebitda_nao_positivo": "O EBITDA não é positivo; EV/EBITDA não é exibido para evitar um múltiplo enganoso.",
    "patrimonio_liquido_nao_positivo": "O patrimônio líquido não é positivo; P/VP não é exibido para evitar um múltiplo enganoso.",
    "preco_multiplas_fontes_sem_prioridade": "Há preços divergentes de fontes diferentes e ainda não existe prioridade canônica entre elas; o preço foi omitido.",
    "preco_moeda_nao_brl": "O preço disponível não está em reais; ele não entrou no valuation em BRL.",
    "cenario_associacional_nao_previsao": "Este valor é um cenário mecânico baseado em associação histórica, não previsão, valor justo ou preço-alvo.",
    "preco_base_indisponivel": "Não há fechamento bruto válido para servir de preço-base do cenário.",
    "cenario_implica_preco_nao_positivo": "O choque extrapola a relação linear para um preço inválido; o preço de cenário foi omitido.",
    "cenario_intervalo_implica_preco_nao_positivo": "Parte do intervalo extrapolado implicaria preço inválido; o intervalo de preço foi omitido.",
    "sensibilidade_indisponivel": "Não há sensibilidade estimável para aplicar ao cenário.",
    "fx_observation_date_cutoff_sem_vintage": "O câmbio respeita a data da observação, mas a fonte atual não prova o vintage histórico contra revisões ou backfills.",
    "par_cambio_desconhecido": "Não encontrei esse par de moedas na cobertura cambial atual.",
    "curva_juros_indisponivel": "Não há curva oficial ANBIMA disponível para a data e o cutoff pedidos.",
    "curva_juros_sem_vintage_pit": "A curva existe, mas o lote disponível não comprova que já estava conhecido no cutoff pedido.",
    # --- orçamento
    "saldo_reserva_desconhecido": "Não há saldo de reserva registrado.",
    "ha_divida_cara_ativa": "Existe dívida cara ativa, e ela vem antes de aportar.",
    "sem_despesa_registrada_capacidade_e_renda_bruta": "Ainda não há despesa registrada, então este número é a renda com que dá para contar, não o que sobra depois de viver.",
    "historico_curto_para_p10": "Ainda há poucos meses observados para calcular com segurança o piso da renda variável.",
    "sem_income_summaries_usando_so_renda_fixa": "Só a renda fixa entrou na conta: ainda não há histórico de renda variável registrado.",
    # --- patrimônio
    "posicoes_sem_classe_de_ativo": "Algumas posições ainda não têm classe de ativo definida.",
    "sem_bem_nao_financeiro_registrado": "Não há bens fora de investimentos registrados.",
    "ha_passivo_no_consolidado": "O consolidado inclui dívidas.",
    "consolidado_omitido_a_pedido": "O consolidado foi omitido a seu pedido.",
    "achado_sem_leitura_para_o_cliente": "Há um ponto de atenção sem leitura escrita ainda; ele não aparece na lista.",
    "ha_pontos_fora_do_plano": "Há pontos de atenção que o seu plano atual não abre.",
    "parte_da_carteira_nao_diagnosticada": "Parte da carteira não pôde ser diagnosticada por falta de cadastro.",
    "recorte_por_familia": "Esta é uma parte do diagnóstico; há outras famílias com achados.",
    "posicoes_sem_preco_ingerido": "Algumas posições não têm preço de fechamento na plataforma, então aparecem pelo valor registrado.",
    "posicoes_sem_emissor_cadastrado": "Algumas posições ainda não têm emissor cadastrado, então não entram na leitura de concentração.",
    "precos_de_datas_diferentes": "Os preços de fechamento não são todos do mesmo pregão; a data mostrada é a mais antiga.",
    "recorte_da_carteira": "Esta é uma parte da carteira; os pesos continuam medidos sobre o total.",
    # --- planejamento
    "aporte_necessario_acima_da_capacidade": "O aporte necessário passa do que sobra hoje: o prazo ou o alvo precisariam mudar.",
    "idade_alvo_nao_esta_no_futuro": "A idade informada não está no futuro.",
    "patrimonio_atual_nao_informado_assumido_zero": "O patrimônio atual não foi informado, então a conta parte do zero.",
    "sem_sobra_para_aportar": "Com a renda com que dá para contar, não sobra valor para aportar depois das despesas — o que move este plano é o orçamento, não a carteira.",
    "objetivo_dificil_com_aporte_atual": "Com o aporte atual, a simulação chega ao alvo em menos da metade dos cenários.",
    "pode_terminar_abaixo_do_depositado": "Em parte dos cenários o valor final fica abaixo do total depositado.",
    "premissas_em_revisao": "As premissas de mercado desta simulação ainda estão em revisão interna: trate os números como ordem de grandeza.",
    # --- produto
    "sem_referencia_de_classe": "Não há referência de custo registrada para essa classe.",
    "come_cotas_incide_no_horizonte": "O come-cotas incide dentro desse prazo.",
    "ha_produto_incompativel_com_veto_do_cliente": "Há produto que conflita com um veto seu.",
    # --- documentos
    "limite_de_documentos_atingido": "Mostrei os primeiros documentos; há mais.",
}


def _avisos(brutos: Any) -> list[str]:
    """Slugs → frases. O que não está no mapa é DESCARTADO, não traduzido pela metade.

    Descartar em silêncio para o cliente, mas com log para quem mantém: aviso novo sem
    frase é bug de quem acrescentou o aviso, e o lugar de descobrir isso é o log, não a
    tela de alguém.
    """
    saida: list[str] = []
    for bruto in list(brutos or []):
        frase = AVISOS_CLIENTE.get(str(bruto))
        if frase is None:
            log.warning("aviso sem frase para o cliente, descartado: %r", bruto)
            continue
        if frase not in saida:
            saida.append(frase)
    return saida
PADRAO_MAX_BLOCOS = 6
PADRAO_MAX_PONTOS = 400

NOTA_MERCADO = ("Métrica descritiva sobre dados oficiais passados, ILUSTRATIVA; retorno passado não indica retorno "
                "futuro e isto não é indicação de compra ou venda.")
NOTA_SIMULACAO = "Simulação ILUSTRATIVA sob as premissas indicadas; não é projeção de rentabilidade nem indicação de investimento."
NOTA_DIDATICA = "Exemplo DIDÁTICO com a taxa informada; não é projeção de rentabilidade de nenhum produto real."
NOTA_DOCUMENTO = ("Trecho literal do documento oficial citado, na data indicada. É o que o emissor publicou — "
                  "não é análise da Plexo nem indicação de investimento.")
NOTA_PERFIL = ("Diagnóstico do que está registrado no seu contexto, na data indicada. Onde falta dado, o "
               "indicador aparece como não medido — não como zero. Não é indicação de investimento.")
NOTA_CONTEXTO = ("Comparação com o que está registrado no seu contexto. Nada é alterado sem a sua confirmação.")
NOTA_PATRIMONIO = ("Composição declarada pelo cliente e registrada no escopo, na data de referência; é descrição do "
                   "que está registrado, não avaliação de adequação nem indicação de investimento.")
NOTA_ATENCAO = ("Diagnóstico sobre as posições registradas no escopo, medido contra as referências "
                "versionadas da plataforma na data indicada. Aponta o que foi medido, não o que fazer "
                "com o dinheiro.")
NOTA_CARTEIRA = ("Posições registradas no escopo, avaliadas pelo último fechamento publicado. Preço de fechamento "
                 "é do pregão anterior, não cotação do momento. É descrição do que está registrado, não avaliação "
                 "de adequação nem indicação de compra ou venda.")

# Os quatro grupos vêm de `market.asset_classes.group_name` — o vocabulário é do banco, e o
# rótulo em português vive aqui pelo mesmo motivo que as frases de aviso: é conteúdo de
# produto, e fica gravado junto com o bloco em `agents.messages.content_json`.
_ROTULO_GRUPO = {"caixa": "Caixa e liquidez", "renda_fixa": "Renda fixa",
                 "renda_variavel": "Renda variável", "alternativos": "Alternativos"}


# ------------------------------------------------------------------ utilitários
def _amostrar(pontos: list[dict[str, Any]], max_pontos: int) -> tuple[list[dict[str, Any]], bool]:
    """Reduz a série a `max_pontos` mantendo primeiro e último (passo uniforme)."""
    n = len(pontos)
    if n <= max_pontos or max_pontos < 3:
        return pontos, False
    passo = (n - 1) / (max_pontos - 1)
    indices = sorted({round(i * passo) for i in range(max_pontos)} | {0, n - 1})
    return [pontos[i] for i in indices], True


def _bloco(tipo: str, execution_id: str, n: int, titulo: str, dados: dict[str, Any], proveniencia: dict[str, Any],
           nota: str, subtitulo: str | None = None) -> dict[str, Any]:
    assert tipo in TIPOS
    return {"tipo": tipo, "id": f"{execution_id}:{n}", "titulo": titulo, "subtitulo": subtitulo, "dados": dados,
            "proveniencia": proveniencia, "nota": nota}


def _prov_evidencia(ev: dict[str, Any]) -> dict[str, Any]:
    return {"fonte": ev.get("fonte", ""), "as_of": ev.get("as_of"), "cutoff_date": ev.get("cutoff_date"),
            "n": ev.get("n_observacoes"), "metodo": ev.get("metodo", ""), "premissas": {},
            "avisos": _avisos(ev.get("avisos")), "lacunas": len(ev.get("lacunas", []))}


def _prov_premissas(out: dict[str, Any], fonte: str, metodo: str | None = None) -> dict[str, Any]:
    return {"fonte": fonte, "as_of": None, "cutoff_date": None, "n": None, "metodo": metodo or out.get("metodo") or out.get("nota_metodo", ""),
            "premissas": dict(out.get("premissas_usadas") or {}), "avisos": _avisos(out.get("avisos")), "lacunas": 0}


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


# ------------------------------------------------------------------ educador
def _juros_compostos(out: dict, eid: str, max_pontos: int) -> list[dict]:
    serie = out.get("serie_anual")
    if not isinstance(serie, list) or not serie:
        return []
    prov = _prov_premissas(out, "simulador didático (taxa informada pelo cliente)", out.get("metodo"))
    prov["premissas"].update({"taxa_anual_pct": out.get("taxa_anual_pct"), "aporte_mensal_brl": out.get("aporte_mensal_brl"),
                              "valor_inicial_brl": out.get("valor_inicial_brl"), "prazo_anos": out.get("prazo_anos")})
    aportado = [{"x": f"ano {p['ano']}", "y": p["aportado_acumulado_brl"]} for p in serie]
    juros = [{"x": f"ano {p['ano']}", "y": p["juros_acumulados_brl"]} for p in serie]
    aportado, amostrada = _amostrar(aportado, max_pontos)
    juros, _ = _amostrar(juros, max_pontos)
    if amostrada:
        prov["avisos"].append("serie_amostrada")
    blocos = [_bloco("serie", eid, 1, "Montante ano a ano", {
        "series": [{"nome": "Aportado", "pontos": aportado}, {"nome": "Juros", "pontos": juros}],
        "eixo_y": {"formato": "brl"}, "empilhada": True}, prov, NOTA_DIDATICA,
        subtitulo=f"{out.get('taxa_anual_pct')}% a.a. · {out.get('prazo_anos')} anos")]
    itens = [("Montante final", out.get("montante_final_brl")), ("Total aportado", out.get("total_aportado_brl")),
             ("Juros", out.get("juros_totais_brl"))]
    blocos.append(_bloco("indicadores", eid, 2, "Resultado da simulação",
                         {"itens": [{"rotulo": r, "valor": v, "formato": "brl"} for r, v in itens if _num(v) is not None]},
                         prov, NOTA_DIDATICA))
    return blocos


def _exemplo_didatico(out: dict, eid: str, max_pontos: int) -> list[dict]:
    linhas = out.get("linhas")
    if not isinstance(linhas, list) or not linhas:
        return []
    prov = _prov_premissas(out, f"verbete aprovado · {out.get('slug', '')}")
    blocos = [_bloco("tabela", eid, 1, out.get("titulo_conteudo") or "Exemplo com números", {
        "colunas": [{"chave": "rotulo", "rotulo": "Item"}, {"chave": "valor_brl", "rotulo": "Valor", "formato": "brl"},
                    {"chave": "detalhe", "rotulo": "Premissa"}],
        "linhas": [{"rotulo": l.get("rotulo"), "valor_brl": l.get("valor_brl"), "detalhe": l.get("detalhe", "")} for l in linhas]},
        prov, NOTA_DIDATICA)]
    if out.get("conceito") == "ir_regressivo":
        faixas = [l for l in linhas if str(l.get("rotulo", "")).startswith("imposto se resgatado")]
        aplicado = next((l for l in linhas if str(l.get("rotulo", "")).startswith("imposto neste prazo")), None)
        if faixas:
            itens = [{"rotulo": l["rotulo"].replace("imposto se resgatado ", ""), "valor": l.get("valor_brl"), "detalhe": l.get("detalhe", "")} for l in faixas]
            if aplicado is not None:
                for it in itens:
                    if _num(it["valor"]) == _num(aplicado.get("valor_brl")):
                        it["destaque"] = "referencia"
            blocos.append(_bloco("barras", eid, 2, "Imposto por faixa de prazo", {"itens": itens, "formato": "brl"}, prov, NOTA_DIDATICA))
    return blocos


# ------------------------------------------------------------------ assessor
def _reserva(out: dict, eid: str, max_pontos: int) -> list[dict]:
    if _num(out.get("meses_cobertos")) is None:
        return []
    prov = _prov_premissas(out, "orçamento do escopo", "reserva = custo mensal × meses")
    prov["premissas"].update({k: v for k, v in (out.get("fontes") or {}).items()})
    maximo = max(_num(out.get("alvo_meses")) or 0, _num(out.get("meses_cobertos")) or 0) or 1
    blocos = [_bloco("progresso", eid, 1, "Cobertura da reserva de emergência", {
        "valor": out["meses_cobertos"], "maximo": maximo, "formato": "meses",
        "marcas": [m for m in ({"rotulo": "mínimo", "valor": out.get("minimo_meses")}, {"rotulo": "alvo", "valor": out.get("alvo_meses")})
                   if _num(m["valor"]) is not None]}, prov, NOTA_SIMULACAO,
        subtitulo=f"custo mensal considerado: R$ {out.get('custo_mensal_brl', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))]
    itens = [("Falta para o alvo", out.get("gap_para_alvo_brl"), "brl"), ("Falta para o mínimo", out.get("gap_para_minimo_brl"), "brl"),
             ("Meses para fechar o alvo", out.get("meses_para_fechar_alvo"), "meses")]
    blocos.append(_bloco("indicadores", eid, 2, "Distância até a referência",
                         {"itens": [{"rotulo": r, "valor": v, "formato": f} for r, v, f in itens if _num(v) is not None]}, prov, NOTA_SIMULACAO))
    return blocos


def _capacidade(out: dict, eid: str, max_pontos: int) -> list[dict]:
    dec = out.get("decomposicao")
    blocos: list[dict] = []
    prov = _prov_premissas(out, f"renda do escopo ({out.get('fonte', '')})", out.get("regra"))
    if isinstance(dec, dict) and _num(dec.get("fixa_brl")) is not None:
        itens = [{"rotulo": "Renda fixa", "valor": dec.get("fixa_brl")}, {"rotulo": "Piso da variável (p10)", "valor": dec.get("piso_variavel_brl")}]
        if _num(dec.get("media_variavel_brl")) is not None:
            itens.append({"rotulo": "Média da variável", "valor": dec.get("media_variavel_brl"), "destaque": "referencia", "detalhe": "só referência: a capacidade usa o piso"})
        dados = {"itens": itens, "formato": "brl"}
        if _num(out.get("capacidade_mensal_brl")) is not None:
            dados["referencia"] = {"rotulo": "capacidade mensal", "valor": out["capacidade_mensal_brl"]}
        blocos.append(_bloco("barras", eid, 1, "De onde vem a capacidade de aporte", dados, prov, NOTA_SIMULACAO))
    dividas = out.get("dividas_caras")
    if isinstance(dividas, list) and dividas:
        blocos.append(_bloco("tabela", eid, 2, "Dívidas caras ativas", {
            "colunas": [{"chave": "descricao", "rotulo": "Dívida"}, {"chave": "outstanding_brl", "rotulo": "Saldo", "formato": "brl"},
                        {"chave": "annual_rate", "rotulo": "Juros a.a.", "formato": "pct_fracao"}, {"chave": "custo_anual_estimado_brl", "rotulo": "Custo anual estimado", "formato": "brl"}],
            "linhas": [{k: d.get(k) for k in ("descricao", "outstanding_brl", "annual_rate", "custo_anual_estimado_brl")} for d in dividas]},
            prov, NOTA_SIMULACAO))
    return blocos


def _composicao_patrimonio(out: dict, eid: str, max_pontos: int) -> list[dict]:
    """Composição da carteira. NÃO é simulação: nota própria, sem 'projeção de rentabilidade'."""
    classes = out.get("composicao")
    if not isinstance(classes, list) or not classes:
        return []
    # `_avisos()`, e não `list(...)`: até a F19 este mapeador (e outros três) montavam a
    # proveniência à mão e mandavam o SLUG cru. `Bloco.tsx` descarta tudo que casa
    # /^[a-z0-9_]+$/, então `ha_passivo_no_consolidado` nunca chegou a ninguém — com a
    # frase já escrita em `AVISOS_CLIENTE`, esperando.
    prov = {"fonte": out.get("fonte", ""), "as_of": out.get("as_of"), "cutoff_date": None,
            "n": out.get("classes"), "metodo": "soma das posições registradas, por classe de ativo",
            "premissas": {}, "avisos": _avisos(out.get("avisos")), "lacunas": 0}
    itens = [{"rotulo": c.get("rotulo") or c.get("classe"), "valor": c.get("valor_brl"),
              "detalhe": f"{c.get('share_pct')}% da carteira"}
             for c in classes if _num(c.get("valor_brl")) is not None]
    if not itens:
        return []
    dados = {"itens": itens, "formato": "brl"}
    if _num(out.get("total_investido_brl")) is not None:
        dados["referencia"] = {"rotulo": "total investido", "valor": out["total_investido_brl"]}
    contas = out.get("contas")
    blocos = [_bloco("barras", eid, 1, "Onde a carteira está hoje", dados, prov, NOTA_PATRIMONIO,
                     subtitulo=f"{out.get('classes')} classes em {contas} conta(s)" if _num(contas) else None)]

    consolidado = [("Investido", out.get("total_investido_brl")), ("Imóveis", out.get("imoveis_brl")),
                   ("Demais bens", out.get("outros_bens_brl")), ("Passivo", out.get("passivo_brl")),
                   ("Patrimônio líquido", out.get("patrimonio_liquido_brl"))]
    indicadores = [{"rotulo": r, "valor": v, "formato": "brl"} for r, v in consolidado if _num(v) is not None]
    if indicadores:
        blocos.append(_bloco("indicadores", eid, 2, "Patrimônio consolidado",
                             {"itens": indicadores}, prov, NOTA_PATRIMONIO))
    return blocos


def _posicoes_carteira(out: dict, eid: str, max_pontos: int) -> list[dict]:
    """A carteira aberta (F19): grupo → ativo, com o peso na linha.

    Dois blocos, e a ordem importa: primeiro ONDE está o dinheiro (barras por grupo, que é a
    leitura de risco), depois O QUE está lá dentro (a carteira item a item). Quem abre a
    conversa perguntando de um ativo específico lê o segundo; quem pergunta "onde está meu
    dinheiro" para no primeiro. Inverter faria a lista de onze linhas ser a primeira coisa a
    aparecer, e a proporção — que é o que decide — ficaria embaixo.
    """
    posicoes = out.get("posicoes")
    if not isinstance(posicoes, list) or not posicoes:
        return []
    prov = {"fonte": out.get("fonte", ""), "as_of": out.get("posicao_em"),
            "cutoff_date": out.get("fechamento_em"), "n": out.get("itens"),
            "metodo": "posições registradas no escopo, avaliadas pelo último fechamento publicado",
            "premissas": {}, "avisos": _avisos(out.get("avisos")), "lacunas": len(out.get("sem_preco") or [])}

    blocos: list[dict] = []
    grupos = out.get("por_grupo")
    if isinstance(grupos, list) and grupos:
        itens = [{"rotulo": _ROTULO_GRUPO.get(g.get("grupo"), g.get("grupo")), "valor": g.get("valor_brl"),
                  "detalhe": f"{g.get('share_pct')}% da carteira · {g.get('posicoes')} posição(ões)"}
                 for g in grupos if _num(g.get("valor_brl")) is not None]
        if itens:
            dados = {"itens": itens, "formato": "brl"}
            if _num(out.get("total_da_carteira_brl")) is not None:
                dados["referencia"] = {"rotulo": "carteira", "valor": out["total_da_carteira_brl"]}
            blocos.append(_bloco("barras", eid, 1, "Onde o capital está alocado", dados, prov,
                                 NOTA_CARTEIRA))

    linhas = []
    for p in posicoes[:max_pontos]:
        if not isinstance(p, dict) or _num(p.get("valor_registrado_brl")) is None:
            continue
        linhas.append({
            # `codigo` é None para o que não é negociado em bolsa: a tela mostra o nome, e é
            # por isso que os dois campos vêm separados em vez de um "rótulo" já resolvido.
            "codigo": p.get("codigo"), "nome": p.get("nome"), "grupo": p.get("grupo"),
            "classe": p.get("rotulo_classe"), "emissor": p.get("emissor"),
            "quantidade": p.get("quantidade"), "preco_medio": p.get("preco_medio"),
            "preco_fechamento": p.get("preco_fechamento"), "valor": p.get("valor_registrado_brl"),
            "share_pct": p.get("share_pct"), "variacao_pct": p.get("variacao_sobre_preco_medio_pct"),
            "taxa_adm_aa": p.get("taxa_adm_aa"), "liquidez_dias": p.get("liquidez_dias"),
            "fgc": p.get("coberto_pelo_fgc"),
        })
    if not linhas:
        return blocos

    n = len(blocos) + 1
    contas = out.get("contas")
    sub = f"{out.get('itens')} posição(ões) em {contas} conta(s)" if _num(contas) else None
    blocos.append(_bloco("carteira", eid, n, "A carteira, posição a posição",
                         {"linhas": linhas,
                          "grupos": [{"grupo": g.get("grupo"),
                                      "rotulo": _ROTULO_GRUPO.get(g.get("grupo"), g.get("grupo")),
                                      "valor": g.get("valor_brl"), "share_pct": g.get("share_pct")}
                                     for g in (grupos or []) if isinstance(g, dict)],
                          "total_brl": out.get("total_da_carteira_brl"),
                          "posicao_em": out.get("posicao_em"), "fechamento_em": out.get("fechamento_em")},
                         prov, NOTA_CARTEIRA, subtitulo=sub))
    return blocos


def _pontos_de_atencao(out: dict, eid: str, max_pontos: int) -> list[dict]:
    """Os pontos de atenção do Raio-X (F19).

    Um bloco só, e de propósito: a lista É a leitura. Acrescentar um gráfico de barras por
    gravidade transformaria "você tem um problema crítico de concentração" em "você tem 1
    crítico, 3 altos e 1 baixo", que é a contagem substituindo o conteúdo.

    A ordem é a que veio: `priority_score` do banco, gerado por (impacto × confiança) /
    atrito. Reordenar aqui — por gravidade, por exemplo — seria trocar a fila do produto por
    uma opinião do renderizador.
    """
    pontos = out.get("pontos")
    if not isinstance(pontos, list) or not pontos:
        return []
    prov = {"fonte": out.get("fonte", ""), "as_of": out.get("as_of"), "cutoff_date": None,
            "n": out.get("total"),
            "metodo": "posições registradas medidas contra as referências versionadas da plataforma",
            "premissas": {}, "avisos": _avisos(out.get("avisos")), "lacunas": int(out.get("ocultos") or 0)}

    itens = []
    for p in pontos[:max_pontos]:
        if not isinstance(p, dict) or not p.get("leitura"):
            continue
        itens.append({"titulo": p.get("titulo"), "gravidade": p.get("gravidade"),
                      "familia": p.get("familia"), "leitura": p.get("leitura"),
                      # `unidade_do_impacto` viaja junto: sem ela a tela escreveria
                      # "R$ 20.000 por ano" sobre um valor exposto que não é anual nem custo.
                      "impacto": p.get("impacto_brl_ano"),
                      "unidade_do_impacto": p.get("unidade_do_impacto")})
    if not itens:
        return []

    total_carteira = out.get("total_carteira_brl")
    sub = None
    if _num(total_carteira) is not None:
        sub = f"sobre a carteira registrada de R$ {float(total_carteira):,.2f}".replace(
            ",", "·").replace(".", ",").replace("·", ".")
    return [_bloco("atencao", eid, 1, "Pontos de atenção",
                   {"itens": itens, "ocultos": int(out.get("ocultos") or 0),
                    "ocultos_familias": list(out.get("ocultos_familias") or []),
                    "plano": out.get("plano"),
                    "cobertura_pct": out.get("cobertura_pct"),
                    "nao_diagnosticado": dict(out.get("nao_diagnosticado") or {})},
                   prov, NOTA_ATENCAO, subtitulo=sub)]


def _documento_oficial(out: dict, eid: str, max_pontos: int) -> list[dict]:
    """Trecho citado vira BLOCO (F13b). Antes, a evidência documental só chegava ao cliente se o
    modelo resolvesse reproduzi-la na prosa — o que é sorte, não evidência."""
    documentos = out.get("documentos")
    if not isinstance(documentos, list) or not documentos:
        return []
    itens = [{"titulo": d.get("titulo"), "publisher": d.get("publisher"), "publicado_em": d.get("publicado_em"),
              "url": d.get("url"), "trecho": d.get("trecho")}
             for d in documentos if isinstance(d, dict) and d.get("trecho")]
    if not itens:
        return []
    ev = out.get("evidencia_documental") or {}
    prov = {"fonte": ev.get("fonte") or out.get("fonte", ""), "as_of": ev.get("as_of"), "cutoff_date": None,
            "n": ev.get("n_documentos") or len(itens), "metodo": ev.get("metodo", ""),
            "premissas": {}, "avisos": list(ev.get("avisos") or []), "lacunas": 0}
    if not prov["fonte"]:
        return []                       # regra da F11: sem fonte, sem bloco
    titulo = "O que o emissor publicou" if len(itens) == 1 else "O que os emissores publicaram"
    return [_bloco("citacao", eid, 1, titulo, {"itens": itens}, prov, NOTA_DOCUMENTO,
                   subtitulo=out.get("termo") or None)]


def _expectativas(out: dict, eid: str, max_pontos: int) -> list[dict]:
    """Focus: mediana por horizonte. `pct` porque o BCB publica em pontos percentuais (13,75), não fração."""
    horizontes = out.get("horizontes")
    if not isinstance(horizontes, list) or not horizontes:
        return []
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente", True):
        return []                                   # regra da F11: evidência insuficiente, sem bloco
    prov = _prov_evidencia(ev)
    itens = [{"rotulo": str(h.get("referencia")), "valor": h.get("mediana"),
              "detalhe": f"{h.get('respondentes')} respondentes" if _num(h.get("respondentes")) is not None else ""}
             for h in horizontes if _num(h.get("mediana")) is not None]
    if not itens:
        return []
    return [_bloco("barras", eid, 1, f"O que o mercado projeta · {out.get('indicador', '')}".strip(" ·"),
                   {"itens": itens, "formato": "pct"}, prov, NOTA_MERCADO,
                   subtitulo=f"coleta de {out.get('data_coleta', '')} · janela: {out.get('janela', '')}")]


def _cenarios(out: dict, eid: str, titulo: str, alvo_chave: str, alvo_rotulo: str) -> list[dict]:
    cen = out.get("cenarios")
    if not isinstance(cen, dict):
        return []
    rf, rv = cen.get("renda_fixa"), cen.get("renda_variavel")
    if not isinstance(rf, dict) or not isinstance(rv, dict):
        return []
    prov = _prov_premissas(out, "premissas de política (retornos reais)", out.get("nota_metodo"))
    nomes = {"renda_fixa": "Renda fixa", "renda_variavel": "Renda variável"}
    blocos = []
    itens = [{"rotulo": nomes[k], "valor": c.get("valor_projetado_brl"), "detalhe": f"retorno real {c.get('retorno_real_aa', 0) * 100:.1f}% a.a."}
             for k, c in (("renda_fixa", rf), ("renda_variavel", rv)) if _num(c.get("valor_projetado_brl")) is not None]
    if itens:
        dados = {"itens": itens, "formato": "brl"}
        if _num(out.get(alvo_chave)) is not None:
            dados["referencia"] = {"rotulo": alvo_rotulo, "valor": out[alvo_chave]}
        blocos.append(_bloco("barras", eid, 1, titulo, dados, prov, NOTA_SIMULACAO))
    itens2 = [{"rotulo": nomes[k], "valor": c.get("aporte_necessario_brl"), "detalhe": "aporte mensal necessário"}
              for k, c in (("renda_fixa", rf), ("renda_variavel", rv)) if _num(c.get("aporte_necessario_brl")) is not None]
    if itens2:
        dados2 = {"itens": itens2, "formato": "brl"}
        ref = out.get("capacidade_mensal_brl") if _num(out.get("capacidade_mensal_brl")) is not None else out.get("aporte_considerado_brl")
        if _num(ref) is not None:
            dados2["referencia"] = {"rotulo": "capacidade mensal" if _num(out.get("capacidade_mensal_brl")) is not None else "aporte considerado", "valor": ref}
        blocos.append(_bloco("barras", eid, 2, "Aporte necessário por cenário", dados2, prov, NOTA_SIMULACAO))
    return blocos


def _projecao(out: dict, eid: str, max_pontos: int) -> list[dict]:
    return _cenarios(out, eid, "Valor projetado no prazo", "valor_alvo_brl", "objetivo")


def _aposentadoria(out: dict, eid: str, max_pontos: int) -> list[dict]:
    return _cenarios(out, eid, "Patrimônio projetado na idade-alvo", "patrimonio_necessario_brl", "patrimônio necessário")


def _custo_fundo(out: dict, eid: str, max_pontos: int) -> list[dict]:
    if _num(out.get("custo_adm_total_estimado_brl")) is None:
        return []
    prov = _prov_premissas(out, f"taxa: {out.get('fonte', '')}", out.get("metodo"))
    blocos = [_bloco("indicadores", eid, 1, f"Custo estimado · {out.get('descricao', '')}".strip(), {"itens": [
        {"rotulo": "Custo estimado no horizonte", "valor": out["custo_adm_total_estimado_brl"], "formato": "brl"},
        {"rotulo": "Taxa de administração", "valor": out.get("taxa_adm_aa"), "formato": "pct_fracao"},
        *([{"rotulo": "Referência da classe", "valor": out["referencia_classe_aa"], "formato": "pct_fracao", "detalhe": out.get("classe") or ""}]
          if _num(out.get("referencia_classe_aa")) is not None else [])]}, prov, NOTA_SIMULACAO)]
    if _num(out.get("referencia_classe_aa")) is not None and _num(out.get("taxa_adm_aa")) is not None:
        blocos.append(_bloco("barras", eid, 2, "Taxa do produto × referência da classe", {
            "itens": [{"rotulo": out.get("descricao") or "produto", "valor": out["taxa_adm_aa"],
                       **({"destaque": "desvio"} if out.get("acima_da_referencia") else {})}],
            "referencia": {"rotulo": f"referência {out.get('classe') or ''}".strip(), "valor": out["referencia_classe_aa"]},
            "formato": "pct_fracao"}, prov, NOTA_SIMULACAO))
    return blocos


def _comparar(out: dict, eid: str, max_pontos: int) -> list[dict]:
    produtos = out.get("produtos")
    if not isinstance(produtos, list) or not produtos:
        return []
    prov = _prov_premissas(out, "taxas informadas ou do catálogo", out.get("metodo"))
    chaves = ("descricao", "classe", "taxa_adm_aa", "custo_adm_total_estimado_brl", "referencia_classe_aa", "liquidez_dias", "come_cotas", "compativel_com_vetos")
    blocos = [_bloco("tabela", eid, 1, "Alternativas lado a lado (sem ranking)", {
        "colunas": [{"chave": "descricao", "rotulo": "Produto"}, {"chave": "classe", "rotulo": "Classe"},
                    {"chave": "taxa_adm_aa", "rotulo": "Taxa a.a.", "formato": "pct_fracao"},
                    {"chave": "custo_adm_total_estimado_brl", "rotulo": "Custo estimado", "formato": "brl"},
                    {"chave": "referencia_classe_aa", "rotulo": "Referência", "formato": "pct_fracao"},
                    {"chave": "liquidez_dias", "rotulo": "Liquidez (dias)"}, {"chave": "come_cotas", "rotulo": "Come-cotas", "formato": "bool"},
                    {"chave": "compativel_com_vetos", "rotulo": "Compatível com seus vetos", "formato": "bool"}],
        "linhas": [{k: p.get(k) for k in chaves} for p in produtos]},
        prov, NOTA_SIMULACAO, subtitulo=f"R$ {out.get('valor_aplicado_brl', 0):,.0f} por {out.get('horizonte_anos')} anos".replace(",", "."))]
    itens = [{"rotulo": p.get("descricao") or "produto", "valor": p.get("custo_adm_total_estimado_brl"),
              **({"destaque": "desvio"} if p.get("acima_da_referencia") else {}),
              **({"detalhe": "incompatível com um veto seu"} if p.get("compativel_com_vetos") is False else {})}
             for p in produtos if _num(p.get("custo_adm_total_estimado_brl")) is not None]
    if itens:
        blocos.append(_bloco("barras", eid, 2, "Custo estimado no horizonte", {"itens": itens, "formato": "brl"}, prov, NOTA_SIMULACAO))
    return blocos


# ------------------------------------------------------------------ analista
def _serie_de_pontos(pontos: Any) -> list[dict[str, Any]]:
    if not isinstance(pontos, list):
        return []
    return [{"x": p.get("data"), "y": p.get("valor")} for p in pontos if _num(p.get("valor")) is not None]


def _serie_precos(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    pontos = _serie_de_pontos(out.get("pontos"))
    if not pontos:
        return []
    prov = _prov_evidencia(ev)
    pontos, amostrada = _amostrar(pontos, max_pontos)
    if amostrada and "serie_amostrada" not in prov["avisos"]:
        prov["avisos"].append("serie_amostrada")
    ticker = out.get("ticker", "")
    blocos = [_bloco("serie", eid, 1, f"Fechamentos · {ticker}", {"series": [{"nome": ticker, "pontos": pontos}], "eixo_y": {"formato": "brl"}, "empilhada": False},
                     prov, NOTA_MERCADO, subtitulo=f"{pontos[0]['x']} a {pontos[-1]['x']}")]
    itens = []
    if isinstance(out.get("primeiro"), dict):
        itens.append({"rotulo": "Primeiro fechamento", "valor": out["primeiro"].get("valor"), "formato": "brl", "detalhe": out["primeiro"].get("data")})
    if isinstance(out.get("ultimo"), dict):
        itens.append({"rotulo": "Último fechamento", "valor": out["ultimo"].get("valor"), "formato": "brl", "detalhe": out["ultimo"].get("data")})
    if itens:
        blocos.append(_bloco("indicadores", eid, 2, "Pontas da série", {"itens": itens}, prov, NOTA_MERCADO))
    return blocos


def _historico_comparado(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    series_entrada = out.get("series")
    if not isinstance(series_entrada, list) or not series_entrada:
        return []
    series = []
    amostrada = False
    for serie in series_entrada[:2]:
        pontos = [{"x": p.get("data"), "y": p.get("indice"), "valor_original": p.get("valor_original"),
                   "variacao_pct": p.get("variacao_pct")}
                  for p in (serie.get("pontos") or []) if _num(p.get("indice")) is not None]
        pontos, reduziu = _amostrar(pontos, max_pontos)
        amostrada = amostrada or reduziu
        series.append({"nome": serie.get("nome") or "série", "papel": serie.get("papel"), "pontos": pontos})
    prov = _prov_evidencia(ev)
    if amostrada and "serie_amostrada" not in prov["avisos"]:
        prov["avisos"].append("serie_amostrada")
    ticker = str(out.get("ticker") or "").upper()
    benchmark = str(out.get("benchmark") or "BOVA11").upper()
    periodo = out.get("periodo") or "1a"
    dados = {
        "series": series,
        "eixo_y": {"formato": "indice_base_100", "unidade": "base 100"},
        "empilhada": False,
        "consulta": {"ticker": ticker, "benchmark": benchmark, "periodo": periodo,
                     "periodos": ["1m", "3m", "1a", "5a", "tudo"],
                     "cutoff_date": ev.get("cutoff_date"), "interativa": True},
        "resumo": out.get("resumo") or {},
    }
    return [_bloco("serie", eid, 1, f"Desempenho comparado · {ticker}", dados, prov, NOTA_MERCADO,
                   subtitulo=f"{out.get('de')} a {out.get('ate')} · base 100 · referência {benchmark}")]


def _serie_indice(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    pontos = _serie_de_pontos(out.get("pontos"))
    if not pontos:
        return []
    prov = _prov_evidencia(ev)
    pontos, amostrada = _amostrar(pontos, max_pontos)
    if amostrada and "serie_amostrada" not in prov["avisos"]:
        prov["avisos"].append("serie_amostrada")
    unidade = out.get("unidade") or ""
    formato = "pct" if unidade.startswith("taxa") or unidade == "percentual" else "numero"
    nome = str(out.get("indice", "")).upper()
    blocos = [_bloco("serie", eid, 1, f"{nome} · {unidade}".strip(" ·"), {"series": [{"nome": nome, "pontos": pontos}], "eixo_y": {"formato": formato, "unidade": unidade}, "empilhada": False},
                     prov, NOTA_MERCADO, subtitulo=f"{pontos[0]['x']} a {pontos[-1]['x']}")]
    if _num(out.get("acumulado_periodo_pct")) is not None:
        blocos.append(_bloco("indicadores", eid, 2, "Acumulado no período", {"itens": [{"rotulo": f"{nome} acumulado", "valor": out["acumulado_periodo_pct"], "formato": "pct"}]}, prov, NOTA_MERCADO))
    return blocos


def _retorno_vol(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    itens = [(r, out.get(k)) for r, k in (("Retorno acumulado", "retorno_acumulado_pct"), ("Retorno anualizado", "retorno_anualizado_pct"),
                                          ("Volatilidade anualizada", "vol_anualizada_pct"),
                                          ("Downside deviation anualizada (alvo periódico 0%)", "downside_deviation_anualizada_pct"),
                                          ("Máximo drawdown", "max_drawdown_pct"))]
    itens = [{"rotulo": r, "valor": v, "formato": "pct"} for r, v in itens if _num(v) is not None]
    drawdown = out.get("drawdown") or {}
    duration = _num(drawdown.get("duration_intervals"))
    recovery = _num(drawdown.get("recovery_intervals"))
    if duration is not None:
        itens.append({"rotulo": "Duração do pior drawdown", "valor": duration, "formato": "numero",
                      "detalhe": "intervalos observados"})
    if recovery is not None:
        itens.append({"rotulo": "Recuperação após o fundo", "valor": recovery, "formato": "numero",
                      "detalhe": "intervalos observados"})
    if not itens:
        return []
    per = out.get("periodo") or {}
    nota = NOTA_MERCADO
    if duration is not None:
        nota += " Duração e recuperação de drawdown são contadas em intervalos observados, não em dias corridos."
    return [_bloco("indicadores", eid, 1, f"Risco e retorno histórico · {out.get('ticker', '')}".strip(), {"itens": itens}, _prov_evidencia(ev), nota,
                   subtitulo=f"{per.get('de')} a {per.get('ate')} · {per.get('n')} pregões" if per else None)]


def _correlacao(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente") or _num(out.get("correlacao")) is None:
        return []
    prov = _prov_evidencia(ev)
    nota = "Correlação não é causalidade nem previsão. " + NOTA_MERCADO
    return [
        _bloco("progresso", eid, 1, f"Correlação · {out.get('par', '')}".strip(), {"valor": out["correlacao"], "minimo": -1, "maximo": 1, "formato": "numero",
                                                                                 "marcas": [{"rotulo": "sem relação", "valor": 0}]}, prov, nota),
        _bloco("indicadores", eid, 2, "Base da correlação", {"itens": [
            {"rotulo": "Coeficiente (Pearson)", "valor": out["correlacao"], "formato": "numero"},
            {"rotulo": "Pares alinhados", "valor": out.get("n_pares"), "formato": "inteiro"},
            {"rotulo": "Defasagem", "valor": out.get("defasagem_dias"), "formato": "dias"}]}, prov, nota),
    ]


def _dependencia(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    coef = _num(out.get("coeficiente"))
    if not ev.get("suficiente") or coef is None:
        return []
    prov = _prov_evidencia(ev)
    nota = "Dependência estatística não é causalidade nem previsão. " + NOTA_MERCADO
    metodo = str(out.get("metodo") or "").capitalize() or "Dependência"
    lag = out.get("defasagem_observacoes")
    return [
        _bloco("progresso", eid, 1, f"Dependência · {out.get('par', '')}".strip(),
               {"valor": coef, "minimo": -1, "maximo": 1, "formato": "numero",
                "marcas": [{"rotulo": "sem associação", "valor": 0}]}, prov, nota),
        _bloco("indicadores", eid, 2, "Base da dependência", {"itens": [
            {"rotulo": f"Coeficiente ({metodo})", "valor": coef, "formato": "numero"},
            {"rotulo": "Pares alinhados", "valor": out.get("n_pares"), "formato": "inteiro"},
            {"rotulo": "Defasagem", "valor": lag, "formato": "inteiro", "detalhe": "observações comuns"},
        ]}, prov, nota),
    ]



def _analise_condicional(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    n_cond = out.get("n_condicional")
    n_total = out.get("n_total")
    cond = out.get("condicional") or {}
    media = _num(cond.get("media_pct"))
    if not isinstance(n_cond, int) or n_cond <= 0 or media is None:
        return []
    prov = _prov_evidencia(ev)
    nota = ("Comparação histórica condicional, sem teste de significância e sem inferência causal. "
            + NOTA_MERCADO)
    direcao = "alta" if out.get("direcao") == "alta" else "queda"
    itens = [
        {"rotulo": "Retorno médio condicional", "valor": media, "formato": "pct"},
        {"rotulo": "Retorno mediano condicional", "valor": cond.get("mediana_pct"), "formato": "pct"},
        {"rotulo": "Períodos positivos", "valor": cond.get("taxa_positiva_pct"), "formato": "pct"},
        {"rotulo": "Retorno médio da base", "valor": (out.get("base") or {}).get("media_pct"), "formato": "pct"},
        {"rotulo": "Diferença das médias", "valor": out.get("diferenca_media_pct_pontos"), "formato": "pct"},
        {"rotulo": "Amostra condicional", "valor": n_cond, "formato": "inteiro"},
    ]
    itens = [item for item in itens if _num(item.get("valor")) is not None]
    return [_bloco(
        "indicadores", eid, 1,
        f"{out.get('ticker', '')} quando {out.get('condicionante', '')} está em {direcao}".strip(),
        {"itens": itens}, prov, nota,
        subtitulo=f"{n_cond} de {n_total} intervalos" if isinstance(n_total, int) else None,
    )]

def _sensibilidade(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    estimate = out.get("sensibilidade") or {}
    beta = _num(estimate.get("estimate"))
    if beta is None:
        return []
    prov = _prov_evidencia(ev)
    nota = ("Associação linear histórica estimada por OLS com incerteza HAC/Newey-West; "
            "não implica causalidade nem previsão. " + NOTA_MERCADO)
    ci = estimate.get("confidence_interval") or {}
    unit = estimate.get("unit")
    detalhe = ("p.p. de retorno por 1 p.p. do driver"
               if unit == "pct_return_per_percentage_point"
               else "p.p. de retorno por 1 p.p. de retorno do driver")
    itens = [
        {"rotulo": "Sensibilidade estimada", "valor": beta, "formato": "numero", "detalhe": detalhe},
        {"rotulo": "Limite inferior do IC", "valor": ci.get("lower"), "formato": "numero"},
        {"rotulo": "Limite superior do IC", "valor": ci.get("upper"), "formato": "numero"},
        {"rotulo": "R²", "valor": (_num(out.get("r_squared")) * 100.0
                                      if _num(out.get("r_squared")) is not None else None), "formato": "pct"},
        {"rotulo": "Pares usados", "valor": out.get("n"), "formato": "inteiro"},
        {"rotulo": "Lags HAC", "valor": out.get("hac_lags"), "formato": "inteiro"},
    ]
    itens = [item for item in itens if _num(item.get("valor")) is not None]
    return [_bloco(
        "indicadores", eid, 1,
        f"Sensibilidade histórica · {out.get('ticker', '')} × {out.get('driver', '')}".strip(),
        {"itens": itens}, prov, nota,
        subtitulo=f"IC {float(out.get('confidence_level', 0.95))*100:.0f}% · {out.get('covariance_method', '')}",
    )]


def _regimes(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    groups = out.get("grupos") or []
    if not isinstance(groups, list) or len(groups) != 2:
        return []
    prov = _prov_evidencia(ev)
    nota = ("Comparação histórica por regimes explícitos; não implica causalidade, previsão nem mudança estrutural. "
            + NOTA_MERCADO)
    itens: list[dict] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        label = str(group.get("rotulo") or "regime").capitalize()
        for suffix, key, formato in (
            ("retorno médio", "media_pct", "pct"),
            ("volatilidade amostral", "desvio_amostral_pct", "pct"),
            ("períodos positivos", "taxa_positiva_pct", "pct"),
            ("observações", "n", "inteiro"),
        ):
            value = group.get(key)
            if _num(value) is not None:
                itens.append({"rotulo": f"{label} · {suffix}", "valor": value, "formato": formato})
    if _num(out.get("diferenca_media_pct_pontos")) is not None:
        itens.append({"rotulo": "Diferença das médias (regime 1 − regime 2)",
                      "valor": out.get("diferenca_media_pct_pontos"), "formato": "pct"})
    if not itens:
        return []
    criterio = "nível alto/baixo" if out.get("criterio") == "level" else "direção alta/queda"
    threshold = out.get("limiar_usado")
    source = out.get("origem_limiar")
    subtitle_parts = [criterio]
    if _num(threshold) is not None:
        subtitle_parts.append(f"corte {threshold:g}")
    if source == "sample_median":
        subtitle_parts.append("mediana retrospectiva da amostra")
    return [_bloco(
        "indicadores", eid, 1,
        f"Regimes históricos · {out.get('ticker', '')} × {out.get('driver', '')}".strip(),
        {"itens": itens}, prov, nota,
        subtitulo=" · ".join(subtitle_parts),
    )]


def _event_study(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    ar = out.get("ar")
    if not isinstance(ar, list) or not ar:
        return []
    prov = _prov_evidencia(ev)
    nota = "Descreve o que aconteceu na janela; não infere significância nem projeta reação futura. " + NOTA_MERCADO
    acumulado, car = 0.0, []
    for p in ar:
        if _num(p.get("ar_pct")) is None:
            continue
        acumulado += p["ar_pct"]
        car.append({"x": p.get("data"), "y": acumulado})
    evento = out.get("data_evento_efetiva") or out.get("data_evento")
    blocos = [_bloco("serie", eid, 1, f"Retorno anormal acumulado (CAR) · {out.get('ticker', '')}".strip(), {
        "series": [{"nome": "CAR", "pontos": car}], "eixo_y": {"formato": "pct"}, "empilhada": False,
        **({"anotacao": {"x": evento, "rotulo": "evento"}} if evento else {})}, prov, nota,
        subtitulo=f"benchmark {out.get('benchmark', '')} · método {out.get('metodo', '')}")]
    blocos.append(_bloco("barras", eid, 2, "Retorno anormal por pregão", {
        "itens": [{"rotulo": p.get("data"), "valor": p.get("ar_pct"), **({"destaque": "referencia"} if p.get("data") == evento else {})}
                  for p in ar if _num(p.get("ar_pct")) is not None], "formato": "pct"}, prov, nota))
    return blocos


def _event_study_v2(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    ar = out.get("ar")
    if not isinstance(ar, list) or not ar:
        return []
    prov = _prov_evidencia(ev)
    nota = ("Estudo histórico de evento; AR/CAR não provam causalidade nem preveem reação futura. "
            "Quando há intervalo de confiança, ele usa hipóteses clássicas explícitas e não é um rótulo automático de significância. "
            + NOTA_MERCADO)
    evento = out.get("data_evento_efetiva") or out.get("data_evento")
    blocks: list[dict] = []

    itens = []
    if _num(out.get("car_pct")) is not None:
        itens.append({"rotulo": "CAR", "valor": out.get("car_pct"), "formato": "pct"})
    if _num(out.get("desvio_residuos_pct")) is not None:
        itens.append({"rotulo": "Desvio dos resíduos", "valor": out.get("desvio_residuos_pct"), "formato": "pct"})
    estimate = out.get("car_estimate") or {}
    ci = estimate.get("confidence_interval") if isinstance(estimate, dict) else None
    if isinstance(ci, dict):
        if _num(ci.get("lower")) is not None:
            itens.append({"rotulo": "Intervalo de confiança · limite inferior", "valor": ci.get("lower"), "formato": "pct"})
        if _num(ci.get("upper")) is not None:
            itens.append({"rotulo": "Intervalo de confiança · limite superior", "valor": ci.get("upper"), "formato": "pct"})
    if itens:
        blocks.append(_bloco(
            "indicadores", eid, 1,
            f"Estudo de evento · {out.get('ticker', '')}".strip(),
            {"itens": itens}, prov, nota,
            subtitulo=f"benchmark {out.get('benchmark', '')} · método {out.get('metodo', '')}",
        ))

    acumulado, car = 0.0, []
    for p in ar:
        if _num(p.get("ar_pct")) is None:
            continue
        acumulado += p["ar_pct"]
        car.append({"x": p.get("data"), "y": acumulado})
    if car:
        blocks.append(_bloco(
            "serie", eid, len(blocks) + 1,
            f"Retorno anormal acumulado (CAR) · {out.get('ticker', '')}".strip(),
            {"series": [{"nome": "CAR", "pontos": car}], "eixo_y": {"formato": "pct"}, "empilhada": False,
             **({"anotacao": {"x": evento, "rotulo": "evento"}} if evento else {})},
            prov, nota,
        ))
    blocks.append(_bloco(
        "barras", eid, len(blocks) + 1, "Retorno anormal por observação",
        {"itens": [{"rotulo": p.get("data"), "valor": p.get("ar_pct"),
                    **({"destaque": "referencia"} if p.get("data") == evento else {})}
                   for p in ar if _num(p.get("ar_pct")) is not None], "formato": "pct"},
        prov, nota,
    ))
    return blocks



def _composicao_indice(out: dict, eid: str, max_pontos: int) -> list[dict]:
    rows = out.get("componentes")
    if not isinstance(rows, list) or not rows:
        return []
    raw_prov = out.get("provenance") or {}
    raw_warnings = list(raw_prov.get("warnings") or [])
    fixed = [
        warning for warning in raw_warnings
        if not str(warning).startswith("ticker_fora_da_carteira:")
    ]
    avisos = _avisos(fixed)
    for warning in raw_warnings:
        text_warning = str(warning)
        if text_warning.startswith("ticker_fora_da_carteira:"):
            ticker = text_warning.split(":", 1)[1]
            avisos.append(
                f"{ticker} não aparece no snapshot oficial de composição selecionado."
            )

    linhas = []
    for row in rows[:max_pontos]:
        if not isinstance(row, dict):
            continue
        peso = _num(row.get("peso_pct"))
        if not row.get("ticker") or peso is None:
            continue
        linhas.append({
            "ticker": row.get("ticker"),
            "nome": row.get("nome"),
            "peso_pct": peso,
            "quantidade_teorica": row.get("quantidade_teorica"),
        })
    if not linhas:
        return []
    if len(rows) > len(linhas):
        frase = "A apresentação foi reduzida para caber no bloco; os pesos não foram recalculados."
        if frase not in avisos:
            avisos.append(frase)

    prov = {
        "fonte": ",".join(raw_prov.get("source_codes") or ["market"]),
        "as_of": raw_prov.get("reference_date") or out.get("data_carteira"),
        "cutoff_date": raw_prov.get("cutoff_date"),
        "n": out.get("n_componentes_total"),
        "metodo": raw_prov.get("temporal_semantics") or "official_index_snapshot",
        "premissas": {
            "membership": "snapshot_oficial_persistido",
            "peso": "peso_oficial_sem_recalculo",
        },
        "avisos": list(dict.fromkeys(avisos)),
        "lacunas": sum(
            str(w).startswith("ticker_fora_da_carteira:") for w in raw_warnings
        ),
    }
    indice = str(out.get("indice") or "").upper()
    data_carteira = out.get("data_carteira")
    total = out.get("n_componentes_total")
    peso_total = _num(out.get("peso_total_pct"))
    detalhes = []
    if total is not None:
        detalhes.append(f"{total} componentes")
    if peso_total is not None:
        detalhes.append(f"peso total {peso_total:.3f}%")
    subtitulo = " · ".join(
        [str(data_carteira)] + detalhes if data_carteira else detalhes
    ) or None
    nota = (
        "Carteira oficial do índice em snapshot persistido; pesos e quantidades são fatos da fonte. "
        "Não há inferência de membership em datas sem snapshot, nem análise de carteira do cliente, "
        "ranking de atratividade ou recomendação. " + NOTA_MERCADO
    )
    return [_bloco(
        "tabela", eid, 1, f"Composição oficial · {indice}".strip(),
        {"colunas": [
            {"chave": "ticker", "rotulo": "Ticker"},
            {"chave": "nome", "rotulo": "Empresa"},
            {"chave": "peso_pct", "rotulo": "Peso (%)"},
            {"chave": "quantidade_teorica", "rotulo": "Quantidade teórica"},
        ], "linhas": linhas},
        prov,
        nota,
        subtitulo=subtitulo,
    )]

def _curva_juros(out: dict, eid: str, max_pontos: int) -> list[dict]:
    pontos = out.get("pontos")
    if not isinstance(pontos, list) or not pontos:
        return []
    curva = str(out.get("curva") or "")
    labels = {
        "ettj_pre": "ETTJ prefixada",
        "ettj_ipca": "ETTJ IPCA",
        "inflacao_implicita": "Inflação implícita",
    }
    serie = [
        {"x": p.get("vertice_du"), "y": p.get("taxa_pct_aa_252")}
        for p in pontos
        if isinstance(p, dict) and _num(p.get("vertice_du")) is not None
        and _num(p.get("taxa_pct_aa_252")) is not None
    ]
    if not serie:
        return []
    raw_prov = out.get("provenance") or {}
    raw_warnings = list(raw_prov.get("warnings") or [])
    fixed = [w for w in raw_warnings if not str(w).startswith("vertice_ettj_indisponivel:")]
    avisos = _avisos(fixed)
    for warning in raw_warnings:
        text_warning = str(warning)
        if text_warning.startswith("vertice_ettj_indisponivel:"):
            du = text_warning.split(":", 1)[1]
            avisos.append(
                f"O vértice exato de {du} d.u. não foi publicado nessa curva; nenhum valor aproximado foi usado."
            )
    prov = {
        "fonte": ",".join(raw_prov.get("source_codes") or ["anbima"]),
        "as_of": raw_prov.get("reference_date") or out.get("data_curva"),
        "cutoff_date": raw_prov.get("cutoff_date"),
        "n": out.get("n_vertices_retornados"),
        "metodo": raw_prov.get("temporal_semantics") or "official_vertices_no_interpolation",
        "premissas": {"day_count": "du_252", "interpolacao": False, "extrapolacao": False},
        "avisos": list(dict.fromkeys(avisos)),
        "lacunas": sum(str(w).startswith("vertice_ettj_indisponivel:") for w in raw_warnings),
    }
    nota = (
        "Curva oficial ANBIMA de fechamento, em vértices publicados e % a.a./252 d.u.; "
        "não há interpolação, extrapolação, previsão, choque, duration/DV01, fair value ou recomendação."
    )
    label = labels.get(curva, curva or "Curva de juros")
    data_curva = out.get("data_curva")
    if len(serie) <= 20:
        return [_bloco(
            "tabela", eid, 1, f"{label} oficial",
            {"colunas": [
                {"chave": "vertice_du", "rotulo": "Vértice (d.u.)"},
                {"chave": "taxa_pct_aa_252", "rotulo": "Taxa (% a.a.)"},
            ], "linhas": [
                {"vertice_du": p["x"], "taxa_pct_aa_252": p["y"]} for p in serie
            ]},
            prov, nota, subtitulo=str(data_curva) if data_curva else None,
        )]
    sampled, reduziu = _amostrar(serie, max_pontos)
    if reduziu:
        frase = AVISOS_CLIENTE["serie_amostrada"]
        if frase not in prov["avisos"]:
            prov["avisos"].append(frase)
    return [_bloco(
        "serie", eid, 1, f"{label} oficial",
        {
            "series": [{"nome": label, "pontos": sampled}],
            "eixo_x": {"formato": "inteiro", "unidade": "dias úteis"},
            "eixo_y": {"formato": "pct", "unidade": out.get("unidade") or "% a.a./252 d.u."},
            "empilhada": False,
        },
        prov, nota, subtitulo=str(data_curva) if data_curva else None,
    )]


# ------------------------------------------------------------------ FQ5 · fundamentos, valuation e cenários de mercado
def _fundamentos_empresa(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    rows = out.get("fundamentos")
    if not isinstance(rows, list) or not rows:
        return []
    linhas = []
    for row in rows[:max_pontos]:
        if not isinstance(row, dict) or _num(row.get("value")) is None:
            continue
        unidade = row.get("value_unit") or ""
        valor = row.get("value")
        if unidade == "brl":
            formato = "brl"
        elif unidade == "percent":
            formato = "pct"
        else:
            formato = "numero"
        linhas.append({
            "metrica": row.get("metric"),
            "valor": valor,
            "formato": formato,
            "unidade": unidade,
            "referencia": row.get("reference_date"),
            "disponivel_em": row.get("availability_date"),
            "classe": row.get("instrument_id"),
        })
    if not linhas:
        return []
    prov = _prov_evidencia(ev)
    nota = ("Fundamentos point-in-time: entram apenas vintages já disponíveis no cutoff; unidade raw não entra em valuation. "
            + NOTA_MERCADO)
    return [_bloco(
        "tabela", eid, 1, f"Fundamentos disponíveis · {out.get('ticker', '')}".strip(),
        {"colunas": [
            {"chave": "metrica", "rotulo": "Métrica"},
            {"chave": "valor", "rotulo": "Valor"},
            {"chave": "unidade", "rotulo": "Unidade"},
            {"chave": "referencia", "rotulo": "Referência"},
            {"chave": "disponivel_em", "rotulo": "Disponível em"},
        ], "linhas": linhas}, prov, nota,
        subtitulo=str(out.get("periodo") or "último DFP anual disponível no cutoff"),
    )]


def _tendencias_fundamentais(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    metrics = out.get("metricas")
    if not isinstance(metrics, list) or not metrics:
        return []
    labels = {
        "revenue": "Receita",
        "ebitda": "EBITDA",
        "net_income": "Lucro líquido",
        "total_equity": "Patrimônio líquido",
        "cash_and_equivalents": "Caixa e equivalentes",
        "gross_debt": "Dívida bruta",
        "net_debt": "Dívida líquida",
        "free_cash_flow": "Fluxo de caixa livre",
    }
    linhas = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        latest = _num(metric.get("latest_value"))
        if latest is None:
            continue
        linhas.append({
            "metrica": labels.get(str(metric.get("metric")), metric.get("metric")),
            "atual": latest,
            "anterior": metric.get("previous_value"),
            "variacao_abs": metric.get("absolute_change"),
            "crescimento_pct": metric.get("growth_pct"),
        })
    if not linhas:
        return []
    prov = _prov_evidencia(ev)
    nota = (
        "Tendência fundamental point-in-time sobre DFP anual: cada período usa somente o último vintage "
        "que já estava disponível no cutoff. Crescimento percentual só é mostrado com base anterior positiva; "
        "não há ITR, forecast, CAGR ou fair value. " + NOTA_MERCADO
    )
    blocks = [_bloco(
        "tabela", eid, 1, f"Tendências fundamentais · {out.get('ticker', '')}".strip(),
        {"colunas": [
            {"chave": "metrica", "rotulo": "Métrica"},
            {"chave": "atual", "rotulo": "Atual"},
            {"chave": "anterior", "rotulo": "Anterior"},
            {"chave": "variacao_abs", "rotulo": "Variação"},
            {"chave": "crescimento_pct", "rotulo": "Crescimento"},
        ], "linhas": linhas}, prov, nota,
        subtitulo="DFP anual · comparação com o período anterior",
    )]

    margins = out.get("margens")
    if isinstance(margins, list):
        series = []
        margin_labels = {"ebitda_margin": "Margem EBITDA", "net_margin": "Margem líquida"}
        for margin in margins:
            if not isinstance(margin, dict):
                continue
            points = margin.get("points")
            if not isinstance(points, list):
                continue
            compact = [
                {"x": p.get("reference_date"), "y": p.get("value_pct")}
                for p in points[-max_pontos:]
                if isinstance(p, dict) and _num(p.get("value_pct")) is not None
            ]
            if compact:
                series.append({"nome": margin_labels.get(str(margin.get("margin")), margin.get("margin")), "pontos": compact})
        if series:
            blocks.append(_bloco(
                "serie", eid, 2, "Evolução das margens anuais",
                {"series": series, "eixo_y": {"formato": "pct"}, "empilhada": False},
                prov, nota,
            ))
    return blocks


def _valor_mercado(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    prov = _prov_evidencia(ev)
    nota = ("Market cap, EV e múltiplos são medidas de precificação observada; não são valor intrínseco, fair value ou recomendação. "
            + NOTA_MERCADO)
    itens = []
    for label, key, formato in (
        ("Preço da classe consultada", "requested_price_brl", "brl"),
        ("Valor de mercado", "market_cap_brl", "brl"),
        ("Dívida líquida", "net_debt_brl", "brl"),
        ("Enterprise value (EV)", "enterprise_value_brl", "brl"),
    ):
        if _num(out.get(key)) is not None:
            itens.append({"rotulo": label, "valor": out.get(key), "formato": formato})
    multiples = out.get("multiples") or {}
    for label, key, formato in (
        ("P/L", "pe", "numero"),
        ("EV/EBITDA", "ev_ebitda", "numero"),
        ("P/VP", "price_to_book", "numero"),
        ("FCF yield", "fcf_yield_pct", "pct"),
    ):
        if _num(multiples.get(key)) is not None:
            itens.append({"rotulo": label, "valor": multiples.get(key), "formato": formato})
    blocks = []
    if itens:
        blocks.append(_bloco(
            "indicadores", eid, 1, f"Precificação de mercado · {out.get('ticker', '')}".strip(),
            {"itens": itens}, prov, nota,
            subtitulo=(f"fechamento {out.get('requested_price_date')}" if out.get("requested_price_date") else None),
        ))
    classes = out.get("classes")
    if isinstance(classes, list) and len(classes) > 1:
        linhas = []
        for row in classes[:max_pontos]:
            if not isinstance(row, dict):
                continue
            linhas.append({
                "ticker": row.get("ticker"),
                "preco": row.get("price_brl"),
                "acoes": row.get("shares_outstanding"),
                "valor_mercado": row.get("market_value_brl"),
                "data": row.get("price_date"),
            })
        if linhas:
            blocks.append(_bloco(
                "tabela", eid, len(blocks) + 1, "Classes consideradas no valor de mercado",
                {"colunas": [
                    {"chave": "ticker", "rotulo": "Classe"},
                    {"chave": "preco", "rotulo": "Preço"},
                    {"chave": "acoes", "rotulo": "Ações"},
                    {"chave": "valor_mercado", "rotulo": "Valor de mercado"},
                    {"chave": "data", "rotulo": "Data"},
                ], "linhas": linhas}, prov, nota,
            ))
    return blocks


def _comparaveis_setor(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    rows = out.get("comparacoes")
    if not isinstance(rows, list) or not rows:
        return []
    labels = {
        "market_cap_brl": "Valor de mercado",
        "pe": "P/L",
        "ev_ebitda": "EV/EBITDA",
        "price_to_book": "P/VP",
        "fcf_yield_pct": "FCF yield",
        "revenue_yoy_pct": "Crescimento da receita",
        "ebitda_yoy_pct": "Crescimento do EBITDA",
        "net_income_yoy_pct": "Crescimento do lucro líquido",
        "ebitda_margin_pct": "Margem EBITDA",
        "net_margin_pct": "Margem líquida",
    }
    linhas = []
    for row in rows[:max_pontos]:
        if not isinstance(row, dict):
            continue
        target = _num(row.get("target_value"))
        median = _num(row.get("median"))
        if target is None and median is None:
            continue
        linhas.append({
            "metrica": labels.get(str(row.get("metric")), row.get("metric")),
            "alvo": target,
            "mediana_pares": median,
            "diferenca": row.get("delta_target_vs_median"),
            "unidade": row.get("delta_unit") or row.get("unit"),
            "n": row.get("n_valid"),
        })
    if not linhas:
        return []
    prov = _prov_evidencia(ev)
    nota = (
        "Comparação descritiva company-level contra pares B3 do mesmo subsetor/setor. "
        "A mediana dos pares não é fair value, preço-alvo, ranking nem recomendação; missing não vira zero. "
        "Valuation, crescimento e margens reutilizam as medições canônicas existentes. " + NOTA_MERCADO
    )
    classificacao = out.get("classificacao")
    nivel = out.get("nivel")
    peer_count = out.get("peer_count_total")
    subtitulo = " · ".join(
        str(x) for x in (nivel, classificacao, f"{peer_count} pares" if peer_count is not None else None) if x
    )
    return [_bloco(
        "tabela", eid, 1, f"Comparáveis · {out.get('ticker', '')}".strip(),
        {"colunas": [
            {"chave": "metrica", "rotulo": "Métrica"},
            {"chave": "alvo", "rotulo": "Empresa"},
            {"chave": "mediana_pares", "rotulo": "Mediana dos pares"},
            {"chave": "diferenca", "rotulo": "Diferença vs mediana"},
            {"chave": "unidade", "rotulo": "Unidade"},
            {"chave": "n", "rotulo": "Pares válidos"},
        ], "linhas": linhas},
        prov,
        nota,
        subtitulo=subtitulo or None,
    )]


def _cenario_sensibilidade(out: dict, eid: str, max_pontos: int) -> list[dict]:
    ev = out.get("evidencia") or {}
    if not ev.get("suficiente"):
        return []
    base = _num(out.get("base_price_brl"))
    scenario = _num(out.get("scenario_price_brl"))
    impact = _num(out.get("impacto_incremental_pct"))
    if base is None or scenario is None or impact is None:
        return []
    prov = _prov_evidencia(ev)
    nota = ("Cenário linear associacional: slope histórico × choque explícito sobre o fechamento bruto. "
            "Não é previsão, causalidade, fair value nem preço-alvo. " + NOTA_MERCADO)
    itens = [
        {"rotulo": "Preço-base", "valor": base, "formato": "brl"},
        {"rotulo": "Choque no driver", "valor": out.get("choque_driver"), "formato": "numero",
         "detalhe": str(out.get("unidade_choque") or "")},
        {"rotulo": "Impacto incremental", "valor": impact, "formato": "pct"},
        {"rotulo": "Preço no cenário mecânico", "valor": scenario, "formato": "brl"},
    ]
    if _num(out.get("r_squared")) is not None:
        itens.append({"rotulo": "R² histórico", "valor": float(out["r_squared"]) * 100.0, "formato": "pct"})
    ci = out.get("scenario_price_interval_brl") or {}
    if _num(ci.get("lower")) is not None:
        itens.append({"rotulo": "Faixa do cenário · limite inferior", "valor": ci.get("lower"), "formato": "brl"})
    if _num(ci.get("upper")) is not None:
        itens.append({"rotulo": "Faixa do cenário · limite superior", "valor": ci.get("upper"), "formato": "brl"})
    return [_bloco(
        "indicadores", eid, 1,
        f"Cenário por sensibilidade · {out.get('ticker', '')} × {out.get('driver', '')}".strip(),
        {"itens": itens}, prov, nota,
        subtitulo=(f"preço-base em {out.get('base_price_date')} · {out.get('n', 0)} pares históricos"),
    )]


def _dependencia_macro(out: dict, eid: str, max_pontos: int) -> list[dict]:
    blocks = _dependencia(out, eid, max_pontos)
    if blocks:
        tipo = out.get("factor_type")
        codigo = out.get("factor_code")
        for block in blocks:
            if block.get("subtitulo") is None and codigo:
                block["subtitulo"] = f"fator {tipo}: {codigo}"
    return blocks


# ------------------------------------------------------------------ contexto (F14)
def _verificar_mudanca(out: dict, eid: str, max_pontos: int) -> list[dict]:
    """O card não é bloco: ele chega pelo evento `proposta`. O bloco aqui é o ANTES × DEPOIS,
    que é o que faz o cliente entender a pergunta antes de responder."""
    novo = _num(out.get("valor_informado"))
    if novo is None:
        return []
    atual = _num(out.get("valor_atual"))
    formato = "brl" if out.get("unidade") == "BRL" else "numero"
    prov = {"fonte": f"contexto do cliente · fonte que manda: {out.get('fonte_que_manda', '')}",
            "as_of": None, "cutoff_date": None, "n": None,
            "metodo": out.get("metodo", ""), "premissas": {},
            "avisos": list(out.get("avisos") or []), "lacunas": 0}
    itens = [{"rotulo": "Informado agora", "valor": novo, "formato": formato}]
    if atual is not None:
        itens.insert(0, {"rotulo": "Registrado hoje", "valor": atual, "formato": formato})
        if _num(out.get("variacao")) is not None:
            itens.append({"rotulo": "Variação", "valor": out["variacao"], "formato": formato,
                          "detalhe": "acima do limiar" if out.get("e_mudanca_material") else "abaixo do limiar"})
    return [_bloco("indicadores", eid, 1, out.get("rotulo") or "Mudança no contexto",
                   {"itens": itens}, prov, NOTA_CONTEXTO,
                   subtitulo=out.get("motivo"))]


def _perfil_financeiro(out: dict, eid: str, max_pontos: int) -> list[dict]:
    """Perfil por família. Área indisponível vira barra sem valor com o motivo — mostrar 0
    seria dizer que o cliente vai mal onde ninguém mediu."""
    areas = out.get("areas")
    if not isinstance(areas, list) or not areas:
        return []
    prov = {"fonte": "motor do perfil (engine.runs)", "as_of": out.get("calculado_em"),
            "cutoff_date": None, "n": None, "metodo": out.get("metodo", ""), "premissas": {},
            "avisos": list(out.get("avisos") or []), "lacunas": len(out.get("fatos_faltando") or [])}
    itens = []
    for a in areas:
        if a.get("indisponivel") or _num(a.get("score")) is None:
            continue
        itens.append({"rotulo": a.get("rotulo") or a.get("area"), "valor": a["score"],
                      **({"destaque": "desvio"} if a.get("elo_mais_fraco") else {})})
    blocos = []
    if itens:
        blocos.append(_bloco("barras", eid, 1, "Diagnóstico por área",
                             {"itens": itens, "formato": "numero"}, prov, NOTA_PERFIL,
                             subtitulo="0 a 1 · a área destacada é a que mais limita o rumo hoje"))
    indisponiveis = [a for a in areas if a.get("indisponivel")]
    if indisponiveis:
        blocos.append(_bloco("tabela", eid, len(blocos) + 1, "O que ainda não dá para medir",
                             {"colunas": [{"chave": "area", "rotulo": "Área"},
                                          {"chave": "motivo", "rotulo": "Por quê"}],
                              "linhas": [{"area": a.get("rotulo") or a.get("area"),
                                          "motivo": a.get("motivo") or "sem base suficiente"}
                                         for a in indisponiveis[:max_pontos]]},
                             prov, NOTA_PERFIL))
    return blocos


# ------------------------------------------------------------------ simulação (F17)
def _simulacao_objetivo(out: dict, eid: str, max_pontos: int) -> list[dict]:
    """A distribuição do valor final, com o CENÁRIO RUIM primeiro.

    NÃO É UM FAN CHART, e a diferença importa: fan chart mostra a distribuição ao longo do
    TEMPO, e para isso seriam necessários percentis por período. `planning.goal_projections`
    guarda a distribuição TERMINAL — uma linha por alocação. Desenhar um leque sobre dados
    que não têm eixo de tempo seria inventar a forma da trajetória, que é exatamente o tipo
    de figura que este projeto recusa.

    O guardrail do §8 do documento é atendido de outro jeito, e mais forte: o p5 é a PRIMEIRA
    barra do primeiro bloco, e a comparação entre carteiras é feita SOBRE o cenário ruim —
    não sobre a mediana. Quem lê de cima para baixo lê o piso antes do meio.
    """
    projecoes = out.get("projecoes")
    if not isinstance(projecoes, list) or not projecoes:
        return []
    premissas = out.get("premissas_de_mercado") or {}
    # A fonte deixou de citar `PLEXO_BASE v1 (draft)`: nome de conjunto e status interno não
    # dizem nada ao cliente, e "(draft)" parece defeito. Que as premissas estão em revisão é
    # informação legítima — e vira aviso traduzido, não sufixo técnico.
    prov_base = {"fonte": "simulação de mercado com premissas versionadas",
                 "as_of": None, "cutoff_date": None, "n": None,
                 "metodo": out.get("metodo", ""), "premissas": {}, "lacunas": 0}
    avisos_gerais = [a for a in (out.get("avisos") or []) if not str(a).startswith("objetivo:")]
    nota = f"{out.get('nota', '')} {out.get('limitacao', '')}".strip()

    blocos: list[dict] = []
    for p in projecoes[:max(1, max_pontos // 4)]:
        n = len(blocos) + 1
        # Aviso é DO OBJETIVO, não da execução. Antes um `prov` único era reusado em todos os
        # blocos, e o cliente lia embaixo da faculdade um aviso que falava da aposentadoria.
        prov = dict(prov_base,
                    avisos=_avisos(avisos_gerais + list(p.get("avisos") or [])))
        meses = int(p.get("prazo_meses") or 0)
        anos = meses // 12
        prazo = f"{anos} anos" if anos >= 2 and meses % 12 == 0 else f"{meses} meses"
        blocos.append(_bloco(
            "faixa", eid, n, f"{p.get('objetivo', 'Objetivo')} · {prazo}",
            {"probabilidade": p.get("chance_de_atingir"),
             "rotulo_probabilidade": "de chance de chegar ao alvo",
             "p5": p.get("cenario_ruim_p5"), "p25": p.get("p25"), "p50": p.get("mediana_p50"),
             "p75": p.get("p75"), "p95": p.get("cenario_bom_p95"),
             "alvo": p.get("valor_alvo"), "formato": "brl",
             "rotulos": {"baixo": "cenário ruim", "meio": "valor mais provável",
                         "alto": "cenário bom", "alvo": "alvo"},
             "arrependimento": p.get("chance_de_ficar_abaixo_do_depositado"),
             "rotulo_arrependimento": "de chance de terminar abaixo do que você depositou",
             "acao": ({"rotulo": "para chegar lá em 9 de cada 10 cenários, o aporte seria de",
                       "valor": p.get("aporte_para_90_por_cento"), "formato": "brl",
                       "sufixo": "por mês"}
                      if p.get("aporte_para_90_por_cento") else None),
             "aporte_atual": {"rotulo": "aporte considerado",
                              "valor": p.get("aporte_mensal"), "formato": "brl",
                              "sufixo": "por mês"}},
            prov, nota, subtitulo=p.get("veredito_de_risco")))

        comparadas = p.get("carteiras_comparadas")
        if isinstance(comparadas, list) and len(comparadas) > 1:
            blocos.append(_bloco(
                "barras", eid, len(blocos) + 1, "Cenário ruim por carteira",
                {"itens": [{"rotulo": c.get("carteira"), "valor": c.get("cenario_ruim_p5"),
                            **({"destaque": "referencia"} if c.get("carteira") == p.get("carteira") else {})}
                           for c in comparadas],
                 "formato": "brl"}, prov, nota,
                subtitulo="a comparação entre carteiras é feita sobre o PISO, não sobre a mediana"))
    return blocos


MAPEADORES: dict[str, Callable[[dict, str, int], list[dict]]] = {
    "educacao.simulador_juros_compostos": _juros_compostos,
    "educacao.exemplo_didatico": _exemplo_didatico,
    "orcamento.reserva_emergencia": _reserva,
    "orcamento.capacidade_aporte": _capacidade,
    "contexto.documento_oficial": _documento_oficial,
    "dados.expectativas_mercado": _expectativas,
    "planejamento.composicao_patrimonio": _composicao_patrimonio,
    "planejamento.posicoes_carteira": _posicoes_carteira,
    "planejamento.pontos_de_atencao": _pontos_de_atencao,
    "planejamento.projecao_objetivo": _projecao,
    "planejamento.aposentadoria_antecipada": _aposentadoria,
    "produto.custo_fundo": _custo_fundo,
    "produto.comparar_alternativas": _comparar,
    "dados.serie_precos": _serie_precos,
    "dados.historico_comparado": _historico_comparado,
    "dados.serie_indice": _serie_indice,
    "dados.fundamentos_empresa": _fundamentos_empresa,
    "dados.curva_juros": _curva_juros,
    "dados.composicao_indice": _composicao_indice,
    "quant.retorno_volatilidade": _retorno_vol,
    "quant.correlacao": _correlacao,
    "quant.risco_retorno": _retorno_vol,
    "quant.dependencia": _dependencia,
    "quant.dependencia_macro": _dependencia_macro,
    "quant.tendencias_fundamentais": _tendencias_fundamentais,
    "quant.valor_mercado": _valor_mercado,
    "quant.comparaveis_setor": _comparaveis_setor,
    "quant.cenario_sensibilidade": _cenario_sensibilidade,
    "quant.analise_condicional": _analise_condicional,
    "quant.sensibilidade": _sensibilidade,
    "quant.regimes": _regimes,
    "quant.event_study": _event_study_v2,
    "contexto.verificar_mudanca": _verificar_mudanca,
    "contexto.perfil_financeiro": _perfil_financeiro,
    "planejamento.simulacao_objetivo": _simulacao_objetivo,
}


def blocos_de(code: str, payload: dict[str, Any], *, execution_id: str,
              max_blocos: int = PADRAO_MAX_BLOCOS, max_pontos: int = PADRAO_MAX_PONTOS) -> list[dict[str, Any]]:
    """Blocos de uma execução. Tool sem mapeador (glossário, resolver) ou payload inesperado ⇒ []."""
    fn = MAPEADORES.get(code)
    if fn is None or not isinstance(payload, dict):
        return []
    try:
        blocos = fn(payload, execution_id, max(3, int(max_pontos)))
    except (KeyError, TypeError, ValueError, AttributeError):
        return []
    return blocos[: max(0, int(max_blocos))]


async def blocos_de_execucoes(conn: AsyncConnection, execucoes: list[tuple[str, str]], *,
                              max_blocos: int = PADRAO_MAX_BLOCOS, max_pontos: int = PADRAO_MAX_PONTOS) -> list[dict[str, Any]]:
    """Reconstrói blocos a partir de `tools.tool_executions.output_payload` (RLS da sessão). Usado pelo relatório research."""
    saida: list[dict[str, Any]] = []
    for code, execution_id in execucoes:
        cur = await conn.execute("select output_payload from tools.tool_executions where id = %s", (execution_id,))
        row = await cur.fetchone()
        if row is None or row[0] is None:
            continue
        payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        saida.extend(blocos_de(code, payload, execution_id=execution_id, max_blocos=max_blocos, max_pontos=max_pontos))
    return saida[: max(0, int(max_blocos))]
