# Checkpoint — FQ5.7 dados.curva_juros promotion GREEN

Data: 2026-10-03
Status: **GREEN / capability pública**

## Capability pública
- `dados.curva_juros` **1.0.1**;
- `exposed_to_llm=True`;
- família `dados`;
- catálogo total: **36 tools**;
- públicas: **33**;
- ocultas/replay: **3**.

## Fonte e ingestão
- ANBIMA first-party `CurvaZero_.csv`;
- referência física: 02/10/2026;
- 2.899 bytes;
- SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`;
- 65 vértices IPCA / 19 PRE / 19 inflação implícita;
- parser físico fail-closed;
- bridge bytes -> ingestão semântica canônica;
- 103 linhas canônicas;
- idempotência por hash;
- strict PIT pelo lote succeeded/finished_at.

## Semântica pública
A tool lê somente vértices oficiais exatos de:
- `ettj_pre`;
- `ettj_ipca`;
- `inflacao_implicita`.

Não:
- interpola ou extrapola;
- converte prazo para vértice implicitamente;
- escolhe nearest;
- calcula delta entre datas;
- calcula slope/curvature;
- calcula duration/DV01;
- aplica choque;
- faz forecast;
- calcula fair value ou recomendação.

## Planner / apresentação
- roteamento explícito por tipo de curva;
- Selic/IPCA como série temporal continuam em `dados.serie_indice`;
- pergunta genérica "curva de juros" é explicitada como ETTJ prefixada;
- bloco determinístico: tabela para recorte pequeno, série para curva maior;
- provenance ANBIMA/cutoff e warning de vértice ausente;
- payload máximo observado da fixture oficial < 5 KB.

## Gate pós-promoção
Run #249 / `37146548276`: **success**.

- PostgreSQL 18.6 + migrations: GREEN;
- validador/invariantes admin + service: GREEN;
- directed gate: **145 passed**;
- peers: 10/10/10 queries, payloads 4009/4171/4163 bytes;
- full suite: **906 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: GREEN;
- tools sync --check: GREEN.

## Estado
FQ5.7 client-facing encerrada para a capability de leitura exata de curva.

Não existe FQ5.8 canônica congelada neste snapshot. Antes de nova feature, reabrir o capability audit/roadmap de Company & Market Analytics e aplicar reuse-before-build; Portfolio Analytics permanece fora de escopo.
