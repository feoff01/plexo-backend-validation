"""Camada de tools: código determinístico que CALCULA (o LLM só escolhe e preenche parâmetros).

Registro por decorator (registry), espelho auditável no banco (sync: git_sha + sha256 do fonte),
execução com cache content-addressed e gates do banco (executor).
"""
from __future__ import annotations


def carregar_tools() -> None:
    """Importa os módulos de tools (o import registra via decorator). Idempotente."""
    from app.tools.assessor import (  # noqa: F401
        atencao, orcamento, patrimonio, planejamento, posicoes, produto, simulacao_objetivo,
    )
    from app.tools.educador import exemplo_didatico, glossario, juros_compostos  # noqa: F401
    from app.tools.analista import (analise_condicional, cenario_sensibilidade, correlacao, dependencia, dependencia_macro,  # noqa: F401
                                    event_study, event_study_v2, expectativas, fundamentos_empresa,
                                    historico_comparado, regimes, resolver_instrumento, retorno_volatilidade,
                                    risco_retorno, sensibilidade, serie_indice, serie_precos, tendencias_fundamentais,
                                    valor_mercado)
    from app.tools.contexto import mudanca, oficial, perfil  # noqa: F401

