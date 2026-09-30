"""A carteira do cliente — posições, grupos e pontos de atenção, num payload só.

POR QUE UM ENDPOINT E NÃO TRÊS
    A tela lê as três coisas juntas ou não lê nenhuma: a distribuição só faz sentido ao lado
    das posições que a compõem, e um alerta de concentração sem a linha do ativo que o
    produziu é uma acusação sem prova. Três requisições dariam três estados de carregamento
    para uma leitura só.

REUSA AS TOOLS, NÃO REESCREVE A CONSULTA
    `preparar_posicoes` e `preparar_atencao` são as mesmas funções que o Copiloto invoca. Uma
    consulta própria aqui produziria, com o tempo, dois números diferentes para a mesma
    pergunta — o cliente veria um total na tela e outro na conversa. É o defeito que a F18
    corrigiu na capacidade de aporte, e não se repete de propósito.

    A metade impura roda sob `app_session` (RLS do escopo); a metade pura é a mesma que o
    golden trava. Nada aqui grava.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import Identidade, identidade
from app.tools.assessor.atencao import AtencaoParams, calcular_atencao, preparar_atencao
from app.tools.assessor.posicoes import PosicoesParams, calcular_posicoes, preparar_posicoes
from app.tools.executor import ToolContext, ToolConteudoIndisponivel, ToolInsumoFaltante

router = APIRouter()


@router.get("/carteira")
async def ler_carteira(request: Request, ident: Identidade = Depends(identidade)):
    """Posições + grupos + pontos de atenção. Ausência é DECLARADA, nunca convertida em zero.

    Carteira vazia devolve 200 com `posicoes: null` e o motivo — e não 404. A tela precisa
    dizer "não sei onde seu dinheiro está" com um caminho para resolver, o que é diferente
    de "esta página não existe". Mesma lógica para o diagnóstico ainda não executado.
    """
    db = request.app.state.db
    async with db.app_session(user_id=ident.user_id, scope_id=ident.scope_id) as conn:
        ctx = ToolContext(conn=conn, scope_id=ident.scope_id, conversation_id=None)

        posicoes = motivo_posicoes = None
        try:
            posicoes = calcular_posicoes(await preparar_posicoes(PosicoesParams(), ctx)).model_dump()
        except (ToolInsumoFaltante, ToolConteudoIndisponivel) as e:
            motivo_posicoes = str(e)

        # O contexto da tool é reaproveitado de propósito: as políticas lidas ficam
        # registradas uma vez só, e o `_policies` da execução reflete a leitura inteira.
        atencao = motivo_atencao = None
        try:
            atencao = calcular_atencao(await preparar_atencao(AtencaoParams(), ctx)).model_dump()
        except (ToolInsumoFaltante, ToolConteudoIndisponivel) as e:
            motivo_atencao = str(e)

    return {"posicoes": posicoes, "posicoes_indisponivel": motivo_posicoes,
            "atencao": atencao, "atencao_indisponivel": motivo_atencao}
