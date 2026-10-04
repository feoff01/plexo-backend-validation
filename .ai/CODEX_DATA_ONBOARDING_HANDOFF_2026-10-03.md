# Codex Handoff — onboarding de base grande no Plexo

Data: 2026-10-03 (America/Sao_Paulo)
Objetivo: dar ao Codex contexto suficiente para conectar/auditar uma base grande sem quebrar arquitetura, temporalidade, replay ou governança.

## 0. Repo autorizado e fonte de verdade

Repo: `feoff01/plexo-backend-validation`
Branch: `bootstrap/plexo-project`

A memória persistente do projeto é `.ai/`.
Antes de alterar qualquer código, leia nesta ordem:

1. `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
2. `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
3. `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`
4. `.ai/PROJECT_STATE.md`
5. `.ai/DECISIONS.md`
6. `.ai/TASKS.md`
7. `.ai/CHANGELOG.md`
8. `.ai/WORKING_PROTOCOL.md`
9. `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`
10. checkpoints citados pelos documentos acima.

Não trate blocos históricos antigos como estado atual quando houver override mais novo.

## 1. Estado funcional confiável

Último HEAD integralmente GREEN antes do audit documental de Brent:
- HEAD: `bf16dfd561f97e136060d77d80f50092cdc4538d`
- run #341 / `37162973757`: **success**
- PostgreSQL 18 + migrations/invariantes: GREEN
- directed gate: **186 passed**
- peers: **10/10/10 queries**
- full suite: **929 passed, 53 skipped, 19 warnings, 0 failed**
- prompts check: GREEN
- tools sync --check: GREEN
- catálogo: **37 tools / 34 públicas / 3 ocultas-replay**

Estado público relevante:
- `quant.risco_retorno` **1.2.0 pública/GREEN**
- `dados.curva_juros` 1.0.1 pública/GREEN
- `dados.composicao_indice` 1.0.1 pública/GREEN
- `quant.tendencias_fundamentais` 1.0.1 pública/GREEN
- `quant.comparaveis_setor` 1.0.1 pública/GREEN
- FQ0.5–FQ4 encerrados
- FQ5.1–FQ5.7 encerrados no escopo documentado
- `quant.event_study_v2` NÃO deve ser registrado
- legacy/replay deve continuar oculto.

## 2. HEAD atual e pendência de CI que NÃO pode ser ignorada

HEAD documental atual:
`2f962de8a2800480bf2800cf41b04d01298cfb05`

Run #347 / `37164219295`: **failure**.

A falha aconteceu depois da virada UTC para 2026-10-04 e atingiu somente dois testes strict-PIT:
- `tests/test_fq57_yield_curve_db.py::test_yield_curve_ingest_is_idempotent_and_loader_returns_exact_vertices`
- `tests/test_index_composition_db.py::test_index_composition_loader_reuses_official_snapshot_and_tool_is_compact`

Sintomas:
- yield curve esperava vértices `[(21, 14.0), (252, 13.5)]` e recebeu `[]`;
- index composition esperava reference_date `2026-10-02` e recebeu `None`;
- directed gate: **184 passed, 2 failed**.

Causa técnica observada:
- os testes ingerem snapshots históricos e depois consultam com cutoff `2026-10-03`;
- `app/market/ingest.py::fechar_lote()` grava `finished_at = clock_timestamp()`;
- quando o runner virou para 2026-10-04 UTC, o lote criado pelo teste passou a ter `finished_at::date = 2026-10-04`;
- os loaders strict-PIT corretamente escondem lote com `finished_at::date > cutoff`.

Portanto:
- NÃO afrouxe strict PIT;
- NÃO remova o gate de `finished_at`;
- primeiro torne os testes/fixtures temporais determinísticos, usando disponibilidade histórica explícita/injetável ou fixture de batch com `finished_at` controlado;
- preserve a semântica de produção.

Esse problema deve ser corrigido antes de usar o HEAD atual como nova baseline GREEN.

## 3. Arquitetura obrigatória

Fluxo:
`usuário -> LLM interpreta/roteia -> tool params -> preparar() -> loaders/resolvers -> calcular() -> output versionado -> LLM explica`.

Responsabilidades:
- LLM: interpretar, rotear, explicar;
- código determinístico: identidade, loading, cutoff, quality, provenance, matemática, versionamento;
- DB: persistência auditável;
- `.ai/`: memória de decisões/gates.

Preservar:
- semver;
- source fingerprint;
- replay/golden;
- content-addressed cache;
- cutoff/temporal semantics;
- provenance;
- warnings;
- payload compacto;
- PostgreSQL 18 gates;
- prompts/tools sync.

## 4. Reuse-before-build é gate obrigatório

Antes de criar qualquer coisa, responder:
1. a matemática já existe em `app/market/analytics/`?
2. o schema canônico já comporta o dado sem abuso semântico?
3. já existe loader/resolver reaproveitável?
4. é nova fonte ou nova intenção analítica?
5. uma tool existente pode ganhar o dado sem nova tool?
6. há temporalidade/vintage/source-priority que precisa ser governado antes?

Não criar tool por tabela, arquivo, vendor ou fonte.

## 5. Escopo

Frente atual: **Company & Market Analytics / Analista de Mercado**.

Fora do escopo:
- Portfolio Analytics;
- suitability;
- análise da carteira do cliente;
- planejamento financeiro pessoal;
- metas/aposentadoria/vida financeira.

Não misturar essas frentes sem decisão explícita.

## 6. Como tratar a base grande que o usuário vai conectar

A base grande NÃO deve ser conectada diretamente a cada tool.

Arquitetura alvo:
`base externa -> source onboarding -> canonical mapping -> ingestion batches -> loaders/resolvers -> tools existentes -> LLM`.

Primeira tranche obrigatória: **AUDITORIA READ-ONLY DA BASE**, sem migrations e sem alterar tools.

### 6.1 Inventário mínimo
Produzir:
- schemas/databases disponíveis;
- tabelas/views;
- volume aproximado por tabela;
- chaves primárias/uniques;
- índices relevantes;
- datas mínima/máxima;
- frequência/cadência;
- source/vendor original;
- timezone;
- currency;
- units;
- campos de revision/vintage/availability/publication/ingestion;
- identifiers: ticker, ISIN, CNPJ, company code, instrument id, index code etc.;
- histórico vs snapshot;
- dados raw vs derivados;
- direitos/licença/restrições de redistribuição se existirem.

Não ler segredos além do estritamente necessário para a conexão e nunca persistir credenciais no repo/logs.

### 6.2 Matriz de encaixe canônico
Para cada dataset/tabela, classificar em uma destas categorias:

**A — encaixa no schema/loaders atuais**
Ex.: preços B3 compatíveis, fundamentals CVM compatíveis, índices/taxas, FX, setores.

**B — precisa somente adapter/normalização**
Mesmo conceito canônico, formato físico diferente.

**C — precisa novo tipo canônico/schema**
Ex.: commodity USD/barril, se não houver representação honesta atual.

**D — exige nova governança temporal/source-priority**
Ex.: backfills, revisões, múltiplos vendors para o mesmo dado.

**E — habilita nova intenção analítica**
Só aqui considerar tool nova, e somente depois de provar que tools existentes não cobrem a pergunta.

### 6.3 Matriz source-priority
Se a base duplicar B3/CVM/ANBIMA/Bacen/EIA/Economatica:
- não escolher fonte silenciosamente;
- não sobrescrever first-party;
- mapear conflitos;
- medir divergência;
- propor policy explícita de prioridade por dataset/campo;
- Economatica/vendor auxiliar nunca deve masquerade como B3/CVM.

### 6.4 Temporalidade
Distinguir explicitamente:
- observation_date;
- reference_date;
- publication_date;
- availability_date;
- ingestion finished_at;
- revision/vintage.

Não retrodata:
- setor atual;
- membership atual;
- fundamentals revisados;
- corporate actions;
- FX/macro revisável;
- qualquer snapshot sem vintage provado.

### 6.5 Performance
Para base grande:
- evitar N+1;
- preferir batch loaders;
- medir query count;
- medir resolved payload;
- manter output client-facing compacto;
- adicionar regression gate quando query count/materialização for relevante.

O precedente de peers reduziu 38/98/218 queries para 10/10/10; preservar essa disciplina.

## 7. O que já pode reutilizar muitas linhas novas sem criar tools

Dependendo do mapping da base, dados novos podem alimentar:
- `quant.risco_retorno`;
- `quant.dependencia`;
- `quant.analise_condicional`;
- `quant.sensibilidade`;
- `quant.regimes`;
- `quant.event_study`;
- `quant.valor_mercado`;
- `quant.cenario_sensibilidade`;
- `quant.tendencias_fundamentais`;
- `quant.comparaveis_setor`;
- série/índice/curva/composição já existentes.

Não presumir que mais dados = mais tools.

## 8. Estado da frente Brent

Audit/design já congelado:
- `.ai/COMPANY_MARKET_DELTA_AUDIT_POST_RISK_1_2_2026-10-03.md`
- `.ai/BRENT_EIA_SOURCE_AUDIT_2026-10-03.md`
- `.ai/BRENT_FACTOR_FOUNDATION_DESIGN_2026-10-03.md`

Fonte candidata:
- EIA `RBRTE`;
- Europe Brent Spot Price FOB;
- USD/barril;
- daily.

Mas implementação está BLOQUEADA por:
- payload machine-readable físico ainda não congelado no repo;
- metadata específica de copyright/licença ainda não congelada.

Se a base grande do usuário já contém Brent:
- audite origem/licença/series identity;
- não assuma que é equivalente a EIA spot;
- distinguir spot, futures, front month, continuous contract e vendor-derived;
- talvez a base resolva o source gate, mas isso deve ser provado.

## 9. Fair value / reverse DCF

Continua bloqueado.

O core `app/market/analytics/valuation.py` produz market cap/EV/múltiplos e explicitamente NÃO produz intrinsic/fair value.

Não implementar reverse DCF/fair value até governar:
- forecasts;
- WACC;
- ERP;
- risk-free;
- beta ou alternativa;
- debt cost/tax;
- terminal growth ou terminal multiple;
- sensibilidade;
- provenance das premissas.

Não inventar defaults via LLM.

## 10. Primeira entrega esperada do Codex para a base

ANTES DE CÓDIGO, gerar em `.ai/` um documento de audit, por exemplo:
`.ai/EXTERNAL_DATA_BASE_AUDIT_<date>.md`

O documento deve conter:
1. inventário da base;
2. matriz tabela -> conceito canônico Plexo;
3. coverage temporal;
4. identity mapping;
5. units/currencies;
6. source provenance;
7. vintage/availability semantics;
8. duplicações com fontes atuais;
9. conflitos/source priority;
10. performance/volume;
11. gaps de schema;
12. quais tools existentes passam a ganhar cobertura;
13. quais adapters/loaders são necessários;
14. quais supostas "novas tools" NÃO são necessárias;
15. lista mínima de capabilities realmente novas, se houver;
16. riscos e gates;
17. proposta de tranches curtas.

## 11. Ordem de execução depois do audit

Somente depois do audit ser revisado:

1. corrigir primeiro o CI temporal atual (#367; mesma causa originalmente observada no #347) sem enfraquecer strict PIT;
2. escolher UMA tranche de onboarding;
3. design;
4. adapter/schema/loader shadow;
5. testes puros;
6. PostgreSQL 18;
7. quality/provenance/performance;
8. somente depois conectar tools existentes;
9. semver/replay/golden quando contrato público mudar;
10. planner/bloco/evals;
11. full suite + prompts/tools sync;
12. promotion checkpoint;
13. atualizar toda `.ai/`.

Não encadear várias capabilities no mesmo passo.

## 12. Regras de segurança/operacionais

- não ler/publicar `.env`;
- não commitar credenciais/tokens/DSNs;
- não editar migrations históricas;
- migration nova somente quando schema novo for realmente necessário;
- não executar operação destrutiva contra banco remoto;
- começar com SELECT/read-only;
- não tocar em outro repo;
- não substituir source first-party por vendor auxiliar sem policy;
- não enfraquecer PIT para fazer teste passar;
- registrar cada decisão/gate/fix em `.ai/`.

## 13. Pergunta que deve guiar o onboarding

Para cada parte da base, responder:

> "Isso adiciona DADOS para uma capability existente, exige uma nova FUNDAÇÃO canônica, ou representa de fato uma nova INTENÇÃO ANALÍTICA que justifica uma tool?"

A maior parte de uma base grande deve cair nas duas primeiras categorias.

## Override 2026-10-04 — a base é parte de uma integração maior

Este documento continua válido para auditoria da base, mas a missão atual é maior: integrar as tools/metodologias ao backend e LLM já existentes.

Antes de qualquer adapter, ler também:
- `.ai/LLM_BACKEND_PRODUCTION_INTEGRATION_MASTER_PLAN_2026-10-04.md`;
- `.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`;
- `.ai/PRODUCTION_TOOL_PARITY_MATRIX_2026-10-04.md`;
- `.ai/CODEX_PRODUCTION_INTEGRATION_RUNBOOK_2026-10-04.md`.

A base externa/real deve ser mapeada para as tools existentes dentro do runtime/orquestrador real. Não basta demonstrar queries corretas isoladas: é obrigatório provar LLM -> tool -> DB -> método -> output -> LLM ponta a ponta.

Nenhuma tabela deve ser considerada "integrada" até a capability consumidora passar pelo standard de certificação.

## Override de CI — 2026-10-04

O run mais recente do pacote documental/integration, #367 / `37227204860`, repetiu exatamente as mesmas duas falhas strict-PIT: 184 directed passed / 2 failed. Não surgiu regressão funcional nova.

Use #367 como estado atual; mantenha #347 apenas como registro de quando o problema foi inicialmente observado.
