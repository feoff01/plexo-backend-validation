"""
F19 — a carteira aberta posição a posição, e a reconciliação que a tornou confiável.

O QUE ESTES TESTES PROVAM, E POR QUE CADA UM EXISTE

  · o seed da conta de demonstração escreve POSIÇÕES, não só um agregado — era a ausência
    disso que fazia o Assessor responder "não há posição registrada no escopo" a quem tinha
    R$ 780.000 declarados no rollup;
  · o rollup é DERIVADO das posições e o banco recusa qualquer outro (migration 53);
  · a tool devolve cada ativo com peso medido sobre a carteira INTEIRA, mesmo sob filtro —
    "PETR4 é 9% da sua carteira" e "PETR4 é 23% das suas ações" são frases diferentes, e a
    que importa para risco é a primeira;
  · reavaliação a preço de fechamento só existe quando há quantidade E preço: um CDB
    declarado em reais não tem "valor no fechamento", e devolver o valor registrado nesse
    campo faria a tela afirmar que o CDB foi reavaliado hoje;
  · a data do preço é a MAIS ANTIGA entre as posições precificadas, não a mais recente;
  · a RLS continua valendo: posição de outro escopo não aparece sob papel real;
  · a parte pura está travada por golden master.

NADA AQUI DEPENDE DE DADO COMMITADO. Os três primeiros aplicam a conta de demonstração
dentro da própria transação (`aplicar(conn, HELENA)`), como `test_f16_personas.py` já fazia
com os seis arquétipos; o resto constrói uma carteira controlada. A primeira versão LIA o
escopo da Helena do banco e quebrou no CI, que semeia só `dev.sql` e `persona.sql` — ver o
comentário longo antes do primeiro teste.

Os números exatos vivem nas fixturas próprias, e não na Helena: a carteira dela é avaliada
pelo último fechamento ingerido e se move quando o mercado se move. Congelar o número dela
seria congelar o relógio, que é o defeito que a F17 levou meia sessão para achar.
"""
from __future__ import annotations

import json
import pathlib
import uuid

import httpx
import pytest
import pytest_asyncio

from app.seeds.conta_teste import CARTEIRA, HELENA
from app.seeds.personas import aplicar
from app.tools.assessor.posicoes import (
    PosicoesParams, PosicoesResolvidas, calcular_posicoes, preparar_posicoes,
)
from app.tools.executor import ToolContext, ToolInsumoFaltante

GOLDEN = pathlib.Path(__file__).parent / "golden"


# =============================================================================
# O seed da conta de demonstração — aplicado DENTRO da transação do teste
#
# A primeira versão destes três testes LIA o escopo da Helena do banco, contando que
# `plexo seed conta-teste` tivesse rodado. Passou aqui e **quebrou no CI na primeira
# execução**, porque `tools/preparar_ambiente.py` aplica só `dev.sql` e `persona.sql` — a
# conta de demonstração é um seed Python, e é assim de propósito: o docstring de
# `conta_teste.py` diz que ela existe para "alguém entrar nela e mexer", e golden não pode
# depender de dado que alguém vai editar.
#
# É o MESMO defeito que este projeto já registrou três vezes ("teste que depende do que
# sobrou de outra execução só ainda não falhou") — e que eu tinha acabado de documentar como
# pendência da persona `autonomo_volatil` quando o cometi aqui.
#
# A correção é a que `test_f16_personas.py` já usava: aplicar o arquétipo dentro da
# transação, como ele faz com as seis personas. O teste passa a provar exatamente o que
# alega — que o SEED produz carteira, rollup reconciliado e emissor consolidado — sem
# depender de nada estar commitado, e sem deixar resíduo.
# =============================================================================
async def test_o_seed_da_conta_de_demonstracao_abre_a_carteira(db):
    """O defeito de 2026-08-30, virado teste: a conta tinha R$ 780.000 e ZERO posições.

    A tool de composição lê `wealth.holdings_snapshots`; o prompt do agente lê o rollup.
    Com o detalhe vazio, o agente recebia um número no contexto e "não há posição" da tool,
    no mesmo turno.
    """
    async with db.service_session() as conn:
        ids = await aplicar(conn, HELENA)
        cur = await conn.execute(
            "select i.ticker, i.kind::text from wealth.v_latest_holdings h "
            "  join market.instruments i on i.id = h.instrument_id "
            " where h.scope_id = %s", (ids["scope_id"],))
        gravadas = await cur.fetchall()

    presentes = {t for t, _ in gravadas}
    faltando = {p.codigo for p in CARTEIRA} - presentes
    # CONTINÊNCIA, não igualdade: `holdings_snapshots` é append-only, então o dia pode conter
    # posição de uma versão anterior do arquétipo — é o que acontece no banco de dev depois de
    # um instrumento ser renomeado, e o próprio seed avisa no log. Exigir igualdade faria este
    # teste passar no CI (banco limpo) e falhar na máquina de quem desenvolve, que é o mesmo
    # defeito de acoplamento a estado, só que espelhado.
    assert not faltando, f"o seed não gravou estas posições declaradas: {sorted(faltando)}"
    acoes = sum(1 for t, kind in gravadas if kind == "acao")
    assert acoes >= 4, "sem ações individuais não há como responder 'devo vender minhas ações?'"


async def test_o_rollup_e_a_soma_das_posicoes(db):
    """A regra da migration 53 valendo sobre o seed inteiro: o agregado é o detalhe.

    Não é um teste de igualdade decorativo — é o invariante que impede o contexto do agente
    e a tool de afirmarem coisas diferentes sobre o mesmo patrimônio. E ele passa a ser
    exercitado pelo caminho real: se `_gravar_carteira` derivasse o rollup da lista em
    memória em vez da tabela, o trigger recusaria a escrita e o `aplicar` acima estouraria.
    """
    async with db.service_session() as conn:
        ids = await aplicar(conn, HELENA)
        cur = await conn.execute(
            "select p.total_brl::float, p.invested_brl::float, p.cash_brl::float, "
            "       (select coalesce(sum(h.value_brl), 0)::float from wealth.holdings_snapshots h "
            "         where h.scope_id = p.scope_id and h.as_of_date = p.as_of_date) "
            "  from wealth.portfolio_snapshots p "
            " where p.scope_id = %s order by p.as_of_date desc limit 1", (ids["scope_id"],))
        linha = await cur.fetchone()
    assert linha is not None, "o seed não gravou rollup nenhum"
    total, investido, caixa, soma = linha
    assert total == pytest.approx(soma, abs=0.01)
    assert investido + caixa == pytest.approx(total, abs=0.01)


async def test_o_conglomerado_consolida_na_view_que_nunca_tinha_sido_lida(db):
    """`diagnostics.v_issuer_concentration` existe desde a migration 15 e devolvia vazio para
    todo escopo, porque `market.issuers` estava vazia e nenhum instrumento tinha `issuer_id`.

    A consolidação por `parent_issuer_id` é o ponto: ação do banco, CDB do banco e LCI da
    financeira DO MESMO GRUPO são um risco de crédito só. Somados como três, cada um parece
    pequeno.
    """
    async with db.service_session() as conn:
        ids = await aplicar(conn, HELENA)
        cur = await conn.execute(
            "select issuer_name, exposure_brl::float, concentration_pct::float "
            "  from diagnostics.v_issuer_concentration where scope_id = %s "
            " order by exposure_brl desc limit 1", (ids["scope_id"],))
        maior = await cur.fetchone()
        cur = await conn.execute(
            "select max(h.value_brl)::float from wealth.v_latest_holdings h where h.scope_id = %s",
            (ids["scope_id"],))
        maior_posicao = (await cur.fetchone())[0]
    assert maior is not None, "nenhum emissor cadastrado — a concentração é incalculável"
    nome, exposicao, pct = maior
    # Três instrumentos do mesmo grupo. Se a consolidação não funcionasse, o maior emissor
    # seria o CDB sozinho e a exposição bateria com UMA posição.
    assert exposicao > maior_posicao, "a exposição do grupo não consolidou mais de uma posição"
    assert pct > 0.30, f"{nome} deveria ser a concentração que a conta existe para exibir"


# =============================================================================
# A tool — fixture própria, números exatos
# =============================================================================
async def _carteira_de_teste(db, escopos) -> None:
    """Carteira controlada dentro da transação: dois papéis com preço, um CDB sem cotação.

    Números escolhidos para que cada asserção adiante seja aritmética conferível à mão.
    """
    async with db.service_session() as conn:
        conta = str(uuid.uuid4())
        await conn.execute(
            "insert into wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) "
            "values (%s, %s, 'corretora', 'Corretora F19', 'Instituição F19', current_date - 100)",
            (conta, escopos.s1))
        emissor = str(uuid.uuid4())
        await conn.execute(
            "insert into market.issuers (id, name, kind, fgc_covered) "
            "values (%s, 'Banco F19', 'banco', true)", (emissor,))
        papeis = []
        for codigo, nome, kind, classe, iss in (
                ("F19AAA", "Papel F19 A", "acao", "acoes_br", None),
                ("F19BBB", "Papel F19 B", "acao", "acoes_br", None),
                ("F19CDB", "CDB F19", "cdb", "selic", emissor)):
            cur = await conn.execute(
                "insert into market.instruments (kind, name, ticker, asset_class_code, issuer_id, "
                "  liquidity_days) values (%s::market.instrument_kind, %s, %s, %s, %s, 2) "
                "returning id::text", (kind, nome, codigo, classe, iss))
            papeis.append((await cur.fetchone())[0])
        # Preços em DATAS DIFERENTES de propósito: é o que o teste da data mais antiga usa.
        await conn.execute(
            "insert into market.prices (price_date, instrument_id, kind, value, source_code) "
            "values (current_date - 1, %s, 'close', 20.00, 'b3'), "
            "       (current_date - 3, %s, 'close', 10.00, 'b3')", (papeis[0], papeis[1]))
        await conn.execute(
            "insert into wealth.holdings_snapshots (scope_id, account_id, instrument_id, as_of_date, "
            "  quantity, unit_price, value_brl, avg_cost, origin) values "
            "(%s, %s, %s, current_date, 3000, 20.00, 60000.00, 16.00, 'manual'), "
            "(%s, %s, %s, current_date, 2000, 10.00, 20000.00, 12.50, 'manual'), "
            "(%s, %s, %s, current_date, null, null, 20000.00, null, 'manual')",
            (escopos.s1, conta, papeis[0], escopos.s1, conta, papeis[1],
             escopos.s1, conta, papeis[2]))


async def _saida(db, escopos, **params):
    async with db.app_session(user_id=escopos.u1, scope_id=escopos.s1) as conn:
        ctx = ToolContext(conn=conn, scope_id=escopos.s1, conversation_id=None)
        resolvido = await preparar_posicoes(PosicoesParams(**params), ctx)
    return calcular_posicoes(resolvido)


async def test_posicoes_abre_cada_ativo_com_peso_e_resultado(db, escopos):
    """O que a composição por classe nunca deu: o ativo, e o que aconteceu com ele."""
    await _carteira_de_teste(db, escopos)
    saida = await _saida(db, escopos)

    assert saida.total_da_carteira_brl == 100000.00
    assert saida.itens == 3
    por_codigo = {p.codigo or p.nome: p for p in saida.posicoes}

    a = por_codigo["F19AAA"]
    assert a.share_pct == 60.00                       # 60.000 / 100.000
    assert a.valor_no_fechamento_brl == 60000.00      # 3.000 × 20,00
    assert a.variacao_sobre_preco_medio_pct == 25.00  # 20,00 / 16,00 − 1
    assert a.coberto_pelo_fgc is False

    b = por_codigo["F19BBB"]
    assert b.variacao_sobre_preco_medio_pct == -20.00  # 10,00 / 12,50 − 1 — uma no vermelho
    assert saida.maior_posicao == "F19AAA" and saida.maior_posicao_share_pct == 60.00


async def test_cdb_declarado_em_reais_nao_tem_valor_no_fechamento(db, escopos):
    """Sabotagem: devolver o valor registrado no campo de reavaliação faria a tela afirmar
    que um CDB foi reavaliado pelo pregão de ontem. Não foi: ele não tem cotação."""
    await _carteira_de_teste(db, escopos)
    saida = await _saida(db, escopos)
    cdb = next(p for p in saida.posicoes if p.tipo == "cdb")
    assert cdb.valor_registrado_brl == 20000.00
    assert cdb.valor_no_fechamento_brl is None
    assert cdb.variacao_sobre_preco_medio_pct is None
    assert cdb.codigo is None, "CDB não é papel de bolsa — exibir o código interno como ticker inventa mercado"
    assert cdb.coberto_pelo_fgc is True


async def test_fgc_e_do_instrumento_nao_do_emissor(db, escopos):
    """Sabotagem achada no primeiro smoke real: ITUB4 voltou como coberta pelo FGC.

    A cobertura depende de DUAS coisas — instituição associada E instrumento do tipo
    garantido. Lendo só `market.issuers.fgc_covered`, uma AÇÃO emitida por um banco entra
    como garantida. Não é cosmético: o teto de R$ 250 mil por instituição soma o que é
    coberto, e incluir a ação inflaria a exposição, fazendo o alerta disparar sobre um
    número que não existe — ou, pior, deixar de disparar quando o cliente vendesse a ação.
    """
    async with db.service_session() as conn:
        conta = str(uuid.uuid4())
        await conn.execute(
            "insert into wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) "
            "values (%s, %s, 'corretora', 'Corretora FGC', 'Instituição FGC', current_date - 10)",
            (conta, escopos.s1))
        banco = str(uuid.uuid4())
        await conn.execute(
            "insert into market.issuers (id, name, kind, fgc_covered) "
            "values (%s, 'Banco associado', 'banco', true)", (banco,))
        # MESMO emissor associado, dois instrumentos: um garantido, outro não.
        for codigo, nome, kind, classe in (("F19ACAO", "Ação do banco", "acao", "acoes_br"),
                                           ("F19CDB2", "CDB do banco", "cdb", "selic")):
            cur = await conn.execute(
                "insert into market.instruments (kind, name, ticker, asset_class_code, issuer_id) "
                "values (%s::market.instrument_kind, %s, %s, %s, %s) returning id::text",
                (kind, nome, codigo, classe, banco))
            iid = (await cur.fetchone())[0]
            await conn.execute(
                "insert into wealth.holdings_snapshots (scope_id, account_id, instrument_id, "
                "  as_of_date, value_brl, origin) values (%s, %s, %s, current_date, 50000, 'manual')",
                (escopos.s1, conta, iid))

    saida = await _saida(db, escopos)
    por_nome = {p.nome: p for p in saida.posicoes}
    assert por_nome["CDB do banco"].coberto_pelo_fgc is True
    assert por_nome["Ação do banco"].coberto_pelo_fgc is False, (
        "ação emitida por banco associado NÃO é coberta pelo FGC — a cobertura é do "
        "instrumento, não do emissor")


async def test_a_data_do_preco_e_a_mais_antiga_entre_as_posicoes(db, escopos):
    """Datar a carteira pela sua parte mais fresca é dizer que ela toda é daquele dia."""
    await _carteira_de_teste(db, escopos)
    saida = await _saida(db, escopos)
    async with db.service_session() as conn:
        cur = await conn.execute("select (current_date - 3)::text")
        mais_antiga = (await cur.fetchone())[0]
    assert saida.fechamento_em == mais_antiga
    assert "precos_de_datas_diferentes" in saida.avisos
    assert saida.posicao_em != saida.fechamento_em, "posição e preço são datas distintas"


async def test_o_filtro_muda_o_que_mostra_nunca_o_denominador(db, escopos):
    """A regra que evita a frase errada: sob filtro, o peso continua sobre a carteira inteira.

    Se o denominador virasse o recorte, "suas ações" apareceriam somando 100% e a
    concentração desapareceria exatamente na tela que existe para mostrá-la.
    """
    await _carteira_de_teste(db, escopos)
    saida = await _saida(db, escopos, apenas_grupo="renda_variavel")
    assert saida.itens == 2
    assert saida.total_da_carteira_brl == 100000.00          # a carteira inteira
    assert saida.total_listado_brl == 80000.00               # o recorte
    assert sum(p.share_pct for p in saida.posicoes) == 80.00
    assert "recorte_da_carteira" in saida.avisos


async def test_filtro_sem_posicao_diz_o_que_existe(db, escopos):
    """Pedir uma classe que o cliente não tem devolve insumo faltante COM a lista do que há —
    senão o agente pergunta de novo o que a tool já sabia responder."""
    await _carteira_de_teste(db, escopos)
    with pytest.raises(ToolInsumoFaltante) as erro:
        await _saida(db, escopos, apenas_classe="cripto")
    assert "acoes_br" in str(erro.value) and "selic" in str(erro.value)


async def test_carteira_vazia_e_insumo_faltante_nunca_zero(db, escopos):
    """Zero posições não é uma carteira de R$ 0,00: é uma carteira desconhecida."""
    with pytest.raises(ToolInsumoFaltante) as erro:
        await _saida(db, escopos)
    assert "não há posição registrada" in str(erro.value)


async def test_posicao_de_outro_escopo_nao_aparece(db, escopos):
    """RLS sob papel real (`plexo_app`), não sob o administrador, que tem BYPASSRLS."""
    await _carteira_de_teste(db, escopos)
    async with db.service_session() as conn:
        conta = str(uuid.uuid4())
        await conn.execute(
            "insert into wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) "
            "values (%s, %s, 'corretora', 'Da vizinha', 'Outra', current_date - 10)", (conta, escopos.s2))
        cur = await conn.execute(
            "insert into market.instruments (kind, name, ticker, asset_class_code) "
            "values ('acao', 'Papel da vizinha', 'F19ZZZ', 'acoes_br') returning id::text")
        iid = (await cur.fetchone())[0]
        await conn.execute(
            "insert into wealth.holdings_snapshots (scope_id, account_id, instrument_id, as_of_date, "
            "  value_brl, origin) values (%s, %s, %s, current_date, 999999, 'manual')",
            (escopos.s2, conta, iid))

    saida = await _saida(db, escopos)
    assert saida.total_da_carteira_brl == 100000.00
    assert all(p.codigo != "F19ZZZ" for p in saida.posicoes)


# =============================================================================
# Parte pura
# =============================================================================
def test_posicoes_golden():
    """Parte pura travada: mudança de número exige justificativa no commit."""
    dados = json.loads((GOLDEN / "planejamento_posicoes_carteira.json").read_text(encoding="utf-8"))
    saida = calcular_posicoes(PosicoesResolvidas.model_validate(dados["resolvido"]))
    assert saida.model_dump() == dados["esperado"]


def test_bloco_das_posicoes_tem_fonte_e_nao_e_simulacao():
    """Sem proveniência, sem bloco (regra da F11). E a nota não pode falar de projeção:
    descrever a carteira não é simular nada."""
    from app.agents.blocos import blocos_de

    dados = json.loads((GOLDEN / "planejamento_posicoes_carteira.json").read_text(encoding="utf-8"))
    blocos = blocos_de("planejamento.posicoes_carteira", dados["esperado"],
                       execution_id=str(uuid.uuid4()))
    assert blocos, "a tool devolve carteira — precisa de mapeador em blocos.py"
    for bloco in blocos:
        assert bloco["proveniencia"]["fonte"] and bloco["proveniencia"]["as_of"]
        assert bloco["nota"] and "projeção de rentabilidade" not in bloco["nota"]

    golden = json.loads((GOLDEN / "blocos_planejamento_posicoes_carteira.json").read_text(encoding="utf-8"))
    assert [{**b, "id": None} for b in blocos] == [{**b, "id": None} for b in golden["blocos"]]


def test_a_tool_nao_promete_o_que_e_do_analista():
    """A descrição é o que o LLM lê para escolher a tool. Se ela prometesse retorno ou
    volatilidade, o Assessor a escolheria para uma pergunta que só o Analista responde —
    e a resposta seria 'esta ferramenta não entrega isso', que foi o defeito da F18."""
    from app.tools.registry import spec_de

    from app.tools import carregar_tools
    carregar_tools()
    d = spec_de("planejamento.posicoes_carteira").description.lower()
    assert "analista" in d, "a descrição precisa dizer para onde vai o que ela não faz"
    for proibido in ("volatilidade", "retorno anualizado", "correlação"):
        assert proibido not in d.replace("para retorno, volatilidade ou comparação com índice", "")


# =============================================================================
# O endpoint da tela (F19c)
# =============================================================================
@pytest_asyncio.fixture
async def api(db):
    from app.config.policies import PolicyStore
    from app.llm.fake import FakeLLM
    from app.main import criar_app

    aplicacao = criar_app(db=db, llm=FakeLLM([]), policies=PolicyStore(db, ttl_s=0))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=aplicacao),
                                 base_url="http://teste") as c:
        yield c


async def test_carteira_endpoint_devolve_posicoes_e_atencao(api, db, escopos):
    """A tela lê as três coisas juntas — distribuição, alerta e detalhe — ou nenhuma."""
    await _carteira_de_teste(db, escopos)
    r = await api.get("/carteira", headers={"X-Plexo-User-Id": escopos.u1,
                                            "X-Plexo-Scope-Id": escopos.s1})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["posicoes"]["total_da_carteira_brl"] == 100000.00
    assert len(corpo["posicoes"]["posicoes"]) == 3
    assert corpo["posicoes_indisponivel"] is None
    # Sem Raio-X executado, o diagnóstico vem DECLARADAMENTE ausente — não vazio.
    assert corpo["atencao"] is None
    assert "não há diagnóstico" in corpo["atencao_indisponivel"]


async def test_carteira_vazia_e_200_com_motivo_nunca_404(api, escopos):
    """"Não sei onde seu dinheiro está" é uma resposta; "esta página não existe" é outra."""
    r = await api.get("/carteira", headers={"X-Plexo-User-Id": escopos.u1,
                                            "X-Plexo-Scope-Id": escopos.s1})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["posicoes"] is None
    assert "não há posição registrada" in corpo["posicoes_indisponivel"]


async def test_carteira_exige_sessao(api):
    assert (await api.get("/carteira")).status_code == 401


async def test_o_seed_funciona_sem_preco_ingerido(db):
    """O caminho que o CI toma: banco limpo, `market.prices` vazia.

    A carteira é avaliada pelo último fechamento ingerido, e num banco recém-migrado não há
    nenhum. Se o seed dependesse da ingestão, ele quebraria exatamente onde não há ninguém
    para ver — foi por isso que `Posicao.preco_referencia` existe, e é isto que prova que ela
    não é decoração. (A F16 perdeu tempo com o gêmeo disto: um golden que dependia de haver
    CDI ingerido e divergia entre o dev e um banco limpo.)
    """
    from dataclasses import replace

    from app.seeds.personas import Posicao

    # Arquétipo mínimo com um papel que NENHUMA ingestão conhece.
    sem_preco = replace(
        HELENA, nome="helena_sem_preco",
        emissores=(), carteira=(
            Posicao("F19SEMPRECO", "Papel sem cotação na plataforma", "acao", "acoes_br",
                    quantidade=1000, preco_referencia=12.34, preco_medio=10.00,
                    liquidez_dias=2, negociado_em_bolsa=True),))

    async with db.service_session() as conn:
        ids = await aplicar(conn, sem_preco)
        cur = await conn.execute(
            "select h.quantity::float, h.unit_price::float, h.value_brl::float "
            "  from wealth.v_latest_holdings h join market.instruments i on i.id = h.instrument_id "
            " where h.scope_id = %s and i.ticker = 'F19SEMPRECO'", (ids["scope_id"],))
        quantidade, preco, valor = await cur.fetchone()
        cur = await conn.execute(
            "select total_brl::float from wealth.portfolio_snapshots "
            " where scope_id = %s order by as_of_date desc limit 1", (ids["scope_id"],))
        total = (await cur.fetchone())[0]

    assert (quantidade, preco, valor) == (1000.0, 12.34, 12340.0)
    assert total == 12340.0, "o rollup precisa bater com o valor derivado do preço de referência"
