# Checkpoint — composição oficial de índice shadow candidate

Data: 2026-10-03
Status: **CANDIDATE / aguardando PostgreSQL 18**

## Gap provado
- `market.index_weights` e ingestão B3/IBrA já existiam e estavam GREEN;
- não existia consumer client-facing PIT para membership/peso;
- nenhuma matemática, tabela ou fonte nova era necessária.

## Implementação
- `app/market/index_compositions.py`: loader read-only strict PIT;
- `dados.composicao_indice` 1.0.0 shadow, `exposed_to_llm=False`;
- data exata não faz nearest/fallback;
- sem filtro, output é limitado e ordenado por peso oficial apenas para apresentação;
- com `tickers`, matching é exato e ausentes viram warning;
- valida soma de pesos próxima de 100%, ticker único, fonte e lote;
- nenhuma migration, planner ou bloco público.

## Catálogo esperado
- 37 tools no registry;
- 33 expostas ao LLM;
- 4 ocultas, sendo 3 legacy/replay + 1 shadow nova.

## Gate pendente
- PostgreSQL 18/migrations/invariantes;
- testes shadow puros + DB;
- strict PIT/look-ahead;
- gate dirigido;
- suíte completa;
- prompts check;
- tools sync --check;
- payload/provenance antes de qualquer promoção.
