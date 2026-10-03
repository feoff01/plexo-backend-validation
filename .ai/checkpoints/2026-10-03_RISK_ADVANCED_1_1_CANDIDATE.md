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
