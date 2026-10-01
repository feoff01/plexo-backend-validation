# Checkpoint — FQ5.5 Promotion Candidate

Data: 2026-09-30
Estado: shadow verde; promoção preparada; aguardando CI pós-promoção.

## Shadow gate
Commit: `e863e674d2a5b873d9502faa2915c25a65ddefd6`
Run #56: `36795497161` — success.
- E2E/gate: 93 passed;
- full suite: 837 passed, 52 skipped, 19 warnings, 0 failed;
- prompts/tools sync, validador, migrations e invariantes: verdes.

## Promoção candidata
- `quant.tendencias_fundamentais` 1.0.1 pública;
- 1.0.0 permanece identificável como shadow no histórico Git;
- planner snapshot vs tendência atualizado;
- blocos determinísticos: tabela-resumo + série de margens;
- catálogo F5 atualizado;
- registry: 34 tools, 33 anteriores sem drift.

## Bloqueio
FQ5.5 só encerra após CI PostgreSQL 18 pós-promoção verde. FQ5.6 ainda não deve iniciar.
