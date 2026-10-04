# Checkpoint — FQ4.4 Event Study v2

Data: 2026-09-25

## Entregue
- `analytics/event_study.py` puro;
- `quant.event_study_v2` 1.0.0 shadow;
- `event_study_legacy_1_0_1.py` autocontido para replay;
- `quant.event_study` 1.0.2 com cálculo legacy intacto e descrição temporal corrigida;
- alinhamento de preços comuns antes do cálculo de retornos;
- market model / market adjusted;
- inferência opcional `classic_iid_normal` do CAR via `MetricEstimate`;
- blocos e warnings v2.

## Inferência clássica
Default = none.

Market model:
`Var(CAR)=sigma²[L + L²/T + (sum(x_evt)-L*xbar_est)²/Sxx_est]`, `sigma²=SSE/(T-2)`.

Market adjusted:
`SE(CAR)=sd(resíduos_est)*sqrt(L)`.

Sem p-value, sem booleano de significância, sem causalidade.

## Testes
- 22/22 específicos;
- 250 modelos exatos alpha/beta;
- 250 testes de invariância à escala;
- legacy 1.0.1 reproduz golden bit a bit;
- regressão ampla sem DB: 426 passed / 16 skipped / 355 DB-deselected / 0 failed;
- compileall verde;
- registry audit: 29 -> 30, somente legacy event study mudou e somente v2 foi adicionada.

## Pendente
- PostgreSQL CI;
- `tools sync --check` e sync;
- cutover canônico da v2;
- planner/evals para v2;
- otimização do reader para lookback por número de observações (a shadow carrega toda a história do par até o cutoff, correctness-first).
