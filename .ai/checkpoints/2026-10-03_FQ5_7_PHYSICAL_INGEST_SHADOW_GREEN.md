# Checkpoint — FQ5.7 physical ingest + shadow GREEN

Data: 2026-10-03
Status: **GREEN / source path completo / tool ainda shadow**

## Implementação validada
- payload físico oficial ANBIMA congelado: `CurvaZero_.csv`, 2.899 bytes;
- SHA-256: `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`;
- parser físico fail-closed: `app/market/anbima_yield_curve_source.py`;
- ponte física -> semântica: `app/market/yield_curve_ingest_anbima_csv.py`;
- ingestão semântica canônica reutilizada: `ingest_anbima_yield_curve()`;
- loader PIT existente reutilizado;
- `dados.curva_juros` 1.0.0 permanece shadow.

## Prova PostgreSQL
Run #234 / `37145970504` — success.

- PostgreSQL 18.6 + migrations: GREEN;
- validador + invariantes admin/service: GREEN;
- gate dirigido: **142 passed**;
- CSV oficial -> 103 linhas canônicas = 65 IPCA + 19 PRE + 19 inflação implícita;
- idempotência por hash: GREEN;
- hash inesperado falha antes de escrita: GREEN;
- benchmark peers preservado: 10/10/10 queries, payloads 4009/4171/4163 bytes;
- suíte completa: **903 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: GREEN;
- tools sync --check: GREEN;
- catálogo: 36 tools; a nova capability continua oculta.

## Próximo gate
Preparar promoção pública controlada de `dados.curva_juros` somente como leitura exata de uma curva/data:
- semver patch;
- bloco determinístico;
- planner restritivo;
- payload compacto/provenance;
- promotion readiness;
- CI pós-promoção.

Fora da v1: comparação/delta entre datas, slope/curvature, interpolação, extrapolação, duration/DV01, choque, forecast e fair value.
