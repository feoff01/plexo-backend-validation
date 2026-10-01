# Plexo — Tasks

Atualizado em: 2026-09-21

## Estado da trilha Quant

### FQ0.5 — Fundação de versionamento ✅

- [x] fingerprint composto com `source_dependencies`;
- [x] compatibilidade de hash para tools de arquivo único;
- [x] `exposed_to_llm`;
- [x] filtros de turno/planner/compiler;
- [x] testes de hash/exposição.

### FQ1 — Quant Data Foundation ✅ código / ⏳ integração DB

- [x] `MarketSeriesLoader` + `SeriesReader`;
- [x] preço e índice/taxa no mesmo contrato;
- [x] `raw_close` vs `adjusted_close`;
- [x] `observation_date_cutoff` vs `retrospective_as_known_now`;
- [x] quality/provenance;
- [x] calendário oficial + fallback explícito;
- [x] regressão PostgreSQL escrita para corporate action;
- [ ] executar `.github/workflows/verify.yml` com PostgreSQL 18;
- [ ] definir policy de prioridade de fontes antes de múltiplos `source_code` concorrentes.

### FQ2 — Quant Core ✅

- [x] `returns`;
- [x] `statistics`;
- [x] `risk`;
- [x] `dependence`;
- [x] migração das tools legacy sem mudar goldens;
- [x] property/compatibility tests.

### FQ3 — Tools canônicas ✅ código / ⏳ ativação produção

- [x] `quant.risco_retorno` 1.0.1 exposta;
- [x] `quant.dependencia` 1.0.1 exposta;
- [x] `quant.retorno_volatilidade` 1.0.4 oculta, replay preservado;
- [x] `quant.correlacao` 1.0.3 oculta, replay preservado;
- [x] planner/evals/Research/blocos migrados para canônicas;
- [x] regra `price_basis -> temporal_semantics` centralizada em Data Foundation;
- [ ] PostgreSQL CI;
- [ ] `tools sync --check` e publicação das versões;
- [ ] sync/aprovação do `analista.planner`;
- [ ] só então chamar o cutover de ativo em produção.

### FQ4.1 — `quant.analise_condicional` ✅ shadow

- [x] design documentado antes do código;
- [x] `analytics/conditional.py` puro;
- [x] condição por retorno para ativo/índice em pontos;
- [x] condição por mudança de nível para taxa/percentual;
- [x] retorno do ativo no mesmo intervalo da condicionante, sem look-ahead;
- [x] baseline vs amostra condicional;
- [x] alta/queda/neutro;
- [x] amostra curta mantém métricas + warning;
- [x] `sem_eventos_condicao`;
- [x] output compacto + bloco determinístico;
- [x] tool `1.0.0` shadow, fora do catálogo/planner;
- [x] 19 testes específicos + 400 cenários sintéticos;
- [x] regressão sem DB: 343 passed / 16 skipped / 355 DB-deselected / 0 failed;
- [ ] executar no PostgreSQL CI;
- [ ] promover para `exposed_to_llm=True` somente após gate verde, com patch semver e planner/eval.

### FQ4.2 — `quant.sensibilidade` ✅ shadow

- [x] definir variável resposta/driver e transformação por unidade;
- [x] OLS univariada com intercepto para point estimate;
- [x] HAC/Newey-West Bartlett + correção `n/(n-k)` para SE/CI;
- [x] bandwidth automático auditável em observações;
- [x] CI 95% por aproximação normal, sem p-value/significant;
- [x] manter stdlib, sem adicionar NumPy/SciPy/statsmodels nesta fase;
- [x] `MetricEstimate` + `ConfidenceInterval` + `EvidenciaEstatistica`;
- [x] frequência: driver define intervalos; output expõe min/mediana/max de dias;
- [x] missing sem imputação; outliers sem winsorização/trimming;
- [x] estabilidade numérica com influência centrada;
- [x] `quant.sensibilidade` 1.0.0 shadow + bloco determinístico;
- [x] 27 testes novos + regressão sem DB 383/16/355/0;
- [ ] executar PostgreSQL CI/sync antes de promoção;
- [ ] promover somente depois de gate verde + planner/evals.

### FQ4.3 — `quant.regimes`

- [x] design congelado antes do código;
- [x] critérios explícitos `nivel`/`direcao`, sem clustering/threshold oculto;
- [x] Regimes Engine puro + alinhamento sem look-ahead;
- [x] `quant.regimes` 1.0.0 em shadow mode;
- [x] bloco determinístico + warnings cliente;
- [x] 21 testes específicos/property + regressão ampla 404/16/355/0;
- [x] auditoria confirmou 0 mudanças nas 28 tools anteriores;
- [ ] executar PostgreSQL CI/sync antes de promoção.

### FQ4.4 — `quant.event_study` v2 ✅ shadow / ⏳ cutover

- [x] Event Study Engine sobre Quant Core;
- [x] alinhar níveis por datas comuns antes de calcular retornos;
- [x] `quant.event_study_v2` 1.0.0 shadow;
- [x] default `adjusted_close`, raw opt-in;
- [x] linguagem `point-in-time` removida do contrato legacy visível, com bump 1.0.2;
- [x] replay autocontido da 1.0.1 + golden histórico;
- [x] inferência `classic_iid_normal` opcional, sem p-value/significant;
- [x] bloco/warnings e output compacto;
- [x] 22 testes específicos + 500 cenários property + regressão ampla 426/16/355/0;
- [ ] PostgreSQL CI/sync;
- [ ] cutover canônico v2 após gates e revisão planner/evals.

### Gate de integração FQ4 — ✅ preparado / ⏳ execução PostgreSQL

- [x] E2E DB das quatro shadows via `executar_tool()`;
- [x] assert de `tool_executions` e cache;
- [x] gate FQ4 ligado ao `verify.yml` PostgreSQL 18;
- [x] planner preparado condicionalmente ao catálogo;
- [x] promotion readiness tests;
- [x] plano de promoção/cutover documentado;
- [ ] executar o workflow PostgreSQL 18 real;
- [ ] `tools sync --check`/`prompts check` no runner;
- [ ] promover shadows apenas se todo o gate ficar verde.

## Gates transversais pendentes

- [ ] primeiro run verde de `.github/workflows/verify.yml` (agora inclui `test_fq4_integration_db.py`);
- [ ] `tools sync`/prompt sync do FQ3;
- [ ] decisão de storage histórico Parquet/PostgreSQL/híbrido;
- [ ] prioridade explícita de múltiplas fontes de preço;
- [ ] availability/vintage real para corporate actions e macro revisável;
- [ ] mecanismo de payload compacto/artifact antes de outputs longos/econométricos;
- [x] fundação estruturada de evidência inferencial (`EvidenciaEstatistica`) antes de regressões com erro-padrão/CI.
- [x] validar o primeiro uso real dessa evidência em `quant.sensibilidade`.

## Fora da trilha Quant atual

Planejamento financeiro pessoal, orçamento, aposentadoria, suitability individual e vida financeira do cliente possuem estrutura própria e não entram nesta roadmap.



## 2026-09-30 — após CI PostgreSQL verde

- [x] Executar FQ4 E2E em PostgreSQL 18 real.
- [x] Executar suíte Python completa em PostgreSQL real.
- [x] Executar `prompts check`.
- [x] Executar `tools sync --check`.
- [x] Corrigir incompatibilidades de fixtures/expectativas reveladas pelo CI.
- [ ] Limpar workflow temporário de bootstrap e confirmar PR-only CI verde.
- [ ] Abrir branch/PR separado para promoção controlada de FQ4.
- [ ] Promover `quant.analise_condicional`, `quant.sensibilidade`, `quant.regimes` com patch semver.
- [ ] Fazer cutover versionado de Event Study v2 para `quant.event_study`, preservando replay histórico.

## FQ4 — pós-promoção

- [x] Executar PostgreSQL 18 real em CI.
- [x] Validar migrations + FQ1/F5/F22/FQ4 E2E.
- [x] Validar suíte completa + prompts check + tools sync --check.
- [x] Promover analise_condicional/sensibilidade/regimes com patch bump.
- [x] Fazer cutover de event study para código canônico 2.0.0.
- [x] Retirar alias `quant.event_study_v2` do registry.
- [x] Exigir CI pós-promoção totalmente verde — run 36760273363 (#39), PostgreSQL 18.
- [x] Encerrar FQ4 após CI pós-promoção verde; próxima camada pode iniciar sem reabrir matemática base.

## Fechamento FQ4 — 2026-09-30

- [x] Run pós-promoção #39 (`36760273363`) totalmente verde.
- [x] Suíte completa: **806 passed, 52 skipped, 19 warnings**.
- [x] `prompts check` verde.
- [x] `tools sync --check` verde.
- [x] Golden visual de Event Study atualizado de forma explícita para o mapper canônico v2; números históricos preservados.
- [x] FQ4 encerrado no branch de validação.


## Fechamento FQ5.1–FQ5.4 — 2026-09-30
- [x] 0062: unidade/currency e coordenada multi-classe sem editar migration histórica;
- [x] Fundamentals Data Foundation PIT;
- [x] `dados.fundamentos_empresa` 1.0.0 pública;
- [x] `quant.valor_mercado` 1.0.0 pública;
- [x] `quant.cenario_sensibilidade` 1.0.0 pública, reutilizando FQ4.2;
- [x] `quant.dependencia_macro` 1.0.0 pública, incluindo USD/BRL;
- [x] blocos compactos e planner governado;
- [x] shadow run #47 verde;
- [x] pós-promoção run #49 verde;
- [x] E2E 74 passed;
- [x] full suite 816 passed / 52 skipped / 19 warnings / 0 failed;
- [x] prompts/tools sync verdes;
- [x] FQ5.1–FQ5.4 encerrado.

Próximas tranches, ainda **sem Portfolio Analytics**:
- [ ] FQ5.5 tendências fundamentais PIT: crescimento, margens, ROE/ROIC e leverage;
- [ ] FQ5.6 peers/setor cross-sectional;
- [ ] ampliar fatores canônicos (ex.: petróleo/Brent);
- [ ] FQ5.7 fair value/reverse DCF só com forecasts e premissas explícitas/auditáveis;
- [ ] resolver prioridade de fontes e availability/vintage de FX/macro.


## Gate antes da próxima feature — Architecture / Capability Audit — 2026-09-30

- [x] inventariar todas as tools do Analista e separar públicas vs legacy;
- [x] inventariar Quant Core e capacidades já implementadas;
- [x] mapear loaders/adapters e fontes de dados existentes;
- [x] mapear schemas latentes (`sector_classification`, `index_weights`, `yield_curve`);
- [x] classificar duplicação real vs legacy intencional vs composição legítima;
- [x] registrar regra `reuse-before-build`;
- [ ] desenhar consolidação `ResolvedFactor`/factor loader para asset/index/FX e extensões futuras;
- [ ] desenhar cutover versionado para remover a duplicação pública `quant.dependencia_macro` × `quant.dependencia` sem quebrar replay/fingerprint;
- [ ] só depois liberar FQ5.5 tendências fundamentais / FQ5.6 peers-setor.

**Bloqueio:** nenhuma nova matemática/tool de análise deve ser iniciada antes do design de consolidação de fatores/dependência.


## Próxima sequência proposta após a auditoria — aguardando aprovação

- [ ] desenhar consolidação de fatores/dependência (`ResolvedFactor`/factor loader);
- [ ] definir cutover versionado de `quant.dependencia_macro` para a interface canônica, preservando replay/fingerprint;
- [ ] implementar apenas após aprovação do design;
- [ ] validar equivalência numérica + PostgreSQL 18 + E2E + suíte completa + prompts/tools sync;
- [ ] só então retomar FQ5.5 tendências fundamentais e FQ5.6 peers/setor.

Referência operacional: `.ai/WORKING_PROTOCOL.md`.


## Consolidação fatores/dependência — design

- [x] desenhar `FactorRef`/`ResolvedFactor`;
- [x] separar resolução de dados de transformação estatística;
- [x] definir cobertura inicial ativo/índice/FX;
- [x] desenhar contrato recomendado `quant.dependencia` 2.0.0;
- [x] desenhar estratégia de replay para dependência 1.0.1 e macro 1.0.0;
- [x] definir testes de equivalência e gates de promoção;
- [ ] **revisar/aprovar design antes de código**;
- [ ] implementar factor resolver em shadow;
- [ ] implementar dependência 2.0.0 em shadow;
- [ ] executar equivalência/replay;
- [ ] promover cutover atômico;
- [ ] só depois desbloquear FQ5.5/FQ5.6.

Documento: `.ai/FACTOR_DEPENDENCY_CONSOLIDATION_DESIGN.md`.


## Consolidação fatores/dependência — fechamento

- [x] aprovar design;
- [x] implementar FactorRef/ResolvedFactor em shadow;
- [x] congelar replay de dependência 1.0.1 e macro 1.0.0;
- [x] implementar quant.dependencia 2.0.0;
- [x] provar equivalência ativo×ativo, ativo×índice e ativo×FX;
- [x] cobrir Pearson, Spearman e lags assinados;
- [x] ocultar quant.dependencia_macro 1.0.1 do LLM;
- [x] atualizar planner, Research, E2E, blocos e goldens;
- [x] confirmar 33 -> 33 tools e drift somente nas duas interfaces previstas;
- [x] executar cutover atômico no branch autorizado;
- [x] validar PostgreSQL 18, invariantes e E2E;
- [x] validar suíte: 831 passed, 52 skipped, 19 warnings, 0 failed;
- [x] validar prompts check e tools sync --check;
- [x] registrar checkpoint final.

Próximo trabalho desbloqueado, mas não iniciado: Fundamentals + Valuation sob o gate reuse-before-build.

## FQ5.5 — Tendências fundamentais PIT

- [x] aplicar reuse-before-build ao snapshot atual;
- [x] identificar risco de fingerprint ao editar `app/market/fundamentals.py`;
- [x] desenhar histórico anual em módulo novo, sem migration;
- [x] limitar v1 a DFP anual; ITR/trimestre fora;
- [ ] implementar loader histórico em shadow;
- [ ] implementar engine de crescimento/margens em shadow;
- [ ] implementar `quant.tendencias_fundamentais` 1.0.0 shadow;
- [ ] provar fingerprints das 33 tools existentes inalterados;
- [ ] rodar testes locais + PostgreSQL 18 shadow gate;
- [ ] promover planner/blocos/catalog somente após shadow verde;
- [ ] CI pós-promoção e checkpoint;
- [ ] somente depois avaliar FQ5.6 peers/setor.

### FQ5.5 shadow — atualização
- [x] implementar loader histórico em módulo novo;
- [x] implementar engine de YoY/margens;
- [x] registrar `quant.tendencias_fundamentais` 1.0.0 shadow;
- [x] auditoria registry: 33 -> 34, zero drift nas 33 existentes;
- [x] testes puros relevantes: 29 passed;
- [ ] PostgreSQL 18 shadow gate;
- [ ] promoção planner/blocos/catalog somente se shadow gate verde;

### FQ5.5 promoção — atualização
- [x] PostgreSQL 18 shadow gate: run #56 verde (93 gate / 837 full suite);
- [x] preparar promoção 1.0.1 pública com patch bump de fingerprint;
- [x] atualizar planner: snapshot vs tendência;
- [x] adicionar blocos compactos e warnings client-facing;
- [x] atualizar catálogo exato F5 e promotion readiness;
- [x] registry promoção: 34 total, 33 anteriores intactas;
- [ ] publicar promoção no branch autorizado;
- [ ] CI pós-promoção completamente verde;
- [ ] checkpoint final + handoff;
- [ ] somente então abrir FQ5.6 peers/setor.


### FQ5.5 fechamento
- [x] publicar promoção no branch autorizado (`a8eb2bfeee7c77361fbefffe4d689b4328c70122`);
- [x] CI pós-promoção run #57 completamente verde;
- [x] gate explícito: 93 passed;
- [x] suíte completa: 838 passed, 52 skipped, 19 warnings, 0 failed;
- [x] prompts check e tools sync --check verdes;
- [x] checkpoint final + handoff;
- [x] FQ5.5 encerrado.

### FQ5.6 peers/setor — próximo gate
- [ ] aplicar reuse-before-build antes de código;
- [ ] auditar schema + ingestão/cobertura de `market.sector_classification`;
- [ ] documentar limitação de `reference_date` sem `availability_date`;
- [ ] desenhar universo de peers company-level com deduplicação de classes;
- [ ] mapear reuso de fundamentos/tendências/valuation sem duplicar matemática;
- [ ] somente depois decidir se há implementação/promocão segura.


## FQ5.6 — Peers/Setor

### Design / audit
- [x] confirmar schema existente `market.sector_classification`;
- [x] confirmar ausência de ingestão/consumer real no repo;
- [x] escolher B3 como única fonte da v1;
- [x] definir identidade CNPJ -> issuer e dedupe company-level;
- [x] definir PIT por `ingestion_batches.finished_at` sem migration nova;
- [x] separar FQ5.6A fundação de FQ5.6B comparação;
- [x] documentar reuso de valuation, FQ5.5 e `statistics.describe`.

### FQ5.6A — data foundation
- [ ] validar contrato técnico oficial B3 de download/API;
- [ ] capturar fixture real oficial e testar parser fail-closed;
- [ ] implementar ingestão append-only + relatório de cobertura em shadow;
- [ ] implementar loader PIT setorial em shadow;
- [ ] medir matched/unmatched/ambiguous no universo real;
- [ ] CI PostgreSQL 18 completo.

### FQ5.6B — peers
- [ ] só desbloquear após coverage gate FQ5.6A;
- [ ] design final de métricas/output compacto;
- [ ] implementação shadow reutilizando engines existentes;
- [ ] promoção apenas após registry/fingerprint/CI verdes.


### FQ5.6A1/A2a — atualização
- [x] validar existência/cadência da classificação oficial B3;
- [x] identificar UP2DATA Empresas Listadas / SummaryData como contrato estruturado oficial preferido;
- [x] rejeitar `listedCompaniesProxy` como contrato de produção não documentado;
- [x] documentar bloqueio de parser/coletor até fixture oficial real;
- [x] implementar loader PIT setorial em shadow sem rede/tool/migration;
- [x] testar seleção latest + consistência multi-classe em testes puros;
- [x] remover warning falso de cobertura baseado apenas em número de classes;
- [x] exigir target ação `is_in_universe` no peer universe;
- [x] escrever E2E PostgreSQL para strict PIT/dedupe/conflito/target fora do universo;
- [x] auditar registry: 34 -> 34, zero drift;
- [x] publicar shadow de código (`08bda53fa47eeef576a5fa525260f69d7818d906`);
- [ ] CI PostgreSQL 18 completo;
- [ ] somente após fixture oficial implementar parser/ingestão;
- [ ] coverage gate real antes de FQ5.6B.


### FQ5.6A2a — fechamento do loader shadow
- [x] CI PostgreSQL 18 completo — run #61 / `36799893075`;
- [x] gate explícito com loader setorial: 98 passed;
- [x] suíte completa: 849 passed, 52 skipped, 19 warnings, 0 failed;
- [x] prompts check e tools sync --check verdes;
- [x] loader PIT setorial shadow considerado GREEN;
- [ ] obter fixture real oficial B3/UP2DATA ou export oficial equivalente;
- [ ] implementar parser fail-closed somente depois da fixture;
- [ ] implementar ingestão append-only + relatório de cobertura;
- [ ] medir coverage real;
- [ ] somente depois desbloquear FQ5.6B peers.


### FQ5.6A2 — ingestão semântica / coverage shadow
- [x] localizar link oficial da amostra `Listed_Companies.zip` na página B3;
- [x] confirmar que Catálogo de Taxonomia não substitui fixture real do `SummaryData`;
- [x] manter parser físico bloqueado sem bytes oficiais;
- [x] criar `SectorSourceRecord` independente do formato do fornecedor;
- [x] reutilizar `market.ingestion_batches` para idempotência/provenance;
- [x] matching estrito CNPJ -> issuer;
- [x] expandir companhia para todas as classes `acao`;
- [x] conflito de mesma chave/conteúdo divergente falha fechado;
- [x] criar measurement de coverage PIT por nível explícito;
- [x] adicionar testes puros + E2E PostgreSQL ao gate explícito;
- [ ] executar CI PostgreSQL 18 do shadow;
- [ ] materializar fixture oficial real `Listed_Companies.zip`/SummaryData;
- [ ] somente então implementar parser físico e medir cobertura real;
- [ ] `quant.comparaveis_setor` continua bloqueada.


### FQ5.6A2 — fechamento GREEN
- [x] executar CI PostgreSQL 18 do shadow — run #63;
- [x] gate explícito 103 passed;
- [x] suíte completa 861 passed / 52 skipped / 19 warnings / 0 failed;
- [x] prompts check e tools sync --check verdes;
- [x] confirmar catálogo sem drift;
- [x] registrar checkpoint GREEN;
- [ ] materializar fixture oficial real `Listed_Companies.zip`/SummaryData;
- [ ] implementar parser físico somente depois da fixture;
- [ ] ingerir snapshot oficial real e medir cobertura por nível;
- [ ] decidir limiar de promoção somente com dados observados;
- [ ] FQ5.6B / `quant.comparaveis_setor` permanece bloqueada.


## Economatica — fonte auxiliar

- [x] auditar estrutura dos ZIPs fornecidos pelo usuário;
- [x] confirmar campos de setor/subsetor e métricas financeiras;
- [x] confirmar ausência de CNPJ/segmento B3 no export auditado;
- [x] detectar que metadata de cadastro/setor não é vintage anual;
- [x] proibir retrodatação de classificação pelos anos dos workbooks;
- [x] classificar Economatica como validação auxiliar;
- [ ] decidir integração auxiliar de classificação corrente com source_code próprio;
- [ ] se aprovada, desenhar match ticker exato -> instrument -> issuer;
- [ ] manter B3/UP2DATA como fonte canônica desejada para strict PIT/segmento;
- [ ] não ingerir preços/fundamentos Economatica no acervo canônico antes de policy específica.


## FQ5.6 — Economatica auxiliar shadow
- [x] auditar arquivos e semântica temporal;
- [x] desenhar source separado e match ticker exato;
- [ ] registrar source `economatica` via migration nova;
- [ ] implementar parser XLSX fail-closed;
- [ ] implementar ingestão corrente por ticker/issuer;
- [ ] testar arquivo real local sem versionar raw;
- [ ] testar PostgreSQL 18;
- [ ] provar zero drift no registry;
- [ ] registrar checkpoint GREEN;
- [ ] decidir política de consumo antes de FQ5.6B.


### FQ5.6 Economatica auxiliar — shadow
- [x] registrar source `economatica` via migration nova 0063;
- [x] implementar parser XLSX fail-closed;
- [x] validar parser no arquivo real 2025: 478 ações B3 ativas;
- [x] implementar ingestão corrente por ticker exato -> issuer -> classes;
- [x] preservar segment/listing como NULL;
- [x] adicionar testes puros e DB ao gate explícito;
- [ ] executar PostgreSQL 18 CI;
- [ ] provar zero drift no registry;
- [ ] checkpoint GREEN;
- [ ] decidir source policy de FQ5.6B.


### FQ5.6 Economatica auxiliar — fechamento shadow
- [x] migration 0063/source provenance;
- [x] parser XLSX fail-closed;
- [x] arquivo real 2025: 478 ações B3 ativas;
- [x] ingestão por ticker exato/issuer/classes;
- [x] PostgreSQL 18 CI run #71;
- [x] gate 108 passed;
- [x] full suite 866/52/19/0;
- [x] prompts/tools sync verdes;
- [x] 34 tools sem drift;
- [x] checkpoint GREEN;
- [ ] criar/rodar dry-run de matching contra universo real do Plexo;
- [ ] medir matched/unmatched por ticker;
- [ ] decidir fonte e nível da FQ5.6B;
- [ ] só depois abrir `quant.comparaveis_setor`.
