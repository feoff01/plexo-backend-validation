# Checkpoint — quant.risco_retorno 1.1.0 GREEN

Data: 2026-10-03
Status: **GREEN / pública**

## Capability
`quant.risco_retorno` evoluiu de 1.0.1 para **1.1.0** sem criar tool paralela.

Novidade pública:
- `downside_deviation_anualizada_pct`;
- `downside_target_periodic_pct = 0.0` explícito;
- bloco passa a apresentar duração e recuperação do pior drawdown em **intervalos observados** quando disponíveis;
- planner roteia downside risk, semidesvio, duração de drawdown e tempo de recuperação para a tool canônica.

## Reuse-before-build
Nenhuma matemática nova:
- downside deviation reutiliza `annualized_downside_deviation()`;
- duração/recovery reutilizam `maximum_drawdown_episode()` e `DrawdownDetail`;
- retorno, volatilidade e maximum drawdown existentes preservam as fórmulas anteriores.

Nenhuma fonte, migration, tabela ou loader novo.

## Compatibilidade / replay
Run #295 / `37154280303` detectou uma única regressão:
- **1 failed, 917 passed, 52 skipped, 19 warnings**;
- falha no golden de bloco legacy `quant.retorno_volatilidade`;
- causa: título cosmético alterado no mapper compartilhado.

Correção:
- título histórico restaurado;
- campos novos continuam condicionados à presença no payload 1.1.0;
- replay legacy preservado;
- nenhuma matemática revertida.

## Gate final
HEAD funcional validado: `687966a22053136000f39542bb7f1feebcde71cf`.
Run #296 / `37154531785`: **success**.

- PostgreSQL 18.6 + migrations/invariantes: GREEN;
- directed gate: **175 passed**;
- benchmark FQ5.6 peers: **10/10/10 queries**;
- payload peers: 4009/4171/4163 bytes;
- full suite: **918 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: GREEN;
- tools sync --check: GREEN;
- catálogo permanece **37 total / 34 expostas / 3 ocultas-replay**.

## Limites preservados
Fora desta tranche:
- rolling volatility / série móvel;
- Sharpe, Sortino, Calmar;
- VaR / Expected Shortfall;
- stress/choque;
- forecast;
- recomendação;
- Portfolio Analytics.

## Próximo passo
Reauditar as lacunas restantes no estado pós-`quant.risco_retorno` 1.1.0. Não abrir rolling volatility automaticamente sem congelar janela, semântica e compactação.
