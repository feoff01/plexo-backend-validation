# Plexo — Project State

Atualizado em: 2026-09-25
Commit-base desta revisão: `51d87b46dbacbd7d814e4df4920b366b1105e480`

## Objetivo geral

Plexo é um Copiloto financeiro no qual o LLM entende a pergunta, escolhe tools registradas e redige a leitura; números client-facing são produzidos por código determinístico, versionado e auditável.

## Frente ativa

**Analista de Mercado / Quant Core.** Esta frente NÃO inclui planejamento financeiro pessoal, orçamento, metas, aposentadoria, suitability individual ou análise da vida financeira do cliente.

Objetivo atual: transformar o Analista em uma camada de inteligência de mercado com ferramentas quantitativas fortes, preservando a infraestrutura atual de tools/Research.

## Arquitetura atual a preservar

- `app/agents/turn.py`: orquestração do turno e tool-use.
- `app/tools/registry.py`: `@tool`; Pydantic gera o `param_schema` enviado ao LLM.
- `app/tools/executor.py`: validação → `preparar()` → cache → `calcular()` → `tool_executions`.
- `preparar(params, ctx)`: I/O, RLS, policies, cutoff e resolução de insumos.
- `calcular(resolvido)`: função pura/determinística, protegida por golden.
- `tools.tool_versions`: semver + git SHA + source SHA256.
- `analysis.*`: analyses, findings, Research DAG, planner/compiler/executor/report.
- `app/agents/blocos.py`: blocos derivam apenas de `output_payload`.
- Gates de família, plano e policy permanecem no banco.

## Estado atual do Analista

Tools Quant canônicas visíveis no working copy:
- `quant.risco_retorno` 1.0.1 — Returns/Statistics/Risk Core;
- `quant.dependencia` 1.0.1 — Returns/Dependence Core;
- `quant.event_study` 1.0.2 — implementação legacy determinística; contrato temporal corrigido e replay 1.0.1 congelado.

Tools FQ4 em shadow:
- `quant.analise_condicional` 1.0.0 — `exposed_to_llm=False`, Conditional Core;
- `quant.sensibilidade` 1.0.0 — `exposed_to_llm=False`, OLS + HAC/Newey-West sobre intervalos do driver;
- `quant.regimes` 1.0.0 — `exposed_to_llm=False`, comparação descritiva entre regimes explícitos de nível ou direção;
- `quant.event_study_v2` 1.0.0 — `exposed_to_llm=False`, MarketSeriesLoader + retornos sincronizados + market model/market adjusted + CI clássico opcional do CAR.

Event study visível durante a migração:
- `quant.event_study` 1.0.2 — cálculo legacy preservado; somente contrato temporal corrigido; replay puro da 1.0.1 congelado em `event_study_legacy_1_0_1.py`.

Legacy preservada para replay/auditoria, mas oculta de novos turnos/planos:
- `quant.retorno_volatilidade` 1.0.4;
- `quant.correlacao` 1.0.3.

Dados/infra relevantes:
- F22 criou `market.trading_calendar`, `sector_classification`, `index_weights`, `yield_curve`, `fundamentals`, `v_fatores_ajuste`, `v_precos_ajustados`.
- Tools canônicas de risco/dependência e FQ4 usam `MarketSeriesLoader`; adapters legacy e `event_study` ainda existem onde compatibilidade histórica é necessária.
- O acervo histórico já existe fora do backend em Parquet normalizado (Mercado Brasil Collector); `tools/projetar_acervo.py` tentava projetá-lo para PostgreSQL.
- A tentativa de carregar ~2,9 milhões de preços no PostgreSQL hospedado saturou o plano e a carga histórica está parada.
- `market.corporate_actions` não possui `availability_date`/announcement date; `adjusted_close` permanece explicitamente retrospectivo e não deve ser tratado como vintage PIT.

## Arquitetura-alvo Quant

Catálogo canônico inicial:
- `quant.risco_retorno`;
- `quant.dependencia`;
- `quant.analise_condicional`;
- `quant.sensibilidade`;
- `quant.regimes`;
- `quant.event_study` (conceito mantido, implementação evolui).

Legacy planejado:
- `quant.retorno_volatilidade` → substituído gradualmente por `quant.risco_retorno`;
- `quant.correlacao` → substituído gradualmente por `quant.dependencia`.

Estratégia:
- funções matemáticas pequenas ficam internas;
- engines reutilizáveis ficam abaixo das tools;
- tools representam intenções analíticas completas;
- Research combina investigações, não fórmulas pequenas.

## Invariante nova descoberta no FQ0

Antes de extrair matemática para engines compartilhados, o fingerprint de uma tool precisa incluir os arquivos de implementação dos quais o resultado depende. Hoje `source_sha256` cobre apenas o módulo da tool; mudar `_comum.py` ou um futuro engine pode alterar números sem alterar a versão/hash da tool.

Esta correção é pré-requisito do Quant Core.

## Problemas conhecidos / riscos

1. Fingerprint composto já foi implementado no working copy; engines futuros precisam declarar seus arquivos via `source_dependencies` e bumpar semver quando a implementação material mudar.
2. `output_payload` completo é enviado ao LLM; séries/outputs ricos podem aumentar tokens fortemente.
3. `Evidencia.metricas` continua restrito a escalares simples; `MetricEstimate`/`ConfidenceInterval` + `EvidenciaEstatistica` já suportam estimativas inferenciais estruturadas e `quant.sensibilidade` é o primeiro uso real.
4. `v_precos_ajustados` é retrospectiva; sem disponibilidade temporal de corporate actions não deve ser tratada automaticamente como série PIT histórica.
5. `MarketSeriesLoader` usa `trading_calendar` quando a janela oficial está completa; quando não está, usa fallback explícito derivado dos preços do universo. A cobertura oficial do calendário ainda precisa ser garantida operacionalmente.
6. Storage histórico definitivo ainda não foi decidido.
7. O Research executa até 8 tasks, sequencialmente, e não passa outputs genericamente entre nós.
8. `market.prices` pode conter mais de uma fonte por data; o comportamento legado escolhe `source_code` em ordem alfabética. Isto é determinístico, mas não é uma política de qualidade. Antes de ingerir múltiplas fontes concorrentes, definir prioridade explícita por dataset/instrumento. A view de ajuste também precisa herdar essa regra.

## FQ1 implementado no working copy

- Criado `app/market/series.py` com `SeriesReader`, `PostgresSeriesReader` e `MarketSeriesLoader`.
- O loader cobre preços de instrumentos e `market.index_values` pelo mesmo contrato.
- `PriceBasis`: `raw_close` / `adjusted_close`.
- `TemporalSemantics`: `observation_date_cutoff` / `retrospective_as_known_now`.
- `observation_date_cutoff` limita por data da observação, mas NÃO promete vintage point-in-time.
- `adjusted_close` exige `retrospective_as_known_now` enquanto corporate actions não tiverem data de disponibilidade.
- Quality inclui cobertura, lacunas, staleness, datas inesperadas e fonte do calendário.
- Provenance inclui dataset, fontes, batches de série e de calendário, basis, semântica temporal e warnings.
- `market.trading_calendar` tem precedência somente quando a janela diária está completa; do contrário usa fallback de preços do universo.
- `_comum.carregar_serie` e `_comum.carregar_indice` agora são adapters legacy para o loader canônico.
- `dados.serie_precos`, `dados.serie_indice`, `dados.historico_comparado`, `quant.retorno_volatilidade`, `quant.correlacao` e `quant.event_study` declaram `series.py`/`_comum.py` no fingerprint e tiveram patch bump de semver.
- Outputs/goldens das tools legacy permaneceram iguais nos testes puros.

## FQ2.1 implementado no working copy — Returns + Statistics

- Criado `app/market/analytics/` como package puramente matemática, sem banco/LLM/policy/registry.
- `models.py`: `ReturnMethod`, `IndexUnit`, `ReturnObservation`, `DistributionSummary`, todos imutáveis/`extra=forbid`.
- `returns.py`: retornos simples/log, retorno acumulado por preço, anualização geométrica com base explícita, composição de retornos simples e conversão de índices/taxas (`taxa_aa`, `taxa_am`, `percentual`, `pontos`).
- `statistics.py`: validação de amostra finita, desvio-padrão amostral e resumo descritivo.
- Edge cases são explícitos: série vazia/1 ponto retorna `None` onde a métrica é indefinida; preço <= 0, datas não crescentes, NaN/inf e taxa impossível falham fechado.
- Nenhuma constante de negócio (ex.: 252) vive no Quant Core; `periods_per_year` é sempre input explícito.
- `quant.retorno_volatilidade` 1.0.2 já usa `returns.py`/`statistics.py` para retorno e volatilidade; output/golden legacy permaneceu idêntico.
- Fingerprint da tool agora inclui `models.py`, `returns.py` e `statistics.py`.
- Testes FQ2.1: 18 testes diretos, incluindo 500 caminhos sintéticos/property checks e equivalência com helpers legacy.
- Bateria local completa sem PostgreSQL após FQ2.1: 263 passed, 16 skipped, 355 DB-deselected, 0 failed.

## FQ2.2 implementado no working copy — Risk Engine

- Criado `app/market/analytics/risk.py`, puro e sem I/O/policy/LLM.
- Volatilidade anualizada preserva `statistics.stdev` amostral × raiz da base explícita.
- Rolling volatility é datada no fim da janela e não faz padding/interpolação.
- Downside deviation usa `sqrt(mean(min(r-target,0)^2))` em todas as observações; target e anualização são explícitos.
- Drawdown possui série detalhada, maximum drawdown e episódio com pico/fundo/recuperação.
- Duração/recovery são medidas em intervalos observados; calendário não entra no engine.
- `quant.retorno_volatilidade` 1.0.3 já usa Risk Engine para volatilidade e maximum drawdown; golden legacy continua idêntico.
- Fingerprint da tool inclui `risk.py`.
- Testes FQ2.2: 17 diretos; property/compatibility inclui 500 caminhos de drawdown e 750+750 comparações com fórmulas legacy.
- Bateria local ampla após FQ2.2: 280 passed, 16 skipped, 355 DB-deselected, 0 failed.

## FQ2.3 implementado no working copy — Dependence Engine

- Criado `app/market/analytics/dependence.py`, puro e sem I/O/policy/LLM.
- Pearson preserva `statistics.correlation` no domínio normal e retorna `None` para amostra curta/série constante.
- Spearman usa ranks médios em empates e Pearson sobre ranks.
- `align_returns` faz interseção de datas sem padding e suporta lag assinado em observações comuns: positivo = X antecede Y; negativo = Y antecede X.
- Cada par preserva `x_date`, `y_date` e `as_of_date=max(...)` para a defasagem não esconder temporalidade.
- Rolling dependence usa número de pares alinhados, sem interpolação; janela constante retorna coeficiente `None`.
- Up/down-market condiciona pelo retorno da série de mercado após alinhamento; retorno exatamente no threshold é neutro/excluído.
- `quant.correlacao` 1.0.2 já usa Returns + Dependence Core, preservando schema/output/golden legacy.
- Fingerprint da tool inclui `models.py`, `returns.py` e `dependence.py`.
- Testes FQ2.3: 14 diretos; 750 equivalências Pearson+lag legacy; 250 simetrias de lag assinado; golden de `quant.correlacao` idêntico.
- Bateria local ampla após FQ2.3: 294 passed, 16 skipped, 355 DB-deselected, 0 failed.

**FQ2 base fechado no working copy:** `returns`, `statistics`, `risk` e `dependence`. `event_study` permanece na FQ4 (relações econômicas), não é pré-requisito para abrir FQ3.

## Próximos passos imediatos

1. Executar `.github/workflows/verify.yml` com PostgreSQL 18 para fechar os gates FQ1/FQ3 e executar também os testes DB do novo código.
2. Rodar `tools sync --check`/sync e a governança do prompt planner para ativar o cutover FQ3 em produção.
3. Manter `quant.analise_condicional` em shadow até o primeiro run PostgreSQL verde; depois promover com patch semver + planner/eval próprios.
4. FQ4.2 foundation já congelou o envelope de estimativa/incerteza. O próximo design de `quant.sensibilidade` deve definir variável resposta/driver, transformação, método de regressão/covariância, unidade do coeficiente e amostra mínima sobre esse contrato, sem reutilizar `Evidencia.metricas` de forma ad hoc.
5. Storage histórico, prioridade de múltiplas fontes e verdadeiro vintage PIT continuam decisões de infraestrutura independentes.

Plano detalhado: `.ai/ANALISTA_MARKET_PLAN.md`.

## Checkpoint de testes — 2026-09-21

- suíte sem fixture `db`: 243 passed, 16 skipped, 355 deselected; nenhuma falha;
- 14 dos skips pertencem a F16 e dependem de catálogo lido do PostgreSQL durante a coleta; os outros 2 são testes opt-in de rede/provedor;
- alvo crítico FQ1/F22/F5 sem banco: 41 passed, 26 DB deselected;
- fuzz/property checks adicionais: 20.000 janelas de cutoff, 5.000 alinhamentos, 5.000 cenários de quality e 3.000 séries de preço + edge cases, todos verdes;
- `compileall`/AST: 175 arquivos Python válidos;
- grafo Alembic: 61 revisions, head único `0061_acervo_de_mercado`, sem parent ausente e nenhum revision id > 32;
- registry: 24 tools, sem código duplicado, sem source dependency inexistente e hashes compostos válidos;
- achado corrigido pelos testes: `STRICT_POINT_IN_TIME` era uma promessa excessiva para preços/índices sem vintage/availability. Renomeado para `OBSERVATION_DATE_CUTOFF`; adjusted close segue explicitamente retrospectivo.

## Gate de integração automatizado — 2026-09-21

- Criado `.github/workflows/verify.yml`, separado do deploy, para `pull_request` e `workflow_dispatch`.
- O job sobe PostgreSQL 18 descartável, cria `.env` somente local, aplica migrations do zero, prepara seeds/tools/policies/prompts, executa validador, regras SQL sob admin e `plexo_service`, gate FQ1/F5/F22, pytest completo e checks locais de drift.
- O workflow não usa segredos de produção, banco remoto, EC2 nem comando de deploy.
- `tests/test_fq1_ci_verify.py` protege essa separação como memória executável.
- Bateria local após o workflow: 245 passed, 16 skipped, 355 DB-deselected, 0 failed.
- O único gate não executável neste runtime continua sendo o bloco PostgreSQL real; agora existe caminho CI isolado e repetível para executá-lo antes de merge.

## FQ3.1 implementado — canonical `quant.risco_retorno` em shadow mode

- `dados.serie_precos` 1.0.2 não promete mais point-in-time/vintage: o contrato descreve cutoff pela
  data da observação e explicita a limitação contra backfills/revisões.
- Nova `quant.risco_retorno` 1.0.0 registrada, auditável e `exposed_to_llm=False`.
- Default canônico: `adjusted_close`, sempre com `retrospective_as_known_now`.
- Alternativa explícita: `raw_close`, sempre com `observation_date_cutoff`.
- `temporal_semantics` é derivada deterministicamente da base, não escolhida pela LLM.
- Tool usa `ResolvedMarketSeries` diretamente e não volta ao adapter `Serie` legacy.
- Output compacto: período + basis/semântica + retorno acumulado/anualizado + volatilidade + máximo
  drawdown + episódio de drawdown + Evidencia; nenhuma série inteira no payload.
- Distinção nova: instrumento desconhecido vs. conhecido fora da cobertura.
- FQ3.1: 12 testes específicos verdes; bateria sem PostgreSQL após a mudança: 306 passed,
  16 skipped, 355 DB-deselected, 0 failed.
- Registry atual: 25 tools registradas, 24 expostas, 1 shadow (`quant.risco_retorno`).

### Próximo passo exato
FQ3.2: desenhar `quant.dependencia` shadow sobre Returns + Dependence Core. Só depois fazer FQ3.3
(cutover das duas canônicas, ocultação das duas legacy e atualização de planner/blocos/evals).


## FQ3.2 + FQ3.3 concluídos no código — dependência canônica e cutover

- Criada `quant.dependencia` canônica, sobre Returns + Dependence Core, com Pearson/Spearman, lag assinado e ativo×ativo/ativo×índice.
- Contrato inicial permanece compacto: rolling/up-down-market continuam internos para tools especializadas do FQ4.
- `price_basis` é explícito para ativos; default `adjusted_close`. Índices/taxas usam `observation_date_cutoff` sem price basis.
- Regra `price_basis -> temporal_semantics` foi centralizada em `app/market/series.py`; nenhuma tool canônica depende da outra.
- Cutover FQ3.3 aplicado no código:
  - `quant.risco_retorno` `1.0.1`, `exposed_to_llm=True`;
  - `quant.dependencia` `1.0.1`, `exposed_to_llm=True`;
  - `quant.retorno_volatilidade` `1.0.4`, `exposed_to_llm=False`;
  - `quant.correlacao` `1.0.3`, `exposed_to_llm=False`.
- Planner, evals, Research tests e blocos usam as canônicas para novas execuções; mapeadores legacy continuam para replay.
- Registry após cutover: 26 tools registradas, códigos únicos e fingerprints válidos; catálogo visível do Analista usa somente as canônicas entre os pares migrados.
- Regressão local sem PostgreSQL: 324 passed, 16 skipped, 355 DB-deselected, 0 failed.
- **Importante:** o cutover está completo no código, não em produção. PostgreSQL CI, `tools sync` e sync/aprovação do prompt planner ainda são gates obrigatórios antes de merge/deploy/ativação.

### Próximo passo exato
Executar os gates DB/sync do FQ3.3. Depois abrir FQ4 (`quant.analise_condicional`, `quant.sensibilidade`, `quant.regimes`, `quant.event_study` v2), sem reabrir o Quant Core base.


## FQ4.1 implementado em shadow — `quant.analise_condicional`

- Criado `app/market/analytics/conditional.py` como engine puro.
- A condicionante define os intervalos; o ativo-resposta é medido no mesmo intervalo com último preço em ou antes de cada endpoint, sem look-ahead.
- Ativo/índice em pontos condiciona por retorno simples; taxa/percentual condiciona por mudança do nível, evitando confundir carry positivo com alta da taxa.
- O retorno da resposta é simples e diretamente interpretável em percentual; não herda log-return da policy para esta estatística descritiva.
- O engine separa alta/queda/neutro e compara amostra condicional contra a base de todos os intervalos válidos.
- Amostra curta mantém métricas calculáveis, mas `Evidencia.suficiente=false` + `serie_curta`; ausência de eventos usa `sem_eventos_condicao`.
- Criada `quant.analise_condicional` 1.0.0 com `exposed_to_llm=False`; output compacto não envia pares/séries para a LLM.
- Bloco determinístico específico foi adicionado e mostra amostras pequenas com warning em vez de apagar números.
- Registry: 27 tools registradas; catálogo Analista continua com 8 visíveis porque a nova tool está shadow.
- Testes FQ4.1: 19 verdes, incluindo 400 cenários sintéticos/property checks e gates de stale endpoint/overlap; regressão ampla sem PostgreSQL: 343 passed, 16 skipped, 355 DB-deselected, 0 failed.
- Produção/planner não foram alterados; promoção depende do gate PostgreSQL/sync.


## FQ4.2 foundation implementada — estimativas estatísticas estruturadas

- Criado `app/market/analytics/estimates.py` com `ConfidenceInterval` e `MetricEstimate`, ambos imutáveis, `extra=forbid` e sem NaN/inf.
- `MetricEstimate` carrega estimate, unidade, n, erro-padrão, CI, método e warnings; estimate indefinido exige warning e não pode carregar SE/CI fictícios.
- O contrato não inclui `p_value` nem booleano `significant`; significância não será inferida pelo envelope.
- Criado `app/tools/analista/evidencia_estatistica.py` com `EvidenciaEstatistica(Evidencia)`; o `Evidencia` base ficou intacto para preservar JSON/goldens legacy.
- `analysis._finding_quantitativo` inclui `estimativas` somente quando a evidência especializada possui valores, preservando findings antigos.
- `estimates.py` e `evidencia_estatistica.py` foram isolados de `analytics/models.py` e `_comum.py` porque esses arquivos participam de fingerprints existentes. Comparação FQ4.1 vs FQ4.2 confirmou 27/27 tool specs com semver/exposição/source SHA idênticos.
- 13 testes específicos do contrato passaram; FQ4.1 + foundation: 32 testes.
- Regressão ampla sem PostgreSQL após a etapa: 356 passed, 16 skipped, 355 DB-deselected, 0 failed.
- Nenhuma regressão/`quant.sensibilidade` foi implementada nesta etapa; próximo passo é design econométrico explícito.

## FQ4.2 implementado no working copy — Regression/Sensitivity Engine

- Criado `app/market/analytics/regression.py`: OLS univariada com intercepto e covariance HAC/Newey-West Bartlett com correção finita `n/(n-k)`.
- Bandwidth automático: `floor(4*(n/100)^(2/9))`, limitado a `n-2`; lag sempre medido em observações e devolvido no resultado.
- CI bilateral de 95% por aproximação normal assintótica (`statistics.NormalDist`), sem SciPy/statsmodels e sem p-value/significant.
- Covariance implementada por funções de influência centradas; evita cancelamento catastrófico de `X'X` e dos resíduos quando o driver tem offset muito grande.
- Criado `app/market/analytics/sensitivity.py`: transforma driver e resposta em unidades explícitas, registra min/mediana/max de dias dos intervalos e não remove outliers/imputa dados.
- Driver taxa/percentual usa mudança de nível em p.p.; ativo/índice em pontos usa retorno simples em p.p.; resposta é retorno simples do ativo em p.p. no mesmo intervalo.
- Criada `quant.sensibilidade` 1.0.0 em shadow mode, com `EvidenciaEstatistica`, output compacto e bloco determinístico.
- Amostra com dois pares pode ter slope/intercepto, mas não SE/CI; evidência permanece insuficiente. Driver constante falha fechado com estimate `None`.
- 27 testes novos específicos, incluindo 500 regressões sintéticas, fórmula HAC independente, invariâncias e offset de `1e12`.
- Regressão local ampla: 383 passed, 16 skipped, 355 DB-deselected, 0 failed.
- Registry FQ4.2 foundation → sensibilidade: 27 → 28 tools; 0 mudanças de semver/exposição/SHA nas 27 existentes.

## FQ4.3 implementado no working copy — Regimes Engine

- Criado `app/market/analytics/regimes.py` como engine puro de regimes históricos explícitos.
- Critérios v1: `level` e `direction`; não há clustering, HMM ou threshold otimizado.
- `level` classifica o retorno do intervalo pelo nível do driver no INÍCIO do intervalo; default sem limiar = mediana retrospectiva dos níveis de início dos intervalos válidos.
- `direction` usa retorno para ativo/índice em pontos e mudança de nível para taxa/percentual; limiar default = zero.
- Resposta usa os mesmos intervalos do driver, com as-of backward e `max_dias_defasagem`, sem look-ahead.
- Regimes podem ser não contíguos; v1 não calcula drawdown por regime. Reporta média, mediana, desvio amostral, mínimo/máximo, fração positiva e cobertura por grupo.
- Criada `quant.regimes` 1.0.0 em shadow mode; output compacto, sem pares/séries ponto a ponto.
- Regime de nível em ativo usa a unidade da série de preço (`currency` quando disponível), não o rótulo genérico `pontos`.
- 21 testes específicos/property passaram; property suite inclui 400 translações de regime de nível, 400 simetrias de direção e 300 invariâncias à escala de preço.
- Regressão ampla sem PostgreSQL: 404 passed, 16 skipped, 355 DB-deselected, 0 failed.
- Registry: 29 tools; as 28 anteriores mantiveram semver, exposição e source SHA idênticos; somente `quant.regimes` foi adicionada.
- Promoção para LLM/produção continua bloqueada pelos gates PostgreSQL/sync já pendentes.


## Gate de integração FQ4 preparado — 2026-09-25

- `tests/test_fq4_integration_db.py` prova as quatro shadows pelo executor real em PostgreSQL;
- o E2E cobre sync, policies, market schema/views, MarketSeriesLoader, cálculo, `tool_executions` e cache;
- `.github/workflows/verify.yml` inclui explicitamente o gate FQ4 antes da suíte completa;
- `analista.planner.j2` já contém roteamento FQ4 condicionado à presença das tools no catálogo;
- as quatro FQ4 continuam shadow; não houve promoção local;
- regressão sem DB após o gate: 429 passed / 16 skipped / 357 DB-deselected / 0 failed;
- execução PostgreSQL real permanece pendente porque este runtime não possui servidor/container e DNS externo está bloqueado;
- promoção/cutover está documentado em `.ai/FQ4_INTEGRATION_PROMOTION_PLAN.md`.


## Atualização 2026-09-30 — FQ4 PostgreSQL gate verde

O gate de integração que estava pendente foi executado em PostgreSQL 18 real e descartável no repositório dedicado de validação. Run `36753446081`: migrations, invariantes SQL, FQ1/F5/F22/FQ4 E2E, suíte completa, prompts check e tools sync --check verdes. Suíte completa: 806 passed, 52 skipped, 19 warnings.

As quatro capacidades FQ4 continuam em shadow. O projeto está autorizado tecnicamente a entrar na etapa de promoção controlada, mas nenhuma exposição/cutover foi aplicada ainda.

## Atualização 2026-09-30 — FQ4 promovido em validação

Após o gate PostgreSQL 18 verde, a branch `bootstrap/plexo-project` entrou em promoção controlada:

- `quant.analise_condicional` 1.0.1 exposta;
- `quant.sensibilidade` 1.0.1 exposta;
- `quant.regimes` 1.0.1 exposta;
- `quant.event_study` 2.0.0 agora usa a implementação FQ4.4 sobre MarketSeriesLoader/Quant Core;
- `quant.event_study_v2` não é mais registrado;
- implementação legacy do event study continua preservada para golden/replay;
- mapper de blocos canônico aponta para o contrato v2.

Estado atual: a promoção está aplicada apenas no repositório dedicado de validação e ainda precisa do CI pós-promoção totalmente verde para ser considerada encerrada.

## Fechamento canônico FQ4 — 2026-09-30

Esta seção substitui qualquer frase anterior deste arquivo que ainda trate o CI pós-promoção como pendente.

- `quant.analise_condicional` 1.0.1: pública;
- `quant.sensibilidade` 1.0.1: pública;
- `quant.regimes` 1.0.1: pública;
- `quant.event_study` 2.0.0: implementação canônica FQ4.4 sobre MarketSeriesLoader/Quant Core;
- alias `quant.event_study_v2`: removido do registry;
- replay histórico 1.0.1: preservado;
- Event Study legacy permanece sem decorator para golden/replay;
- run pós-promoção #39 (`36760273363`) verde;
- HEAD documentado `c11cb160743c00d18a06b2fa5689fdb56cd64dff` também passou no run #40 (`36760679156`);
- suíte completa: **806 passed, 52 skipped, 19 warnings**;
- FQ1 + F5 + F22 + FQ4 E2E, `prompts check` e `tools sync --check`: verdes.

**FQ4 está encerrado no repositório de validação.**

Pendências reais passam a ser transversais: destino de integração/produção, storage histórico, prioridade de múltiplas fontes, availability/vintage real e mecanismo de payload/artifacts antes de abrir outra grande família Quant.


## Fechamento FQ5.1–FQ5.4 — Company / Market Analytics — 2026-09-30

Escopo confirmado: Analista permanece focado em **empresa e mercado**. Portfolio Analytics, suitability, `wealth.*` e análise da carteira/cliente ficam fora desta frente.

Tools públicas novas:
- `dados.fundamentos_empresa` 1.0.0 — DFP point-in-time por `availability_date`, unidade/currency e provenance;
- `quant.valor_mercado` 1.0.0 — fechamento bruto, market cap multi-classe, dívida líquida, EV e múltiplos; não produz fair value;
- `quant.cenario_sensibilidade` 1.0.0 — cenário mecânico `slope × choque explícito` reutilizando FQ4.2; não é forecast/causalidade/preço-alvo;
- `quant.dependencia_macro` 1.0.0 — Pearson/Spearman entre ativo e índice/taxa ou FX canônico, incluindo USD/BRL.

Schema/Data Foundation:
- migration nova `0062_fundamentals_units`, sem editar 0061;
- `value_unit`/currency explícitos e chave de vintage com `instrument_id` + `NULLS NOT DISTINCT`;
- `value_unit=raw` é preservado, mas não entra silenciosamente em valuation monetário;
- FX declara `fx_observation_date_cutoff_sem_vintage` porque o schema atual não prova availability/vintage contra backfills.

Planner:
- perguntas compostas são decompostas em medições independentes; o LLM não calcula entre outputs;
- sem magnitude de choque, não inventar 1 p.p.; usar `quant.sensibilidade`;
- market cap/EV/múltiplos nunca são chamados de valor justo.

Gates:
- shadow commit `3611b29a2d39af517eead9b599793b51404fed64`, run #47 `36783804502`: verde;
- promoção `8271df65f4db7dbe945a7defc800f9705ed0c30d`; run #48 detectou apenas gate de catálogo F5 desatualizado;
- correção `14c522cba2ebabaa95e32e6937879be1557b3256`;
- run pós-promoção #49 `36784983441`: **totalmente verde**;
- E2E FQ1/F5/F22/FQ4/FQ5: **74 passed**;
- full suite: **816 passed, 52 skipped, 19 warnings, 0 failed**;
- validador 0/0; invariantes SQL normal + `plexo_service`, `prompts check` e `tools sync --check`: verdes.

FQ4 não foi reaberto.


## Atualização canônica — auditoria arquitetural/capability inventory — 2026-09-30

Antes de abrir nova feature, foi executada uma revisão transversal para impedir duplicação de capacidades já existentes. Documento canônico: `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md`.

Achados principais:
- `quant.dependencia_macro` sobrepõe a orquestração de `quant.dependencia`; a lacuna real que justificou FQ5 foi o adapter de FX, não nova matemática de dependência;
- legacy `quant.correlacao`/`quant.retorno_volatilidade` e Event Study legacy são preservação intencional de replay, não base para features novas;
- `quant.cenario_sensibilidade` é composição válida: reutiliza `quant.sensibilidade` e só aplica choque/preço de cenário deterministicamente;
- Quant Core já contém capacidades ainda não plenamente expostas: rolling vol, downside deviation, drawdown duration/recovery, rolling dependence e up/down-market dependence;
- `market.sector_classification`, `market.index_weights` e `market.yield_curve` já existem no schema, mas ainda não têm consumer Python do Analista;
- matemática de carteira/`market.class_correlations` pertence ao domínio de planejamento e não deve ser confundida com estatística empírica do Analista.

Nova regra canônica: **reuse-before-build**. Antes de nova tool deve ser provado qual é o gap real (fonte, loader, contrato, composição ou matemática). Não criar tools por fonte (`*_macro`, `*_fx`, `*_petroleo`).

Próxima etapa antes de FQ5.5: design de consolidação de factor resolver + dependência, preservando semver/fingerprint/replay e sem reabrir a matemática FQ3/FQ4.

Estado remoto de referência confirmado nesta auditoria: branch `bootstrap/plexo-project`, HEAD `efd27727615cb9fdffa00ac250813798dbbd38e5`; run #50 `36785509026` verde: 74 E2E, 816 passed, 52 skipped, 19 warnings, 0 failed.


## Protocolo de continuidade adotado — 2026-09-30

`.ai/WORKING_PROTOCOL.md` passa a ser referência operacional canônica para impedir dependência de memória de chat. Toda etapa relevante deve atualizar `.ai/` antes de ser considerada encerrada.

Próxima sequência recomendada, ainda sem implementação: design de consolidação de fatores/dependência -> cutover versionado -> retomada de Fundamentals + Valuation.


## Design de consolidação de fatores/dependência — 2026-09-30

Design concluído em `.ai/FACTOR_DEPENDENCY_CONSOLIDATION_DESIGN.md`; implementação ainda não iniciada.

Proposta principal para revisão:
- nova camada compartilhada `FactorRef`/`ResolvedFactor` no domínio de resolução do Analista;
- ativo/índice/FX usam a mesma abstração de resolução, mas cada análise continua escolhendo sua transformação matemática;
- `quant.dependencia` recomendada para 2.0.0 com `serie_b={tipo,codigo}`;
- `quant.dependencia_macro` passa a compatibilidade oculta somente após cutover verde;
- sem big-bang em sensibilidade/condicional/regimes;
- nenhum FQ3/FQ4 engine será alterado.

Estado de referência anterior ao design: commit `fe268e2213a5c8524f7bb4baa852f2a6ecd5739e`; run #52 `36789531777` success.
