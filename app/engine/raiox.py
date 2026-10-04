"""O Raio-X da carteira — o produtor que a taxonomia esperava desde a migration 15.

POR QUE ESTE ARQUIVO EXISTIA COMO BURACO
    `diagnostics.finding_types` tem 21 tipos semeados desde a 15, com severidade, plano
    mínimo e atrito de execução. `findings` tem `priority_score` gerado por
    `(impacto × confiança) / atrito`. `actions` exige os cinco blocos por CHECK.
    `v_action_queue` ordena a fila com a Fundação na frente. `v_issuer_concentration`
    consolida conglomerado por `parent_issuer_id`. `coverage_reports` mede o que a análise
    não alcançou. `gate_reveals` guarda a revelação estrutural do paywall. `engine.run_kind`
    tem 'raiox' e 'coverage' desde a migration 02.

    E `diagnostics.findings` tinha ZERO linhas em 2026-08-30. Nada nunca escreveu nela.

    É o terceiro achado do mesmo tipo nesta base — `foundation_status` (F16) e o campo
    `plano` do arquétipo foram os outros dois. A F16 já tinha escrito a frase: "um gate sem
    quem o alimente não é gate: é intenção". Aqui ela vira também estrutura: a migration 54
    fez `implemented_at` ser condição de existência, então este arquivo e o catálogo não
    conseguem mais divergir em silêncio.

DUAS METADES, COMO O RESTO DO MOTOR
    `detectar(carteira, premissas)` é PURA: sem banco, sem relógio, sem aleatório. É ela que
    o golden trava. `executar(conn, scope_id)` lê o mundo, chama a pura e grava.

O QUE ELE NÃO FAZ, E POR QUÊ
    Não escreve `diagnostics.actions`. A ação exige cinco blocos — gatilho, evidência,
    quantificação, passo e "por que agora" — e o quarto é uma instrução ao cliente sobre o
    que fazer com o dinheiro. Sob a RCVM 19, antes da autorização, isso é exatamente o que a
    plataforma não emite. O finding DESCREVE o que foi medido; a ação PRESCREVE. Uma vem
    antes da autorização, a outra não. O CHECK de cinco blocos continua guardando a porta.

CONCENTRAÇÃO SE MEDE SOBRE A CARTEIRA INTEIRA
    `v_issuer_concentration` divide pela soma das posições COM emissor cadastrado — o que é
    correto para a view, e errado para o alerta: uma carteira metade sem emissor faria 30%
    virar 60%. Aqui o denominador é sempre o total da carteira, e o que não tem emissor
    aparece em `coverage_reports` como o que não foi possível ler.

Config-first: todo limiar vem de `RAIOX_LIMIARES`; a referência de custo de fundo reusa
`PRODUTO_REFERENCIAS`, que já é aprovada, em vez de inventar uma segunda. Zero número de
negócio neste arquivo.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.db.repos import policies as policies_repo
from app.tools.hashing import canonical_json, sha256_hex

log = logging.getLogger(__name__)

PACOTE = "plexo-engine"
SEMVER = "1.0.0"
POLICY = "RAIOX_LIMIARES"
POLICY_CUSTO = "PRODUTO_REFERENCIAS"

# Cobertura do FGC é do INSTRUMENTO, não do emissor (ver `app/tools/assessor/posicoes.py`,
# onde a mesma lista está documentada com a fonte). Importar de lá acoplaria o motor à
# camada de tools; a duplicação é deliberada e as duas têm teste.
KINDS_COBERTOS_PELO_FGC = ("cdb", "lci_lca", "poupanca")


@dataclass(frozen=True)
class Posicao:
    """Uma linha da carteira, do jeito que o detector precisa dela."""
    instrument_id: str
    nome: str
    kind: str
    classe: str | None
    grupo: str | None
    emissor_id: str | None
    emissor_nome: str | None
    emissor_fgc: bool
    valor_brl: float
    liquidez_dias: int | None
    taxa_adm_aa: float | None
    # A posição está numa conta marcada como reserva de emergência? Sem isto, o caixa dessa
    # conta é contado DUAS vezes no achado de dinheiro parado: uma como posição de classe
    # `caixa`, outra como saldo em `account_balances`. Não acontece nos dados de hoje porque
    # os seeds separam as contas — mas numa importação real a conta de reserva é justamente
    # a que costuma ter caixa parado, e o alerta sairia com o dobro do valor no campo que
    # alimenta `priority_score`. Achado do /code-review de 2026-08-30.
    conta_e_reserva: bool = False


@dataclass(frozen=True)
class Carteira:
    posicoes: tuple[Posicao, ...]
    total_brl: float
    # OS DOIS NÚMEROS DA RESERVA, e confundi-los é o defeito que a primeira execução expôs.
    # `reserva_saldo_brl` é o que está guardado hoje nas contas marcadas como reserva;
    # `reserva_requerida_brl` é quanto ela PRECISA ser (meses-alvo × despesa essencial).
    # A primeira versão comparava o caixa da corretora contra o SALDO e concluía que não havia
    # caixa parado — quando o certo é o contrário: reserva já cheia é exatamente a condição
    # que transforma o resto do caixa em dinheiro parado.
    reserva_saldo_brl: float | None
    reserva_requerida_brl: float | None

    @property
    def classes_presentes(self) -> set[str]:
        return {p.classe for p in self.posicoes if p.classe}


@dataclass(frozen=True)
class Achado:
    """Um finding, antes de virar linha. `chave` é o `finding_key` estável do banco."""
    tipo: str
    chave: str
    subject_kind: str
    subject_id: str | None
    severidade: str
    confianca: float
    impacto_brl_ano: float | None
    quantificacao: dict[str, Any]
    evidencia: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Metade PURA — sem banco, sem relógio, sem aleatório
# =============================================================================
def detectar(c: Carteira, premissas: dict[str, Any],
             referencias_de_custo: dict[str, float]) -> list[Achado]:
    """A carteira e os limiares entram; os achados saem. Determinística.

    A ordem da lista é a de DETECÇÃO, não de prioridade: quem ordena é `priority_score`,
    gerado pelo banco. Ordenar aqui seria opinião embutida em código, e ela já vive na
    fórmula `(impacto × confiança) / atrito` da migration 06.
    """
    if c.total_brl <= 0 or not c.posicoes:
        return []

    achados: list[Achado] = []
    confianca = float(premissas["impacto_padrao_confianca"])

    # ---------------------------------------------------------------- emissor
    # O denominador é a carteira inteira, sempre. Dividir pela parte com emissor conhecido
    # (que é o que `v_issuer_concentration` faz, corretamente, para o seu propósito)
    # transformaria uma carteira metade sem cadastro num falso alerta.
    limite_emissor = float(premissas["concentracao_emissor_max"])
    por_emissor: dict[str, float] = {}
    nomes: dict[str, str] = {}
    for p in c.posicoes:
        if p.emissor_id is None:
            continue
        por_emissor[p.emissor_id] = round(por_emissor.get(p.emissor_id, 0.0) + p.valor_brl, 2)
        nomes[p.emissor_id] = p.emissor_nome or p.emissor_id
    for emissor_id, exposicao in sorted(por_emissor.items(), key=lambda kv: (-kv[1], kv[0])):
        share = exposicao / c.total_brl
        if share <= limite_emissor:
            continue
        achados.append(Achado(
            tipo="risco.concentracao_emissor",
            chave=f"risco.concentracao_emissor:issuer:{emissor_id}",
            subject_kind="issuer", subject_id=emissor_id,
            # Severidade cresce com o excesso: 2× o limiar é outra conversa.
            severidade="critica" if share >= limite_emissor * 2 else "alta",
            confianca=confianca,
            # Concentração não tem custo anual em reais: o que ela muda é a dispersão do
            # resultado, não a despesa. `impact_brl_year` fica NULO em vez de receber um
            # número inventado — e `priority_score` cai para zero, que é honesto: a fila
            # ordena por impacto medido, e este achado não tem um.
            impacto_brl_ano=None,
            quantificacao={"emissor": nomes[emissor_id], "exposicao_brl": exposicao,
                           "share_pct": round(share * 100, 2),
                           "limiar_pct": round(limite_emissor * 100, 2),
                           "excedente_brl": round(exposicao - c.total_brl * limite_emissor, 2)},
            evidencia={"consolida_conglomerado": True, "total_carteira_brl": c.total_brl,
                       "unidade_do_impacto": None}))

    # ---------------------------------------------------------------- FGC
    teto = float(premissas["teto_fgc_brl"])
    garantido: dict[str, float] = {}
    for p in c.posicoes:
        if p.emissor_id is None or not p.emissor_fgc or p.kind not in KINDS_COBERTOS_PELO_FGC:
            continue
        garantido[p.emissor_id] = round(garantido.get(p.emissor_id, 0.0) + p.valor_brl, 2)
    for emissor_id, coberto in sorted(garantido.items(), key=lambda kv: (-kv[1], kv[0])):
        if coberto <= teto:
            continue
        excedente = round(coberto - teto, 2)
        achados.append(Achado(
            tipo="risco.exposicao_acima_do_fgc",
            chave=f"risco.exposicao_acima_do_fgc:issuer:{emissor_id}",
            subject_kind="issuer", subject_id=emissor_id,
            severidade="alta", confianca=confianca,
            # Aqui existe número: o excedente é a parte que fica sem garantia. Não é custo,
            # é valor exposto — e é ele que a fila deve ordenar.
            impacto_brl_ano=excedente,
            quantificacao={"emissor": nomes.get(emissor_id, emissor_id),
                           "coberto_brl": coberto, "teto_brl": teto, "excedente_brl": excedente},
            # `impact_brl_year` recebe VALOR EXPOSTO, não custo por ano — a coluna tem esse
            # nome desde a 06 e `priority_score` divide por atrito sem olhar unidade. Declarar
            # a natureza do número aqui é o que impede a tela de escrever "R$ 20.000 por ano"
            # sobre uma quantia que não é anual nem é custo.
            evidencia={"instrumentos_garantidos": list(KINDS_COBERTOS_PELO_FGC),
                       "unidade_do_impacto": "valor_exposto_brl"}))

    # ---------------------------------------------------------------- classe
    limite_classe = float(premissas["concentracao_classe_max"])
    por_classe: dict[str, float] = {}
    for p in c.posicoes:
        if p.classe:
            por_classe[p.classe] = round(por_classe.get(p.classe, 0.0) + p.valor_brl, 2)
    for classe, valor in sorted(por_classe.items(), key=lambda kv: (-kv[1], kv[0])):
        share = valor / c.total_brl
        if share <= limite_classe:
            continue
        achados.append(Achado(
            tipo="risco.concentracao_classe", chave=f"risco.concentracao_classe:class:{classe}",
            subject_kind="asset_class", subject_id=None,
            severidade="media", confianca=confianca, impacto_brl_ano=None,
            quantificacao={"classe": classe, "valor_brl": valor,
                           "share_pct": round(share * 100, 2),
                           "limiar_pct": round(limite_classe * 100, 2)},
            evidencia={"total_carteira_brl": c.total_brl, "unidade_do_impacto": None}))

    # ---------------------------------------------------------------- caixa ocioso
    # Caixa não é problema: caixa ALÉM da reserva é. Sem saber quanto a reserva PRECISA ser,
    # não há alerta — dizer "você tem dinheiro parado" a quem ainda está construindo a
    # reserva é o oposto do certo, e é por isso que a condição é sobre a requerida e não
    # sobre o saldo.
    #
    # O caixa contado é o total: o que está nas contas de reserva MAIS o que está parado na
    # corretora. Olhar só um dos dois dá as duas respostas erradas — quem tem a reserva toda
    # na corretora pareceria não ter reserva, e quem tem reserva cheia mais dinheiro parado
    # pareceria estar em ordem.
    if c.reserva_requerida_brl is not None:
        # Só o caixa FORA das contas de reserva: o de dentro já entra por `reserva_saldo_brl`.
        caixa_investido = round(sum(p.valor_brl for p in c.posicoes
                                    if p.classe == "caixa" and not p.conta_e_reserva), 2)
        caixa_total = round(caixa_investido + (c.reserva_saldo_brl or 0.0), 2)
        folga = float(premissas["caixa_ocioso_multiplo_da_reserva"])
        limite_caixa = round(c.reserva_requerida_brl * folga, 2)
        if caixa_total > limite_caixa >= 0:
            excedente = round(caixa_total - limite_caixa, 2)
            achados.append(Achado(
                tipo="alocacao.caixa_parado_excessivo",
                chave="alocacao.caixa_parado_excessivo:scope:caixa",
                subject_kind="scope", subject_id=None,
                severidade="alta", confianca=confianca,
                # O impacto não é o excedente inteiro: é o CUSTO de ele estar parado, e esse
                # número exigiria uma premissa de retorno que este motor não tem. O valor
                # exposto é o que se declara, e ele é o excedente.
                impacto_brl_ano=excedente,
                quantificacao={"caixa_total_brl": caixa_total,
                               "caixa_na_carteira_brl": caixa_investido,
                               "reserva_saldo_brl": c.reserva_saldo_brl,
                               "reserva_requerida_brl": c.reserva_requerida_brl,
                               "excedente_brl": excedente},
                evidencia={"multiplo_da_reserva": folga,
                           "unidade_do_impacto": "valor_parado_brl"}))

    # ---------------------------------------------------------------- liquidez
    dias_min = int(premissas["iliquido_dias_min"])
    share_max = float(premissas["iliquido_share_max"])
    travado = round(sum(p.valor_brl for p in c.posicoes
                        if p.liquidez_dias is not None and p.liquidez_dias >= dias_min), 2)
    share_travado = travado / c.total_brl
    if travado > 0 and share_travado > share_max:
        achados.append(Achado(
            tipo="liquidez.resgate_longo_excessivo",
            chave=f"liquidez.resgate_longo_excessivo:scope:d{dias_min}",
            subject_kind="scope", subject_id=None,
            severidade="media", confianca=confianca, impacto_brl_ano=None,
            quantificacao={"valor_brl": travado, "share_pct": round(share_travado * 100, 2),
                           "limiar_pct": round(share_max * 100, 2), "a_partir_de_dias": dias_min},
            evidencia={"unidade_do_impacto": None,
                       "posicoes": sorted(p.nome for p in c.posicoes
                                          if p.liquidez_dias is not None and p.liquidez_dias >= dias_min)}))

    # ---------------------------------------------------------------- custo
    # Reusa `PRODUTO_REFERENCIAS`, que já é aprovada e já serve a `produto.custo_fundo`.
    # Uma segunda referência de custo produziria dois números diferentes para a mesma
    # pergunta na mesma tela — foi o que a F18 encontrou com a capacidade de aporte.
    #
    # LIMITAÇÃO DECLARADA: a busca é pela chave direta da classe, exatamente como
    # `produto.custo_fundo:106` faz. As chaves da política hoje são `acoes`, `renda_fixa` e
    # `multimercado`, e não os códigos de `market.asset_classes` (`acoes_br`, `selic`, `ipca`).
    # Fundo de classe sem referência simplesmente NÃO é avaliado quanto a custo — e é assim
    # de propósito: inventar aqui um mapa classe→chave faria a mesma pergunta ter duas
    # respostas na mesma tela, dependendo de qual caminho o cliente tomou. O conserto certo
    # é alinhar as chaves em `PRODUTO_REFERENCIAS`, que é decisão de compliance.
    folga_taxa = float(premissas["taxa_fundo_folga_sobre_referencia"])
    for p in c.posicoes:
        if p.taxa_adm_aa is None or not p.classe:
            continue
        referencia = referencias_de_custo.get(p.classe)
        if referencia is None or p.taxa_adm_aa <= referencia + folga_taxa:
            continue
        excesso_aa = round(p.taxa_adm_aa - referencia, 6)
        achados.append(Achado(
            tipo="custo.taxa_fundo_alta",
            chave=f"custo.taxa_fundo_alta:instrument:{p.instrument_id}",
            subject_kind="instrument", subject_id=p.instrument_id,
            severidade="alta", confianca=confianca,
            # Aqui o impacto é dinheiro de verdade e por ano: a diferença de taxa sobre o
            # valor aplicado. É o achado mais acionável da lista, e a fila reflete isso.
            impacto_brl_ano=round(p.valor_brl * excesso_aa, 2),
            quantificacao={"produto": p.nome, "taxa_aa": p.taxa_adm_aa,
                           "referencia_aa": referencia, "excesso_aa": excesso_aa,
                           "valor_aplicado_brl": p.valor_brl,
                           "custo_ano_brl": round(p.valor_brl * excesso_aa, 2)},
            evidencia={"referencia": POLICY_CUSTO, "classe": p.classe,
                       "unidade_do_impacto": "custo_ano_brl"}))

    # ---------------------------------------------------------------- internacional
    # Ausência, e não excesso: não é quantificável (`is_quantifiable = false` na 15), então
    # não carrega quantificação nem impacto. Só existe se houver carteira para diversificar.
    if "acoes_int" not in c.classes_presentes:
        achados.append(Achado(
            tipo="alocacao.sem_exposicao_internacional",
            chave="alocacao.sem_exposicao_internacional:scope:acoes_int",
            subject_kind="scope", subject_id=None,
            severidade="baixa", confianca=confianca, impacto_brl_ano=None,
            quantificacao={},
            evidencia={"classes_presentes": sorted(c.classes_presentes), "unidade_do_impacto": None}))

    return achados


# =============================================================================
# Metade IMPURA — lê o mundo, chama a pura, grava
# =============================================================================
async def _engine_version_id(conn: AsyncConnection) -> str:
    cur = await conn.execute(
        "select id::text from engine.engine_versions where package = %s and semver = %s",
        (PACOTE, SEMVER))
    row = await cur.fetchone()
    if row:
        return row[0]
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             check=False).stdout.strip()
    except OSError:
        sha = ""
    sha = sha if len(sha) == 40 else "0" * 40
    fonte = sha256_hex(canonical_json({"pacote": PACOTE, "semver": SEMVER, "motor": "raiox"}))
    cur = await conn.execute(
        "insert into engine.engine_versions (package, semver, git_sha, source_sha256, notes) "
        "values (%s, %s, %s, %s, %s) returning id::text",
        (PACOTE, SEMVER, sha, fonte, "Raio-X da carteira (F19)."))
    return (await cur.fetchone())[0]


async def ler_carteira(conn: AsyncConnection, scope_id: str) -> tuple[Carteira, dict[str, Any]]:
    """A carteira mais recente do escopo, mais o que NÃO foi possível ler.

    O segundo valor vira `coverage_reports`: posição sem classe, sem emissor ou sem preço é
    exatamente o que o Raio-X não consegue diagnosticar, e o cliente tem direito de saber
    que existe uma parte cega — é a diferença entre "não encontrei problema" e "não olhei".
    """
    cur = await conn.execute(
        "select h.instrument_id::text, coalesce(i.name, 'Posição sem cadastro'), "
        "       coalesce(i.kind::text, 'outro'), i.asset_class_code, ac.group_name, "
        "       coalesce(raiz.id, iss.id)::text, coalesce(raiz.name, iss.name), "
        "       coalesce(raiz.fgc_covered, iss.fgc_covered, false), "
        "       h.value_brl::float, i.liquidity_days, ff.management_fee::float, "
        "       (h.account_id = any(coalesce(rs.reserve_account_ids, '{}'::uuid[]))) as e_reserva "
        "  from wealth.v_latest_holdings h "
        "  left join market.instruments i on i.id = h.instrument_id "
        "  left join market.asset_classes ac on ac.code = i.asset_class_code "
        "  left join market.issuers iss on iss.id = i.issuer_id "
        "  left join market.issuers raiz on raiz.id = coalesce(iss.parent_issuer_id, iss.id) "
        "  left join market.fund_facts ff on ff.instrument_id = i.id "
        "  left join budget.reserve_settings rs on rs.scope_id = h.scope_id "
        " where h.scope_id = %s", (scope_id,))
    posicoes = tuple(
        Posicao(instrument_id=r[0], nome=r[1], kind=r[2], classe=r[3], grupo=r[4],
                emissor_id=r[5], emissor_nome=r[6], emissor_fgc=r[7], valor_brl=round(r[8], 2),
                liquidez_dias=r[9], taxa_adm_aa=r[10], conta_e_reserva=bool(r[11]))
        for r in await cur.fetchall())
    total = round(sum(p.valor_brl for p in posicoes), 2)

    sem_classe = round(sum(p.valor_brl for p in posicoes if not p.classe), 2)
    sem_emissor = round(sum(p.valor_brl for p in posicoes if p.emissor_id is None), 2)
    # "Coberto" = o que o Raio-X CONSEGUE diagnosticar, e a classe é o insumo mínimo: sem ela
    # a posição não entra em concentração de classe, nem em caixa, nem em liquidez. A ausência
    # de emissor é declarada à parte porque é mais estreita — tira a posição só da leitura de
    # concentração e do FGC, e há caso legítimo (saldo em conta não tem emissor de crédito).
    cobertura = {"total_value_brl": total,
                 "covered_value_brl": round(total - sem_classe, 2),
                 "uncovered": {k: v for k, v in
                               (("sem_classe_de_ativo", sem_classe),
                                ("sem_emissor_para_concentracao", sem_emissor))
                               if v > 0}}

    # A reserva vem das MESMAS fontes que a Fundação usa (`reserve_settings` ×
    # `account_balances` × `monthly_summaries`): dois números diferentes de reserva na mesma
    # tela foi o defeito que a F18 corrigiu na capacidade de aporte, e ele não se repete aqui.
    cur = await conn.execute(
        "select coalesce(sum(b.balance_brl), 0)::float "
        "  from budget.reserve_settings rs "
        "  join lateral unnest(rs.reserve_account_ids) as ra(id) on true "
        "  join lateral (select balance_brl from wealth.account_balances ab "
        "                 where ab.account_id = ra.id order by ab.as_of_date desc limit 1) b on true "
        " where rs.scope_id = %s", (scope_id,))
    row = await cur.fetchone()
    saldo = float(row[0]) if row and row[0] is not None else None

    # Quanto a reserva PRECISA ser: meses-alvo do próprio cliente × despesa essencial média.
    # Sem despesa registrada não há requerida, e sem requerida não há alerta de caixa parado —
    # que é o comportamento certo: não se diz a alguém que tem dinheiro sobrando sem saber
    # quanto ele gasta.
    cur = await conn.execute(
        "select (rs.target_months * m.media)::float "
        "  from budget.reserve_settings rs "
        "  join lateral (select avg(essential_expense_brl) as media "
        "                  from budget.monthly_summaries ms "
        "                 where ms.scope_id = rs.scope_id "
        "                   and ms.essential_expense_brl is not null) m on true "
        " where rs.scope_id = %s", (scope_id,))
    row = await cur.fetchone()
    requerida = round(float(row[0]), 2) if row and row[0] is not None else None

    return Carteira(posicoes=posicoes, total_brl=total, reserva_saldo_brl=saldo,
                    reserva_requerida_brl=requerida), cobertura


async def executar(conn: AsyncConnection, scope_id: str, *, as_of: date | None = None,
                   client_facing: bool = False) -> dict[str, Any]:
    """Roda o Raio-X e grava findings, observações e cobertura. Idempotente por escopo/dia."""
    as_of = as_of or date.today()

    politica = await policies_repo.get_current(conn, POLICY)
    if politica is None:
        raise RuntimeError(f"política {POLICY} não encontrada — aplique a migration 54")
    # A chave é `referencia_taxa_adm_aa`, a MESMA que `produto.custo_fundo:106` lê. A primeira
    # versão inventou um nome (`taxa_adm_referencia_por_classe`), o `.get` devolveu vazio e o
    # achado de custo simplesmente nunca disparava — em silêncio, que é o pior jeito.
    referencias = await policies_repo.get_current(conn, POLICY_CUSTO)
    por_classe = dict((referencias.payload.get("referencia_taxa_adm_aa") or {})
                      if referencias else {})

    carteira, cobertura = await ler_carteira(conn, scope_id)
    if not carteira.posicoes:
        log.info("raio-x (scope=%s): nenhuma posição registrada — nada a diagnosticar", scope_id)
        return {"run_id": None, "achados": [], "cobertura": cobertura, "sem_carteira": True}

    achados = detectar(carteira, politica.payload, por_classe)

    engine_version_id = await _engine_version_id(conn)
    entrada = {"scope_id": scope_id, "as_of": as_of.isoformat(),
               "posicoes": [(p.instrument_id, p.valor_brl) for p in carteira.posicoes],
               "policy": politica.id, "semver": SEMVER}
    cur = await conn.execute(
        "insert into engine.runs (scope_id, kind, engine_version_id, policy_version_ids, "
        "                         params, input_hash, status, is_client_facing, as_of_date, "
        "                         triggered_by) "
        "values (%s, 'raiox', %s, %s, %s, %s, 'running', %s, %s, 'job') returning id::text",
        (scope_id, engine_version_id, [politica.id],
         Jsonb({"semver": SEMVER, "policy_status": politica.compliance_status,
                "total_carteira_brl": carteira.total_brl}),
         sha256_hex(canonical_json(entrada)), client_facing, as_of))
    run_id = (await cur.fetchone())[0]

    vistos: list[str] = []
    for a in achados:
        cur = await conn.execute(
            # Upsert pela chave lógica: o recálculo ATUALIZA o finding. Se criasse outro, a
            # recusa do cliente ("não me mostre mais isso") seria esquecida na madrugada
            # seguinte — `dismissal_count` e `cooldown_until` vivem no finding justamente
            # porque a ação é reemitida a cada run (COMMENT da 06).
            "insert into diagnostics.findings "
            "  (scope_id, finding_type_code, finding_key, subject_kind, subject_id, severity, "
            "   confidence, impact_brl_year, execution_friction, evidence, quantification, "
            "   first_run_id, last_run_id) "
            "select %s, %s, %s, %s, %s, %s::diagnostics.severity, %s, %s, ft.execution_friction, "
            "       %s, %s, %s, %s from diagnostics.finding_types ft where ft.code = %s "
            "on conflict (scope_id, finding_key) do update set "
            "  severity = excluded.severity, confidence = excluded.confidence, "
            "  impact_brl_year = excluded.impact_brl_year, evidence = excluded.evidence, "
            "  quantification = excluded.quantification, last_run_id = excluded.last_run_id, "
            "  last_detected_at = now(), is_current = true, resolved_at = null, resolution = null "
            "returning id::text",
            (scope_id, a.tipo, a.chave, a.subject_kind, a.subject_id, a.severidade,
             a.confianca, a.impacto_brl_ano, Jsonb(a.evidencia), Jsonb(a.quantificacao),
             run_id, run_id, a.tipo))
        finding_id = (await cur.fetchone())[0]
        vistos.append(finding_id)
        await conn.execute(
            "insert into diagnostics.finding_observations "
            "  (finding_id, run_id, observed_on, severity, confidence, impact_brl_year, payload) "
            "values (%s, %s, %s, %s::diagnostics.severity, %s, %s, %s) "
            "on conflict (finding_id, run_id) do nothing",
            (finding_id, run_id, as_of, a.severidade, a.confianca, a.impacto_brl_ano,
             Jsonb(a.quantificacao)))

    # O que sumiu deixou de ser verdade: fechar é tão importante quanto abrir. Sem isto, um
    # alerta de concentração resolvido continuaria na tela para sempre.
    await conn.execute(
        "update diagnostics.findings set is_current = false, resolved_at = now(), "
        "  resolution = 'disappeared' "
        " where scope_id = %s and is_current and resolved_at is null "
        "   and not (id::text = any(%s)) "
        "   and finding_type_code in (select code from diagnostics.finding_types "
        "                              where implemented_at is not null)",
        (scope_id, vistos))

    await conn.execute(
        "insert into diagnostics.coverage_reports "
        "  (scope_id, as_of_date, run_id, total_value_brl, covered_value_brl, coverage_pct, "
        "   uncovered_breakdown) values (%s, %s, %s, %s, %s, %s, %s) "
        "on conflict (scope_id, as_of_date) do update set run_id = excluded.run_id, "
        "  total_value_brl = excluded.total_value_brl, covered_value_brl = excluded.covered_value_brl, "
        "  coverage_pct = excluded.coverage_pct, uncovered_breakdown = excluded.uncovered_breakdown, "
        "  computed_at = now()",
        (scope_id, as_of, run_id, cobertura["total_value_brl"], cobertura["covered_value_brl"],
         round(cobertura["covered_value_brl"] / cobertura["total_value_brl"], 4)
         if cobertura["total_value_brl"] else 0,
         Jsonb(cobertura["uncovered"])))

    saida = {"achados": [{"tipo": a.tipo, "chave": a.chave, "quantificacao": a.quantificacao}
                         for a in achados], "cobertura": cobertura}
    await conn.execute(
        "update engine.runs set status = 'succeeded', output_hash = %s, finished_at = now() "
        "where id = %s", (sha256_hex(canonical_json(saida)), run_id))

    log.info("raio-x (scope=%s): %d achado(s) sobre R$ %.2f em %d posição(ões)",
             scope_id, len(achados), carteira.total_brl, len(carteira.posicoes))
    return {"run_id": run_id, "achados": achados, "cobertura": cobertura, "sem_carteira": False}
