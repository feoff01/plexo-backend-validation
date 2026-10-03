# Checkpoint — quant.risco_retorno 1.1.0 candidate

Data: 2026-10-03
Status: **CANDIDATE / aguardando PostgreSQL CI**

## Reuse-before-build
- nenhuma fonte, schema, loader ou matemática nova;
- reutiliza `annualized_downside_deviation()` e `maximum_drawdown_episode()` do Risk Core;
- não cria tool paralela.

## Mudança candidata
- `quant.risco_retorno` 1.0.1 -> **1.1.0**;
- adiciona `downside_deviation_anualizada_pct`;
- target periódico zero fica explícito em `downside_target_periodic_pct=0.0` e na metodologia;
- bloco apresenta duração e recuperação do pior drawdown em **intervalos observados**;
- planner roteia downside/semidesvio/duração/recovery para a tool canônica.

## Compatibilidade
As métricas já públicas — retorno acumulado/anualizado, volatilidade anualizada, máximo drawdown e episódio — preservam a mesma matemática. A mudança é aditiva.

## Explicitamente fora
- rolling volatility;
- Sharpe/Sortino/Calmar;
- VaR/Expected Shortfall;
- choque/stress;
- forecast;
- recomendação;
- Portfolio Analytics.

## Gate pendente
- PostgreSQL 18/migrations/invariantes;
- directed gate incluindo FQ3 + readiness;
- full suite;
- prompts check;
- tools sync --check.

Não considerar GREEN antes do CI.

## Gate intermediário #295 — correção de replay
Run #295 / `37154280303`:
- migrations/invariantes: GREEN;
- directed gate: GREEN;
- peers benchmark: GREEN;
- full suite: **1 failed, 917 passed, 52 skipped, 19 warnings**;
- única falha: golden de bloco legacy `quant.retorno_volatilidade`.

Causa: mudança cosmética do título no mapper compartilhado afetou replay legacy mesmo sem campos novos.

Correção: título histórico `Retorno e volatilidade` restaurado. Os itens novos continuam condicionados à presença dos campos 1.1.0; nenhuma matemática ou contrato numérico foi revertido.
