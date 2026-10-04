"""Seis personas que cobrem a superfície de falha do diagnóstico.

POR QUE SEIS, E POR QUE ESTAS
    A F15 fechou com cinco correções, todas achadas rodando UMA persona, uma vez. A conta é
    incômoda: uma passada por um cliente produziu cinco defeitos. A superfície que ninguém
    visitou é grande, e visitá-la é mais barato que descobri-la com cliente real.

    Cada arquétipo abaixo foi escolhido por FORÇAR UM COMPORTAMENTO do motor, não por parecer
    um cliente plausível — embora precisem ser plausíveis, senão o golden não protege nada:

      endividado_rotativo         Fundação crítica ⇒ TODOS os scores desativados (D11)
      dependentes_sem_seguro      lacuna de seguro real; proteção como elo mais fraco
      autonomo_volatil            p10 muito abaixo da média; concentração de renda em 1,0
      aposentado                  horizonte curto; estoque alto com fluxo apertado
      jovem_sem_patrimonio        cobertura baixíssima — o vazio honesto, quase tudo indisponível
      patrimonio_alto_sem_fluxo   estoque bom e fluxo ruim: o caso que uma MÉDIA esconderia

    O último existe para provar, com números, a decisão de não ter nota geral.

COMO ISTO ESCALA
    Persona é um `Arquetipo` — um punhado de números com nome. O inseridor é um só. A sétima
    persona custa quinze linhas, não duzentas e trinta.

SEGURANÇA
    Cada uma vive em escopo PRÓPRIO, derivado por uuid5 do nome: rodar duas vezes não duplica,
    e nenhum teste, golden ou eval existente muda de valor por causa deste arquivo — a mesma
    regra que o cabeçalho de `seeds/persona.sql` estabeleceu.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

# Namespace fixo: o mesmo nome sempre gera os mesmos uuids, em qualquer máquina.
NS = uuid.UUID("f16a0000-0000-4000-8000-000000000000")
MESES_DE_ORCAMENTO = 12


@dataclass(frozen=True)
class Divida:
    kind: str
    descricao: str
    saldo: float
    taxa_anual: float
    parcela: float


@dataclass(frozen=True)
class Emissor:
    """Quem deve o dinheiro. É o que faz `diagnostics.v_issuer_concentration` funcionar.

    `matriz` consolida conglomerado: CDB do banco X e LCI da financeira do banco X são o
    MESMO risco de crédito e o MESMO teto de FGC. Sem isso, duas posições de R$ 150.000 no
    mesmo grupo passam como duas exposições de 150 mil, quando são uma de 300 mil — e o
    teto do FGC, que é por CPF e por instituição, é medido errado por construção.
    """
    codigo: str                      # chave do seed; vira uuid5 e nunca aparece na tela
    nome: str
    kind: str                        # banco | gestora | empresa | governo | seguradora | outro
    fgc_covered: bool = False
    matriz: str | None = None        # `codigo` do emissor-raiz do conglomerado


@dataclass(frozen=True)
class Posicao:
    """Uma linha da carteira.

    SOBRE `codigo`: é o código do CATÁLOGO, não necessariamente um papel de bolsa. Só
    `acao`, `etf` e `fii` são negociados com ticker público — CDB, LCI, Tesouro, fundo e
    saldo em conta recebem código interno, e `negociado_em_bolsa` diz qual é qual. A tool
    mostra o nome nesses casos; exibir "CDBITAU108" como se fosse um ticker seria inventar
    um mercado que não existe.

    DUAS FORMAS DE DECLARAR O VALOR, e a escolha é sobre honestidade, não sobre conveniência:

      · `quantidade` + `preco_referencia` — para o que tem preço público. O valor sai de
        quantidade × ÚLTIMO FECHAMENTO ingerido, e `preco_referencia` é o fallback para
        quando `mercado ingerir` ainda não rodou. O seed não pode depender de ingestão:
        na F16 um golden dependia de haver CDI ingerido e divergia entre o dev e um banco
        limpo. Aqui a carteira nasce nos dois.
      · `valor_brl` — para o que não tem cotação (CDB, LCI, saldo). Quantidade fica NULL,
        que é o registro correto: um CDB não tem "quantas unidades".
    """
    codigo: str
    nome: str
    kind: str                        # market.instrument_kind
    classe: str                      # market.asset_classes.code
    emissor: str | None = None       # `codigo` de um Emissor do mesmo arquétipo
    quantidade: float | None = None
    preco_referencia: float | None = None
    valor_brl: float | None = None
    preco_medio: float | None = None
    liquidez_dias: int | None = None
    taxa_adm_aa: float | None = None
    maturidade: date | None = None
    negociado_em_bolsa: bool = False


@dataclass(frozen=True)
class Arquetipo:
    nome: str
    titulo: str
    forca: str                      # o comportamento do motor que esta persona existe para forçar
    idade: int
    plano: str = "essential"
    renda_fixa: float = 0.0
    renda_variavel: float = 0.0
    renda_p10: float = 0.0          # piso observado do variável
    fontes_de_renda: int = 1
    despesa_total: float = 0.0
    despesa_essencial: float = 0.0
    fixo_contratado: float = 0.0
    reserva: float = 0.0
    dependentes: int = 0
    seguro_vida: float | None = None      # None = não informado (≠ zero)
    investido: float = 0.0
    # Carteira aberta posição a posição. Quando vazia, `investido` continua sendo o
    # agregado declarado — é assim que vivem os seis arquétipos, e a migration 53 aceita
    # agregado sem detalhe de propósito. Quando preenchida, ela MANDA: o rollup passa a
    # ser derivado dela e `investido` é ignorado, porque havendo detalhe o agregado é o
    # detalhe.
    emissores: tuple[Emissor, ...] = ()
    carteira: tuple[Posicao, ...] = ()
    imoveis: float = 0.0
    dividas: tuple[Divida, ...] = ()
    objetivo: tuple[float, int] | None = None   # (valor alvo, prazo em meses)
    # Vários objetivos: é o que exercita a regra "a MENOR probabilidade entre os ativos"
    # (F17). `objetivo` continua valendo sozinho — nenhum arquétipo existente muda.
    objetivos: tuple[tuple[str, float, int], ...] = ()   # (nome, valor alvo, prazo em meses)
    # Fatos que o cliente DECLAROU, gravados como confirmados de `formulario`. É o que
    # permite existir uma conta em que Destino e Comportamento saem com nota — hoje nenhuma
    # persona declara `destino.idade_aposentadoria` nem `comportamento.*`, e as duas famílias
    # ficam sem base em todas elas.
    fatos_declarados: tuple[tuple[str, object], ...] = ()

    @property
    def renda_total(self) -> float:
        return self.renda_fixa + self.renda_variavel

    def uid(self, papel: str) -> str:
        return str(uuid.uuid5(NS, f"{self.nome}:{papel}"))

    @property
    def email(self) -> str:
        return f"{self.nome}@teste.local"


ARQUETIPOS: tuple[Arquetipo, ...] = (
    Arquetipo(
        nome="endividado_rotativo",
        titulo="Endividado no rotativo",
        forca="Fundação crítica: reserva de meio mês e rotativo a 400% a.a. ⇒ todos os scores desativados",
        idade=34, plano="free",
        renda_fixa=6500, renda_p10=6500, fontes_de_renda=1,
        despesa_total=6200, despesa_essencial=4800, fixo_contratado=3400,
        reserva=2400, dependentes=1,
        dividas=(Divida("cartao_rotativo", "Cartão rotativo", 18000, 4.00, 1600),
                 Divida("cheque_especial", "Cheque especial", 4200, 1.80, 400)),
        investido=1200,
    ),
    Arquetipo(
        nome="dependentes_sem_seguro",
        titulo="Provedor sem proteção",
        forca="Três dependentes, financiamento aberto e seguro NÃO INFORMADO: a lacuna vira pergunta, não número",
        idade=41,
        renda_fixa=14000, renda_p10=14000, fontes_de_renda=1,
        despesa_total=10500, despesa_essencial=7800, fixo_contratado=6200,
        reserva=32000, dependentes=3, seguro_vida=None,
        investido=95000, imoveis=620000,
        dividas=(Divida("financiamento_imovel", "Financiamento do apartamento", 380000, 0.098, 4100),),
        objetivo=(400000, 180),
    ),
    Arquetipo(
        nome="autonomo_volatil",
        titulo="Autônoma de renda variável",
        forca="Piso p10 muito abaixo da média e fonte única: concentração de renda em 1,0",
        idade=37,
        renda_fixa=0, renda_variavel=13500, renda_p10=4200, fontes_de_renda=1,
        despesa_total=8900, despesa_essencial=6100, fixo_contratado=4900,
        reserva=54000, dependentes=0, seguro_vida=0.0,
        investido=180000,
        objetivo=(1200000, 240),
    ),
    Arquetipo(
        nome="aposentado",
        titulo="Aposentado com patrimônio",
        forca="Horizonte curto e fluxo apertado sobre estoque alto — o inverso do jovem",
        idade=68,
        renda_fixa=9200, renda_p10=9200, fontes_de_renda=3,
        despesa_total=8400, despesa_essencial=6900, fixo_contratado=5200,
        reserva=110000, dependentes=1, seguro_vida=150000,
        investido=1450000, imoveis=890000,
        objetivo=(200000, 24),
    ),
    Arquetipo(
        nome="jovem_sem_patrimonio",
        titulo="Primeiro emprego",
        forca="Cobertura baixíssima: quase tudo indisponível, e a tela precisa dizer isso sem parecer quebrada",
        idade=24, plano="free",
        renda_fixa=3800, renda_p10=3800, fontes_de_renda=1,
        despesa_total=3500, despesa_essencial=3100, fixo_contratado=2400,
        reserva=1500, dependentes=0,
        investido=0,
    ),
    Arquetipo(
        nome="patrimonio_alto_sem_fluxo",
        titulo="Patrimônio herdado, fluxo apertado",
        forca="Estoque excelente com fluxo ruim: o caso que uma nota geral média esconderia",
        idade=45,
        renda_fixa=7000, renda_p10=7000, fontes_de_renda=1,
        despesa_total=6800, despesa_essencial=5900, fixo_contratado=5400,
        reserva=18000, dependentes=2, seguro_vida=0.0,
        investido=2100000, imoveis=1300000,
        objetivo=(500000, 120),
    ),
)

POR_NOME = {a.nome: a for a in ARQUETIPOS}


# =============================================================================
# Carteira aberta — emissores, instrumentos, taxas e posições
# =============================================================================
async def _gravar_carteira(conn: AsyncConnection, a: Arquetipo, sid: str, hoje: date
                           ) -> tuple[float, float, float, dict, dict]:
    """Grava a carteira posição a posição e devolve o rollup DERIVADO dela.

    Devolve `(total, investido, caixa, by_asset_class, by_account)`. Sem carteira declarada,
    devolve o agregado do arquétipo e não escreve nada — é como vivem os seis arquétipos da
    F16, e a migration 53 aceita agregado sem detalhe de propósito.

    O catálogo (`market.issuers` / `instruments` / `fund_facts`) é GLOBAL, não do escopo: a
    Petrobras é a mesma para todo mundo. Por isso o enriquecimento é por `coalesce` — o que
    já estava preenchido não é sobrescrito, e `is_in_universe` nunca é tocado (quem decide a
    cobertura de análise é `seeds/dev.sql`, não uma persona).
    """
    if not a.carteira:
        return a.investido, a.investido, 0.0, {}, {}

    # --- emissores. Matriz primeiro: `parent_issuer_id` é FK para a própria tabela.
    ids_emissor: dict[str, str] = {}
    for e in sorted(a.emissores, key=lambda e: e.matriz is not None):
        eid = a.uid(f"emissor:{e.codigo}")
        ids_emissor[e.codigo] = eid
        await conn.execute(
            "insert into market.issuers (id, name, kind, fgc_covered, parent_issuer_id) "
            "values (%s, %s, %s, %s, %s) on conflict (id) do update set "
            "name = excluded.name, kind = excluded.kind, fgc_covered = excluded.fgc_covered, "
            "parent_issuer_id = excluded.parent_issuer_id",
            (eid, e.nome, e.kind, e.fgc_covered,
             ids_emissor.get(e.matriz) if e.matriz else None))

    conta = a.uid("conta:carteira")
    await conn.execute(
        "insert into wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) "
        "values (%s, %s, 'corretora', 'Carteira de investimentos', 'Corretora de demonstração', %s) "
        "on conflict (id) do nothing", (conta, sid, date(hoje.year - 5, 3, 1)))

    total = caixa = 0.0
    por_classe: dict[str, float] = {}

    for p in a.carteira:
        # `do update` (e não `do nothing`) porque o RETURNING precisa devolver o id também
        # quando o instrumento já existe — PETR4 e VALE3 vêm de `seeds/dev.sql` sem emissor,
        # e é aqui que eles ganham um.
        cur = await conn.execute(
            "insert into market.instruments (kind, name, ticker, asset_class_code, issuer_id, "
            "  liquidity_days, maturity_date, is_in_universe) "
            "values (%s::market.instrument_kind, %s, %s, %s, %s, %s, %s, false) "
            "on conflict (ticker) where ticker is not null do update set "
            "  issuer_id = coalesce(market.instruments.issuer_id, excluded.issuer_id), "
            "  liquidity_days = coalesce(market.instruments.liquidity_days, excluded.liquidity_days), "
            "  maturity_date = coalesce(market.instruments.maturity_date, excluded.maturity_date) "
            "returning id::text",
            (p.kind, p.nome, p.codigo, p.classe,
             ids_emissor.get(p.emissor) if p.emissor else None,
             p.liquidez_dias, p.maturidade))
        iid = (await cur.fetchone())[0]

        if p.taxa_adm_aa is not None:
            await conn.execute(
                "insert into market.fund_facts (instrument_id, management_fee, data_as_of) "
                "values (%s, %s, %s) on conflict (instrument_id) do update set "
                "management_fee = excluded.management_fee, data_as_of = excluded.data_as_of",
                (iid, p.taxa_adm_aa, hoje))

        # O preço ingerido manda; `preco_referencia` é o fallback que faz o seed funcionar
        # num banco onde `mercado ingerir` ainda não rodou.
        preco = None
        if p.quantidade is not None:
            cur = await conn.execute(
                "select value::float from market.prices where instrument_id = %s "
                "order by price_date desc limit 1", (iid,))
            achado = await cur.fetchone()
            preco = achado[0] if achado else p.preco_referencia
            if preco is None:
                raise ValueError(
                    f"{a.nome}/{p.codigo}: posição por quantidade sem preço ingerido e sem "
                    f"`preco_referencia` — o seed não pode inventar um valor.")
            valor = round(p.quantidade * preco, 2)
        else:
            if p.valor_brl is None:
                raise ValueError(f"{a.nome}/{p.codigo}: posição sem `quantidade` nem `valor_brl`.")
            valor = round(p.valor_brl, 2)

        await conn.execute(
            "insert into wealth.holdings_snapshots (scope_id, account_id, instrument_id, "
            "  as_of_date, quantity, unit_price, value_brl, avg_cost, origin) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, 'manual') "
            "on conflict (as_of_date, scope_id, account_id, instrument_id, origin) do nothing",
            (sid, conta, iid, hoje, p.quantidade, preco, valor, p.preco_medio))

    # A carteira do dia pode conter MAIS do que o arquétipo declara, e o operador precisa
    # saber. `holdings_snapshots` é append-only: mudar a carteira declarada (renomear o
    # código de um instrumento, tirar uma linha) não apaga o que já foi gravado hoje, e a
    # posição antiga continua somando. Não é erro do seed — é o que série append-only
    # significa, e a correção é a de sempre: linha nova em data nova, ou seja, rodar o seed
    # no dia seguinte. O que não pode é acontecer em silêncio.
    cur = await conn.execute(
        "select coalesce(i.ticker, i.name, h.instrument_id::text) "
        "  from wealth.v_latest_holdings h "
        "  left join market.instruments i on i.id = h.instrument_id "
        " where h.scope_id = %s and coalesce(i.ticker, '') <> all(%s)",
        (sid, [p.codigo for p in a.carteira]))
    sobrando = [r[0] for r in await cur.fetchall()]
    if sobrando:
        log.warning(
            "%s: a carteira do dia tem %d posição(ões) fora do arquétipo (%s). "
            "Snapshot é append-only: elas saem sozinhas no próximo dia.",
            a.nome, len(sobrando), ", ".join(sorted(sobrando)))

    # O ROLLUP SAI DA TABELA, NÃO DA LISTA EM MEMÓRIA — e a diferença não é estilo.
    # `holdings_snapshots` é append-only: mexer na carteira declarada aqui (trocar o código de
    # um instrumento, tirar uma linha) NÃO apaga a posição já gravada no dia. Somando a lista,
    # o rollup afirmaria um total que a tabela não sustenta, e a migration 53 recusaria a
    # escrita — que foi exatamente o que aconteceu na primeira execução deste seed depois de
    # um instrumento ser renomeado. O rollup é, por definição, a soma do que está lá.
    cur = await conn.execute(
        "select coalesce(sum(h.value_brl), 0)::float, "
        "       coalesce(sum(h.value_brl) filter (where i.asset_class_code = 'caixa'), 0)::float "
        "  from wealth.v_latest_holdings h "
        "  left join market.instruments i on i.id = h.instrument_id "
        " where h.scope_id = %s", (sid,))
    total, caixa = await cur.fetchone()
    cur = await conn.execute(
        "select coalesce(i.asset_class_code, 'outros'), sum(h.value_brl)::float "
        "  from wealth.v_latest_holdings h "
        "  left join market.instruments i on i.id = h.instrument_id "
        " where h.scope_id = %s group by 1", (sid,))
    por_classe = {classe: round(valor, 2) for classe, valor in await cur.fetchall()}

    total, caixa = round(total, 2), round(caixa, 2)
    return total, round(total - caixa, 2), caixa, por_classe, {"corretora": total}


# =============================================================================
# Inserção — idempotente por uuid5, uma transação por persona
# =============================================================================
async def aplicar(conn: AsyncConnection, a: Arquetipo) -> dict[str, str]:
    """Cria (ou atualiza) a persona. Devolve {user_id, scope_id}."""
    uid, sid = a.uid("user"), a.uid("scope")
    hoje = date.today()
    mes = date(hoje.year, hoje.month, 1)

    await conn.execute(
        "insert into identity.users (id, email, full_name, status, birth_date) "
        "values (%s, %s, %s, 'active', %s) "
        "on conflict (id) do update set full_name = excluded.full_name, birth_date = excluded.birth_date",
        (uid, a.email, a.titulo, date(hoje.year - a.idade, 6, 15)))
    await conn.execute(
        "insert into identity.scopes (id, kind, display_name, owner_user_id) "
        "values (%s, 'personal', %s, %s) on conflict (id) do nothing",
        (sid, a.titulo, uid))
    await conn.execute(
        "insert into identity.scope_members (scope_id, user_id, role, accepted_at) "
        "values (%s, %s, 'owner', now()) on conflict do nothing", (sid, uid))

    # --- família. Tudo daqui em diante é idempotente por chave determinística (uuid5):
    # `delete` é recusado nas append-only, e a migration 28 revogou DELETE até para o
    # serviço. A persona respeita a mesma disciplina que qualquer escrita do produto.
    # --- família: um titular mais os dependentes declarados
    await conn.execute(
        "insert into household.members (id, scope_id, user_id, relation, display_name, "
        "  birth_year, dependency, contributes_income, in_consolidation) "
        "values (%s, %s, %s, 'titular', %s, %s, 'nao', true, true) on conflict (id) do nothing",
        (a.uid("membro:titular"), sid, uid, a.titulo, hoje.year - a.idade))
    for i in range(a.dependentes):
        await conn.execute(
            "insert into household.members (id, scope_id, relation, display_name, birth_year, "
            "  dependency, contributes_income, in_consolidation) "
            "values (%s, %s, 'filho', %s, %s, 'total', false, true) on conflict (id) do nothing",
            (a.uid(f"membro:{i}"), sid, f"Dependente {i + 1}", hoje.year - 10 - i))

    # --- renda
    for i in range(a.fontes_de_renda):
        fatia = a.renda_total / a.fontes_de_renda
        variavel = (a.renda_variavel / a.renda_total) if a.renda_total else 0.0
        await conn.execute(
            # `monthly_gross_brl` é GERADA a partir de gross_amount_brl × frequência —
            # escrever nela é recusado pelo banco, e é assim que se garante que o número
            # mensal nunca diverge da fonte.
            "insert into budget.income_sources (id, scope_id, member_id, kind, stability, "
            "  frequency, gross_amount_brl, variable_share, is_active) "
            "values (%s, %s, %s, %s::budget.income_kind, %s::budget.income_stability, "
            "        'mensal', %s, %s, true) on conflict (id) do nothing",
            (a.uid(f"renda:{i}"), sid, a.uid("membro:titular"),
             "aposentadoria_inss" if a.idade >= 65 else ("autonomo" if variavel > 0.5 else "salario_clt"),
             # `fixo` EXIGE parte variável zero (CONSTRAINT fixed_has_no_variable_part, 24).
             # A regra antiga era `variavel > 0.5`, e ela quebrava no primeiro caso realista
             # de CLT com bônus: 20% de parte variável virava `fixo` com share 0,2 e o banco
             # recusava. Nenhum arquétipo existente muda — todos têm parte variável 0 ou > 0,5.
             "fixo" if variavel == 0 else "variavel", fatia, variavel))

    await conn.execute(
        "insert into budget.income_summaries (scope_id, month, fixed_brl, variable_brl, "
        "  variable_p10_brl, committable_brl, months_observed, top_source_share) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (scope_id, month) do update set "
        "fixed_brl = excluded.fixed_brl, variable_brl = excluded.variable_brl, "
        "variable_p10_brl = excluded.variable_p10_brl, committable_brl = excluded.committable_brl",
        (sid, mes, a.renda_fixa, a.renda_variavel, a.renda_p10,
         a.renda_fixa + a.renda_p10 if a.renda_variavel else a.renda_fixa,
         MESES_DE_ORCAMENTO, round(1.0 / a.fontes_de_renda, 4)))

    # --- orçamento: 12 meses fechados, com leve variação para não virar linha reta
    for k in range(MESES_DE_ORCAMENTO):
        m = date(mes.year - (1 if mes.month - k <= 0 else 0),
                 (mes.month - k - 1) % 12 + 1, 1)
        ajuste = 1 + ((k % 3) - 1) * 0.03
        await conn.execute(
            "insert into budget.monthly_summaries (scope_id, month, income_brl, expense_brl, "
            "  essential_expense_brl) values (%s, %s, %s, %s, %s) "
            "on conflict (scope_id, month) do update set income_brl = excluded.income_brl, "
            "expense_brl = excluded.expense_brl, essential_expense_brl = excluded.essential_expense_brl",
            (sid, m, round(a.renda_total * ajuste, 2), round(a.despesa_total * ajuste, 2),
             round(a.despesa_essencial * ajuste, 2)))

    if a.fixo_contratado:
        await conn.execute(
            "insert into budget.recurring_items (id, scope_id, flow, description, amount_brl, "
            "  starts_on, is_active) values (%s, %s, 'saida', 'Gastos fixos contratados', %s, %s, true) on conflict (id) do nothing",
            (a.uid("fixo"), sid, a.fixo_contratado, date(hoje.year - 1, 1, 1)))

    # A reserva precisa EXISTIR como saldo, não como número no arquétipo: a derivação a lê
    # de `reserve_settings.reserve_account_ids` × `wealth.account_balances`. Sem esta conta,
    # `protecao.reserva_atual` nunca nasce — e foi assim que a primeira leitura das personas
    # mostrou Proteção com 0% de cobertura em todas elas.
    conta = a.uid("conta:reserva")
    await conn.execute(
        "insert into wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) "
        "values (%s, %s, 'corretora', 'Reserva de emergência', 'Instituição de demonstração', %s) "
        "on conflict (id) do nothing", (conta, sid, date(hoje.year - 2, 1, 1)))
    # append-only (trigger da 05): `do nothing`, nunca `do update` — o saldo do dia é
    # registro, e o teste de sabotagem T-append-only recusaria a atualização de todo jeito.
    await conn.execute(
        "insert into wealth.account_balances (account_id, scope_id, as_of_date, balance, "
        "  balance_brl, origin) values (%s, %s, %s, %s, %s, 'manual') "
        "on conflict (account_id, as_of_date, origin) do nothing",
        (conta, sid, hoje, a.reserva, a.reserva))
    await conn.execute(
        "insert into budget.reserve_settings (scope_id, target_months, reserve_account_ids) "
        "values (%s, 6.0, %s::uuid[]) on conflict (scope_id) do update "
        "set reserve_account_ids = excluded.reserve_account_ids", (sid, [conta]))

    # --- dívidas
    for i, d in enumerate(a.dividas):
        await conn.execute(
            "insert into budget.debts (id, scope_id, kind, description, outstanding_brl, "
            "  annual_rate, monthly_payment_brl, is_expensive) "
            "values (%s, %s, %s::budget.debt_kind, %s, %s, %s, %s, %s) on conflict (id) do nothing",
            (a.uid(f"divida:{i}"), sid, d.kind, d.descricao, d.saldo, d.taxa_anual,
             d.parcela, d.taxa_anual > 0.20))

    # --- carteira aberta (quando o arquétipo declara uma)
    total, investido, caixa, por_classe, por_conta = await _gravar_carteira(conn, a, sid, hoje)

    # --- patrimônio: snapshot financeiro + imóvel como bem não financeiro
    # A ORDEM IMPORTA e agora é imposta pelo banco: a migration 53 recusa um rollup que
    # discorde das posições do mesmo dia, então `_gravar_carteira` precisa ter rodado antes.
    await conn.execute(
        "insert into wealth.portfolio_snapshots (scope_id, as_of_date, total_brl, invested_brl, "
        "  cash_brl, by_asset_class, by_account) values (%s, %s, %s, %s, %s, %s, %s) "
        "on conflict (scope_id, as_of_date) do update set "
        "total_brl = excluded.total_brl, invested_brl = excluded.invested_brl, "
        "cash_brl = excluded.cash_brl, by_asset_class = excluded.by_asset_class, "
        "by_account = excluded.by_account",
        (sid, hoje, total, investido, caixa, Jsonb(por_classe), Jsonb(por_conta)))

    if a.imoveis:
        await conn.execute(
            "insert into estate.assets (id, scope_id, owner_member_id, kind, label, "
            "  ownership_share, liquidity, status, also_in_wealth) "
            "values (%s, %s, %s, 'imovel_residencial', 'Imóvel residencial', 1.0, "
            "        'iliquido', 'ativo', false) on conflict (id) do nothing",
            (a.uid("imovel"), sid, a.uid("membro:titular")))
        await conn.execute(
            "insert into estate.valuations (id, asset_id, scope_id, as_of_date, value_brl, "
            "  method, confidence) values (%s, %s, %s, %s, %s, 'declarado', 0.7) on conflict (id) do nothing",
            (a.uid("aval"), a.uid("imovel"), sid, hoje, a.imoveis))

    # --- assinatura
    # `plano` existia no arquétipo desde a F16 e NINGUÉM o escrevia: sem linha em
    # `billing.subscriptions`, `plano_do_escopo` devolve 'free' e as tools com
    # `min_plan='essential'` ficam invisíveis para a persona. Campo sem produtor é a mesma
    # armadilha do `foundation_status` — só que aqui ela escondia metade do catálogo de tools.
    if a.plano != "free":
        await conn.execute(
            "insert into billing.subscriptions (id, scope_id, payer_user_id, plan_code, "
            "  interval, status, current_period_start, current_period_end) "
            "values (%s, %s, %s, %s, 'monthly', 'active', now(), now() + interval '30 days') "
            "on conflict (id) do update set plan_code = excluded.plan_code, status = 'active'",
            (a.uid("assinatura"), sid, uid, a.plano))

    # --- fatos declarados pelo cliente (confirmados, fonte `formulario`)
    for chave, valor in a.fatos_declarados:
        cur = await conn.execute(
            "select subject_kind::text, attribute, value_type::text, unit "
            "from context.fact_definitions where fact_key = %s and is_active", (chave,))
        definicao = await cur.fetchone()
        if definicao is None:
            continue
        subject_kind, attribute, tipo, unidade = definicao
        if tipo == "booleano":
            bruto = {"bool": bool(valor)}
        elif tipo == "texto":
            bruto = {"text": str(valor)}
        elif tipo == "data":
            bruto = {"date": str(valor)}
        else:
            bruto = {"amount": float(valor)}
        # C22a: asserção NASCE `declarado`; confirmar é um segundo ato, com `confirmed_by`.
        # É o gate epistêmico do projeto e vale também para seed — o mesmo caminho de
        # `confirmar_seguro`. Gravar direto como confirmado seria o seed mentindo sobre a
        # procedência do dado, que é justamente o que a coluna existe para impedir.
        cur = await conn.execute(
            "select 1 from context.assertions where scope_id = %s and fact_key = %s "
            "and status = 'confirmado' and superseded_at is null", (sid, chave))
        if await cur.fetchone():
            continue
        async with conn.transaction():
            cur = await conn.execute(
                "insert into context.assertions (scope_id, user_id, fact_key, subject_kind, "
                "  attribute, value, unit, modality, confidence, source) "
                "values (%s, %s, %s, %s::context.subject_kind, %s, %s, %s, 'fato', 0.95, "
                "  'formulario') returning id::text",
                (sid, uid, chave, subject_kind, attribute, Jsonb(bruto), unidade))
            await conn.execute(
                "update context.assertions set status = 'confirmado', confirmed_at = now(), "
                "confirmed_by = %s where id = %s", (uid, (await cur.fetchone())[0]))

    # --- objetivo(s)
    for i, (rotulo, valor, prazo) in enumerate(a.objetivos):
        await conn.execute(
            "insert into planning.goals (id, scope_id, created_by, name, kind, "
            "  target_amount_brl, target_date, priority, status) "
            "values (%s, %s, %s, %s, 'outro', %s, %s, %s, 'ativa') on conflict (id) do nothing",
            (a.uid(f"objetivo:{i}"), sid, uid, rotulo, valor,
             date(hoje.year + prazo // 12, hoje.month, 1), i + 1))

    if a.objetivo:
        valor, prazo = a.objetivo
        await conn.execute(
            "insert into planning.goals (id, scope_id, created_by, name, kind, "
            "  target_amount_brl, target_date, priority, status) "
            "values (%s, %s, %s, 'Objetivo principal', 'outro', %s, %s, 1, 'ativa') on conflict (id) do nothing",
            (a.uid("objetivo"), sid, uid, valor,
             date(hoje.year + prazo // 12, hoje.month, 1)))

    return {"user_id": uid, "scope_id": sid, "email": a.email}


async def aplicar_todas(conn: AsyncConnection) -> list[dict[str, str]]:
    return [await aplicar(conn, a) for a in ARQUETIPOS]


# =============================================================================
# O fato que a derivação NÃO alcança
# =============================================================================
async def confirmar_seguro(conn: AsyncConnection, a: Arquetipo) -> bool:
    """Cobertura de seguro entra como fato CONFIRMADO, não derivado — não há tabela de apólice.

    `seguro_vida = None` significa **não informado**, e é assim que
    `dependentes_sem_seguro` prova que o indicador fica indisponível em vez de afirmar uma
    lacuna sobre o que não se sabe. `0.0` significa "não tem", que é informação.
    """
    if a.seguro_vida is None:
        return False
    sid, uid = a.uid("scope"), a.uid("user")
    cur = await conn.execute(
        "select subject_kind::text, attribute, unit from context.fact_definitions "
        "where fact_key = 'protecao.cobertura_vida'")
    subject_kind, attribute, unit = await cur.fetchone()
    cur = await conn.execute(
        "select id::text from context.assertions where scope_id = %s "
        "and fact_key = 'protecao.cobertura_vida' and status = 'confirmado' "
        "and superseded_at is null", (sid,))
    if await cur.fetchone():
        return False
    cur = await conn.execute(
        "insert into context.assertions (scope_id, user_id, fact_key, subject_kind, attribute, "
        "  value, unit, modality, source) "
        "values (%s, %s, 'protecao.cobertura_vida', %s::context.subject_kind, %s, %s, %s, "
        "        'fato', 'formulario') returning id::text",
        (sid, uid, subject_kind, attribute, Jsonb({"amount": a.seguro_vida}), unit))
    aid = (await cur.fetchone())[0]
    await conn.execute(
        "update context.assertions set status = 'confirmado', confirmed_at = now(), "
        "confirmed_by = %s where id = %s", (uid, aid))
    return True
