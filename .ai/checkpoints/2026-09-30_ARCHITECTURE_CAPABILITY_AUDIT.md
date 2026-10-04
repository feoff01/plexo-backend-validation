# Checkpoint — Architecture / Capability Audit

Data: 2026-09-30

## Motivo
Foi detectada sobreposição real entre `quant.dependencia` e `quant.dependencia_macro`. A matemática de dependência já existia; a lacuna real era o adapter de FX.

## Resultado
- inventário completo do Analista documentado em `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md`;
- Quant Core mapeado antes de novas features;
- capacidades latentes identificadas (rolling vol, downside risk, drawdown duration/recovery, rolling/up/down-market dependence);
- schemas existentes sem consumer identificados: `market.sector_classification`, `market.index_weights`, `market.yield_curve`;
- legacy intencional separado de duplicação real;
- `quant.cenario_sensibilidade` classificada como composição legítima, pois reutiliza `quant.sensibilidade` e o DAG não possui output-to-param dataflow;
- fronteira Portfolio/cliente reafirmada; `market.class_correlations` são premissas de planejamento, não correlação empírica do Analista.

## Decisão
Adotar `reuse-before-build` como gate obrigatório. Não criar tool por fonte/fator. Criar design de consolidação de factor resolver + dependência antes de FQ5.5.

## Código
Nenhum código, migration, cálculo ou tool foi alterado nesta auditoria.

## Estado verde de referência
HEAD remoto antes da auditoria documental: `efd27727615cb9fdffa00ac250813798dbbd38e5`.
GitHub Actions run #50 / `36785509026`: success; 74 E2E, 816 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes.
