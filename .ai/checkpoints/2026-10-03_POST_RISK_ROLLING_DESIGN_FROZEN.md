# Checkpoint — pós-risco 1.1 · audit + rolling-vol design congelado

Data: 2026-10-03
Estado: **GREEN documental / pronto para shadow interno**
Base funcional preservada: `quant.risco_retorno` 1.1.0
Run funcional de referência: #296 / `37154531785`

## Fechado nesta tranche
- reauditoria pós-risco concluída;
- lacunas restantes classificadas;
- rolling volatility selecionada por `reuse-before-build`;
- confirmado que a matemática já existe no Quant Core;
- decidido evoluir `quant.risco_retorno`, sem tool paralela;
- design 1.2.0 congelado;
- nenhum código/tool/schema/migration/policy/planner/bloco alterado.

Documentos:
- `.ai/COMPANY_MARKET_DELTA_AUDIT_POST_RISK_2026-10-03.md`;
- `.ai/RISK_ROLLING_VOLATILITY_DESIGN_2026-10-03.md`.

## Próximo gate
Implementar somente shadow interno não registrado + testes de equivalência 1.1.0.

Não promover 1.2.0 antes de PostgreSQL 18 + semantics + payload + provenance + readiness.
