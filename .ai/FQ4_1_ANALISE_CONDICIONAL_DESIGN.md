# FQ4.1 — `quant.analise_condicional`

Data: 2026-09-21
Estado: design congelado antes do código

## Objetivo

Responder perguntas descritivas do tipo:

- "Como PETR4 se comportou nos períodos em que a Selic caiu?"
- "Como VALE3 se comportou nos períodos em que o minério/índice subiu?"
- "O retorno do ativo foi diferente nos períodos de alta vs. queda da condicionante?"

A tool NÃO é regressão, NÃO é causalidade, NÃO é previsão e NÃO faz teste de significância nesta fase.
Ela mede a distribuição histórica do retorno do ativo nos mesmos intervalos em que uma segunda série
subiu ou caiu.

## Princípio central: condição e resposta são grandezas diferentes

A série condicionante não é convertida de uma única forma para todos os datasets.

### Condicionante = ativo ou índice em pontos

A condição é a variação relativa entre dois níveis consecutivos:

`return = P_t / P_(t-1) - 1`

- `alta`: retorno > 0;
- `queda`: retorno < 0;
- retorno = 0 é neutro e não entra em nenhuma direção.

### Condicionante = taxa/percentual (`taxa_aa`, `taxa_am`, `percentual`)

A condição é a mudança do NÍVEL informado:

`delta = nivel_t - nivel_(t-1)`

Isso é obrigatório. Converter Selic 14% a.a. em carry diário faria quase todos os retornos positivos e
não responderia se a taxa SUBIU ou CAIU.

- `alta`: delta > 0;
- `queda`: delta < 0;
- delta = 0 é neutro.

A unidade da mudança é pontos percentuais para séries percentuais/taxas.

## Relógio da análise: os intervalos da condicionante

A análise não pega simplesmente o retorno diário do ativo na data de uma série mensal/esparsa.
Cada mudança da condicionante define um intervalo `[t_(i-1), t_i]`.

Para esse mesmo intervalo, o retorno do ativo é medido entre:

- último preço do ativo conhecido em ou antes de `t_(i-1)`;
- último preço do ativo conhecido em ou antes de `t_i`.

Nenhum preço futuro é usado para preencher endpoint. O as-of de cada endpoint também respeita a tolerância versionada `max_dias_defasagem`; se o último preço anterior estiver velho demais, o intervalo é descartado. Se não houver dois endpoints distintos, aquele
intervalo não produz par.

Isso torna a semântica reutilizável para séries diárias ou esparsas e evita comparar, por exemplo,
uma mudança mensal de taxa com apenas um retorno diário do ativo.

## Retorno da resposta

O retorno do ativo por intervalo é retorno SIMPLES:

`P_fim / P_inicio - 1`

Motivo: é a medida diretamente interpretável como percentual de desempenho no intervalo da condição.
O FQ4.1 não herda `metodo_retorno=log` da policy para essa estatística descritiva.

## Base de preço

`price_basis` vale para todos os ativos envolvidos:

- default `adjusted_close` -> `retrospective_as_known_now`;
- opt-in `raw_close` -> `observation_date_cutoff`.

Índices/taxas usam `observation_date_cutoff` e não recebem `price_basis`.

## Input canônico inicial

- `ticker`: ativo cuja resposta é analisada;
- exatamente um entre `ticker_condicao` e `indice_condicao`;
- `direcao`: `alta` ou `queda`;
- `janela_dias` ou `de`/`ate`;
- `data_referencia`;
- `price_basis`: default `adjusted_close`.

Não expor nesta fase:

- threshold customizado;
- lead/lag;
- horizonte futuro;
- rolling;
- p-value/significância;
- regressão.

Esses parâmetros pertencem às fases de sensibilidade/regimes ou a uma evolução posterior.

## Resultado matemático

Para os pares válidos, produzir:

### Base

Todos os intervalos da condicionante com retorno de resposta observável.

### Condicional

Subconjunto cuja mudança satisfaz `direcao`.

### Estatísticas para retorno do ativo

- `n`;
- média;
- mediana;
- desvio-padrão amostral;
- mínimo;
- máximo;
- proporção de retornos positivos.

### Comparação

- número total de intervalos válidos;
- número de intervalos condicionais;
- proporção dos intervalos que satisfaz a condição;
- média condicional;
- média da base;
- diferença entre médias, em pontos percentuais;
- magnitude média/mediana da mudança condicionante.

Sem inferência estatística: diferença de médias pequena/grande não deve ser chamada de significativa.

## Suficiência

As estatísticas calculáveis NÃO são apagadas quando `n_condicional < min_observacoes`.

Motivo: eventos como cortes de Selic podem ser raros; esconder os números seria menos informativo.

A tool:

- calcula o que for matematicamente definido;
- marca `Evidencia.suficiente=false` quando a amostra condicional não atinge a policy;
- adiciona `serie_curta`;
- a LLM deve comunicar a fragilidade amostral.

Sem eventos na direção selecionada -> `sem_eventos_condicao` e métricas condicionais `None`.

## Output compacto

Não enviar séries/pairs para a LLM.

Output:

- ativo resposta;
- condicionante e tipo;
- direção;
- medida da condição (`retorno` / `variacao_nivel`);
- unidade da variação condicionante;
- base/semântica dos ativos;
- período efetivamente observado;
- `n_total`, `n_condicional`, proporção;
- resumo condicional;
- resumo base;
- diferença da média;
- magnitude média/mediana da condição;
- `Evidencia`.

## Migração/exposição

A tool nasce `exposed_to_llm=False` (shadow).

Motivo: FQ3 ainda tem gates DB/sync pendentes e esta é a primeira tool FQ4. O contrato deve ser
validado em isolamento antes de entrar no catálogo/planner.

## Fingerprint

A fingerprint deve cobrir ao menos:

- `analise_condicional.py`;
- `_comum.py`;
- `series.py`;
- `analytics/models.py`;
- `analytics/returns.py`;
- `analytics/statistics.py`;
- `analytics/conditional.py`.

## Fora de escopo FQ4.1

- causalidade;
- regressões;
- elasticidade/beta de sensibilidade;
- inferência estatística;
- regime clustering;
- event study v2;
- vintage point-in-time real.
