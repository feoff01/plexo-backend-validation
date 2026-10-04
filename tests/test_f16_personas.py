"""F16 — o diagnóstico das seis personas, congelado.

O QUE ESTE ARQUIVO PROTEGE, E QUE PROPRIEDADE NÃO ALCANÇA
    `test_f16_propriedades.py` afirma coisas que valem para qualquer cliente. Isto aqui
    afirma o que acontece com SEIS clientes concretos — e é onde mora o defeito que só a
    combinação real de dados produz.

    Na primeira leitura das seis, esta camada achou quatro coisas que nenhuma propriedade
    pegaria, porque nenhuma delas é uma regra abstrata violada:

      · `diagnostics.foundation_status` não tinha produtor: a regra D11 nunca disparava,
        e nenhum teste percebia porque todos testavam o GATE, não o produtor;
      · a rigidez orçamentária dividia pela renda média, e a autônoma com piso a um terço
        da média saía com Fluxo 0,86;
      · o cliente SEM dívida ficava sem score de Estoque;
      · o elo mais fraco era apontado com diferença de 0,01.

COMO O GOLDEN NÃO VIRA RUÍDO
    O snapshot é NORMALIZADO: sem data, sem run_id, sem uuid, valores arredondados. Um
    golden que muda sozinho todo dia é ruído que se aprende a ignorar — e um golden ignorado
    protege menos que golden nenhum, porque dá a sensação de proteção.

COMO ATUALIZAR — E CONTRA QUE BANCO
    **Regrave SEMPRE contra um Postgres LIMPO**, o mesmo que o CI usa:

        docker run -d -e POSTGRES_PASSWORD=plexo -e POSTGRES_DB=plexo -p 5433:5432 postgres:18
        # backup do .env, DATABASE_URL -> localhost:5433 com ?sslmode=disable
        alembic upgrade head && python tools/preparar_ambiente.py
        PLEXO_REGRAVAR_GOLDEN=1 pytest tests/test_f16_personas.py

    Regravar contra o banco de dev produz golden ERRADO, e produziu: o de `aposentado` ficou
    com 20 fatos e `objetivo.prazo_meses` ausente, porque o escopo carregava histórico de
    execuções anteriores. No banco limpo são 21 e o fato existe. Um golden gerado em
    condições diferentes das que o CI usa para lê-lo não protege nada — ele só transfere o
    problema para o pipeline de outra pessoa.

    **Leia o diff antes de aceitar**: cada linha que mudou é uma mudança no diagnóstico de um
    cliente, e é decisão humana — não resultado de teste.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

from app.engine.perfil import calcular_perfil
from app.seeds.personas import ARQUETIPOS, aplicar, confirmar_seguro

pytestmark = pytest.mark.asyncio

GOLDEN = pathlib.Path(__file__).parent / "golden"
REGRAVAR = os.environ.get("PLEXO_REGRAVAR_GOLDEN") == "1"

# CDI de referência do golden, em PERCENTUAL (é assim que `market.index_values` guarda).
# Fixá-lo é obrigatório: sem CDI ingerido, `fundacao.py` avalia dívida cara contra o piso do
# spread, e `dependentes_sem_seguro` sai com Fundação CRÍTICA; com CDI, não sai. O
# diagnóstico passava a depender de o banco ter dado de mercado ingerido — verdadeiro no dev,
# falso num banco limpo, e o golden divergia entre os dois ambientes sem que nada estivesse
# errado no motor. Insumo de fora do escopo do teste se PINA dentro dele.
CDI_DO_GOLDEN = 14.0


async def _fixar_cdi(conn) -> None:
    """Garante que existe CDI para o motor ler. `do nothing` porque série de mercado é
    append-only (migration 31): UPDATE é recusado até para o serviço, e é assim que deve ser.

    Se o banco já tem CDI, o dele vale — e a asserção abaixo garante que o teste nunca roda
    no regime SEM CDI, que é o que fazia o golden divergir entre ambientes. A referência não
    precisa ser um número exato: precisa EXISTIR e estar numa faixa plausível, porque é a
    presença dela que decide se `dependentes_sem_seguro` tem Fundação crítica ou não.
    """
    await conn.execute(
        "insert into market.index_values (index_code, value_date, value) "
        "values ('cdi', current_date, %s) on conflict (index_code, value_date) do nothing",
        (CDI_DO_GOLDEN,))
    cur = await conn.execute(
        "select value::float from market.index_values where index_code = 'cdi' "
        "order by value_date desc limit 1")
    linha = await cur.fetchone()
    assert linha is not None, "sem CDI o diagnóstico muda; o golden não pode rodar assim"
    assert 5.0 <= linha[0] <= 25.0, (
        f"CDI de {linha[0]}% fora da faixa plausível — o golden foi congelado com uma "
        "referência de mercado normal, e um valor fora disso muda o que é dívida cara")


def _normalizar(resultado, cobertura: dict) -> dict:
    """O snapshot estável: o que o DIAGNÓSTICO diz, sem o que muda a cada execução.

    Fora de propósito: `run_id`, `as_of_date`, uuids e `computed_at`. Dentro: score por
    família com cobertura e confiança, indicador por indicador com o motivo da ausência, e
    a cobertura do catálogo — que é o que o cliente vê e o que precisa de revisão humana
    quando muda.
    """
    return {
        "fundacao_critica": resultado.fundacao_critica,
        "cobertura_do_catalogo": round(resultado.cobertura_do_catalogo, 3),
        # `confianca` fica DE FORA, e a ausência é a correção de um defeito deste arquivo.
        # Ela é o produto da confiança gravada pelo DECAIMENTO POR FRESCOR, e frescor é
        # distância até `now()`: a partir do momento em que `plexo seed personas` persiste as
        # asserções no banco de dev, o número escorrega sozinho — 0,700 na hora de gravar o
        # golden, 0,694 três horas depois. Golden que muda sozinho vira ruído, e ruído que se
        # aprende a ignorar protege menos que golden nenhum. O decaimento em si é testado
        # exatamente, e sem relógio, em `test_f14_perfil.py::test_confianca_cai_com_o_frescor`.
        "scores": sorted(
            [{"score": s["score_code"],
              "valor": None if s["value"] is None else round(s["value"], 3),
              "cobertura": round(s["coverage"], 3),
              "critica": s["is_critical_family"],
              "indisponivel": s["is_disabled"],
              "motivo": s["disabled_reason"]}
             for s in resultado.scores], key=lambda x: x["score"]),
        "indicadores": sorted(
            [{"indicador": i["indicator_code"],
              "valor": None if i["value"] is None else round(i["value"], 3),
              "unidade": i["unit"],
              "cobertura": round(i["coverage"], 3),   # sem `confianca`, pelo mesmo motivo
              "indisponivel": i["is_unavailable"],
              "motivo": i["unavailable_reason"],
              "faltando": sorted(i["faltando"])}
             for i in resultado.indicadores], key=lambda x: x["indicador"]),
        "fatos_presentes": cobertura["fatos_presentes"],
        "fatos_no_catalogo": cobertura["fatos_no_catalogo"],
    }


async def _elo(conn, scope_id) -> str | None:
    """Qual área a tela apontaria como a que mais limita o rumo — parte do diagnóstico,
    e portanto parte do que o golden precisa congelar."""
    cur = await conn.execute(
        "select score_code from diagnostics.v_client_profile "
        "where scope_id = %s and elo_mais_fraco "
        "  and as_of_date = (select max(as_of_date) from diagnostics.client_scores "
        "                    where scope_id = %s)", (scope_id, scope_id))
    linha = await cur.fetchone()
    return linha[0] if linha else None


@pytest.mark.parametrize("arquetipo", ARQUETIPOS, ids=lambda a: a.nome)
async def test_diagnostico_da_persona_nao_mudou(db, arquetipo):
    """Cada persona, do seed ao diagnóstico, dentro da transação do teste.

    Nada persiste: a persona é criada, derivada e pontuada no savepoint e some no rollback.
    O golden é o único resíduo, e ele é revisado por gente.
    """
    from app.context.catalogo import cobertura as ler_cobertura
    from app.context.derivacao import derivar_escopo
    from app.engine.projecao import projetar_escopo

    async with db.service_session() as conn:
        await _fixar_cdi(conn)
        ids = await aplicar(conn, arquetipo)
        await confirmar_seguro(conn, arquetipo)
        # ORDEM: derivar → projetar → pontuar. A primeira versão disto punha a projeção na
        # frente, porque ela ESCREVE `objetivo.probabilidade_sucesso`, e esqueceu que ela
        # também LÊ `renda.mensal_liquida` e `despesa.total_mensal` — que são DERIVADOS. No
        # banco de dev esses dois já estavam persistidos de execuções anteriores, então
        # passou aqui e quebrou no CI, que parte de um banco limpo. A dependência é de mão
        # dupla e a ordem é a única que satisfaz as duas pontas.
        #
        # A projeção é determinística mesmo passando o tempo: a semente vem da política, e o
        # prazo em meses é estável porque a persona ancora `target_date` em `hoje + prazo`,
        # de modo que alvo e data de referência andam juntos.
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        await projetar_escopo(conn, ids["scope_id"])
        resultado = await calcular_perfil(conn, ids["scope_id"], client_facing=False)
        cob = await ler_cobertura(conn, ids["scope_id"])
        elo = await _elo(conn, ids["scope_id"])

    atual = _normalizar(resultado, cob) | {"elo_mais_fraco": elo}
    caminho = GOLDEN / f"perfil_{arquetipo.nome}.json"

    if REGRAVAR or not caminho.exists():
        caminho.write_text(
            json.dumps({"persona": arquetipo.nome, "forca": arquetipo.forca,
                        "esperado": atual}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        if not REGRAVAR:
            pytest.skip(f"golden criado: {caminho.name} — CONFIRA à mão antes de versionar")
        return

    esperado = json.loads(caminho.read_text(encoding="utf-8"))["esperado"]
    assert atual == esperado, (
        f"o diagnóstico de `{arquetipo.nome}` mudou. Isto NÃO é falha de teste: é uma "
        f"mudança no que o produto diz a um cliente com este perfil. Leia o diff, decida se "
        f"a mudança é intencional e, se for, regrave com PLEXO_REGRAVAR_GOLDEN=1.")


async def test_endividado_tem_fundacao_critica_e_nenhum_score(db):
    """A persona que existe para provar D11 — e que expôs, ao ser lida pela primeira vez,
    que `diagnostics.foundation_status` não tinha quem o escrevesse.

    Reserva de meio mês e rotativo a 400% a.a.: nenhuma área recebe nota, e todas dizem
    `fundacao_critica`. Não é nota baixa — é ausência de nota, de propósito.
    """
    from app.context.derivacao import derivar_escopo
    from app.seeds.personas import POR_NOME

    a = POR_NOME["endividado_rotativo"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        r = await calcular_perfil(conn, ids["scope_id"], client_facing=False)

        # Filtra pelo RUN que este teste acabou de criar. Sem isso, a consulta pegava a
        # linha de outra data — havia uma de 29/08 com a luz da dívida verde, sobrada de uma
        # execução de CLI —, e o teste passou a falhar sozinho quando a data virou. Terceira
        # vez que essa classe aparece nesta base: teste que lê por chave de negócio lê o que
        # outra execução deixou.
        cur = await conn.execute(
            "select is_critical, reserve_light::text, debt_light::text, reserve_months::float "
            "from diagnostics.foundation_status where scope_id = %s and run_id = %s",
            (ids["scope_id"], r.run_id))
        linha = await cur.fetchone()

    assert linha is not None, "a Fundação precisa ter sido GRAVADA — o gate sem produtor é intenção"
    critica, luz_reserva, luz_divida, meses = linha
    assert critica and luz_reserva == "vermelho" and luz_divida == "vermelho"
    assert meses < 1, f"meio mês de reserva, não {meses}"
    assert r.fundacao_critica
    assert all(s["is_disabled"] and s["disabled_reason"] == "fundacao_critica" for s in r.scores)


async def test_sem_divida_nao_significa_sem_diagnostico(db):
    """O cliente sem dívida nenhuma não pode ser punido com "não dá para medir".

    `patrimonio_alto_sem_fluxo` tem R$ 3,4 mi e zero dívida, e saía com Estoque indisponível
    porque `custo_medio` e `parcela_mensal` não nasciam. Zero dívida é a MELHOR notícia
    possível, e é um fato — não uma ausência.
    """
    from app.context.derivacao import derivar_escopo
    from app.seeds.personas import POR_NOME

    a = POR_NOME["patrimonio_alto_sem_fluxo"]
    assert a.dividas == (), "o arquétipo precisa continuar sem dívida para este teste valer"
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        # Fato DERIVADO vive na janela operável, nunca em `v_fact_current` (que é a do
        # agente e só tem o confirmado) — é a separação que a migration 43 criou.
        cur = await conn.execute(
            "select fact_key, numero::float from context.v_fact_operavel "
            "where scope_id = %s and fact_key like 'divida.%%'", (ids["scope_id"],))
        zeros = dict(await cur.fetchall())
        for chave in ("divida.saldo_total", "divida.custo_medio", "divida.parcela_mensal"):
            assert zeros.get(chave) == 0.0, f"{chave} devia nascer zero, veio {zeros.get(chave)}"
        r = await calcular_perfil(conn, ids["scope_id"], client_facing=False)

    estoque = next(s for s in r.scores if s["score_code"] == "score.estoque")
    assert not estoque["is_disabled"], "quem não deve nada precisa receber diagnóstico de estoque"


async def test_plano_declarado_vira_assinatura_de_verdade(db):
    """O campo `plano` existia desde a F16 e ninguém o escrevia.

    Sem linha em `billing.subscriptions`, `plano_do_escopo` devolve 'free' para TODA persona
    — inclusive as quatro que se declaram `essential` — e as tools com `min_plan='essential'`
    somem do catálogo que chega ao modelo. Era a mesma armadilha do `foundation_status`: um
    campo lido em lugar nenhum porque nada o produzia, e nenhum teste percebia porque nenhum
    perguntava quem escreve.
    """
    from app.db.repos import identity as identity_repo
    from app.seeds.conta_teste import HELENA
    from app.seeds.personas import POR_NOME

    async with db.service_session() as conn:
        pago = await aplicar(conn, HELENA)
        assert await identity_repo.plano_do_escopo(conn, pago["scope_id"]) == HELENA.plano

        gratis = await aplicar(conn, POR_NOME["jovem_sem_patrimonio"])
        assert await identity_repo.plano_do_escopo(conn, gratis["scope_id"]) == "free"


async def test_a_conta_de_demonstracao_pontua_as_cinco_familias(db):
    """A única conta do repositório em que o diagnóstico sai INTEIRO.

    As seis personas existem para forçar ausências — é o que elas provam. Faltava o oposto:
    um cliente bem conhecido, em que as cinco famílias saem com número. Sem ele, ninguém
    consegue olhar para a tela e ver o produto funcionando, e um caminho que nunca se percorre
    é um caminho que não se sabe se existe.
    """
    from app.context.derivacao import derivar_escopo
    from app.engine.projecao import projetar_escopo
    from app.seeds.conta_teste import HELENA

    async with db.service_session() as conn:
        # Mesmo motivo do golden: sem CDI, o motor mede dívida cara contra o piso do spread e
        # QUALQUER dívida realista fica cara — a Fundação sai crítica e as cinco famílias
        # ficam sem nota. A conta de demonstração só mostra o produto inteiro num banco com
        # referência de mercado, que é a condição de produção.
        await _fixar_cdi(conn)
        ids = await aplicar(conn, HELENA)
        await confirmar_seguro(conn, HELENA)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        projecoes = await projetar_escopo(conn, ids["scope_id"])
        r = await calcular_perfil(conn, ids["scope_id"], client_facing=False)

    assert not r.fundacao_critica, "a conta de demonstração não pode nascer com Fundação crítica"
    sem_valor = [s["score_code"] for s in r.scores if s["value"] is None]
    assert sem_valor == [], f"famílias sem nota: {sem_valor}"

    assert len(projecoes) == 2, "dois objetivos ativos — é o que exercita a regra da MENOR"
    probabilidades = sorted(
        next(d for d in p.distribuicoes if d.alocacao == p.veredito.alocacao).prob_sucesso
        for p in projecoes)
    assert probabilidades[0] < 0.9 < probabilidades[-1], (
        "um objetivo folgado e um apertado: é o par que faz a regra da menor probabilidade "
        "dizer alguma coisa")


async def test_rigidez_usa_o_piso_da_renda_nao_a_media(db):
    """A regra da migration 24, agora com dentes no motor.

    `autonomo_volatil`: média de R$ 13.500, piso p10 de R$ 4.200, gasto fixo de R$ 4.900.
    Sobre a média, a rigidez daria 36% — confortável. Sobre o piso, passa de 100%: num mês
    ruim ela não cobre nem o contratado. É o segundo número que julga sustentabilidade.
    """
    from app.context.derivacao import derivar_escopo
    from app.seeds.personas import POR_NOME

    a = POR_NOME["autonomo_volatil"]
    async with db.service_session() as conn:
        ids = await aplicar(conn, a)
        await derivar_escopo(conn, ids["scope_id"], ids["user_id"])
        r = await calcular_perfil(conn, ids["scope_id"], client_facing=False)

    rigidez = next(i for i in r.indicadores if i["indicator_code"] == "fluxo.rigidez_orcamentaria")
    assert not rigidez["is_unavailable"], "a renda comprometível precisa ter sido derivada"
    sobre_media = a.fixo_contratado / a.renda_total
    assert rigidez["value"] > sobre_media * 1.5, (
        f"rigidez saiu em {rigidez['value']:.2f}, próxima demais dos {sobre_media:.2f} que a "
        "média daria — o motor voltou a julgar sustentabilidade pelo mês bom")
