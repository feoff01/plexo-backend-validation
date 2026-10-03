# Analista de Mercado — Plano canônico

## Objetivo

Expandir o Analista com cálculos determinísticos de mercado sem envolver planejamento financeiro pessoal.

## Catálogo Quant alvo

```text
quant.risco_retorno
quant.dependencia
quant.analise_condicional
quant.sensibilidade
quant.regimes
quant.event_study
```

### Migração

```text
quant.retorno_volatilidade -> legacy -> quant.risco_retorno
quant.correlacao            -> legacy -> quant.dependencia
quant.event_study            -> mantém nome, evolui implementação
```

## Camadas

```text
LLM / Research planner
        ↓
Tools canônicas
        ↓
Quant Engines
        ↓
Market Series/Data Access
        ↓
market.* / futuro historical store
```

### Tool

Responsável por schema, policies, resolução de inputs, adaptação para `Evidencia`/`output_payload`.

### Engine

Responsável por matemática pura e modelos estatísticos. Não conhece LLM, prompt ou SSE.

### Data access

Responsável por cutoff, preço, calendário, corporate actions, frequência, alinhamento, qualidade e proveniência.

## Quant Engines planejados

```text
series / market-series-loader
returns
risk
dependence
statistics
conditional
events
regression/sensitivity
regimes
```

## Research

Research combina investigações completas, não fórmulas.

Exemplo "o que acontece com PETR4 quando juros caem?":

```text
quant.analise_condicional
quant.event_study
quant.sensibilidade
quant.regimes
```

## Ordem

1. FQ0.5 — fingerprint/exposição de tools.
2. FQ1 — Quant Data Foundation.
3. FQ2 — engines base.
4. FQ3 — tools canônicas risco/retorno e dependência.
5. FQ4 — condicional, sensibilidade, regimes, event study v2.
6. Só depois fundamentos, valuation, fatores, renda fixa, derivativos e backtesting.

## Regras estatísticas

- sample size específico por método;
- sem multiple-testing silencioso;
- sem remoção de outlier silenciosa;
- missing/fill sempre declarado;
- correlação/regressão/event study são associacionais por padrão;
- janelas/thresholds default vivem em policy, não no prompt;
- outputs para LLM devem ser compactos; séries grandes não devem entrar no contexto sem necessidade.

## Decisões abertas

- storage histórico definitivo;
- biblioteca numérica (`numpy`/`scipy`/`statsmodels`) após benchmark/deploy review;
- semântica point-in-time de corporate actions;
- mecanismo de output compacto/artifacts se `output_payload` atual se mostrar insuficiente.


## FQ2.2 — Risk Engine (concluído no working copy)

Implementado:
- annualized volatility;
- rolling volatility;
- downside deviation;
- drawdown series;
- maximum drawdown;
- maximum drawdown episode;
- duração/recovery em intervalos observados.

`quant.retorno_volatilidade` foi migrada para o Risk Engine sem mudar o golden e está em `1.0.3`.

Não incluído ainda: Sharpe, Sortino, Calmar, VaR, Expected Shortfall. Esses dependem de contratos adicionais (risk-free/target/cauda) e entram somente depois do núcleo base.

## FQ2.3 — Dependence Engine (concluído no working copy)

Implementado:
- Pearson compatível com legacy;
- Spearman com ranks médios em empates;
- alinhamento por interseção sem padding;
- lag assinado preservando datas de X/Y;
- rolling dependence;
- up/down-market condicionado ao retorno do market;
- migração de `quant.correlacao` para o engine, sem mudar golden, em `1.0.2`.

O Quant Core base (returns/statistics/risk/dependence) está fechado. `quant.event_study` permanece na FQ4, junto das investigações econômicas.

FQ3 concluído no código: tools canônicas implementadas e cutover de catálogo aplicado. Próximo gate é PostgreSQL CI + sync; depois abre FQ4.

## Checkpoint FQ3.1 — 2026-09-21

FQ3 adotou migração shadow + cutover atômico. `quant.risco_retorno` e `quant.dependencia` estão expostas no código; as duas legacy estão ocultas para novos turnos/planos e preservadas para replay. O planner já usa códigos canônicos. Ativação em produção ainda depende de PostgreSQL CI + sync de tools/prompt.


## Checkpoint FQ3.3 — 2026-09-21

Cutover canônico concluído no código. Versões: `quant.risco_retorno` 1.0.1 e `quant.dependencia` 1.0.1 expostas; `quant.retorno_volatilidade` 1.0.4 e `quant.correlacao` 1.0.3 ocultas. Planner/evals/Research/blocos migrados. Regressão local: 324 passed, 16 skipped, 355 DB-deselected, 0 failed. Antes de produção: PostgreSQL CI, `tools sync --check`/sync e governança do planner.

## Checkpoint FQ4.1 — 2026-09-21

`quant.analise_condicional` foi implementada em shadow mode sobre um novo Conditional Engine puro. A semântica central é interval-based: a condicionante define os endpoints e o retorno simples do ativo é medido no mesmo intervalo usando somente preços em ou antes das datas. Ativo/índice em pontos condiciona por retorno; taxa/percentual por mudança de nível. A tool é descritiva, sem causalidade/significância, compara amostra condicional com baseline e preserva métricas em amostra curta com warning. Regressão local: 343 passed, 16 skipped, 355 DB-deselected, 0 failed. Promoção depende do primeiro gate PostgreSQL verde.

### FQ4.2 foundation — contrato de estimativa

Antes de regressão/sensibilidade:

- `MetricEstimate`: estimate, unit, n, standard_error, confidence_interval, method, warnings;
- `ConfidenceInterval`: lower, upper, level, method opcional;
- `EvidenciaEstatistica` adiciona `estimativas` sem alargar o `Evidencia` legacy;
- findings quantitativos persistem estimativas somente quando presentes;
- sem `p_value`/`significant` no envelope base; essas decisões pertencem ao método da futura tool.

Arquivos novos ficam fora de `models.py`/`_comum.py` para não alterar fingerprints de tools existentes.


## Checkpoint FQ4.2 — Regression/Sensitivity

`quant.sensibilidade` 1.0.0 foi implementada em shadow mode. O modelo inicial é OLS univariado com intercepto e covariance HAC/Newey-West Bartlett + correção finita. Driver em taxa/percentual usa mudança de nível em p.p.; driver ativo/índice em pontos usa retorno simples em p.p.; resposta é retorno simples do ativo no mesmo intervalo. A tool não imputa missing nem remove outlier. O bandwidth Newey-West é automático e explícito no output; CI é 95% normal assintótico, sem p-value/significant. Regressão ampla local: 383 passed, 16 skipped, 355 DB-deselected, 0 failed. Promoção depende do gate PostgreSQL/sync.


## Status FQ4.3 — regimes

Implementado em shadow mode:
- `quant.regimes` 1.0.0;
- `nivel`: alto/baixo por corte explícito ou mediana retrospectiva;
- `direcao`: alta/queda por retorno ou mudança de nível;
- retorno da resposta medido nos mesmos intervalos sem look-ahead;
- estatísticas descritivas por grupo, sem drawdown em amostras descontínuas e sem clustering oculto.

Gate de promoção continua sendo PostgreSQL CI + sync/governança.


## Checkpoint FQ4.4 — Event Study v2 (2026-09-25)

- engine puro concluído;
- v2 shadow concluída;
- replay 1.0.1 congelado;
- legacy visível 1.0.2 apenas com correção de linguagem;
- CI clássico do CAR é opt-in e não produz decisão de significância;
- alinhamento correto é preço-com-preço antes de retorno;
- promoção/cutover depende de PostgreSQL CI + tool/prompt sync.

## Status canônico após FQ4 — 2026-09-30

FQ4 foi promovido e fechado no repositório de validação com PostgreSQL 18 real em CI.

Catálogo Quant público atual:

- `quant.risco_retorno` 1.0.1;
- `quant.dependencia` 1.0.1;
- `quant.analise_condicional` 1.0.1;
- `quant.sensibilidade` 1.0.1;
- `quant.regimes` 1.0.1;
- `quant.event_study` 2.0.0.

O alias `quant.event_study_v2` não está registrado. O replay histórico do Event Study permanece preservado.

Antes de abrir fundamentos/valuation/fatores/renda fixa/derivativos/backtesting, fechar as decisões transversais ainda abertas: storage histórico, prioridade de fontes, availability/vintage real e mecanismo de outputs longos/artifacts. A ordem exata das próximas famílias ainda não foi congelada.


## STATUS CANÔNICO — 2026-10-03

O roadmap já avançou além de várias fases históricas deste documento. Estado atual: FQ4 encerrado; FQ5.5 e FQ5.6 públicas/GREEN; FQ5.7 yield-curve foundation GREEN sem tool pública.

Use `.ai/CURRENT_PROJECT_MAP_2026-10-03.md` e `.ai/NEXT_CHAT_HANDOFF_FINAL.md` como fonte de verdade antes de interpretar tarefas antigas deste plano.
