# Checkpoint — pacote de integração backend/LLM real preparado

Data: 2026-10-04
Estado: **GREEN documental / pronto para Codex discovery + DB audit**
Nenhuma mudança funcional de tool nesta tranche.

## Objetivo
Preparar o Codex para integrar a implementação validada das tools de Company & Market Analytics ao backend/LLM já existente e ao banco real, com certificação de correção financeira ponta a ponta.

## Arquivos canônicos novos
- `.ai/CODEX_START_HERE_2026-10-04.md`
- `.ai/LLM_BACKEND_PRODUCTION_INTEGRATION_MASTER_PLAN_2026-10-04.md`
- `.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`
- `.ai/TOOL_INTEGRATION_CERTIFICATION_MATRIX_2026-10-04.md`
- `.ai/PRODUCTION_TOOL_PARITY_MATRIX_2026-10-04.md`
- `.ai/CODEX_PRODUCTION_INTEGRATION_RUNBOOK_2026-10-04.md`
- `.ai/CODEX_PRODUCTION_INTEGRATION_FIRST_MESSAGE_2026-10-04.md`
- `.ai/PRODUCTION_BACKEND_DISCOVERY_TEMPLATE_2026-10-04.md`
- `.ai/EXTERNAL_DATA_BASE_AUDIT_TEMPLATE_2026-10-04.md`

`AGENTS.md` atualizado para apontar para o pacote atual.

## Arquitetura confirmada na referência
A implementação atual já possui:
- endpoint de turno;
- router/agentes;
- catálogo de tools tipado;
- schemas Pydantic enviados ao LLM;
- executor com params/resolved params;
- policies versionadas;
- input/output hashes;
- content-addressed cache;
- `tools.tool_executions`;
- `preparar()` DB-aware;
- `calcular()` puro;
- evidence/provenance;
- blocos;
- prompt approval;
- semver/source fingerprints.

Portanto o próximo trabalho é integração/paridade, não inventar novo function-calling.

## Regra nova explicitada
Nenhuma tool será considerada pronta no backend real apenas porque retorna JSON/número.

Certificação obrigatória:
1. data correctness;
2. identity/unit correctness;
3. PIT/vintage correctness;
4. independent numerical oracle;
5. contract/replay;
6. provenance;
7. LLM routing;
8. LLM output fidelity;
9. E2E real backend;
10. shadow;
11. monitoring/rollback.

## Primeira tranche Codex
Antes de qualquer port:
1. descobrir backend real;
2. auditar DB real read-only;
3. preencher parity matrix;
4. corrigir fixture temporal strict-PIT;
5. propor vertical slice resolver -> preços -> risco;
6. parar para review.

## Baseline
Último baseline funcional integralmente GREEN continua:
- commit `bf16dfd561f97e136060d77d80f50092cdc4538d`;
- run #341 / `37162973757`;
- 186 directed;
- 929 passed / 53 skipped / 19 warnings / 0 failed;
- 37/34/3.

Commits documentais recentes ainda herdam a falha conhecida dos 2 testes strict-PIT dependentes do relógio. Não enfraquecer os loaders.

## Próximas capabilities
Brent e fair value não devem ser abertos antes do DB audit e da integração do catálogo atual.

Depois da integração, gerar `POST_INTEGRATION_CAPABILITY_AUDIT_2026-10-04.md`.
