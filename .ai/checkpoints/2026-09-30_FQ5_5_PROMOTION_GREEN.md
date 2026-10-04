# Checkpoint — FQ5.5 Tendências Fundamentais PIT — promoção GREEN

Data: 2026-09-30
Status: **encerrado / público**

## Capacidade pública

- `quant.tendencias_fundamentais` 1.0.1
- DFP anual point-in-time por `availability_date <= cutoff`;
- histórico multi-período com vintage/restatement correto;
- crescimento YoY somente quando a base anterior é positiva;
- margens somente quando receita do mesmo período é positiva;
- EBITDA reportado prevalece sobre derivado;
- outputs compactos; sem séries brutas completas no payload do LLM.

## Limites deliberados

- ITR/trimestre fora da v1;
- sem CAGR;
- sem forecast;
- sem fair value/reverse DCF;
- `shares_outstanding` não entra na tendência company-level v1;
- nenhuma imputação de métrica faltante.

## Reuse-before-build

A implementação não alterou `app/market/fundamentals.py`, evitando drift de fingerprint em `dados.fundamentos_empresa` e `quant.valor_mercado`.

Novos módulos:
- `app/market/fundamental_history.py`;
- `app/market/analytics/fundamental_trends.py`.

As 33 tools existentes antes da tranche preservaram semver, exposição e source fingerprint. O catálogo passou de 33 para 34 apenas pela nova tool.

## Gates

Shadow:
- commit `e863e674d2a5b873d9502faa2915c25a65ddefd6`;
- run #56 / `36795497161` — success;
- gate explícito: 93 passed;
- suíte: 837 passed, 52 skipped, 19 warnings, 0 failed.

Promoção:
- commit `a8eb2bfeee7c77361fbefffe4d689b4328c70122`;
- run #57 / `36796184892` — success;
- gate explícito: 93 passed;
- suíte: **838 passed, 52 skipped, 19 warnings, 0 failed**;
- PostgreSQL 18 migrations: green;
- validador: green;
- invariantes admin + `plexo_service`: green;
- `prompts check`: green;
- `tools sync --check`: green.

## Próximo gate

FQ5.6 peers/setor só pode avançar depois de design `reuse-before-build` que confirme:
- uso de `market.sector_classification` existente;
- cobertura/ingestão real da classificação;
- semântica temporal: a tabela tem `reference_date`, mas não `availability_date`;
- deduplicação de emissores com múltiplas classes;
- reuso de FundamentalsLoader/valuation engine sem copiar matemática.
