# Plexo — Codex repository instructions

## Start here

This repository uses `.ai/` as its canonical persistent project memory.

For any substantial task, first read:
1. `.ai/CODEX_START_HERE_2026-10-03.md`
2. the task-specific documents that file points to.

For onboarding or connecting an external/large database, also read:
- `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`

Do not assume older sections of historical documents are current when a newer override/checkpoint exists.

## Architecture

Preserve this boundary:
`user -> LLM interprets/routes/explains -> versioned tool params -> preparar/loaders/resolvers -> deterministic calculation -> versioned output/provenance -> LLM explains`.

The LLM must not invent financial calculations, identities, source precedence, cutoffs, vintages, or assumptions that belong in deterministic code/policy.

Apply **reuse-before-build** before creating any new:
- tool;
- schema/table/migration;
- loader/resolver;
- source adapter;
- financial math;
- policy/default.

Do not create a tool just because a new table, file, source, or vendor exists.

## Canonical project memory

Record every material decision, implementation, test, gate, fix, pending item, and next approved step in `.ai/`.

Core state files:
- `.ai/PROJECT_STATE.md`
- `.ai/DECISIONS.md`
- `.ai/TASKS.md`
- `.ai/CHANGELOG.md`
- `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
- `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
- `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`

Use `.ai/CODEX_START_HERE_2026-10-03.md` to determine which design/checkpoint documents are currently authoritative.

## Current baseline warning

The last fully GREEN functional baseline is:
- commit `bf16dfd561f97e136060d77d80f50092cdc4538d`
- run #341 / `37162973757`
- PostgreSQL 18 + migrations/invariants GREEN
- directed: 186 passed
- peers: 10/10/10 queries
- full suite: 929 passed, 53 skipped, 19 warnings, 0 failed
- prompts check GREEN
- tools sync --check GREEN
- catalog: 37 registered / 34 public / 3 hidden-replay

The newer documentation HEAD has a known CI failure caused by nondeterministic test fixture availability after UTC rollover:
- run #349 / `37166181087`
- 184 directed passed / 2 failed
- failing tests:
  - `tests/test_fq57_yield_curve_db.py::test_yield_curve_ingest_is_idempotent_and_loader_returns_exact_vertices`
  - `tests/test_index_composition_db.py::test_index_composition_loader_reuses_official_snapshot_and_tool_is_compact`

Root cause: test ingestions close batches with `finished_at=clock_timestamp()` while the test queries a fixed historical cutoff. After UTC rolled to 2026-10-04, strict PIT correctly hid those batches.

**Do not weaken strict PIT, remove the finished_at gate, or make production semantics less strict to fix this.**
Make test/fixture availability deterministic instead.

## Scope

Current strategic scope: **Company & Market Analytics / Analista de Mercado**.

Do not open or mix into this work unless explicitly requested:
- Portfolio Analytics;
- suitability;
- client portfolio advice;
- personal financial planning.

Other tool families exist in the repository and should remain functional, but they are not the current expansion scope.

## Tool/version invariants

Preserve:
- semver;
- source fingerprints;
- replay/golden compatibility;
- hidden legacy/replay modules;
- cutoff semantics;
- provenance;
- warnings;
- compact payloads;
- content-addressed cache behavior;
- PostgreSQL gates;
- prompt/tool sync.

Do not register `quant.event_study_v2`; the public code is `quant.event_study`.

Current public risk capability is `quant.risco_retorno` 1.2.0.
Its 1.1.0 replay is frozen in:
- `app/tools/analista/risco_retorno_legacy_1_1_0.py`
- `tests/golden/quant_risco_retorno_1_1_0.json`

## External/large database onboarding

Never wire external tables directly into every tool.

Target architecture:
`external database -> source onboarding/adapters -> canonical Plexo models/storage -> loaders/resolvers -> existing tools -> LLM`.

First step is always **read-only audit**, not implementation.

Before writing code:
- inventory schemas/tables/views/volumes/keys/indexes;
- map identities;
- map units/currencies;
- map observation/reference/publication/availability/ingestion dates;
- detect revisions/vintages;
- identify original source/vendor and licensing;
- compare against B3/CVM/ANBIMA/Bacen/EIA/Economatica;
- identify duplicate/conflicting fields and propose source-priority;
- classify each dataset as:
  A. fits current canonical model;
  B. adapter/normalization only;
  C. new canonical type/schema needed;
  D. temporal/source-priority governance needed;
  E. genuinely new analytical intent.

Only category E can justify a new tool, and only after proving an existing tool cannot cover the intent.

Do not read or commit secrets. Do not log DSNs/tokens/passwords. Start with read-only credentials and preferably staging/replica.

## Brent status

Brent is selected as the next Company & Market data-foundation candidate, not as a new public tool.

Read:
- `.ai/COMPANY_MARKET_DELTA_AUDIT_POST_RISK_1_2_2026-10-03.md`
- `.ai/BRENT_EIA_SOURCE_AUDIT_2026-10-03.md`
- `.ai/BRENT_FACTOR_FOUNDATION_DESIGN_2026-10-03.md`

Candidate series:
- EIA `RBRTE`;
- Europe Brent Spot Price FOB;
- USD/barrel;
- daily.

Implementation is blocked until a real machine-readable payload and series-specific copyright/licensing metadata are frozen.

If the external database already contains Brent, audit whether it is spot, futures, front-month, continuous contract, or vendor-derived. Never silently treat one as another.

## Fair value / reverse DCF

Still blocked.

Do not implement intrinsic/fair value until assumptions are governed and auditable:
- forecasts;
- WACC;
- ERP;
- risk-free;
- beta or approved alternative;
- debt cost/tax;
- terminal growth/multiple;
- sensitivity;
- provenance of assumptions.

Do not invent these defaults in the LLM or code.

## Testing and promotion

For substantial code changes:
1. design/audit;
2. shadow/internal implementation where appropriate;
3. targeted tests;
4. PostgreSQL 18;
5. temporal semantics/provenance/quality;
6. payload/performance;
7. replay/golden if public contract changes;
8. planner/block/evals when exposure changes;
9. full suite;
10. prompts check;
11. tools sync --check;
12. checkpoint/update `.ai/`.

Do not declare a capability GREEN from partial evidence.

## Git discipline

Work only in the authorized repository/branch unless the user explicitly changes it.

Do not:
- rewrite historical migrations;
- silently loosen constraints;
- weaken compliance/PIT semantics to make tests pass;
- commit credentials or environment files;
- make destructive changes to a production database.

When the task is complex, make a small plan, work in short tranches, and keep the canonical `.ai/` state synchronized with the actual code/test result.
