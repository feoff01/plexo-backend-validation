# Plexo — Codex Start Here — 2026-10-04

Status: **ENTRADA CANÔNICA ATUAL**
Objetivo atual: integrar as capabilities validadas neste repo ao backend/LLM e banco reais, com certificação de correção.

## 1. Leia nesta ordem

1. `AGENTS.md`
2. este arquivo
3. `.ai/LLM_BACKEND_PRODUCTION_INTEGRATION_MASTER_PLAN_2026-10-04.md`
4. `.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`
5. `.ai/TOOL_INTEGRATION_CERTIFICATION_MATRIX_2026-10-04.md`
6. `.ai/PRODUCTION_TOOL_PARITY_MATRIX_2026-10-04.md`
7. `.ai/CODEX_PRODUCTION_INTEGRATION_RUNBOOK_2026-10-04.md`
8. `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`
9. `.ai/PROJECT_STATE.md`
10. `.ai/DECISIONS.md`
11. `.ai/TASKS.md`
12. `.ai/CHANGELOG.md`
13. `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
14. `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`
15. `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
16. `.ai/WORKING_PROTOCOL.md`

Templates:
- `.ai/PRODUCTION_BACKEND_DISCOVERY_TEMPLATE_2026-10-04.md`
- `.ai/EXTERNAL_DATA_BASE_AUDIT_TEMPLATE_2026-10-04.md`

Primeira mensagem pronta:
- `.ai/CODEX_PRODUCTION_INTEGRATION_FIRST_MESSAGE_2026-10-04.md`

## 2. O que este repo representa

Este repo contém uma implementação/validação de referência de tools, métodos, loaders, contracts, replay e gates.

Não presumir que ele é idêntico ao backend deployado.

A tarefa atual é:
**descobrir o backend real e portar/adaptar os contratos corretamente**.

## 3. O que já existe na referência

Catálogo:
- 37 tools registradas;
- 34 públicas;
- 3 hidden/compatibilidade;
- 18 públicas de Company & Market Analytics.

A arquitetura já validada inclui:
- LLM tool calling via schemas do registry;
- `preparar()` com DB/policy/PIT;
- `calcular()` puro;
- tool execution audit;
- content-addressed cache;
- semver/source fingerprint;
- replay/golden;
- evidence/provenance;
- blocks;
- prompt approval;
- PostgreSQL gates.

Não reinventar essa separação.

## 4. Baseline funcional confiável

Último baseline totalmente GREEN:
- `bf16dfd561f97e136060d77d80f50092cdc4538d`
- run #341 / `37162973757`
- directed 186 passed
- peers 10/10/10
- full 929 passed / 53 skipped / 19 warnings / 0 failed
- prompts GREEN
- tools sync GREEN
- catálogo 37/34/3.

## 5. CI atual conhecido

HEAD documental/integration package anterior a esta atualização:
`93e2de958b918ea1689e6844971e23dd347c5a72`

Run #367 / `37227204860`:
- **184 passed / 2 failed** no directed gate;
- falhas:
  - `tests/test_fq57_yield_curve_db.py::test_yield_curve_ingest_is_idempotent_and_loader_returns_exact_vertices`;
  - `tests/test_index_composition_db.py::test_index_composition_loader_reuses_official_snapshot_and_tool_is_compact`.

São as mesmas duas falhas temporais observadas desde o rollover UTC.

Causa:
batch de fixture fechado por `clock_timestamp()` + cutoff histórico fixo `2026-10-03`.

Não enfraquecer strict PIT.
Corrigir disponibilidade temporal da fixture/batch.

Esse é o primeiro gate técnico antes de declarar novo baseline GREEN.

## 6. Objetivo de integração

Resultado desejado:

```
LLM real
→ escolhe a tool correta
→ backend valida params
→ loader lê dado correto do banco real
→ cutoff/vintage correto
→ resolved input auditável
→ cálculo determinístico certificado
→ output tipado
→ execution/provenance
→ JSON volta ao modelo
→ LLM explica sem recalcular
```

## 7. Regra de correção

Uma resposta pode estar errada mesmo se o software não der erro.

Por isso validar separadamente:
1. dado;
2. método;
3. temporalidade;
4. output;
5. LLM orchestration.

Use o standard:
`.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`.

## 8. Primeira missão do Codex

ANTES DE PORT:

### A. Production backend discovery
Criar:
`.ai/PRODUCTION_BACKEND_DISCOVERY_2026-10-04.md`

Usar o template.

### B. Database audit
Criar:
`.ai/EXTERNAL_DATA_BASE_AUDIT_2026-10-04.md`

Usar o template.

### C. Parity matrix
Atualizar:
`.ai/PRODUCTION_TOOL_PARITY_MATRIX_2026-10-04.md`

### D. Fix temporal CI
Corrigir as 2 fixtures sem mudar semantics.

### E. Propor vertical slice
Começar:
1. resolver instrumento;
2. série de preços;
3. risco/retorno.

Parar para review antes de migrar as 18 tools.

## 9. 18 tools de mercado

A lista completa e os gates estão em:
`.ai/TOOL_INTEGRATION_CERTIFICATION_MATRIX_2026-10-04.md`.

Nenhuma delas deve ser marcada production-ready apenas porque está GREEN neste repo.

Estado de produção inicial:
`UNMAPPED`.

## 10. Novas capabilities

### Brent
Primeiro verificar o banco real.
Talvez já exista série que resolva o source gate.

Docs:
- `.ai/BRENT_EIA_SOURCE_AUDIT_2026-10-03.md`
- `.ai/BRENT_FACTOR_FOUNDATION_DESIGN_2026-10-03.md`

### Fair value/reverse DCF
Ainda BLOCKED até governança de inputs.

O banco real deve ser auditado para:
- forecasts;
- WACC components;
- ERP;
- risk-free;
- beta;
- debt cost;
- tax;
- terminal assumptions.

Mesmo presentes, precisam de source/vintage/provenance antes de uso.

## 11. Pós-integração

Depois de integrar/certificar o catálogo atual, criar:
`.ai/POST_INTEGRATION_CAPABILITY_AUDIT_2026-10-04.md`

Só esse audit escolhe as próximas tools.

## 12. Regra final

Não otimizar para "ter muitas tools".

O produto certo é:
- poucas capabilities canônicas;
- dados confiáveis;
- cálculo correto;
- PIT correto;
- provenance;
- LLM usando a capability certa;
- resultado reproduzível.

Se houver dúvida entre velocidade e correção financeira, bloquear e investigar.
