# Plexo — Changelog de continuidade

## 2026-09-19 — FQ0 do Analista de Mercado

- Criada a memória persistente `.ai/` conforme protocolo de continuidade do projeto.
- Consolidado o escopo exclusivo de mercado para esta frente.
- Reconciliado o plano do Analista com o backend real no commit `51d87b4`.
- Confirmado que tools Quant atuais ainda usam fechamento bruto.
- Confirmado que F22 já possui views de ajuste e estruturas de acervo, porém a carga histórica ampla está bloqueada por infraestrutura.
- Identificado risco de auditoria/cache: hash de versão de tool não cobre helpers/engines importados.
- Definida como primeira alteração técnica a correção desse fingerprint antes da extração dos Quant Engines.

## 2026-09-19 — FQ0.5: fingerprint composto e exposição de tools

- `ToolSpec` passou a distinguir tool executável de tool exposta ao LLM por `exposed_to_llm`.
- turno e Research planner deixam de oferecer tools ocultas; compiler recusa tool oculta em planos novos.
- runtime/registry continuam capazes de resolver a tool, permitindo janela de migração legacy.
- `source_sha256` ganhou suporte a fingerprint composto por arquivos de implementação declarados (`source_dependencies`).
- o módulo de `preparar` entra automaticamente no fingerprint quando estiver em arquivo diferente do `calcular`.
- uma tool de arquivo único preserva exatamente o SHA legado; compatibilidade CRLF permanece somente para esse caso.
- foram adicionados testes para fingerprint composto, exposição no catálogo e rejeição pelo compiler.
- validação disponível neste ambiente: `py_compile`, `git diff --check`, smokes puros e 8 testes pytest sem banco verdes. A suíte de integração com PostgreSQL permanece pendente por falta da configuração de banco deste ambiente; nenhum `.env` do ZIP foi lido.

## 2026-09-19 — FQ1: Quant Data Foundation

- criado `app/market/series.py` como camada canônica de séries;
- introduzidos `SeriesReader`, `PostgresSeriesReader` e `MarketSeriesLoader`;
- preços e índices/taxas passam a compartilhar cutoff, quality e provenance;
- `raw_close` e `adjusted_close` ficaram separados da semântica temporal;
- adjusted close estritamente point-in-time é recusado enquanto corporate actions não possuírem data de disponibilidade;
- calendário B3 oficial só é aceito com cobertura diária completa da janela; caso contrário o fallback derivado de preços é marcado explicitamente;
- adapters legacy de `_comum.py` foram movidos para o novo loader sem alterar os outputs das tools atuais;
- seis tools de mercado tiveram patch bump e fingerprint composto incluindo `_comum.py` + `app/market/series.py`;
- adicionada suíte FQ1 com cutoff, calendário, provenance, adjusted retrospective, fail-closed PIT, duplicatas, preço inválido, índices negativos legítimos e alinhamento;
- validação local disponível: 42 testes sem banco verdes + `py_compile`/`git diff --check`; integração PostgreSQL está escrita e pendente de execução no ambiente oficial.

## 2026-09-21 — FQ1: bateria ampliada e correção da semântica temporal

- executada a suíte local inteira que não depende do fixture PostgreSQL: 243 testes passaram, sem falhas;
- executados 41 testes críticos FQ1/F22/F5 sem banco;
- adicionada bateria de property/fuzz com dezenas de milhares de combinações para cutoff, alinhamento, quality e valores inválidos;
- validado grafo de 61 migrations Alembic e contratos estáticos da migration 61;
- validado registry de 24 tools e fingerprint composto;
- identificado que `strict_point_in_time` superestimava a garantia disponível: preços/índices têm data de observação, mas não vintage/availability auditável;
- semântica renomeada para `observation_date_cutoff`; adjusted close continua somente retrospectivo até o schema de corporate actions suportar availability;
- integração PostgreSQL continua como gate obrigatório antes de merge/deploy.

## 2026-09-21 — Gate PostgreSQL isolado para FQ1

- criado `.github/workflows/verify.yml` para PR/manual, sem deploy e sem segredos de produção;
- workflow usa PostgreSQL 18 local, migrations do zero, `preparar_ambiente`, validador, invariantes SQL nos dois papéis, gate FQ1/F5/F22, suíte pytest completa e drift local de prompts/tools;
- adicionado `tests/test_fq1_ci_verify.py` para proteger a configuração do workflow;
- após a mudança, suíte local sem banco: 245 passed, 16 skipped, 355 deselected, nenhuma falha;
- integração PostgreSQL real permanece o único gate obrigatório não executado neste runtime.


## 2026-09-21 — FQ2.1: Quant Core de retornos e estatística

- criado `app/market/analytics/` como camada matemática independente de I/O e LLM;
- adicionados modelos imutáveis `ReturnMethod`, `IndexUnit`, `ReturnObservation` e `DistributionSummary`;
- implementados retornos simples/log, acumulado, anualização geométrica, composição e conversão de índices/taxas;
- implementados validação de amostra finita, desvio-padrão amostral e resumo descritivo;
- definidos edge cases fail-closed para preços/taxas/datas inválidos e `None` para estatística sem amostra suficiente;
- `quant.retorno_volatilidade` passou a consumir o novo core para retorno e volatilidade, com semver `1.0.2`;
- o fingerprint da tool inclui os arquivos do Quant Core que alteram o resultado;
- golden legacy de retorno/volatilidade permaneceu idêntico;
- adicionados 18 testes FQ2.1, incluindo 500 caminhos sintéticos/property checks;
- suíte local sem PostgreSQL após a mudança: 263 passed, 16 skipped, 355 DB-deselected, 0 failed.

## 2026-09-21 — FQ2.2: Risk Engine

- criado `app/market/analytics/risk.py` como camada matemática pura;
- adicionados modelos imutáveis para rolling metric, drawdown e episódio de drawdown;
- implementados volatilidade anualizada, rolling volatility, downside deviation, série/max drawdown, duração e recovery;
- duração de drawdown foi definida em intervalos observados, sem inventar calendário no core;
- `quant.retorno_volatilidade` passou a usar Risk Engine para volatilidade e maximum drawdown, com semver `1.0.3`;
- fingerprint da tool passou a incluir `risk.py`;
- golden legacy permaneceu idêntico;
- 17 testes diretos de risco passaram, incluindo 500 caminhos de invariantes, 750 comparações de drawdown legacy e 750 comparações de volatilidade legacy;
- bateria local ampla sem PostgreSQL: 280 passed, 16 skipped, 355 DB-deselected, 0 failed.


## 2026-09-21 — FQ2.3: Dependence Engine

- criado `app/market/analytics/dependence.py` como camada matemática pura;
- adicionados modelos imutáveis para pares de retorno, estimativa de dependência, rolling e condicionais;
- implementados Pearson, Spearman com ranks médios, alinhamento por interseção, lag assinado, rolling dependence e up/down-market;
- lag preserva `x_date`, `y_date` e `as_of_date`, evitando esconder a temporalidade do pareamento;
- `quant.correlacao` passou a usar Returns + Dependence Core, com semver `1.0.2` e fingerprint incluindo os engines relevantes;
- schema/output/golden legacy de `quant.correlacao` permaneceram idênticos;
- 14 testes diretos passaram, além de 750 comparações com Pearson+lag legacy e 250 checks de simetria de lag;
- bateria local ampla sem PostgreSQL: 294 passed, 16 skipped, 355 DB-deselected, 0 failed;
- FQ2 base foi encerrado com returns/statistics/risk/dependence; event study permanece na FQ4.

## 2026-09-21 — FQ3.1 `quant.risco_retorno` shadow

- corrigida a descrição/schema de `dados.serie_precos`: cutoff é pela data da observação e não
  promessa de vintage point-in-time; semver `1.0.1 -> 1.0.2`;
- criada `quant.risco_retorno` `1.0.0` em shadow mode (`exposed_to_llm=False`);
- default da tool canônica é `adjusted_close -> retrospective_as_known_now`; `raw_close` deriva
  `observation_date_cutoff`;
- output compacto inclui retorno acumulado/anualizado, volatilidade, maximum drawdown e episódio de
  drawdown, sem série ponto a ponto;
- provenance/warnings de adjusted retrospectivo e fallback de calendário são preservados;
- blocos agora conhecem frases para `adjusted_close_retrospective` e
  `calendar_fallback_from_prices` em preparação para o cutover;
- 12 testes FQ3.1 verdes; bateria local sem PostgreSQL: 306 passed, 16 skipped, 355 deselected.


## 2026-09-21 — FQ3.2 `quant.dependencia` + FQ3.3 cutover canônico

- criada `quant.dependencia` sobre MarketSeriesLoader + Returns/Dependence Core;
- contrato suporta ativo×ativo ou ativo×índice, Pearson/Spearman e lag assinado em observações comuns;
- output permanece compacto e não envia séries/pares para a LLM;
- adicionado `indice_desconhecido` e loader resolvido de índice em `_comum.py`;
- regra de `price_basis -> temporal_semantics` centralizada em `app/market/series.py`;
- canônicas expostas: `quant.risco_retorno` `1.0.1` e `quant.dependencia` `1.0.1`;
- legacy ocultadas: `quant.retorno_volatilidade` `1.0.4` e `quant.correlacao` `1.0.3`;
- planner, evals, Research e blocos migrados para códigos canônicos em novas execuções; replay legacy preservado;
- adicionados testes de cutover atômico, registry/semver, planner sem legacy e blocos canônicos/legacy;
- regressão local sem PostgreSQL: 324 passed, 16 skipped, 355 DB-deselected, zero falhas;
- ativação em produção permanece pendente de PostgreSQL CI + tool sync + sync/aprovação do planner.

## 2026-09-21 — FQ4.1 `quant.analise_condicional` shadow

- criado `app/market/analytics/conditional.py`;
- adicionados modelos internos de mudança condicionante, pares de intervalos, resumo de retorno e análise condicional;
- condicionantes de ativo/índice em pontos usam retorno simples; taxas/percentuais usam mudança do nível;
- retorno do ativo é medido no mesmo intervalo da condicionante com as-of backward nos endpoints, sem look-ahead;
- baseline contém todos os intervalos válidos; amostra condicional seleciona alta/queda e mantém neutros separados;
- criada `quant.analise_condicional` 1.0.0 em shadow mode;
- output compacto inclui resumos, diferença de médias, magnitude da condição e Evidencia, sem séries/pares;
- amostra curta mantém métricas com warning; ausência de eventos ganhou `sem_eventos_condicao`;
- adicionado mapeador de bloco específico e frase cliente para o novo warning;
- 19 testes FQ4.1 verdes, incluindo 400 cenários property e edge cases de as-of; regressão ampla sem DB: 343 passed, 16 skipped, 355 deselected, 0 failed;
- registry após a etapa: 27 tools registradas; catálogo Analista continua com 8 visíveis porque a nova tool está shadow.


## 2026-09-21 — FQ4.2 foundation: structured statistical estimates

- criado `app/market/analytics/estimates.py` com `ConfidenceInterval` e `MetricEstimate`;
- criado `app/tools/analista/evidencia_estatistica.py` sem alterar `Evidencia` base;
- pipeline de `analysis.evidence_findings` passou a transportar `estimativas` somente quando presentes;
- removida linguagem interna obsoleta de "point-in-time" em comentários/docstrings tocados de `analysis.py`, substituída por as-of/cutoff de observação;
- modelos novos foram isolados de arquivos já fingerprintados para evitar bumps falsos de semver/source hash;
- comparação FQ4.1 vs FQ4.2: 27 tool specs idênticas em semver/exposição/source SHA;
- 13 testes específicos do novo contrato passaram; FQ4.1 + foundation = 32 testes;
- regressão ampla sem DB: 356 passed, 16 skipped, 355 DB-deselected, 0 failed;
- nenhuma regressão estatística ou nova tool foi criada nesta etapa.


## 2026-09-21 — FQ4.2: Regression/Sensitivity Engine + `quant.sensibilidade` shadow

- criado `analytics/regression.py` com OLS univariada + HAC/Newey-West Bartlett/HC1 correction;
- criado `analytics/sensitivity.py` para unidades, escala e diagnóstico de frequência;
- implementada regra automática de lags e CI 95% sem nova dependência numérica;
- corrigida estabilidade numérica via resíduos/funções de influência centrados após teste com offset `1e12`;
- criada `quant.sensibilidade` 1.0.0 em shadow mode, usando `EvidenciaEstatistica`;
- taxa/percentual usa mudança de nível; ativo/índice em pontos usa retorno; resposta usa retorno no mesmo intervalo;
- output não inclui pares, preços ou resíduos; bloco determinístico mostra beta, CI, R², n e lags HAC;
- sem imputação, winsorização ou trimming; linguagem explicitamente associacional/não causal;
- novos warnings client-facing para driver constante, falta de graus de liberdade e amostra insuficiente de regressão;
- 27 testes novos específicos; regressão ampla sem PostgreSQL: 383 passed, 16 skipped, 355 deselected, 0 failed;
- registry cresceu de 27 para 28 tools; nenhuma das 27 anteriores mudou semver/exposição/source SHA.


## 2026-09-21 — FQ4.3: Regimes Engine + `quant.regimes` shadow

- criado `app/market/analytics/regimes.py`;
- regimes v1 são regras auditáveis de `level`/`direction`, sem clustering/HMM/threshold otimizado;
- `level` usa nível do driver no início do intervalo; default = mediana retrospectiva da amostra válida;
- `direction` usa retorno para ativos/índices em pontos e mudança de nível para taxa/percentual;
- alinhamento da resposta usa as-of backward + freshness gate, sem look-ahead;
- nenhuma métrica de drawdown é calculada em amostras de regime descontínuas;
- criada `quant.regimes` 1.0.0 shadow, com output compacto e bloco determinístico;
- adicionados warnings `regime_sem_duas_amostras` e `regime_amostra_insuficiente`;
- 21 testes específicos/property passaram, cobrindo 1.100 cenários sintéticos;
- regressão ampla sem DB: 404 passed, 16 skipped, 355 deselected, 0 failed;
- registry cresceu 28 -> 29; 28 tools anteriores preservaram semver/exposição/source SHA.

## 2026-09-25 — FQ4.4: Event Study v2 shadow + replay 1.0.1

- criado `app/market/analytics/event_study.py`;
- criado `quant.event_study_v2` 1.0.0 shadow sobre MarketSeriesLoader/Returns/Regression/Estimates;
- adicionado alinhamento seguro `synchronized_returns_from_prices`: níveis são intersectados antes dos retornos para garantir endpoints idênticos;
- market model usa OLS point estimate do Regression Core; market adjusted mantém alpha=0/beta=1;
- inferência opcional `classic_iid_normal` produz CI do CAR sem p-value/significance;
- criado replay autocontido `event_study_legacy_1_0_1.py` e validado contra golden histórico;
- `quant.event_study` visível recebeu somente correção textual de semântica temporal e bump 1.0.1 -> 1.0.2, sem mudança numérica;
- novo mapper de blocos v2 e warnings client-facing;
- 22 testes específicos verdes, incluindo 500 cenários sintéticos/property;
- regressão ampla sem PostgreSQL: 426 passed, 16 skipped, 355 DB-deselected, 0 failed;
- registry audit: 29 -> 30 tools; única tool anterior alterada = `quant.event_study`; única nova = `quant.event_study_v2`.

## 2026-09-25 — Gate de integração/promoção FQ4

- criado `tests/test_fq4_integration_db.py` com E2E das quatro shadows pelo executor real;
- teste cobre sync, policies, COTAHIST, MarketSeriesLoader/views, `tool_executions` e cache;
- `.github/workflows/verify.yml` passou a executar o gate FQ4 junto de FQ1/F5/F22 em PostgreSQL 18;
- `tests/test_fq1_ci_verify.py` protege a presença do novo gate;
- planner preparado condicionalmente para `analise_condicional`, `sensibilidade` e `regimes`;
- criado `tests/test_fq4_promotion_readiness.py`, garantindo que preparação do planner não expõe shadows;
- regressão local sem DB: 429 passed, 16 skipped, 357 DB-deselected, 0 failed;
- registry: 30/30 códigos únicos, quatro FQ4 shadows ainda ocultas;
- gate PostgreSQL continua pendente porque este runtime não possui servidor/container e não tem DNS externo.


## 2026-09-30 — FQ4 real PostgreSQL integration gate

- executado CI isolado contra PostgreSQL 18 real;
- gate FQ1/F5/F22/FQ4 E2E verde;
- suíte completa verde: 806 passed, 52 skipped, 19 warnings;
- `prompts check` verde;
- `tools sync --check` verde;
- corrigidas fixtures FQ4 para API async real e asserts para os schemas públicos reais de condicional/sensibilidade/regimes;
- testes F5/F6 atualizados para exigir propagação auditável de warnings metodológicos;
- nenhuma tool FQ4 foi promovida nesta etapa.

## 2026-09-30 — Promoção controlada do FQ4

- após gate PostgreSQL 18 verde, promovidas `quant.analise_condicional` 1.0.1, `quant.sensibilidade` 1.0.1 e `quant.regimes` 1.0.1;
- `quant.event_study` passou para a implementação Quant Core/MarketSeriesLoader em 2.0.0;
- `quant.event_study_v2` deixou de ser um código registrado;
- legacy event study continua disponível apenas para golden/replay;
- testes de catálogo, blocos e E2E PostgreSQL foram atualizados para o estado promovido;
- promoção aplicada somente em `feoff01/plexo-backend-validation`, branch `bootstrap/plexo-project`;
- CI pós-promoção é gate obrigatório antes de considerar o cutover encerrado.

## 2026-09-30 — Fechamento do FQ4 pós-promoção

- CI detectou e corrigiu contratos F5 ainda presos ao catálogo/shape legacy;
- golden de blocos de `quant.event_study` foi atualizado explicitamente para a representação canônica v2;
- números históricos do golden foram preservados;
- run #39 (`36760273363`) ficou totalmente verde;
- suíte: **806 passed, 52 skipped, 19 warnings**;
- FQ1/F5/F22/FQ4 E2E, prompts check e tools sync --check verdes;
- documentação de fechamento atualizada;
- run #40 (`36760679156`) também verde no HEAD `c11cb160743c00d18a06b2fa5689fdb56cd64dff`;
- FQ4 encerrado no repositório dedicado de validação.


## 2026-09-30 — FQ5.1–FQ5.4 promovido e encerrado
- migration 0062 para unidade/currency e fundamentals multi-classe;
- novas foundations: fundamentals PIT, raw price snapshots, FX factors;
- publicadas `dados.fundamentos_empresa`, `quant.valor_mercado`, `quant.cenario_sensibilidade`, `quant.dependencia_macro` 1.0.0;
- market cap exige cobertura completa de classes; múltiplos falham fechado com inputs inadequados;
- cenário usa somente `slope × choque`, sem intercepto, previsão ou fair value;
- planner decompõe empresa/juros/câmbio e não inventa choque;
- blocos determinísticos compactos adicionados;
- shadow run #47 verde: 74 E2E / 810 passed full suite;
- run #48 bloqueou corretamente catálogo F5 desatualizado após promoção;
- run #49 pós-correção totalmente verde: **74 E2E / 816 passed / 52 skipped / 19 warnings / prompts/tools sync verdes**;
- FQ4 permaneceu intacto; nenhuma migration histórica foi editada.


## 2026-09-30 — Auditoria arquitetural / capability inventory pós-FQ5

### Documentação
- novo `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md` com inventário de tools, Quant Core, loaders, schema e gaps reais;
- novo checkpoint `.ai/checkpoints/2026-09-30_ARCHITECTURE_CAPABILITY_AUDIT.md`;
- regra `reuse-before-build` formalizada em `DECISIONS.md` e `TASKS.md`.

### Achados
- `quant.dependencia_macro` classificada como sobreposição real de interface/orquestração com `quant.dependencia`; adapter FX é a adição de dados legítima;
- legacy de correlação/risco/Event Study permanece intencional para replay;
- `quant.cenario_sensibilidade` permanece composição legítima por reutilizar a sensibilidade existente e evitar cálculo numérico pelo LLM;
- capacidades Quant latentes e schemas existentes sem consumer foram catalogados para evitar reinvenção.

### Código
- nenhuma alteração de código, migration, semver, exposição ou source fingerprint nesta rodada.


## 2026-09-30 — Protocolo de memória persistente

- adicionado `.ai/WORKING_PROTOCOL.md` como protocolo canônico de continuidade;
- formalizado que decisões, estado, tarefas, changelog e checkpoints devem ser persistidos em `.ai/` e não depender de memória de chat;
- registrada sequência recomendada pós-auditoria como proposta: consolidação de fatores/dependência -> cutover versionado -> retomada de Fundamentals + Valuation;
- nenhuma alteração de código, migration, tool, semver, exposição ou fingerprint.


## 2026-09-30 — Design de consolidação de fatores/dependência

- criado `.ai/FACTOR_DEPENDENCY_CONSOLIDATION_DESIGN.md`;
- criado checkpoint `.ai/checkpoints/2026-09-30_FACTOR_DEPENDENCY_CONSOLIDATION_DESIGN.md`;
- proposta `FactorRef`/`ResolvedFactor` para resolver ativo/índice/FX sem tool por fonte;
- recomendado cutover `quant.dependencia` 2.0.0 e macro como compatibilidade oculta;
- definido plano de semver/fingerprint/replay, equivalência numérica e gates;
- nenhuma alteração de código, SQL, migration, prompt, tool ou matemática nesta etapa.


## 2026-09-30 — Cutover de dependência / factor resolver — GREEN

- criado `factor_resolution.py` com `FactorRef`/`ResolvedFactor` para ativo, índice/taxa e FX;
- `quant.dependencia` promovida de 1.0.1 para **2.0.0** com `serie_b={tipo,codigo}`;
- `quant.dependencia_macro` promovida de 1.0.0 para **1.0.1** e ocultada do LLM;
- versões históricas congeladas em módulos legacy + goldens;
- planner passa a usar dependência canônica para ativos, índices/taxas e USD/BRL;
- nenhum engine Quant Core FQ3/FQ4, migration ou schema foi alterado;
- registry permaneceu 33 -> 33; apenas as duas interfaces previstas mudaram;
- commit `60bad205666e5cc5c5d0e2b2b8e643f41e2ac322`;
- run #54 `36793672760`: 87 E2E; 831 passed, 52 skipped, 19 warnings, 0 failed; PostgreSQL 18, invariantes, validador 0/0, prompts e tools sync verdes.

## 2026-09-30 — Design FQ5.5 tendências fundamentais PIT

- criado `.ai/FQ5_5_FUNDAMENTAL_TRENDS_DESIGN.md`;
- reuse-before-build confirmou que `market.fundamentals` e o reader atual já fornecem a base necessária;
- detectado e evitado drift de fingerprint: histórico será módulo novo em vez de alteração de `app/market/fundamentals.py`;
- v1 limitada a DFP anual; ITR/trimestre explicitamente fora para evitar interpretação errada de fluxos acumulados;
- nenhuma alteração de código/schema/tool nesta etapa de design.

## 2026-09-30 — FQ5.5 shadow ready

- criado `app/market/fundamental_history.py` sem tocar no foundation fingerprintado;
- criado `app/market/analytics/fundamental_trends.py`;
- criada `quant.tendencias_fundamentais` 1.0.0 shadow;
- adicionados testes de vintage/restatement, YoY, margens, base não positiva, unidade incompatível e E2E PostgreSQL;
- workflow CI atualizado para incluir FQ5.5 shadow no gate explícito;
- registry audit: 33 -> 34, somente nova tool adicionada; 33 fingerprints anteriores intactos;
- 29 testes puros relevantes passaram localmente;
- promoção ainda não realizada.

## 2026-09-30 — FQ5.5 shadow GREEN e promoção preparada

- shadow run #56 `36795497161` success: 93 gate / 837 passed / 52 skipped / 19 warnings / 0 failed;
- `quant.tendencias_fundamentais` preparada para promoção 1.0.1 pública;
- planner passa a diferenciar fundamentos atuais (`dados.fundamentos_empresa`) de evolução anual (`quant.tendencias_fundamentais`);
- mapper de blocos adiciona resumo de métricas e série de margens sem criar números novos;
- warnings de histórico curto, base não positiva, receita não positiva e métrica por classe ganharam tradução client-facing;
- catálogo F5/promotion readiness atualizados;
- nenhuma das 33 tools anteriores alterou source fingerprint.


## 2026-09-30 — FQ5.5 tendências fundamentais PIT — GREEN

- `quant.tendencias_fundamentais` promovida para **1.0.1 pública**;
- planner diferencia snapshot atual de fundamentos versus evolução histórica;
- blocos compactos adicionados sem recalcular métricas no LLM;
- DFP anual PIT preserva vintages/restatements por cutoff;
- ITR, CAGR, forecast e fair value permanecem explicitamente fora da v1;
- as 33 tools existentes antes da tranche mantiveram semver/exposição/source fingerprint;
- commit de promoção `a8eb2bfeee7c77361fbefffe4d689b4328c70122`;
- run #57 `36796184892`: 93 gate; **838 passed, 52 skipped, 19 warnings, 0 failed**; PostgreSQL 18, invariantes, validador, prompts e tools sync verdes;
- criado checkpoint `.ai/checkpoints/2026-09-30_FQ5_5_PROMOTION_GREEN.md`.


## 2026-09-30 — FQ5.6 peers/setor — design e data readiness audit

- auditado `market.sector_classification`: schema existe, mas não há coletor/projetor que o preencha no repo;
- criada `.ai/FQ5_6_PEERS_SECTOR_DESIGN.md` e checkpoint correspondente;
- FQ5.6 dividido em Sector Data Foundation (A) e Peer Comparison (B);
- definida B3 como única fonte da v1;
- definido matching CNPJ -> issuer e projeção para classes de ação, sem heurística por prefixo de ticker;
- definido strict PIT de novos snapshots via `ingestion_batches.finished_at`, sem migration redundante;
- comparação futura deve reutilizar valuation/FQ5.5/statistics existentes;
- nenhuma alteração de código, migration, tool, semver ou fingerprint nesta etapa.
