# FQ4.3 — Regimes Engine / `quant.regimes`

Data: 2026-09-21
Estado: design congelado antes do código.

## Objetivo

Responder de forma determinística perguntas como:

- como um ativo se comportou em regimes de juros altos vs baixos;
- como um ativo se comportou quando inflação acelerou vs desacelerou;
- como um ativo se comportou quando um índice/ativo de mercado subiu vs caiu.

A tool é descritiva e histórica. Não afirma causalidade, previsão ou efeito estrutural.

## Princípios

1. O driver define os intervalos; a resposta do ativo é medida nos mesmos intervalos.
2. Endpoints da resposta usam somente o último preço conhecido em ou antes da data, respeitando `max_dias_defasagem`.
3. Regimes não contíguos NÃO formam uma trajetória econômica única; portanto a v1 não calcula drawdown por regime.
4. A v1 compara distribuição de retornos por regime: média, mediana, desvio amostral, mínimo, máximo e fração positiva.
5. Nenhuma imputação, winsorização ou trimming automático.
6. A tool nasce em shadow mode (`exposed_to_llm=False`).

## Critérios de regime

### `nivel`

Classifica cada intervalo pelo nível do driver **no início do intervalo**. Isso evita usar o nível de fim para classificar um retorno que começou antes dele.

Corte:

- se o usuário fornece `limiar`, ele é usado explicitamente;
- se omite, o corte é a mediana histórica dos níveis de início dos intervalos válidos.

Classes:

- `alto`: nível > corte;
- `baixo`: nível < corte;
- `neutro`: nível == corte.

A mediana da amostra é retrospectiva e deve ser rotulada como tal; não é um threshold point-in-time de backtest.

### `direcao`

Classifica pelo movimento do driver no intervalo.

Transformação:

- ativo ou índice em `pontos`: retorno simples;
- taxa/percentual: mudança do nível.

Classes:

- `alta`: mudança > +limiar;
- `queda`: mudança < -limiar;
- `neutro`: dentro do intervalo simétrico.

Default de `limiar`: zero.

## Unidade do limiar no contrato da tool

Para `nivel`:
- unidade original do driver (`taxa_aa`, `percentual`, `pontos`, etc.).

Para `direcao`:
- driver por retorno: limiar em pontos percentuais de retorno (`1.0` = 1%);
- driver taxa/percentual: limiar em pontos percentuais do nível (`0.25` = 0,25 p.p.).

O engine trabalha em escala matemática interna; a tool faz a conversão de interface.

## Output compacto

A tool deve devolver:

- ativo resposta;
- driver e tipo;
- critério;
- transformação do driver;
- corte/limiar efetivamente usado e origem (`explicit`, `sample_median`, `zero_default`);
- `n_total`, `n_neutro`;
- dois grupos de regime, cada um com:
  - rótulo;
  - n;
  - média de retorno;
  - mediana;
  - desvio amostral;
  - mínimo/máximo;
  - taxa positiva;
- diferença das médias entre grupo 1 e grupo 2;
- diferença da dispersão amostral quando definida;
- Evidencia.

Nenhuma série ponto a ponto entra no payload da LLM.

## Suficiência

A matemática pode existir com amostras pequenas; a tool não apaga métricas calculáveis.

`Evidencia.suficiente=true` somente se:

- qualidade base for suficiente; e
- os dois regimes tiverem pelo menos `ANALISE_PARAMS.min_observacoes` cada.

Warnings específicos:

- `regime_sem_duas_amostras`: um dos dois regimes ficou vazio;
- `regime_amostra_insuficiente`: pelo menos um regime existe, mas ficou abaixo da amostra mínima.

## Não escopo v1

- HMM/Markov switching;
- clustering/k-means;
- threshold otimizado por retorno;
- mudança estrutural endógena;
- inferência causal;
- drawdown por amostras não contíguas;
- p-value automático para diferença de regimes.

Esses itens exigem contratos e validação separados.
