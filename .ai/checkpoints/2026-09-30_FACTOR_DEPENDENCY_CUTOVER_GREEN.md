# Checkpoint — Factor / Dependence Cutover GREEN

Data: 2026-09-30
Estado: encerrado e verde.

## Escopo realizado
- FactorRef/ResolvedFactor compartilhados para ativo, índice/taxa e câmbio.
- quant.dependencia 2.0.0 como interface pública canônica.
- quant.dependencia_macro 1.0.1 oculta, somente compatibilidade.
- dependência 1.0.1 e macro 1.0.0 congeladas para replay.
- planner atualizado para serie_b.
- testes de equivalência e goldens adicionados.

## Invariantes preservados
- nenhuma fórmula nova;
- Quant Core FQ3/FQ4 não alterado;
- sem migration/schema;
- sem refactor de sensibilidade, condicional ou regimes;
- outputs compactos, provenance, cutoff e temporal semantics preservados;
- 33 tools antes e depois; somente as duas interfaces previstas mudaram.

## Validação PostgreSQL 18
Código: 60bad205666e5cc5c5d0e2b2b8e643f41e2ac322
Run: #54 / 36793672760
Conclusão: success

- migrations do zero: verde;
- validador: 0 erros / 0 avisos;
- invariantes SQL admin e plexo_service: verdes;
- FQ1 + F5 + F22 + FQ4 + FQ5 + factor cutover E2E: 87 passed;
- suíte completa: 831 passed, 52 skipped, 19 warnings, 0 failed;
- prompts check: verde;
- tools sync --check: verde.

## Próximo estado
A consolidação está encerrada. Fundamentals + Valuation pode ser retomado aplicando primeiro o capability audit e reuse-before-build. Nenhuma nova feature foi aberta neste checkpoint.
