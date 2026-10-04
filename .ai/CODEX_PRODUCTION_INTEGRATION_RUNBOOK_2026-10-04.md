# Plexo — Codex Production Integration Runbook

Data: 2026-10-04
Status: **EXECUTION RUNBOOK**
Objetivo: portar/integrar as capabilities validadas ao backend/LLM e banco reais com prova de correção.

## 0. Premissa

Pode existir um backend de produção distinto deste repositório de validação.

Não assumir que:
- paths são iguais;
- schemas são iguais;
- prompt system é igual;
- function calling é igual;
- banco de validação é o banco de produção.

Este repo define os contratos e comportamento de referência.
O backend real define o ambiente de integração.

---

## 1. Descobrir o workspace

Sem alterar nada:

- listar repos/worktrees acessíveis;
- identificar o repo que realmente é deployado;
- registrar `git remote -v`, branch e HEAD sem expor tokens;
- localizar entrypoint da API;
- localizar LLM client/orchestrator;
- localizar tool/function registry;
- localizar DB layer;
- localizar migrations;
- localizar deploy workflow.

Gravar resultado em:
`.ai/PRODUCTION_BACKEND_DISCOVERY_2026-10-04.md`.

Se o backend real estiver em outro repo, NÃO mover arquivos automaticamente.
Criar uma matriz de equivalência antes.

---

## 2. Auditar o banco real em read-only

Usar credencial read-only ou réplica/staging sempre que possível.

Proibido nesta fase:
- DDL;
- INSERT;
- UPDATE;
- DELETE;
- TRUNCATE;
- migration;
- backfill.

Auditar:
- schemas;
- tables;
- views;
- materialized views;
- row counts estimadas;
- constraints;
- keys;
- indexes;
- time coverage;
- sources/vendors;
- units;
- currencies;
- identities;
- vintages;
- publication/availability;
- ingestion metadata.

Gerar:
`.ai/EXTERNAL_DATA_BASE_AUDIT_2026-10-04.md`.

---

## 3. Corrigir baseline da referência

Antes de declarar qualquer paridade:
- corrigir os 2 testes strict-PIT dependentes do relógio;
- não alterar loader semantics;
- não remover `finished_at <= cutoff`;
- tornar fixture/batch availability histórica controlável.

Exigir:
- directed GREEN;
- full suite GREEN;
- prompts check GREEN;
- tools sync GREEN.

Registrar novo baseline.

---

## 4. Comparar orquestração LLM

Criar uma tabela reference -> production para:

| Referência | Responsabilidade |
|---|---|
| `app/api/routes/copilot.py` | entrada do turno |
| `app/agents/turn.py` | routing + tool loop + synthesis |
| `app/tools/registry.py` | contratos/schema |
| `app/tools/executor.py` | execução/audit/cache |
| `app/tools/sync.py` | DB registry/semver/fingerprint |
| `app/llm/prompts.py` | prompt aprovado |
| `app/agents/analysis.py` | findings/provenance |
| `app/agents/blocos.py` | UI blocks |
| `app/market/*` | loaders |
| `app/market/analytics/*` | deterministic math |

Para cada linha marcar:
- equivalente já existe;
- precisa adaptar;
- precisa portar;
- incompatível;
- gap.

---

## 5. Criar vertical slice mínimo

Primeiro vertical recomendado:

### Slice 1 — resolver
Pergunta:
"Analise PETR4"

Provar:
- modelo entende ticker;
- `dados.resolver_instrumento` disponível;
- DB devolve instrumento certo;
- execution registrada;
- output volta para LLM.

### Slice 2 — série
Pergunta:
"Mostre os preços de PETR4 no período X"

Provar:
- cutoff;
- prices;
- source;
- batch;
- payload.

### Slice 3 — cálculo
Pergunta:
"Qual foi o risco e retorno de PETR4 no período X?"

Provar:
- LLM chama `quant.risco_retorno`;
- params corretos;
- loader real;
- cálculo;
- oracle independente;
- output;
- LLM repete números sem alterá-los.

Se esses três slices não estiverem GREEN, não migrar as demais tools.

---

## 6. Integração técnica da tool

Para cada tool:

1. identificar code/semver de referência;
2. copiar/adaptar Params model;
3. copiar/adaptar Resolved model;
4. mapear `preparar()` para loaders do backend real;
5. manter `calcular()` puro;
6. declarar dependencies para fingerprint;
7. registrar no catálogo real;
8. sincronizar versão;
9. criar golden;
10. criar DB integration test;
11. criar oracle;
12. criar LLM routing eval;
13. criar E2E test;
14. shadow;
15. produção controlada.

Não pular do passo 4 para 15.

---

## 7. Quando adaptar vs portar

### Portar cálculo
Quando o backend real não tiver matemática equivalente.

### Adaptar loader
Quando os dados já existem em schema diferente.

### Reusar loader real
Quando já houver contrato igual ou superior:
- identity;
- unit;
- PIT;
- provenance;
- source.

### Criar schema novo
Somente se o conceito não puder ser representado honestamente.

Não criar schema só para ficar igual ao repo de referência.

---

## 8. Production execution record

O backend real precisa registrar, por execução material:

- tool code;
- semver;
- code/source fingerprint;
- user/scope;
- conversation/analysis id;
- requested params;
- resolved inputs;
- policies;
- sources;
- cutoff;
- input hash;
- output hash;
- status;
- duration;
- cache origin.

Se já houver tabela equivalente, reusar.
Se não houver, desenhar compatibilidade antes de migration.

---

## 9. Feature flag / shadow

Preferência:
- tool integrada mas não exposta à LLM;
- chamada shadow determinística para casos de teste;
- depois exposição em ambiente interno;
- depois pequeno allowlist;
- depois rollout.

Não ativar 18 tools simultaneamente em produção.

---

## 10. Rollback

Para cada promoção:
- versão anterior reproduzível;
- feature flag/off switch;
- migration reversibility quando aplicável;
- nenhuma perda de dados;
- tool version antiga ainda auditável.

Se uma tool mudar contrato:
- preservar replay/golden.

---

## 11. Validação independente

Usar:
`.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`.

Toda tool precisa:
- data correctness;
- numerical oracle;
- PIT;
- provenance;
- LLM routing;
- E2E;
- shadow.

Não usar o mesmo método de produção como "teste independente".

---

## 12. LLM fidelity test

Para cada tool criar pelo menos um caso com:

- user question;
- expected tool;
- expected critical params;
- canonical tool output;
- expected facts in response;
- forbidden facts/inferences.

Exemplo:

Pergunta:
"Qual foi a volatilidade da PETR4?"

Expected:
- tool = `quant.risco_retorno`;
- ticker = PETR4;
- sem fair value;
- sem recomendação;
- números iguais ao output;
- warnings relevantes aparecem;
- retorno passado não vira previsão.

---

## 13. Depois que as 18 estiverem integradas

Rodar um novo audit do DB e do produto.

Gerar:
`.ai/POST_INTEGRATION_CAPABILITY_AUDIT_2026-10-04.md`.

Perguntas:
- que dados reais agora estão disponíveis?
- quais perguntas relevantes ainda não podem ser respondidas?
- quais são novos cálculos?
- quais são apenas novas fontes?

Só então continuar roadmap.

---

## 14. Fair value

Não implementar só porque existe uma tabela chamada forecast/valuation.

Antes:
- identificar origem de cada forecast;
- verificar datas de publicação;
- unidades;
- consensus vs house estimate;
- risk-free;
- ERP;
- beta;
- WACC;
- terminal assumptions.

Criar primeiro um `FAIR_VALUE_INPUT_GOVERNANCE_AUDIT`.

Se premissas não forem governáveis, manter BLOCKED.

---

## 15. Definition of production integration complete

A integração global só termina quando:

- [ ] backend real descoberto/documentado;
- [ ] DB real auditado;
- [ ] CI referência GREEN;
- [ ] 18 tools mapeadas;
- [ ] tools prioritárias certificadas;
- [ ] LLM tool catalog real usando contratos corretos;
- [ ] outputs reais voltando à LLM;
- [ ] LLM fidelity tests GREEN;
- [ ] E2E GREEN;
- [ ] shadow GREEN;
- [ ] monitoring;
- [ ] rollback;
- [ ] `.ai/` sincronizada.

Até lá, usar a expressão:
**integração em andamento**, não "produção pronta".
