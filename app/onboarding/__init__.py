"""Onboarding obrigatório (F21a) — jornada estruturada que substitui o wizard best-effort.

`jornada.py` orquestra os passos e o funil; `escrita.py` grava fato de formulário
(declarado + confirmado no mesmo ato, C22a) sempre lendo o catálogo, nunca hardcoding
`attribute`/`subject_kind`; `suitability.py` pontua o questionário — função pura, sem
banco; `erros.py` são as exceções de domínio que a rota traduz em HTTPException.

O gate de conclusão (suitability vigente + fatos-núcleo confirmados) é do BANCO
(C59a, `sql/59_onboarding_fundacoes.sql`) — o que está aqui é pré-checagem para dar uma
mensagem melhor que "23514", nunca a fonte da verdade.
"""
