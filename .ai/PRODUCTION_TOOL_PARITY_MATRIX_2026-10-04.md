# Plexo — Production Tool Parity Matrix

Data: 2026-10-04
Status: **A PREENCHER PELO CODEX CONTRA O BACKEND REAL**

## Legenda

### Port status
- NOT_MAPPED
- ALREADY_EQUIVALENT
- ADAPT
- PORT
- GAP
- PORTED

### Certification
- UNMAPPED
- DATA_MAPPED
- DATA_VALIDATED
- NUMERICALLY_CERTIFIED
- E2E_CERTIFIED
- SHADOW_PROD
- PROD_GREEN
- BLOCKED

---

## Matriz inicial

| Tool | Ref semver | Ref implementation | Production implementation | Real DB mapping | Port status | Certification |
|---|---:|---|---|---|---|---|
| `dados.resolver_instrumento` | 1.0.0 | `app/tools/analista/resolver_instrumento.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `dados.serie_precos` | 1.0.2 | `app/tools/analista/serie_precos.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `dados.serie_indice` | 1.1.1 | `app/tools/analista/serie_indice.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `dados.historico_comparado` | 1.1.1 | `app/tools/analista/historico_comparado.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `dados.expectativas_mercado` | 1.0.0 | `app/tools/analista/expectativas.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `dados.fundamentos_empresa` | 1.0.0 | `app/tools/analista/fundamentos_empresa.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `dados.curva_juros` | 1.0.1 | `app/tools/analista/curva_juros.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `dados.composicao_indice` | 1.0.1 | `app/tools/analista/composicao_indice.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.risco_retorno` | 1.2.0 | `app/tools/analista/risco_retorno.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.dependencia` | 2.0.0 | `app/tools/analista/dependencia.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.sensibilidade` | 1.0.1 | `app/tools/analista/sensibilidade.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.analise_condicional` | 1.0.1 | `app/tools/analista/analise_condicional.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.regimes` | 1.0.1 | `app/tools/analista/regimes.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.event_study` | 2.0.0 | `app/tools/analista/event_study_v2.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.valor_mercado` | 1.0.0 | `app/tools/analista/valor_mercado.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.cenario_sensibilidade` | 1.0.0 | `app/tools/analista/cenario_sensibilidade.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.tendencias_fundamentais` | 1.0.1 | `app/tools/analista/tendencias_fundamentais.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |
| `quant.comparaveis_setor` | 1.0.1 | `app/tools/analista/comparaveis_setor.py` | TBD | TBD | NOT_MAPPED | UNMAPPED |

---

## Orchestration parity

| Reference component | Reference path | Production equivalent | Status | Notes |
|---|---|---|---|---|
| HTTP turn endpoint | `app/api/routes/copilot.py` | TBD | NOT_MAPPED | |
| Agent turn loop | `app/agents/turn.py` | TBD | NOT_MAPPED | |
| Tool registry | `app/tools/registry.py` | TBD | NOT_MAPPED | |
| Tool executor | `app/tools/executor.py` | TBD | NOT_MAPPED | |
| Tool DB sync | `app/tools/sync.py` | TBD | NOT_MAPPED | |
| LLM client abstraction | `app/llm/client.py` | TBD | NOT_MAPPED | |
| Prompt loader | `app/llm/prompts.py` | TBD | NOT_MAPPED | |
| Router | `app/agents/router.py` | TBD | NOT_MAPPED | |
| Analysis/evidence | `app/agents/analysis.py` | TBD | NOT_MAPPED | |
| Blocks | `app/agents/blocos.py` | TBD | NOT_MAPPED | |
| Identity/market loaders | `app/market/*` | TBD | NOT_MAPPED | |
| Analytics core | `app/market/analytics/*` | TBD | NOT_MAPPED | |

---

## DB parity

Preencher para o backend real:

| Domain | Reference concept | Production tables/views | Source/vendor | Temporal semantics | Status |
|---|---|---|---|---|---|
| Instrument identity | instruments/aliases/issuer | TBD | TBD | current identity | UNMAPPED |
| Raw prices | price observations | TBD | TBD | observation cutoff | UNMAPPED |
| Adjusted prices | retrospective adjusted series | TBD | TBD | retrospective_as_known_now or vintage | UNMAPPED |
| Trading calendar | official sessions | TBD | TBD | date | UNMAPPED |
| Indices/rates | definitions/values | TBD | TBD | dataset-specific | UNMAPPED |
| FX | currency pair series | TBD | TBD | dataset-specific | UNMAPPED |
| Fundamentals | annual PIT facts | TBD | TBD | availability PIT | UNMAPPED |
| Shares | shares outstanding | TBD | TBD | availability PIT | UNMAPPED |
| Debt/cash | valuation inputs | TBD | TBD | availability PIT | UNMAPPED |
| Sector taxonomy | sector/subsector | TBD | TBD | current/historical? | UNMAPPED |
| Expectations | Focus/consensus | TBD | TBD | collection date | UNMAPPED |
| Yield curve | exact vertices | TBD | TBD | ingestion PIT | UNMAPPED |
| Index membership | official snapshots | TBD | TBD | ingestion PIT | UNMAPPED |
| Commodities | possible Brent/etc | TBD | TBD | TBD | UNMAPPED |
| Forecasts | possible future valuation inputs | TBD | TBD | publication vintage | UNMAPPED |

---

## Per-tool detailed record

Para cada tool, o Codex deve acrescentar uma subseção:

### TOOL_CODE

- Reference semver:
- Reference source SHA:
- Production code path:
- Production registry entry:
- Exposed to LLM:
- Params schema parity:
- Output schema parity:
- DB tables/views:
- Source/vendor:
- Identity mapping:
- Units/currency:
- Cutoff semantics:
- Availability/vintage:
- Policies:
- Oracle:
- Golden:
- Replay:
- Targeted tests:
- DB integration tests:
- LLM routing eval:
- E2E test:
- Shadow:
- Latency:
- Query count:
- Payload bytes:
- Monitoring:
- Rollback:
- Open deviations:
- Certification:
