# Checkpoint — FQ3.1 `quant.risco_retorno`

Data: 2026-09-21

## Estado
FQ1 e FQ2 base preservados. FQ3.1 concluído em shadow mode.

## Mudanças
- `dados.serie_precos` 1.0.2: cutoff por data da observação, sem alegação de vintage PIT.
- `quant.risco_retorno` 1.0.0: registrada, auditável, oculta da LLM.
- adjusted close é default canônico e sempre retrospectivo as-known-now.
- raw close é opt-in e usa observation-date cutoff.
- output compacto usa Quant Core e inclui episódio do maximum drawdown.

## Testes
- FQ3.1: 12/12 verdes.
- Suíte sem PostgreSQL: 306 passed, 16 skipped, 355 DB-deselected, 0 failed.
- `compileall`/`py_compile`: verde.

## Registry
25 tools registradas; 24 expostas; `quant.risco_retorno` é a única shadow.

## Próximo passo
FQ3.2: `quant.dependencia` shadow. FQ3.3 só depois: cutover conjunto das duas tools canônicas.
