# FQ2.3 — Dependence Engine Design

Data: 2026-09-21
Base: FQ2.2 concluído.

## Objetivo

Criar uma camada matemática pura para dependência entre séries de retorno e migrar `quant.correlacao` para ela sem alterar o contrato/output legacy.

## Escopo desta etapa

Implementar:
- Pearson;
- Spearman com ranks médios em empates;
- alinhamento por interseção de datas;
- lag assinado;
- rolling dependence;
- up-market/down-market dependence condicionada ao retorno da série de mercado;
- modelos internos imutáveis para pares/estimativas.

Fora desta etapa:
- partial correlation;
- Kendall;
- tail dependence/copulas;
- mutual information;
- Granger/cointegração;
- causalidade;
- nova tool pública `quant.dependencia`.

## Semântica de lag

`lag_observations` é medido sobre a sequência de DATAS COMUNS após a interseção das duas séries.

- `lag = 0`: `x[t]` com `y[t]`;
- `lag > 0`: `x[t]` com `y[t+lag]` — X antecede Y;
- `lag < 0`: `x[t]` com `y[t+lag]` — Y antecede X.

Cada par preserva `x_date`, `y_date` e `as_of_date=max(x_date,y_date)` para evitar esconder a temporalidade do pareamento.

A tool legacy continua aceitando apenas lag >= 0 e mantém sua interpretação atual.

## Pearson

- usa correlação amostral equivalente a `statistics.correlation` no domínio normal;
- exige comprimentos iguais;
- menos de 2 pares => `None`;
- série constante => `None`;
- NaN/inf => fail closed;
- correlação não é causalidade.

## Spearman

- transforma cada vetor em ranks crescentes;
- empates recebem rank médio;
- calcula Pearson sobre os ranks;
- menos de 2 pares ou rank constante => `None`.

## Rolling dependence

- primeiro alinha as séries com a semântica de lag acima;
- `window` é número de PARES alinhados, não dias;
- sem padding/interpolação;
- cada resultado é datado em `as_of_date` do último par da janela;
- janela com série constante produz coeficiente `None`, não zero.

## Up/down market

Funções condicionais recebem `asset` e `market`.

- up-market: pares em que `market_return > threshold`;
- down-market: pares em que `market_return < threshold`;
- retorno exatamente igual ao threshold é neutro e excluído;
- threshold default = 0.0 e precisa estar na mesma convenção/período dos retornos;
- condicionamento é feito DEPOIS do alinhamento/lag;
- resultado continua associacional, nunca causal.

## Migração legacy

`quant.correlacao` será migrada para:

`retornos -> align_returns -> dependence_estimate(Pearson)`

sem mudar:
- schema de entrada;
- schema de saída;
- nota client-facing;
- suficiência/avisos;
- golden atual.

A tool recebe patch bump e fingerprint passa a incluir `dependence.py` e os modelos compartilhados.

## Critérios de aceite

1. vermelho inicial por módulo ausente;
2. testes diretos de Pearson/Spearman/alinhamento/lag/rolling/up/down;
3. equivalência Pearson legacy em amostras sintéticas;
4. equivalência do lag legacy para lag >= 0;
5. golden `quant.correlacao` idêntico;
6. bateria ampla sem PostgreSQL sem regressões;
7. memória `.ai/` atualizada.
