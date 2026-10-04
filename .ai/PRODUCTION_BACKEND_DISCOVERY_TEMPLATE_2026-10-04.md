# Production Backend Discovery — TEMPLATE

Data:
Autor:
Repo de referência: `feoff01/plexo-backend-validation`
Repo/backend alvo:
Branch/HEAD alvo:

## 1. Deployment topology
- API service:
- Worker service:
- Scheduler:
- Cache:
- DB:
- Queue:
- Frontend consumer:
- Observability:
- Deployment platform:

## 2. LLM orchestration
- HTTP entrypoint:
- Turn/orchestrator:
- Provider abstraction:
- Model configuration:
- Function/tool calling mechanism:
- Tool schema source:
- Tool result return path:
- Prompt source/versioning:
- Approval/compliance:
- Streaming:
- Retry:
- Budget:
- Guardrails:
- Model call audit:

## 3. Tool architecture
- Registry:
- Executor:
- Param validation:
- Resolved input concept:
- Pure calculation boundary:
- Cache:
- Execution audit:
- Versioning:
- Source fingerprint:
- Replay:
- Feature flags/exposure:

## 4. DB architecture
- Engine/version:
- tenant/scope model:
- RLS:
- service role:
- app role:
- policy storage:
- tool catalog storage:
- analysis/evidence storage:
- ingestion metadata:
- staging/replica availability:

## 5. Market data domains
| Domain | Tables/views | Source | Coverage | Availability/vintage | Notes |
|---|---|---|---|---|---|
| Instruments | | | | | |
| Prices | | | | | |
| Adjusted prices | | | | | |
| Corporate actions | | | | | |
| Calendar | | | | | |
| Indices/rates | | | | | |
| FX | | | | | |
| Fundamentals | | | | | |
| Shares | | | | | |
| Debt/cash | | | | | |
| Sector | | | | | |
| Expectations | | | | | |
| Yield curve | | | | | |
| Index membership | | | | | |
| Commodities | | | | | |
| Forecasts | | | | | |

## 6. Reference-to-production architecture mapping
| Reference | Production | Decision | Notes |
|---|---|---|---|
| `app/api/routes/copilot.py` | | | |
| `app/agents/turn.py` | | | |
| `app/tools/registry.py` | | | |
| `app/tools/executor.py` | | | |
| `app/tools/sync.py` | | | |
| `app/llm/client.py` | | | |
| `app/llm/prompts.py` | | | |
| `app/agents/analysis.py` | | | |
| `app/agents/blocos.py` | | | |
| `app/market/*` | | | |
| `app/market/analytics/*` | | | |

Decision enum:
- REUSE_AS_IS
- ALREADY_EQUIVALENT
- ADAPT
- PORT
- GAP
- NOT_NEEDED

## 7. Integration blockers
- 
- 
- 

## 8. Security / secrets
- Credential mode:
- Read-only available:
- Staging available:
- Any secret observed in repo/logs?:
- Required remediation:

Do not paste secret values.

## 9. Recommended vertical slice
- Resolver:
- Prices:
- Risk:
- Reason:

## 10. Decision
- Safe to begin port?:
- Required prerequisites:
- First code tranche:
