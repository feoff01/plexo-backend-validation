# Plexo — Codex Start Here

Data de referência: 2026-10-03 / 2026-10-04 UTC rollover
Status: **manifesto canônico para Codex / VS Code**
Repo: `feoff01/plexo-backend-validation`
Branch: `bootstrap/plexo-project`

Este arquivo é o índice principal do contexto do projeto. Leia-o primeiro junto com o `AGENTS.md` da raiz.

---

## 1. Baseline funcional confiável

Último commit integralmente GREEN:

- commit: `bf16dfd561f97e136060d77d80f50092cdc4538d`
- run #341 / `37162973757`
- PostgreSQL 18 + migrations/invariantes: GREEN
- directed gate: **186 passed**
- peers benchmark: **10/10/10 queries**
- full suite: **929 passed, 53 skipped, 19 warnings, 0 failed**
- prompts check: GREEN
- tools sync --check: GREEN
- catálogo: **37 registradas / 34 públicas / 3 ocultas-replay**

Depois desse baseline foram adicionados apenas documentos de audit/handoff de Brent/Codex, sem nova capability funcional.

### CI atual não-GREEN

HEAD documental antes do `AGENTS.md`:
`6eb7cc3b216a4c4272b15e7782694be034b61c44`

Run #349 / `37166181087`:
- **184 passed / 2 failed** no directed gate;
- falhas:
  - `tests/test_fq57_yield_curve_db.py::test_yield_curve_ingest_is_idempotent_and_loader_returns_exact_vertices`
  - `tests/test_index_composition_db.py::test_index_composition_loader_reuses_official_snapshot_and_tool_is_compact`

Causa observada:
- fixtures ingerem snapshot histórico;
- `app/market/ingest.py::fechar_lote()` usa `finished_at=clock_timestamp()`;
- testes consultam cutoff fixo `2026-10-03`;
- depois da virada UTC para `2026-10-04`, strict PIT corretamente esconde os lotes.

**A correção deve tornar o tempo da fixture determinístico. Não enfraquecer strict PIT.**

---

## 2. Ordem de leitura do contexto

### Sempre
1. `AGENTS.md`
2. `.ai/CODEX_START_HERE_2026-10-03.md`
3. `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
4. `.ai/PROJECT_STATE.md`
5. `.ai/DECISIONS.md`
6. `.ai/TASKS.md`
7. `.ai/CHANGELOG.md`
8. `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`
9. `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
10. `.ai/WORKING_PROTOCOL.md`

### Para onboarding da base grande
11. `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`

### Para risco/rolling 1.2.0
12. `.ai/RISK_ROLLING_VOLATILITY_DESIGN_2026-10-03.md`
13. `.ai/RISK_ROLLING_POLICY_DECISION_2026-10-03.md`
14. `.ai/checkpoints/2026-10-03_RISK_ROLLING_1_2_GREEN.md`

### Para Brent/commodities
15. `.ai/COMPANY_MARKET_DELTA_AUDIT_POST_RISK_1_2_2026-10-03.md`
16. `.ai/BRENT_EIA_SOURCE_AUDIT_2026-10-03.md`
17. `.ai/BRENT_FACTOR_FOUNDATION_DESIGN_2026-10-03.md`
18. `.ai/checkpoints/2026-10-03_POST_RISK_1_2_BRENT_DESIGN_FROZEN.md`

### Documentos históricos úteis
Eles registram decisões anteriores, mas podem conter estados superseded:
- `.ai/COMPANY_MARKET_CAPABILITY_REAUDIT_2026-10-03.md`
- `.ai/COMPANY_MARKET_DELTA_AUDIT_POST_RUN283_2026-10-03.md`
- `.ai/RISK_HISTORY_EVOLUTION_DESIGN_2026-10-03.md`
- checkpoints anteriores de shadow/CI de risco.

Quando houver conflito, o checkpoint/override mais novo vence.

---

## 3. Arquitetura do produto

Regra central:

`usuário -> LLM interpreta/roteia -> params versionados -> preparar/loaders/resolvers -> cálculo determinístico -> output/provenance -> LLM explica`

O LLM:
- entende intenção;
- escolhe tool;
- explica resultado.

Código determinístico:
- resolve identidades;
- lê fontes;
- aplica cutoff;
- calcula;
- valida;
- produz quality/provenance;
- versiona;
- preserva replay.

Nunca mover cálculo financeiro ou decisão de source-priority para o LLM.

---

## 4. Catálogo completo — 37 tools

### 4.1 Company & Market Analytics — 18 públicas

#### 1. `dados.resolver_instrumento` — 1.0.0
Resolve ticker, código antigo ou nome para instrumento canônico; informa cobertura e disponibilidade de preço.

#### 2. `dados.serie_precos` — 1.0.2
Retorna fechamentos oficiais B3 no período, com cutoff, lacunas, fonte e último preço.

#### 3. `dados.serie_indice` — 1.1.1
Retorna séries oficiais de índice/taxa como CDI, Selic e IPCA, com acumulado e provenance.

#### 4. `dados.historico_comparado` — 1.1.1
Compara trajetória de um ativo versus BOVA11/outro ticker, alinhado por pregão e normalizado em base 100.

#### 5. `dados.expectativas_mercado` — 1.0.0
Lê expectativas Focus do Bacen: mediana, dispersão e respondentes para Selic, IPCA, câmbio, PIB etc.

#### 6. `dados.fundamentos_empresa` — 1.0.0
Snapshot point-in-time de fundamentos anuais DFP com availability date, unidade e provenance.

#### 7. `dados.curva_juros` — 1.0.1
Lê vértices oficiais da ETTJ ANBIMA prefixada/IPCA/inflação implícita; não interpola/extrapola.

#### 8. `dados.composicao_indice` — 1.0.1
Lê membros/pesos de snapshot oficial de composição de índice já ingerido.

#### 9. `quant.risco_retorno` — 1.2.0
Retorno acumulado/anualizado, volatilidade, downside deviation, max drawdown, duração/recuperação e evolução histórica rolling opcional.

#### 10. `quant.dependencia` — 2.0.0
Associação Pearson/Spearman entre ativo e ativo/índice/taxa/FX, com lag assinado.

#### 11. `quant.sensibilidade` — 1.0.1
Sensibilidade histórica linear OLS com incerteza HAC/Newey-West entre ativo e fator/série.

#### 12. `quant.analise_condicional` — 1.0.1
Compara comportamento do ativo nos intervalos em que outro ativo/índice/taxa subiu ou caiu.

#### 13. `quant.regimes` — 1.0.1
Compara retorno histórico em regimes explícitos de nível ou direção de outro fator.

#### 14. `quant.event_study` — 2.0.0
Event study canônico: retorno anormal e CAR versus benchmark; CI clássico opcional sob hipóteses explícitas.

#### 15. `quant.valor_mercado` — 1.0.0
Calcula preço observado, market cap, dívida líquida, EV e múltiplos. **Não produz fair value/intrinsic value.**

#### 16. `quant.cenario_sensibilidade` — 1.0.0
Aplica choque explícito à sensibilidade histórica e calcula impacto/preço mecânico de cenário; não é forecast/fair value.

#### 17. `quant.tendencias_fundamentais` — 1.0.1
Analisa evolução anual PIT de fundamentos, YoY e margens EBITDA/líquida.

#### 18. `quant.comparaveis_setor` — 1.0.1
Compara empresa com peers B3 do mesmo subsetor/setor em valuation, crescimento e margens, sem ranking/recomendação.

### 4.2 Planning / portfolio / product — 10 públicas

Essas tools existem e devem permanecer funcionando, mas NÃO fazem parte da expansão atual de Company & Market Analytics.

#### 19. `planejamento.pontos_de_atencao` — 1.1.0
Expõe achados determinísticos do Raio-X: concentração, FGC, classe, caixa, liquidez, custo etc., sem indicar compra/venda.

#### 20. `orcamento.reserva_emergencia` — 1.0.1
Calcula meses cobertos, alvo, gap e tempo para fechar a reserva.

#### 21. `orcamento.capacidade_aporte` — 2.0.0
Calcula sobra mensal para aporte, teto com corte de gastos e decomposição de renda/despesas/dívidas.

#### 22. `planejamento.composicao_patrimonio` — 1.2.0
Agrega patrimônio por classe/grupo, incluindo não financeiro, passivos e patrimônio líquido.

#### 23. `planejamento.projecao_objetivo` — 1.1.1
Projeta objetivo hipotético em cenários determinísticos e calcula aporte necessário.

#### 24. `planejamento.aposentadoria_antecipada` — 1.1.1
Diagnóstico determinístico de independência financeira/aposentadoria antecipada.

#### 25. `planejamento.posicoes_carteira` — 1.0.1
Abre posições uma a uma: quantidade, preço médio, último fechamento, valor, peso, emissor, FGC, liquidez etc.

#### 26. `produto.custo_fundo` — 1.0.0
Decompõe custo estimado de fundo/produto e compara com referência de classe.

#### 27. `produto.comparar_alternativas` — 1.0.0
Compara produtos lado a lado em custo, liquidez, tributação e compatibilidade, sem ranking.

#### 28. `planejamento.simulacao_objetivo` — 1.2.0
Simulação probabilística de objetivo cadastrado, incluindo probabilidade e distribuição de resultados.

### 4.3 Contexto — 3 públicas

#### 29. `contexto.verificar_mudanca` — 1.0.0
Compara um valor novo informado pelo cliente com o contexto registrado e sinaliza mudança material.

#### 30. `contexto.documento_oficial` — 1.0.1
Retorna trecho literal de documento oficial aprovado por compliance, com data, fonte e link.

#### 31. `contexto.perfil_financeiro` — 1.0.0
Diagnóstico estrutural do momento financeiro do cliente e dos dados faltantes.

### 4.4 Educação — 3 públicas

#### 32. `educacao.exemplo_didatico` — 1.0.0
Monta exemplo numérico educacional de conceito aprovado.

#### 33. `educacao.glossario` — 1.0.1
Busca conteúdo educativo aprovado por compliance.

#### 34. `educacao.simulador_juros_compostos` — 1.0.0
Simulador didático de juros compostos.

### 4.5 Ocultas/replay — 3 registradas, não expostas ao LLM

#### 35. `quant.correlacao` — 1.0.3 — hidden
Implementação legacy de correlação; capability canônica atual é `quant.dependencia`.

#### 36. `quant.dependencia_macro` — 1.0.1 — hidden
Compatibilidade executável para chamadas antigas; novos planos usam `quant.dependencia`.

#### 37. `quant.retorno_volatilidade` — 1.0.4 — hidden
Implementação legacy de retorno/vol/drawdown; capability canônica atual é `quant.risco_retorno`.

Além dessas, existem módulos legacy/replay que NÃO registram novas tools, como:
- `dependencia_legacy_1_0_1.py`
- `dependencia_macro_legacy_1_0_0.py`
- `event_study_legacy_1_0_1.py`
- `risco_retorno_legacy_1_1_0.py`.

Não aumentar o catálogo por acidente ao mexer nesses módulos.

---

## 5. Estado das capabilities de Company & Market

### Encerrado
- FQ0.5–FQ4;
- factor/dependence unificado para ativo/índice/FX;
- fundamentos;
- valor de mercado/múltiplos;
- cenários mecânicos;
- tendências fundamentais;
- comparáveis/setor;
- curva ANBIMA;
- composição oficial de índice;
- risco/downside/drawdown;
- rolling volatility em `quant.risco_retorno` 1.2.0.

### Ainda não encerrado / decidido para futuro

#### A. Onboarding da base grande — PRIORIDADE AGORA
Primeiro audit read-only; depois adapters/loaders.

#### B. Brent / commodity foundation
Selecionado como próxima fundação de Company & Market, mas sem nova tool pública decidida.
Bloqueado por source physical/licensing gate ou pela auditoria da base externa, caso ela já possua Brent confiável.

#### C. Fair value / reverse DCF
Candidato futuro, ainda bloqueado por matemática contratual e premissas governadas.

#### D. Histórico retroativo de setor/membership
Só se houver fonte/vintage confiável.

#### E. Source priority / conflicts / vintages
Infraestrutura transversal que passa a ser especialmente importante ao conectar a base externa.

---

## 6. Estratégia para a base grande

Não conectar cada tool diretamente à base externa.

Arquitetura:
`base externa -> audit/source mapping -> adapters/ingestion -> canonical Plexo -> loaders/resolvers -> tools existentes`.

### Primeiro passo obrigatório: read-only audit
Gerar `.ai/EXTERNAL_DATA_BASE_AUDIT_<date>.md` com:

1. schemas/tabelas/views;
2. volumes;
3. PKs/uniques/FKs;
4. índices;
5. coverage temporal;
6. source/vendor original;
7. units/currencies;
8. identifiers;
9. observation/reference/publication/availability/ingestion dates;
10. revisions/vintages;
11. raw vs derivado;
12. histórico vs snapshot;
13. licensing;
14. duplicações com fontes atuais;
15. divergências;
16. source priority proposta;
17. riscos de look-ahead/retrodatação;
18. performance/query patterns;
19. mapping tabela -> conceito canônico;
20. tools existentes que ganham cobertura.

Classificar cada dataset:
- A = encaixa no modelo atual;
- B = só adapter/normalização;
- C = novo tipo canônico/schema;
- D = governança temporal/source-priority;
- E = nova intenção analítica.

Somente E pode justificar tool nova.

---

## 7. Regras temporais essenciais

Distinguir:
- observation_date;
- reference_date;
- publication_date;
- availability_date;
- ingestion finished_at;
- revision/vintage.

Nunca retrodata:
- setor atual;
- membership atual;
- fundamento revisado;
- corporate actions;
- série revisável;
- snapshot sem vintage provado.

Strict PIT é uma propriedade do produto e não pode ser enfraquecida para facilitar testes.

---

## 8. Brent — estado atual

Fonte candidata identificada:
- EIA `RBRTE`;
- Europe Brent Spot Price FOB;
- daily;
- USD/barrel.

Mas implementação está bloqueada até:
- payload machine-readable real;
- SHA-256;
- metadata específica de copyright/licensing;
- confirmação de identidade/frequency/unit.

Se a base externa já possuir Brent, auditar primeiro:
- spot vs futures;
- front month vs continuous;
- exchange/vendor;
- unit;
- timezone/date;
- revisions;
- licensing.

Não usar um tipo como substituto silencioso de outro.

---

## 9. Fair value — estado atual

`app/market/analytics/valuation.py` atualmente calcula market value/EV/múltiplos e explicitamente não produz intrinsic value.

Antes de reverse DCF/fair value:
- forecast governado;
- WACC;
- ERP;
- risk-free;
- beta ou alternativa;
- debt cost/tax;
- terminal growth/multiple;
- sensibilidade;
- provenance das premissas.

Nada disso deve ser inventado pelo LLM.

---

## 10. Próxima ordem recomendada

1. corrigir determinismo temporal dos 2 testes strict-PIT atuais;
2. obter novo HEAD GREEN;
3. conectar base externa em read-only;
4. produzir audit/mapping;
5. escolher UMA tranche de integração;
6. adapter/schema/loader shadow;
7. PostgreSQL 18;
8. quality/provenance/PIT/performance;
9. conectar tools existentes;
10. semver/replay/golden se contrato público mudar;
11. planner/bloco/evals se exposição mudar;
12. full suite + prompts/tools sync;
13. promoção e checkpoint;
14. repetir por tranche.

Não abrir várias capabilities ao mesmo tempo.

---

## 11. O que NÃO fazer

- não criar uma tool para cada tabela;
- não criar uma tool para cada vendor;
- não consultar diretamente a base externa de dentro de todas as tools;
- não commitar DSN/token/password;
- não editar migrations antigas;
- não sobrescrever first-party silenciosamente;
- não usar dado revisado como se fosse PIT;
- não declarar GREEN com CI parcial;
- não registrar `quant.event_study_v2`;
- não abrir Portfolio Analytics nesta frente;
- não implementar fair value com premissas arbitrárias.

---

## 12. Pergunta de decisão para toda nova tabela/dataset

> Isso adiciona **dados** para uma capability já existente, exige uma nova **fundação canônica**, ou representa uma nova **intenção analítica**?

Preferência arquitetural:
1. dados para tool existente;
2. adapter/fundação;
3. somente por último nova tool.
