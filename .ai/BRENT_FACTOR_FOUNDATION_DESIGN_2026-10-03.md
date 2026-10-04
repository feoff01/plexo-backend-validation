# Brent spot / EIA — design da fundação de commodity/fator

Data: 2026-10-03
Estado: **design congelado; implementação bloqueada pelo source physical/legal gate**
Escopo: Company & Market Analytics
Fonte candidata: EIA `RBRTE` — Europe Brent Spot Price FOB

## 1. Objetivo
Criar uma fundação determinística para uma série de commodity spot que possa, em tranche posterior, ser consumida pelo factor resolver e pelas tools quantitativas existentes.

Esta tranche **não cria nova tool pública** e não altera planner.

## 2. Reuse-before-build
Reutilizar:
- `market.ingestion_batches` para hash/status/reference/finished_at;
- `ResolvedMarketSeries`, `SeriesQuality`, `SeriesProvenance`;
- `quant_returns.calculate_returns()` para nível positivo;
- alinhamento e matemática já usados por dependência/sensibilidade/regimes;
- padrão de adapter físico -> ingestão semântica -> loader.

Não reutilizar indevidamente:
- `market.index_values`: domínio/unidade é índice/taxa; constraint atual não representa USD/barril;
- `market.fx_rates`: commodity não é par cambial;
- `market.prices`: exige identidade de instrumento/price basis e não representa unidade por barril.

## 3. Schema proposto após source gate
Nova migration somente depois do payload físico/licença GREEN.

### `market.commodity_definitions`
- `code core.slug PK`;
- `display_name text`;
- `unit text`;
- `currency core.currency`;
- `source_code core.slug FK market.data_sources`;
- `source_series_id text`;
- `frequency text`;
- `is_active boolean`.

Primeiro registro:
- code: `brent_spot`;
- display: `Brent spot Europe FOB`;
- unit: `usd_per_barrel`;
- currency: `USD`;
- source: `eia`;
- source_series_id: `RBRTE`;
- frequency: `daily`.

### `market.commodity_values`
- `commodity_code FK`;
- `value_date date`;
- `value numeric(20,8) CHECK value > 0`;
- `ingestion_batch_id uuid NOT NULL FK`;
- chave única por `commodity_code + value_date + ingestion_batch_id`.

A tabela é versionada por batch; não sobrescrever histórico de ingestão.

## 4. Fonte e dataset
Adicionar source `eia` com atribuição explícita.
Dataset canônico proposto:
`eia.petroleum.pri.spt.rbrte@1`.

Cada ingestão deve:
- congelar hash dos bytes/records físicos;
- criar batch;
- rejeitar unidade/frequência/series id divergente;
- persistir somente valores positivos/finitos;
- encerrar batch succeeded/failed;
- ser idempotente por hash/dataset.

## 5. Loader
Criar `CommoditySeriesLoader`/função equivalente read-only.

Contrato:
- code canônico `brent_spot`;
- seleção por batch `succeeded`;
- strict PIT por `finished_at <= cutoff`;
- `value_date <= cutoff`;
- sem nearest/interpolação/fill;
- sem B3 calendar: datas da commodity são preservadas como publicadas;
- quality factual sobre observações disponíveis;
- provenance com dataset, source=eia, batch ids e cutoff;
- `price_basis=None`;
- `temporal_semantics=observation_date_cutoff` + nota de strict ingestion-batch PIT.

Se não existir batch elegível no cutoff, retornar série vazia/fail-closed conforme contrato do loader; nunca usar batch futuro para preencher passado.

## 6. Factor foundation posterior
Somente após loader GREEN:
- evoluir `FactorKind` para incluir `commodity`;
- `FactorRef(tipo="commodity", codigo="brent_spot")`;
- commodity é nível positivo e usa `calculate_returns()`, não `calculate_index_returns()`;
- `ResolvedFactor` preserva `unit=usd_per_barrel`;
- sem `price_basis`;
- sem calendário B3;
- alinhar por interseção de datas nas análises.

Não registrar `dados.brent`, `quant.brent` ou `quant.commodity` apenas por existir uma nova fonte.

## 7. Cutover futuro das capabilities
Não faz parte desta tranche.

Depois da fundação GREEN, reauditar consumidores.
Candidatos naturais:
- `quant.dependencia`;
- `quant.sensibilidade`;
- `quant.analise_condicional`;
- `quant.regimes`;
- `quant.cenario_sensibilidade` somente se a semântica de choque de commodity for explicitamente compatível.

Cada tool que tiver schema público alterado precisa de semver/replay/golden próprio.

## 8. Planner futuro
Quando houver cutover:
- "PETR4 e Brent andam juntos?" -> fator commodity `brent_spot`;
- "sensibilidade da PETR4 ao Brent" -> mesma série;
- rotular sempre **Brent spot Europe FOB (EIA), USD/barril**;
- perguntas sobre futures/front-month/curva/contango/backwardation ficam unsupported;
- não transformar associação histórica em causalidade, forecast ou recomendação.

## 9. Gates
### Antes de código
- payload machine-readable EIA real congelado;
- SHA-256;
- metadata de copyright/licença específico da série;
- series id/frequency/unit confirmados.

### Shadow foundation
- migration nova sem editar migrations antigas;
- source `eia`;
- parser fail-closed;
- ingestão idempotente;
- strict PIT por batch;
- loader + provenance/quality;
- PostgreSQL 18;
- nenhuma mudança no catálogo de tools.

### Depois
- só então desenhar factor cutover público;
- full suite/prompts/tools sync a cada promoção.

## 10. Próximo passo permitido
**Materializar o payload físico oficial EIA + metadata de copyright da RBRTE.**

Não implementar schema/loader antes desse gate.
