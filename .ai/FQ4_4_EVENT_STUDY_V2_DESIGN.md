# FQ4.4 — Event Study v2 Design

Data: 2026-09-25
Status: design congelado antes da implementação.

## Objetivo

Migrar o estudo de evento para `MarketSeriesLoader + Quant Core`, preservar literalmente a implementação/golden `quant.event_study` 1.0.1 durante a fase shadow e introduzir incerteza estatística somente sob método explícito e auditável.

## Estratégia de migração

- NÃO editar a implementação registrada `quant.event_study` 1.0.1 nesta etapa.
- Criar `quant.event_study_v2` 1.0.0 em `exposed_to_llm=False`.
- O legado continua sendo a única tool visível para novos turnos enquanto a v2 é validada.
- O cutover será uma etapa separada: mover a implementação 1.0.1 para módulo legacy de replay e promover a v2 para o código canônico `quant.event_study` com bump apropriado.
- Esta etapa não promete que o executor atual consegue selecionar versões históricas arbitrárias pelo banco; o replay da 1.0.1 é preservado mantendo seu código/modelos/golden intactos até o cutover.

## Data Foundation

A v2 usa `ResolvedMarketSeries` diretamente.

### Base de preço

- default: `adjusted_close`;
- opt-in: `raw_close`;
- `adjusted_close` implica `retrospective_as_known_now`;
- `raw_close` implica `observation_date_cutoff`.

A mesma basis é aplicada ao ativo e ao benchmark.

### Evento efetivo

A data efetiva não é escolhida só pela existência de preço do ativo. Ela é o primeiro retorno ALINHADO ativo × benchmark com data >= `data_evento`.

Isso garante que o próprio ponto de evento é calculável nas duas séries.

## Relógio e janelas

Todas as janelas são medidas em observações de retorno alinhadas, não em dias corridos.

Parâmetros v2:
- `janela_estimacao_observacoes`;
- `pre_observacoes`;
- `pos_observacoes`.

A janela de evento é inclusiva em [-pre, +pos]. A janela de estimação termina imediatamente antes do início da janela de evento, evitando overlap.

A v2 expõe truncamento pré e pós separadamente. CAR parcial pode ser calculado quando existe parte da janela, mas `Evidencia.suficiente` não deve tratar janela truncada como estudo completo.

## Métodos de retorno esperado

### `market_model`

`r_ativo = alpha + beta * r_benchmark + epsilon`

- alpha/beta pontuais vêm do Regression Core OLS;
- a v2 não usa o SE HAC de alpha/beta como substituto da incerteza do efeito do evento.

### `market_adjusted`

`alpha = 0`, `beta = 1`.

## Retorno anormal e CAR

`AR_t = r_ativo,t - (alpha + beta*r_benchmark,t)`

`CAR = sum(AR_t)` na janela de evento disponível.

O output pode conter AR por observação porque a janela é pequena por design; não envia séries históricas completas, pares de estimação ou resíduos.

## Inferência

### Default: `none`

- mantém caráter descritivo;
- nenhum p-value;
- nenhum rótulo `significant`;
- `car_estimate` inferencial não é produzido.

### Opt-in: `classic_iid_normal`

Fornece SE e CI bilateral do CAR sob hipóteses clássicas EXPLÍCITAS:
- resíduos iid/homoscedásticos na janela de estimação;
- aproximação normal;
- ausência de event-induced variance;
- modelo corretamente especificado.

Não é o mesmo método HAC usado por `quant.sensibilidade`.

#### Market model

Com T observações na estimação e L observações no evento:

`Var(CAR) = sigma² * [L + L²/T + (sum(x_evt) - L*xbar_est)² / Sxx_est]`

onde `sigma² = SSE/(T-2)`.

Requer:
- T >= 3;
- benchmark com variação (`Sxx > 0`);
- CAR calculável.

#### Market adjusted

`SE(CAR) = sd(residuos_estimacao) * sqrt(L)`

com desvio-padrão amostral na janela de estimação.

Requer T >= 2.

### Envelope

A inferência usa `MetricEstimate`:
- estimate = CAR em pontos percentuais;
- standard_error;
- confidence_interval;
- n = tamanho da janela de evento efetivamente usada;
- method explícito;
- warning permanente de hipótese forte quando definida.

## Suficiência

Separar:
- ponto matematicamente calculável;
- inferência calculável;
- suficiência de produto (`ANALISE_PARAMS.min_observacoes`);
- janela completa.

`Evidencia.suficiente` exige, no mínimo:
- método pontual calculável;
- janela de evento não vazia;
- janela de estimação >= `min_observacoes` para market_model;
- janela de evento não truncada;
- sem instrumento ausente/fora de cobertura.

Inferência pode estar indisponível mesmo com CAR descritivo disponível.

## Não fazer nesta versão

- p-value;
- decisão automática de significância;
- bootstrap;
- cross-sectional event study;
- múltiplos eventos/agregação de empresas;
- ajuste por fatores além de um benchmark;
- event-induced variance correction;
- seleção endógena de janela;
- causalidade.

## Output compacto

Devolver:
- ticker/benchmark;
- requested/effective event date;
- price basis/temporal semantics/return method;
- método;
- janela de estimação;
- janela de evento;
- truncamento pré/pós;
- alpha/beta;
- residual stddev;
- AR somente da janela de evento;
- CAR;
- `car_estimate` somente quando inferência solicitada;
- EvidenciaEstatistica.

Não devolver:
- preços históricos completos;
- retornos da estimação;
- pares completos;
- resíduos completos.
