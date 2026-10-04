"""F18 — a conversa que continua de onde parou.

O QUE ERA
    O job de inatividade encerra toda conversa com trinta minutos de silêncio. A partir daí
    ela era **só-leitura para sempre**: `turn.py` recusava o turno com `conversa_indisponivel`
    e não existia reabertura em lugar nenhum do produto. Quem voltasse no dia seguinte para
    continuar de onde parou recomeçava do zero, perdendo o contexto que a conversa carregava.

    Nenhuma IA de mercado se comporta assim, e não havia razão de produto para a nossa se
    comportar — o encerramento existia por um motivo TÉCNICO: era ele que disparava a extração
    de contexto em lote.

O QUE MUDOU, E O QUE PRECISOU MUDAR JUNTO
    Escrever reabre. Mas isso quebra a premissa da camada de extração, que garantia UM lote
    bem-sucedido por conversa: com a regra antiga, tudo o que fosse dito depois de uma
    reabertura jamais seria lido — o cliente contaria uma mudança de vida e o contexto não
    saberia, em silêncio. Daí a migration 52: o run passa a registrar até que `seq` leu, e a
    unicidade passa a ser por TRECHO.

    Os dois testes abaixo cobrem as duas pontas. O segundo é o que importa: sem ele, a
    reabertura seria uma melhoria de conveniência que estragaria o aprendizado do contexto.
"""
from __future__ import annotations

import pytest

from app.agents import conversations as convs

pytestmark = pytest.mark.asyncio


async def _conversa(conn, escopos, status: str = "aberta") -> str:
    cid = await convs.criar(conn, scope_id=escopos.s1, user_id=escopos.u1,
                            agent_code="assessor", plan_code="essential")
    if status != "aberta":
        # `conversation_ended_has_ts` e `conversation_processed_has_ts` (17): estado terminal
        # exige a data que o produziu. O helper respeita os dois — é o mesmo caminho que o
        # job de inatividade percorre.
        await conn.execute(
            "update agents.conversations set status = %s, ended_at = now(), "
            "processed_at = case when %s = 'processada' then now() else processed_at end "
            "where id = %s", (status, status, cid))
    return cid


async def test_escrever_reabre_conversa_encerrada(db, escopos):
    async with db.service_session() as conn:
        cid = await _conversa(conn, escopos, "encerrada")
        assert await convs.reabrir(conn, cid) is True
        atual = await convs.travar(conn, cid)
        assert atual.status == "aberta"


async def test_conversa_processada_tambem_volta(db, escopos):
    """Já extraída não quer dizer terminada: a extração agora é incremental."""
    async with db.service_session() as conn:
        cid = await _conversa(conn, escopos, "processada")
        assert await convs.reabrir(conn, cid) is True
        assert (await convs.travar(conn, cid)).status == "aberta"


async def test_arquivada_nao_reabre(db, escopos):
    """Arquivar é ato deliberado de quem arquivou; silêncio de trinta minutos não é."""
    async with db.service_session() as conn:
        cid = await _conversa(conn, escopos, "arquivada")
        assert await convs.reabrir(conn, cid) is False
        assert (await convs.travar(conn, cid)).status == "arquivada"


async def test_o_banco_aceita_dois_lotes_em_trechos_diferentes(db, escopos):
    """A migration 52 na prática: reler o mesmo trecho continua proibido, ler o que veio
    depois passa a ser possível.

    Sem isso, a reabertura seria uma armadilha: a conversa continuaria, o cliente contaria
    coisas novas, e a extração em lote nunca as leria — porque já havia um sucesso registrado
    para aquela conversa.
    """
    async with db.service_session() as conn:
        # encerrada: o gate da 21 recusa extração em lote sobre conversa aberta, e com razão
        cid = await _conversa(conn, escopos, "encerrada")
        await conn.execute(
            "insert into context.extraction_runs (conversation_id, scope_id, kind, status, ate_seq) "
            "values (%s, %s, 'pos_conversa', 'succeeded', 4)", (cid, escopos.s1))

        # o MESMO trecho: recusado pelo índice
        with pytest.raises(Exception) as excecao:
            async with conn.transaction():
                await conn.execute(
                    "insert into context.extraction_runs (conversation_id, scope_id, kind, status, ate_seq) "
                    "values (%s, %s, 'pos_conversa', 'succeeded', 4)", (cid, escopos.s1))
        assert "extraction_one_success" in str(excecao.value)

        # o trecho SEGUINTE: aceito
        await conn.execute(
            "insert into context.extraction_runs (conversation_id, scope_id, kind, status, ate_seq) "
            "values (%s, %s, 'pos_conversa', 'succeeded', 9)", (cid, escopos.s1))
        cur = await conn.execute(
            "select count(*) from context.extraction_runs where conversation_id = %s "
            "and status = 'succeeded'", (cid,))
        assert (await cur.fetchone())[0] == 2
