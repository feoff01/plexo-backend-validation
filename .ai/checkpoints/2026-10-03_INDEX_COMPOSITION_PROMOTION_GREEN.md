# Checkpoint — dados.composicao_indice promotion GREEN

Data: 2026-10-03
Status: **GREEN / capability pública**

## Capability
- `dados.composicao_indice` **1.0.1**;
- `exposed_to_llm=True`;
- família `dados`;
- catálogo: **37 tools**, **34 expostas**, **3 ocultas/replay**.

## Reuse-before-build
- reutiliza `market.index_definitions`, `market.index_weights`, `market.ingestion_batches` e identidade de instrumentos;
- reutiliza o snapshot oficial B3/IBrA já ingerido;
- nenhuma migration, tabela paralela, fonte nova ou matemática nova;
- loader é somente leitura e strict PIT por lote `succeeded` / `finished_at <= cutoff`.

## Contrato público
A capability responde composição/membership/peso de snapshot oficial persistido:
- membros;
- pesos oficiais;
- quantidade teórica quando publicada;
- filtro por tickers exatos;
- data econômica exata quando explicitamente pedida.

Não:
- infere membership para data sem snapshot;
- escolhe nearest/fallback silencioso;
- calcula performance/retorno do índice;
- transforma peso em ranking de atratividade;
- faz recomendação;
- analisa carteira do cliente.

## Planner / bloco / payload
- planner separa composição/peso de índice de `dados.serie_indice`;
- bloco client-facing é tabela factual derivada somente do output da tool;
- readiness/payload regression gate GREEN;
- contrato limita resposta sem filtro a 25 componentes e o teste conservador permanece abaixo de 5 KB.

## Gate pós-promoção
HEAD funcional validado: `d431fa91d5e2e39eb6e2ad0db7be2cecab2c7ffa`.
Run #283 / `37153499452`: **success**.

- PostgreSQL 18.6 + migrations/invariantes: GREEN;
- directed gate: **153 passed**;
- benchmark FQ5.6 peers: **10/10/10 queries**, payloads 4009/4171/4163 bytes;
- full suite: **914 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: GREEN;
- tools sync --check: GREEN.

## Estado
Tranche de composição oficial de índice encerrada para leitura factual de snapshots persistidos.

Próxima ação obrigatória: reabrir o capability audit no estado atual e aplicar `reuse-before-build`; não assumir nova numeração/FQ e não abrir Portfolio Analytics.
