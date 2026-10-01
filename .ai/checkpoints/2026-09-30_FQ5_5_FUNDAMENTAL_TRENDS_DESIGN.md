# Checkpoint — FQ5.5 Fundamental Trends Design

Data: 2026-09-30
Estado: design concluído; implementação inicia em shadow.

Documento: `.ai/FQ5_5_FUNDAMENTAL_TRENDS_DESIGN.md`.

Decisões principais:
- DFP anual PIT apenas;
- sem migration;
- sem editar `app/market/fundamentals.py` para não alterar fingerprints existentes;
- loader histórico em módulo novo;
- engine puro de variação YoY e margens;
- `quant.tendencias_fundamentais` 1.0.0 começa oculta;
- FQ5.6 bloqueado até FQ5.5 verde.
