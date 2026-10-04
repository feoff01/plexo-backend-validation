# FQ5.6B — Comparação de peers por subsetor/setor — shadow design

Data: 2026-10-01
Estado: **design para implementação shadow; promoção pública bloqueada por coverage real**

## Objetivo

Responder de forma determinística perguntas como:
- "quem são os pares da Petrobras?";
- "como PETR4 negocia contra o subsetor?";
- "o P/L/EV-EBITDA/P-VP está acima ou abaixo da mediana dos pares?";
- "como crescimento e margens da empresa se comparam ao grupo?".

Não produz recomendação, ranking de qualidade, score, fair value, preço-alvo ou decisão de investimento.

## Gate reuse-before-build

Não haverá matemática nova.

Reuso obrigatório:
- universo/identidade setorial: `app.market.sectors.peer_issuers`;
- valuation: `quant.valor_mercado` (preparador + calculador existentes);
- tendências/margens: `quant.tendencias_fundamentais`;
- distribuição: `app.market.analytics.statistics.describe`.

É proibido copiar fórmulas de market cap, EV, múltiplos, crescimento ou margens para a tool de peers.

## Fonte setorial

Fonte canônica: B3, via `market.sector_classification`.

Contrato oficial materializado:
- download B3 com `SETOR / SUBSETOR / CÓDIGO`;
- `subsetor` é o nível mais granular disponível no XLSX;
- `segmento` não existe no arquivo e fica fora da v1.

Níveis v1:
- `subsetor` — default;
- `setor` — opt-in explícito.

Sem auto-widen de subsetor para setor quando a amostra for pequena.

## Tool candidata

`quant.comparaveis_setor` 1.0.0 **shadow** (`exposed_to_llm=False`).

Parâmetros:
- `ticker`;
- `data_referencia`;
- `nivel: subsetor|setor = subsetor`;
- `metricas` opcional; default = conjunto canônico abaixo;
- `max_exemplos` apenas para lista compacta, nunca para cortar a distribuição.

## Métricas canônicas v1

Valuation:
- `pe`;
- `ev_ebitda`;
- `price_to_book`;
- `fcf_yield_pct`.

Tendência/fundamentos:
- `revenue_yoy_pct`;
- `ebitda_yoy_pct`;
- `net_income_yoy_pct`;
- `ebitda_margin_pct`;
- `net_margin_pct`.

Contexto:
- `market_cap_brl` pode ser retornado para target/exemplos e distribuição de porte, mas não vira score ou critério de "melhor".

Tendências usam apenas os 2 últimos DFP anuais PIT necessários para YoY/margem mais recente.

## Universo e identidade

- target deve ser ação `is_in_universe=true`;
- peers são issuers distintos com ação no universo;
- excluir o issuer do target;
- múltiplas classes do mesmo issuer contam uma vez;
- usar um ticker representativo determinístico apenas para chamar as tools company-level existentes;
- distribuição usa **todos** os peers válidos, nunca somente os exemplos exibidos.

## Estatística

Para cada métrica:
- target value;
- `n_valid`;
- mean;
- median;
- sample_stddev;
- min;
- max;
- unidade.

Missing não vira zero.

Delta target-mediana:
- múltiplos: diferença absoluta em `x`;
- percentuais/yields/margens/crescimentos: diferença em pontos percentuais;
- market cap: sem "premium/discount" avaliativo; apenas diferença absoluta opcional/contexto.

Não produzir percentile rank, ranking, score ou winner na v1.

## Output compacto

- target;
- classificação B3 resolvida;
- nível;
- peer_count_total;
- lista de comparações por métrica;
- exemplos de peers limitados e **ordenados alfabeticamente**, para não parecer ranking;
- provenance/warnings.

O resolved/audit pode conter insumos completos; o output enviado ao LLM não deve despejar a tabela inteira de peers.

## Performance

A primeira implementação shadow poderá compor os preparadores canônicos por peer (N+1 controlado) para maximizar correção/reuso.

Antes de promoção:
- medir custo em subsetores/setores reais;
- se necessário, criar preparação batch que continue chamando engines existentes;
- não otimizar copiando fórmulas.

## Warnings

- `classificacao_setorial_indisponivel`;
- `pares_insuficientes`;
- `peer_sem_ticker`;
- `peer_sem_valuation`;
- `peer_sem_tendencia`;
- `metrica_target_indisponivel`;
- `metrica_peer_amostra_insuficiente`.

## Semver/fingerprint/replay

- nova intenção => 1.0.0 shadow;
- `source_dependencies` inclui setores, statistics e módulos canônicos de valuation/tendências;
- nenhuma tool existente deve mudar fingerprint;
- quando/SE promovida, seguir padrão do projeto para bump de exposição/semver e golden/replay.

## Testes antes de considerar shadow GREEN

- target multi-classe não duplica empresa;
- peers multi-classe deduplicados;
- target excluído;
- subsetor default e setor explícito;
- sem segmento;
- distribuição usa todos os peers válidos;
- missing reduz n_valid;
- valores são idênticos às tools canônicas chamadas isoladamente;
- exemplos não afetam estatística;
- output compacto;
- registry: 34 -> 35 apenas pela nova tool shadow; 34 existentes sem drift;
- PostgreSQL 18 + suíte completa + prompts check + tools sync.

## Promoção pública

FQ5.6B **não será exposta ao LLM** até:
1. coverage real B3 × catálogo Plexo medido;
2. gaps unresolved/ambiguous explicados;
3. performance real aceitável;
4. E2E/golden/planner/blocos prontos;
5. decisão registrada em `.ai/`.

Até lá, a tool é laboratório determinístico shadow.
