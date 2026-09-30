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

