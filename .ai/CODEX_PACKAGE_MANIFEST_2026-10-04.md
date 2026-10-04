# Plexo — Codex Integration Package Manifest

Data: 2026-10-04
Status: **PACOTE CANÔNICO PARA VS CODE / CODEX**
Instalar preservando caminhos relativos na raiz do backend/repositório alvo.

## 1. Arquivos obrigatórios — núcleo

### Raiz
- `CODEX_BOOTSTRAP.md`
  - entrypoint manual de uma única linha;
  - evita colar prompts longos no Codex;
  - encaminha para todo o contexto canônico.

- `AGENTS.md`
  - instruções automáticas do Codex;
  - arquitetura;
  - invariantes;
  - baseline;
  - regras de integração/certificação.

- `CODEX_PACKAGE_README.md`
  - instruções humanas de instalação/uso do pacote.

### `.ai/` — entrada atual
- `.ai/CODEX_START_HERE_2026-10-04.md`
- `.ai/CODEX_PACKAGE_MANIFEST_2026-10-04.md`
- `.ai/CODEX_PRODUCTION_INTEGRATION_FIRST_MESSAGE_2026-10-04.md`

## 2. Plano de integração produção

- `.ai/LLM_BACKEND_PRODUCTION_INTEGRATION_MASTER_PLAN_2026-10-04.md`
- `.ai/CODEX_PRODUCTION_INTEGRATION_RUNBOOK_2026-10-04.md`
- `.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`
- `.ai/TOOL_INTEGRATION_CERTIFICATION_MATRIX_2026-10-04.md`
- `.ai/PRODUCTION_TOOL_PARITY_MATRIX_2026-10-04.md`

Esses cinco documentos definem:
- como descobrir o backend/LLM real;
- como portar/adaptar;
- como certificar dado/método/PIT/LLM;
- as 18 tools de Company & Market;
- os estados UNMAPPED -> PROD_GREEN.

## 3. Templates que o Codex deve preencher

- `.ai/PRODUCTION_BACKEND_DISCOVERY_TEMPLATE_2026-10-04.md`
- `.ai/EXTERNAL_DATA_BASE_AUDIT_TEMPLATE_2026-10-04.md`

O Codex deve gerar, no backend real:
- `.ai/PRODUCTION_BACKEND_DISCOVERY_2026-10-04.md`
- `.ai/EXTERNAL_DATA_BASE_AUDIT_2026-10-04.md`

antes de port em massa.

## 4. Memória canônica do projeto

Obrigatórios:
- `.ai/PROJECT_STATE.md`
- `.ai/DECISIONS.md`
- `.ai/TASKS.md`
- `.ai/CHANGELOG.md`
- `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
- `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
- `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`
- `.ai/WORKING_PROTOCOL.md`

Regra:
- documentos históricos podem conter estados antigos;
- overrides/checkpoints mais novos vencem;
- `CODEX_START_HERE_2026-10-04.md` é o índice atual.

## 5. Onboarding do banco

- `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`

Esse documento é complementar ao master plan de integração.
Não interpretar como um projeto isolado de banco.

## 6. Designs/checkpoints ativos relevantes

### Risco
- `.ai/RISK_ROLLING_VOLATILITY_DESIGN_2026-10-03.md`
- `.ai/RISK_ROLLING_POLICY_DECISION_2026-10-03.md`
- `.ai/checkpoints/2026-10-03_RISK_ROLLING_1_2_GREEN.md`

Estado:
`quant.risco_retorno` 1.2.0 pública/GREEN na referência.

### Capability audit / Brent
- `.ai/COMPANY_MARKET_DELTA_AUDIT_POST_RISK_1_2_2026-10-03.md`
- `.ai/BRENT_EIA_SOURCE_AUDIT_2026-10-03.md`
- `.ai/BRENT_FACTOR_FOUNDATION_DESIGN_2026-10-03.md`
- `.ai/checkpoints/2026-10-03_POST_RISK_1_2_BRENT_DESIGN_FROZEN.md`

Estado:
Brent é candidate data foundation, não tool pública decidida.

### Integração produção
- `.ai/checkpoints/2026-10-04_CODEX_PRODUCTION_INTEGRATION_PACKAGE_READY.md`

## 7. Contexto valuation útil

Incluir:
- `.ai/FQ5_FUNDAMENTALS_VALUATION_DESIGN.md`

Esse arquivo registra o desenho histórico de fundamentos/valuation atual e ajuda a evitar confundir:
- market value/multiples;
- intrinsic/fair value.

A regra atual de fair value continua no master plan/standard de 2026-10-04.

## 8. Baseline e CI atual

### Último baseline funcional integralmente GREEN
- commit `bf16dfd561f97e136060d77d80f50092cdc4538d`;
- run #341 / `37162973757`;
- directed 186 passed;
- full 929 passed / 53 skipped / 19 warnings / 0 failed;
- PostgreSQL 18 GREEN;
- prompts/tools sync GREEN;
- catálogo 37/34/3.

### Estado documental/integration package mais recente observado
Run #367 / `37227204860`:
- 184 directed passed;
- 2 failed;
- mesmas duas fixtures strict-PIT dependentes do relógio;
- nenhuma regressão funcional nova identificada.

Falhas:
- yield curve DB fixture;
- index composition DB fixture.

Não enfraquecer strict PIT.

## 9. Arquivos que NÃO precisam ser copiados separadamente

Se o Codex está trabalhando dentro do repo de referência, todo o código:
- `app/`;
- `tests/`;
- `prompts/`;
- `alembic/`;
- `seeds/`;
já está no próprio repositório.

Este pacote de handoff NÃO é substituto do código-fonte.
Ele é a camada de contexto/instrução para integrar esse código/contratos ao backend real.

Se o backend real estiver em outro repo, o Codex deve ter acesso aos DOIS:
1. repo de referência;
2. repo deployado.

Não copiar `app/` inteiro sem discovery/parity.

## 10. Primeira ordem de execução

Depois de instalar os arquivos:

1. abrir a raiz onde está `AGENTS.md`;
2. iniciar Codex;
3. colar o conteúdo de `.ai/CODEX_PRODUCTION_INTEGRATION_FIRST_MESSAGE_2026-10-04.md`;
4. deixar o Codex fazer discovery read-only;
5. deixar o Codex fazer DB audit read-only;
6. preencher parity matrix;
7. corrigir CI temporal;
8. propor vertical slice resolver -> preços -> risco;
9. parar para review.

## 11. Resultado esperado da primeira sessão

O Codex deve entregar:
- `PRODUCTION_BACKEND_DISCOVERY_2026-10-04.md`;
- `EXTERNAL_DATA_BASE_AUDIT_2026-10-04.md`;
- parity matrix parcialmente preenchida;
- correção/diagnóstico do CI temporal;
- plano de vertical slice;
- blockers.

Não deve:
- migrar as 18 tools de uma vez;
- alterar produção sem staging/shadow;
- inventar fair value;
- criar tool por tabela/fonte.

## 12. Regra de integridade do pacote

Ao distribuir esse pacote, preservar:
- nomes;
- paths;
- conteúdo;
- line endings preferencialmente LF.

Se houver SHA manifest externo, comparar antes de uso.
