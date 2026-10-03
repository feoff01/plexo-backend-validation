# Composição oficial de índice — plano de promoção

Data: 2026-10-03
Estado: **promoção autorizada após shadow GREEN**

## Shadow GREEN
Run #274 / `37151124590`:
- PostgreSQL 18 + migrations/invariantes: GREEN;
- gate dirigido: 150 passed;
- peers: 10/10/10 queries, payloads 4009/4171/4163 bytes;
- suíte completa: 911 passed, 52 skipped, 19 warnings, 0 failed;
- prompts check: GREEN;
- tools sync --check: GREEN;
- catálogo shadow: 37 tools, 33 públicas, 4 ocultas.

## Payload
Contrato limita a 25 componentes quando não há filtro de tickers. Medição conservadora com nomes longos ficou abaixo de 5 KB (~3,8 KB). O gate vira teste de regressão.

## Promoção
- `dados.composicao_indice` 1.0.1;
- `exposed_to_llm=True`;
- nenhuma mudança de schema/loader/matemática;
- planner deve distinguir composição/peso de índice de série/nível do índice;
- bloco client-facing deve ser tabela factual, sem linguagem de recomendação.

## Roteamento
Usar para:
- “quais ações compõem o IBrA?”;
- “qual o peso de PETR4 no IBrA?”;
- “mostre a composição disponível do índice”;
- snapshot exato quando a data for explicitada e existir.

Não usar para:
- performance/retorno do índice -> `dados.serie_indice` ou Quant apropriada;
- análise de carteira/overweight do cliente;
- inferir carteira histórica sem snapshot persistido;
- previsão/recomendação.

## Gate pós-promoção
- registry/public visibility;
- planner static contract;
- bloco determinístico;
- payload < 5 KB;
- PostgreSQL 18;
- directed gate;
- suíte completa;
- prompts check;
- tools sync --check;
- checkpoint GREEN antes de encerrar a tranche.
