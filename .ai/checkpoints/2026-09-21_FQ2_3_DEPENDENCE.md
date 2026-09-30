# Checkpoint — FQ2.3 Dependence Engine

Data: 2026-09-21
Base de entrada: backend FQ2.2.

## Pedido
Implementar `dependence.py` cuidadosamente, incluindo Pearson, Spearman, rolling, lagged e up/down-market; migrar `quant.correlacao`; persistir toda decisão/resultado na memória do projeto.

## Entregue
- `app/market/analytics/dependence.py`;
- `DependenceMethod`, `DependenceDirection`, `PairedReturnObservation`, `DependenceEstimate`, `RollingDependenceObservation`, `ConditionalDependenceEstimate`;
- Pearson;
- Spearman com ranks médios;
- alinhamento por interseção;
- lag assinado;
- rolling dependence;
- up/down-market;
- migração de `quant.correlacao` para o engine;
- semver `quant.correlacao` 1.0.2 + fingerprint composto.

## Semânticas congeladas
- lag medido sobre observações comuns após interseção;
- positivo = X antecede Y; negativo = Y antecede X;
- pares guardam datas de X/Y e as-of máximo;
- Spearman usa rank médio em empates;
- rolling por número de pares, sem padding;
- up/down-market usa sinal do retorno do market depois do alinhamento; zero/threshold exato é neutro;
- correlação indefinida => `None`, não zero;
- nenhuma alegação causal.

## Testes
- vermelho inicial confirmado;
- 14 testes diretos FQ2.3 verdes;
- 750 casos equivalentes ao Pearson+lag legacy;
- 250 checks de simetria do lag assinado;
- golden `quant.correlacao` idêntico;
- 8 testes direcionados F5/golden/literal verdes;
- bateria ampla sem PostgreSQL: 294 passed, 16 skipped, 355 deselected, 0 failed.

## Decisão de escopo
FQ2 base fecha com returns/statistics/risk/dependence. `quant.event_study` permanece funcional como legacy atual e sua evolução fica na FQ4.

## Próximo passo
FQ3: contrato das tools canônicas `quant.risco_retorno` e `quant.dependencia`, incluindo estratégia de output rico/compacto e migração legacy sem duplicar matemática.
