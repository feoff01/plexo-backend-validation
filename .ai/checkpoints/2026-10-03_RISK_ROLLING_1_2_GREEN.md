# Checkpoint — quant.risco_retorno 1.2.0 GREEN

Data: 2026-10-03
Status: **GREEN / pública**
Commit funcional validado: `3786af082eba5e99e14908340bd3bc649872fbdb`
Run: #334 / `37162747600` — **success**

## Capability
`quant.risco_retorno` evoluiu de 1.1.0 para **1.2.0** sem criar tool paralela.

Novidade pública opcional:
- `incluir_evolucao_volatilidade: bool = false`;
- `janela_volatilidade_observacoes: int | None`;
- `evolucao_volatilidade` com janela, total de janelas, pontas, mínimo/máximo e série compactada.

Comportamento default permanece compacto: se evolução não for pedida, não calcula rolling e o novo campo sai nulo.

## Policy governada
`ANALISE_PARAMS.risco_janela_movel_observacoes = 21`.

Semântica:
- unidade = observações de retorno, não dias corridos;
- janela explícita do usuário prevalece;
- sem janela explícita, a policy vigente governa;
- não existe fallback literal 21 no código;
- produção continua exigindo aprovação de compliance da policy; o banco descartável de CI usa o fluxo de aprovação já existente em `preparar_ambiente.py`.

Decisão: `.ai/RISK_ROLLING_POLICY_DECISION_2026-10-03.md`.

## Replay 1.1.0
Replay congelado em:
- `app/tools/analista/risco_retorno_legacy_1_1_0.py`;
- `tests/golden/quant_risco_retorno_1_1_0.json`.

O golden prova payload 1.1.0 exato. A execução default 1.2.0 preserva os campos/números 1.1.0 e apenas adiciona `evolucao_volatilidade=null`.

## Reuse-before-build
Nenhuma matemática nova:
- retornos: `quant_returns.calculate_returns()`;
- rolling: `quant_risk.rolling_volatility()`;
- compactação mensal: `amostrar_mensal()`;
- base de retorno/vol/downside/drawdown existente preservada.

Nenhuma fonte, tabela, migration ou loader novo.

## Compactação
- resumo/min/max/início/fim usa a série rolling completa;
- pontos client-facing usam último ponto de cada mês;
- cap estrutural de 60 pontos aproximadamente equidistantes, preservando pontas;
- métricas nunca são recalculadas sobre a amostra;
- payload representativo <5 KB.

## Temporalidade/provenance
### adjusted_close
- `market.v_precos_ajustados`;
- `retrospective_as_known_now`;
- warning `adjusted_close_retrospective`.

### raw_close
- `market.prices`;
- `observation_date_cutoff`;
- sem warning de adjusted retrospective.

Cutoff, ingestion batch, policy metadata, evidence e quality continuam auditáveis.

## Planner/bloco/evals
- pergunta agregada de risco/volatilidade continua sem rolling;
- somente intenção temporal/rolling ativa `incluir_evolucao_volatilidade=true`;
- planner não converte dias corridos em observações;
- bloco mantém indicadores e adiciona uma única série de volatilidade móvel quando presente;
- bloco rotula janela em observações e não infere forecast/sinal/recomendação;
- eval de evolução temporal adicionado.

## Gate final #334
- PostgreSQL 18 + migrations/invariantes: GREEN;
- directed gate: **186 passed**;
- benchmark peers: **10/10/10 queries**;
- full suite: **929 passed, 53 skipped, 19 warnings, 0 failed**;
- prompts check: GREEN;
- tools sync --check: GREEN;
- catálogo: **37 total / 34 públicas / 3 ocultas-replay**.

## Limites preservados
Fora desta capability:
- Sharpe/Sortino/Calmar;
- VaR/Expected Shortfall;
- stress/choque;
- forecast;
- sinal/recomendação;
- Portfolio Analytics.

## Próximo passo
Reabrir o capability audit restante de Company & Market Analytics.

Candidatos continuam:
- Brent/commodities somente após source audit oficial;
- fair value/reverse DCF somente após premissas governadas;
- source priority/vintages/storage quando uma capability concreta exigir.

Não assumir nova FQ automaticamente.
