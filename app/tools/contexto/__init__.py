"""Família `contexto` (F13a/F14): o repertório e o contexto pessoal do cliente.

Única família invocável pelo Analista **e** pelo Assessor (34_docs.sql atualiza
`agents.agent_definitions.allowed_tool_families` dos dois). O Analista a usa para explicar o
movimento; o Assessor, para situar a decisão do cliente — sem que nenhum dos dois ganhe acesso às
tools do outro.

Desde a F14 são três tools, e as três são READ-ONLY de propósito: o executor devolve output de
cache sem executar a função, então uma tool que ESCREVESSE seria silenciosamente pulada na
segunda chamada idêntica. Quem escreve é o orquestrador do turno.

  · `contexto.documento_oficial`   — o que o emissor oficial disse, com data e link (F13a)
  · `contexto.verificar_mudanca`   — o número que o cliente acabou de dizer mudou de verdade?
  · `contexto.perfil_financeiro`   — o diagnóstico por família, e o que ainda falta medir
"""
