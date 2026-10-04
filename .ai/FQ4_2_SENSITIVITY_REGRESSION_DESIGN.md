# FQ4.2 — Regression / Sensitivity Engine

Data: 2026-09-21
Estado: design congelado antes do código

## Objetivo

Criar a primeira regressão do Quant Core e a tool `quant.sensibilidade` sem transformar correlação em causalidade, sem imputar dados, sem remover outliers silenciosamente e sem introduzir uma dependência numérica pesada antes de ela ser necessária.

A pergunta-alvo é do tipo:

> "Historicamente, quanto o retorno de PETR4 esteve associado a uma mudança de 1 p.p. da Selic?"

O resultado é uma **associação linear histórica**, não efeito causal, previsão ou recomendação.

## Separação de responsabilidades

- `conditional.py` continua responsável por transformar a série driver em intervalos auditáveis e alinhar a resposta no mesmo intervalo sem look-ahead.
- `regression.py` será genérico: recebe pares numéricos já alinhados e estima regressão linear simples com intercepto.
- `sensitivity.py` será o adapter quantitativo: escala driver/resposta para unidades client-facing, chama a regressão e produz diagnóstico de frequência/unidade.
- `quant.sensibilidade` resolve dados/policy/provenance e converte o resultado para `EvidenciaEstatistica`/output compacto.

## Modelo estatístico inicial

Regressão univariada com intercepto:

`Y_t = alpha + beta * X_t + epsilon_t`

- `Y_t`: retorno simples do ativo-resposta no intervalo definido pelo driver, em **pontos percentuais de retorno** (`retorno * 100`).
- `X_t` depende semanticamente do driver:
  - ativo ou índice em pontos: retorno simples do driver no intervalo, em **pontos percentuais de retorno** (`retorno * 100`);
  - taxa/percentual: mudança do nível entre observações consecutivas, na unidade já armazenada pelo dataset (pontos percentuais).
- `beta` é a sensibilidade histórica linear por uma unidade de `X`; nunca recebe linguagem causal.

## Unidade do slope

- driver em retorno: `pct_return_per_pct_driver_return`;
- driver taxa/percentual: `pct_return_per_percentage_point`.

O intercepto usa `pct_return`.

## OLS vs incerteza robusta

A estimativa pontual (`alpha`, `beta`) é OLS com intercepto.

A incerteza padrão da primeira versão usa **HAC/Newey–West com kernel Bartlett e correção finita n/(n-k)**, pois as observações são ordenadas no tempo e HC1 isolado não corrige autocorrelação residual.

Não haverá escolha livre de covariance estimator no schema LLM da v1. A escolha fica versionada no código e explícita no output/método.

### Lags Newey–West

Se não houver lag explícito no engine, usar a regra automática convencional:

`L = floor(4 * (n / 100) ** (2 / 9))`

limitada a `0 <= L <= n - 2`.

`L` é medido em **observações**, não dias, e é devolvido no resultado/evidência.

A tool v1 não expõe `hac_lags` à LLM; isso evita schema desnecessário, mas o valor resolvido permanece auditável.

## Intervalo de confiança

- bilateral;
- nível inicial: 95%;
- aproximação normal assintótica usando `NormalDist.inv_cdf` da stdlib;
- método explicitado no `ConfidenceInterval`;
- sem p-value e sem booleano `significant`.

Não será adicionada SciPy/statsmodels nesta fase. A implementação é pequena, determinística, golden-testável e usa apenas stdlib.

## Amostra mínima

Três níveis distintos:

1. `n < 2` ou driver constante: slope não identificável → `estimate=None` + warning;
2. `n == 2`: slope/intercept podem ser calculados, mas não há graus de liberdade residuais → ponto estimado sem SE/CI + warning;
3. `n >= 3`: HAC/CI podem ser calculados quando a matriz é identificável.

Separadamente, `ANALISE_PARAMS.min_observacoes` define suficiência de produto. Uma amostra com `n < min_observacoes` continua podendo devolver estimativa matematicamente calculável, mas `Evidencia.suficiente=false` e `serie_curta`.

## Frequência

O **driver define o relógio**, igual ao FQ4.1.

- cada par usa o intervalo entre duas observações consecutivas do driver;
- o retorno da resposta usa o último preço disponível em ou antes de cada endpoint;
- `max_dias_defasagem` limita o quanto o as-of pode recuar;
- nunca há preenchimento futuro/interpolação.

A regressão registra `min/mediana/max` dos dias de intervalo. HAC lags continuam em número de observações. Não classificaremos frequência como “regular/irregular” por threshold escondido na v1.

## Missing data

Nenhuma imputação.

Intervalos sem endpoints válidos são omitidos pelo alinhamento determinístico; `n` sempre representa os pares realmente usados.

## Outliers

Nenhuma winsorização, trimming ou exclusão automática por magnitude na v1.

Motivo: qualquer regra de outlier precisa ser explícita, versionada e explicável. A robustez inicial entra na covariance (HAC), não por apagar observações.

## Diagnósticos

O engine retorna, no mínimo:

- slope;
- intercepto;
- SE robusto de ambos quando disponível;
- CI bilateral;
- `r_squared` quando definido;
- `n`;
- `hac_lags`;
- nível do CI;
- soma de quadrados residual/total para testes/auditoria interna;
- warnings matemáticos.

## `quant.sensibilidade` v1

Parâmetros LLM:

- `ticker` resposta;
- exatamente um entre `ticker_driver` e `indice_driver`;
- janela (`janela_dias`, `de`, `ate`, `data_referencia`);
- `price_basis` dos ativos, default `adjusted_close`.

Deliberadamente fora da v1:

- regressão múltipla;
- lag como parâmetro LLM;
- escolha de covariance estimator;
- winsor/outlier cutoff;
- p-value/significância;
- causalidade;
- previsão;
- Newey–West em unidades de dias corridos.

A tool nasce `exposed_to_llm=False` (shadow) e só pode ser promovida depois de testes + gate PostgreSQL/sync.

## Linguagem

Permitido:

- “associação linear histórica”;
- “sensibilidade estimada”;
- “na amostra, +1 p.p. no driver esteve associado a X p.p. no retorno”.

Proibido como conclusão da tool:

- “causou”;
- “efeito de”;
- “vai gerar”;
- “prevê”;
- “significativo” sem contrato formal futuro.
