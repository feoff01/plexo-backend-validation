# External / Existing Database Audit — TEMPLATE

Data:
Database environment:
Access mode: READ ONLY
Scope: Company & Market Analytics

## 1. Inventory
| Schema | Table/View | Approx rows | PK/unique | Important indexes | Owner/source |
|---|---|---:|---|---|---|

## 2. Identity
Document:
- instrument id;
- ticker;
- ISIN;
- CNPJ;
- issuer id;
- aliases;
- exchange;
- security type;
- delisted/renamed handling.

## 3. Coverage by domain
| Domain | First date | Last date | Entities | Frequency | Missingness |
|---|---|---|---:|---|---|
| Prices | | | | | |
| Fundamentals | | | | | |
| FX | | | | | |
| Rates | | | | | |
| Expectations | | | | | |
| Yield curve | | | | | |
| Index membership | | | | | |
| Commodities | | | | | |
| Forecasts | | | | | |

## 4. Source lineage
For every domain:
- original publisher;
- vendor/intermediary;
- dataset id;
- license/restriction;
- raw or transformed;
- refresh cadence.

## 5. Units and currencies
Record all non-obvious units.
Explicitly flag:
- thousands/millions;
- percent vs decimal;
- annual vs daily rate;
- BRL vs USD;
- per share vs total;
- barrels/tons/etc.

## 6. Temporal semantics
For every domain identify:
- observation_date;
- reference_date;
- publication_date;
- availability_date;
- ingested_at;
- revised_at;
- vintage id.

If a field does not exist, mark MISSING — do not infer.

## 7. Revision/vintage behavior
- append-only?:
- overwrite?:
- backfill?:
- restatement?:
- history of revisions?:
- recover what was known at a historical date?:

## 8. Duplicates/conflicts
Compare with existing Plexo first-party sources.

| Concept | Existing source | DB source | Same? | Divergence | Proposed priority |
|---|---|---|---|---|---|

No source priority decision without evidence.

## 9. Canonical mapping
Classify every relevant dataset:

A = fits current canonical model
B = adapter/normalization
C = new canonical schema/type
D = temporal/source-priority governance
E = new analytical intent

| DB dataset | Economic concept | Plexo target | Class | Notes |
|---|---|---|---|---|

## 10. Tool coverage impact
| Tool | Data available? | Missing inputs | Adapter needed | Expected coverage |
|---|---|---|---|---|

Include all 18 Company & Market tools.

## 11. Performance
- largest tables;
- query plans sampled;
- important indexes;
- expected N+1 risks;
- batch loader opportunities;
- materialized views;
- payload risks.

## 12. Data quality
For sampled domains report:
- duplicates;
- nulls;
- impossible values;
- stale data;
- unit inconsistencies;
- identifier collisions.

## 13. Brent
If present:
- exact series name/id;
- spot/future/continuous;
- source;
- unit;
- frequency;
- time zone/date;
- license;
- revisions.

## 14. Valuation/fair value inputs
If present:
- forecasts;
- consensus;
- risk-free;
- ERP;
- beta;
- debt cost;
- tax;
- WACC;
- terminal growth;
- terminal multiple.

For each: source + publication/vintage + unit.
Do not treat presence as approval.

## 15. Findings
### Reuse immediately
-

### Adapter needed
-

### New canonical foundation
-

### Governance needed
-

### Genuinely new analytical capabilities
-

## 16. Recommended tranches
1.
2.
3.

Do not implement before this audit is reviewed.
