# Plexo — Project State

Atualizado canonicamente em: 2026-10-03

> **IMPORTANTE:** este arquivo preserva o histórico incremental. As primeiras seções descrevem estados antigos e não devem ser interpretadas como estado atual.
> Estado canônico:
> - `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
> - `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
> - `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`
>
> Referência: HEAD documental `60b234b4614b3bbbc6890597a9e4a2fb5503f58f`, run #215 `37137581471` success.
>
> O histórico abaixo permanece para auditabilidade.

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


## Fechamento canônico — consolidação de fatores/dependência — 2026-09-30

O design de `.ai/FACTOR_DEPENDENCY_CONSOLIDATION_DESIGN.md` foi implementado e validado.

Estado:
- `quant.dependencia` 2.0.0 pública, com `serie_b` tipo ativo/indice/cambio;
- `quant.dependencia_macro` 1.0.1 oculta, somente compatibilidade;
- replay 1.0.1/1.0.0 preservado em módulos legacy + goldens;
- planner usa somente a dependência canônica, inclusive para USD/BRL;
- nenhuma matemática FQ3/FQ4, migration ou schema foi alterado.

Isolamento: 33 tools antes -> 33 depois; somente dependência e macro mudaram semver/exposição/fingerprint; as outras 31 ficaram inalteradas.

Validação: commit `60bad205666e5cc5c5d0e2b2b8e643f41e2ac322`; run #54 `36793672760` success; 87 E2E; suíte 831 passed, 52 skipped, 19 warnings, 0 failed; validador 0/0; PostgreSQL 18, invariantes, prompts e tools sync verdes.

## FQ5.5 aberto — tendências fundamentais PIT — 2026-09-30

Design canônico: `.ai/FQ5_5_FUNDAMENTAL_TRENDS_DESIGN.md`.

A tranche começa por histórico anual DFP point-in-time, sem ITR e sem migration. Para preservar fingerprints de `dados.fundamentos_empresa` e `quant.valor_mercado`, o histórico será implementado em módulo novo e não alterará `app/market/fundamentals.py`.

Tool proposta: `quant.tendencias_fundamentais` 1.0.0, inicialmente shadow. FQ5.6 peers/setor permanece bloqueado até esta tranche ficar verde.

## FQ5.5 shadow ready — 2026-09-30

Implementação shadow concluída localmente:
- `app/market/fundamental_history.py` — histórico DFP PIT sem alterar `fundamentals.py`;
- `app/market/analytics/fundamental_trends.py` — YoY + margens, sem forecast/CAGR/fair value;
- `quant.tendencias_fundamentais` 1.0.0 registrada com `exposed_to_llm=False`.

Auditoria de registry contra o HEAD verde anterior: 33 -> 34; única adição = `quant.tendencias_fundamentais`; **0 mudanças** de semver/exposição/source SHA nas 33 tools existentes.

Validação local: 5 testes focados iniciais verdes; 29 testes puros relevantes verdes. Testes PostgreSQL não são executáveis neste runtime por ausência de `DATABASE_URL`/servidor; o gate CI PostgreSQL 18 é obrigatório antes de promoção.

## FQ5.5 shadow gate GREEN / promoção candidata — 2026-09-30

Shadow commit: `e863e674d2a5b873d9502faa2915c25a65ddefd6`.
GitHub Actions run #56 / `36795497161`: success.
- gate explícito: 93 passed;
- suíte completa: 837 passed, 52 skipped, 19 warnings, 0 failed;
- migrations PostgreSQL 18, validador, invariantes admin/service, prompts e tools sync: verdes.

Promoção candidata local:
- `quant.tendencias_fundamentais` 1.0.1 pública;
- planner distingue snapshot atual de evolução histórica;
- blocos compactos de resumo + margens;
- catálogo F5 atualizado;
- registry: 34 total, 33 specs anteriores sem qualquer drift.

A tranche ainda não está encerrada até CI pós-promoção verde.


## FQ5.5 encerrado — tendências fundamentais PIT — 2026-09-30

`quant.tendencias_fundamentais` **1.0.1** está pública e FQ5.5 está encerrado.

Contrato: DFP anual point-in-time por `availability_date <= cutoff`, histórico multi-período, YoY apenas com base anterior positiva, margens somente com receita positiva do mesmo período e EBITDA reportado preferido ao derivado. A v1 não inclui ITR/trimestre, CAGR, forecast ou fair value.

O design evitou alterar `app/market/fundamentals.py`; as 33 tools pré-existentes mantiveram semver/exposição/source fingerprint e o catálogo passou a 34 apenas pela nova tool.

Promoção: commit `a8eb2bfeee7c77361fbefffe4d689b4328c70122`; run #57 `36796184892` success; 93 no gate explícito; **838 passed, 52 skipped, 19 warnings, 0 failed**; PostgreSQL 18, validador, invariantes, prompts e tools sync verdes.

Checkpoint: `.ai/checkpoints/2026-09-30_FQ5_5_PROMOTION_GREEN.md`.

Próxima frente: FQ5.6 peers/setor somente após design reuse-before-build e verificação de ingestão/cobertura/temporalidade de `market.sector_classification`.


## FQ5.6 Peers/Setor — design/data audit — 2026-09-30

FQ5.5 permanece GREEN; run documental #58 também passou com 93 no gate e 838 passed, 52 skipped, 19 warnings, 0 failed.

FQ5.6 foi auditado antes de código. O schema `market.sector_classification` existe, mas não há coletor/projetor no repo que o popule. Por isso nenhuma tool de peers foi criada.

Design canônico: `.ai/FQ5_6_PEERS_SECTOR_DESIGN.md`.

Decisão: FQ5.6A primeiro resolve fonte B3 + ingestão + loader PIT + cobertura; FQ5.6B só depois implementa comparáveis. Para novos snapshots, strict PIT usa `ingestion_batches.finished_at` em vez de adicionar migration apenas para availability. Matching é CNPJ -> issuer e dedupe é company-level.


## FQ5.6A1 — source audit + loader setorial shadow — 2026-09-30

Auditoria de fonte registrada em `.ai/FQ5_6A1_B3_SOURCE_AUDIT.md`.

Estado:
- UP2DATA `Empresas Listadas / SummaryData` = contrato oficial estruturado preferido;
- acesso recorrente depende de contratação/autenticação e nenhuma credencial foi assumida;
- `listedCompaniesProxy` não será usado como API estável de produção;
- coletor/parser externo continua bloqueado até fixture oficial real;
- `app/market/sectors.py` implementado em shadow somente leitura, sem tool pública/migration;
- strict PIT usa lote `succeeded` + `finished_at`;
- dedupe company-level e conflito multi-classe fail-closed;
- target de peers precisa ser ação `is_in_universe`;
- E2E setorial incluído no gate explícito do CI.

Validação local pura: 6 passed; registry 34 -> 34 com zero drift.
Commit shadow: `08bda53fa47eeef576a5fa525260f69d7818d906`.
PostgreSQL real pendente no CI.


## FQ5.6A2a — loader setorial shadow GREEN

O loader PIT setorial foi validado em PostgreSQL 18 no HEAD `e039d771c1b086e0f425d73d6c73822e688d3faa`, run #61 / `36799893075`.

- gate explícito: 98 passed;
- full suite: 849 passed, 52 skipped, 19 warnings, 0 failed;
- validador/invariantes/prompts/tools sync: verdes;
- catálogo permanece com 34 tools inalteradas.

FQ5.6B continua bloqueado: ainda não existe ingestão oficial populando `market.sector_classification` com cobertura medida. O próximo desbloqueio exige fixture real oficial B3/UP2DATA (ou export oficial equivalente) e então parser + ingestão + coverage gate.


## FQ5.6A2 — ingestão setorial semântica shadow — 2026-09-30

Amostra pública oficial do canal Empresas Listadas foi localizada (`Listed_Companies.zip`), mas os bytes não puderam ser materializados neste runtime. O parser físico continua bloqueado; não foi inferido layout a partir de terceiros nem do catálogo isoladamente.

Implementação shadow criada em `app/market/sector_ingest.py`:
- contrato semântico `SectorSourceRecord`;
- lote idempotente via `market.ingestion_batches`;
- matching estrito CNPJ -> issuer;
- expansão para todas as classes `acao`;
- append-only com conflito fail-closed;
- relatório de ingestão;
- coverage PIT por nível explícito, sem limiar inventado.

Nenhuma migration, tool, engine Quant ou contrato público foi alterado. Próximo gate: CI PostgreSQL 18 do shadow. Parser e coverage real continuam dependentes de bytes oficiais da B3.


## FQ5.6A2 — shadow GREEN — 2026-09-30

A fundação semântica de ingestão setorial está validada em PostgreSQL 18.

Prova:
- código: `36ffa05f9cbacd51c04b7887f74be7036c972489`;
- run #63 / `36801883060`: success;
- gate explícito: 103 passed;
- suíte: 861 passed, 52 skipped, 19 warnings, 0 failed;
- prompts/tools sync verdes e catálogo inalterado.

Checkpoint: `.ai/checkpoints/2026-09-30_FQ5_6A2_SECTOR_INGEST_SHADOW_GREEN.md`.

A camada aceita registros semânticos validados e não depende do layout UP2DATA. O parser físico continua bloqueado até bytes oficiais reais; portanto ainda não há coverage real e FQ5.6B peers permanece bloqueado.


## Auditoria Economatica — 2026-10-01

Foram auditados os dois ZIPs fornecidos pelo usuário. Eles são úteis como fonte auxiliar, especialmente para cobertura atual de setor/subsetor e validação de fundamentos/múltiplos, mas não substituem o contrato B3/CVM.

Achado crítico: os workbooks anuais não são snapshots históricos de cadastro/setor; arquivo 2009 contém tickers modernos. Não retrodatá-los.

Nenhuma ingestão ou tool foi alterada nesta etapa. Documento canônico: `.ai/ECONOMATICA_DATA_AUDIT_2026-10-01.md`.


## FQ5.6 Economatica auxiliar — design — 2026-10-01

Integração auxiliar autorizada em shadow: source próprio `economatica`, setor/subsetor corrente, ticker exato e sem retrodatação. B3 permanece a fonte preferida para contrato oficial/segmento. Nenhuma tool pública será criada nesta etapa.


## FQ5.6 Economatica auxiliar — shadow implementado — 2026-10-01

Implementação candidata adiciona apenas provenance/source, parser XLSX stdlib e ingestão corrente por ticker exato. O parser foi validado localmente no arquivo real 2025 fornecido pelo usuário: 478 ações B3 ativas extraídas. Nenhum raw file foi versionado. Nenhuma tool pública foi criada.


## FQ5.6 Economatica auxiliar — shadow GREEN — 2026-10-01

A integração auxiliar Economatica está GREEN em shadow. Parser validado contra o export real do usuário (478 ações B3 ativas), migration 0063, ingestão corrente por ticker exato e CI PostgreSQL 18 concluídos.

Run #71 `36887239117`: 108 gate; 866 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes; 34 tools sem drift.

Nenhuma tool pública foi criada. FQ5.6B continua bloqueada até coverage real/dry-run e decisão explícita de source policy.

## FQ5.6 — coverage dry-run aberto — 2026-10-01

Próxima tranche: medir Economatica × catálogo Plexo sem escrita. O relatório será company-level por issuer e distinguirá ticker ausente, ticker sem issuer e issuer fora do universo. Resultados do seed CI não serão confundidos com produção.

## FQ5.6 coverage dry-run — shadow implementado — 2026-10-01

Implementado módulo read-only de coverage Economatica × catálogo Plexo e CLI operacional. O parser real do arquivo 2025 continua produzindo 478 ações B3 ativas, com setor/subsetor preenchidos. O CLI força transação read-only e não abre ingestion batch. Coverage de produção ainda não foi medida.

## FQ5.6 coverage dry-run — infraestrutura GREEN — 2026-10-01

Dry-run read-only concluído e validado. Commit af58906642665056e3b244fe21a03629d4f7339a; run #75 36943721475 success; gate 110 passed; suíte 868 passed, 52 skipped, 19 warnings, 0 failed; 34 tools inalteradas.

O export Economatica 2025 tem 478 ações B3 ativas, todas com setor/subsetor. Coverage real contra o catálogo de produção ainda não foi medida porque o CI usa seed reduzido e esta sessão não possui acesso ao banco Aiven. FQ5.6B permanece bloqueada.

## FQ5.6A — fonte oficial B3 GREEN — 2026-10-01

O arquivo oficial B3 foi materializado e integrado em shadow. Parser real: 373 registros, 0 duplicatas/conflitos. Adapter company code -> único issuer/CNPJ reutiliza `ingest_sector_records`.

Run #81 `36949418008`: 116 gate; 874 passed, 52 skipped, 19 warnings, 0 failed; PostgreSQL 18/invariantes/prompts/tools sync verdes; 34 tools inalteradas.

FQ5.6B está liberada apenas para **shadow** nos níveis subsetor/setor. Promoção pública segue dependente de coverage real.


## FQ5.6B — peers shadow GREEN — 2026-10-01

quant.comparaveis_setor 1.0.0 está registrada e oculta do LLM. Subsetor é default; setor é opt-in.

Run #93 (36950608900): 118 gate; 876 passed, 52 skipped, 19 warnings, 0 failed; PostgreSQL 18, invariantes, prompts e tools sync verdes.

Registry: 35 tools; única adição é quant.comparaveis_setor shadow. As 34 anteriores não tiveram semver/exposição alterados.

Run #92 falhou somente por hash inválido no fixture e foi corrigido sem mudança de domínio.

Promoção pública segue bloqueada por coverage real e performance.


## FQ5.6B — peers shadow GREEN — 2026-10-01

quant.comparaveis_setor 1.0.0 está registrada e oculta do LLM. Subsetor é default; setor é opt-in.

Run #93 (36950608900): 118 gate; 876 passed, 52 skipped, 19 warnings, 0 failed; PostgreSQL 18, invariantes, prompts e tools sync verdes.

Registry: 35 tools; única adição é quant.comparaveis_setor shadow. As 34 anteriores não tiveram semver/exposição alterados.

Run #92 falhou somente por hash inválido no fixture e foi corrigido sem mudança de domínio.

Promoção pública segue bloqueada por coverage real e performance.


## FQ5.6 — identidade issuer é o gate atual — 2026-10-02

Fonte B3 oficial e `quant.comparaveis_setor` shadow já estão GREEN. O bloqueio estrutural atual foi localizado: `tools/projetar_acervo.py` projeta instruments mas não issuers/issuer_id. Design canônico: `.ai/FQ5_6_ISSUER_IDENTITY_BRIDGE_DESIGN.md`.


## FQ5.6 — issuer bridge GREEN / universo ainda pendente — 2026-10-02

O bridge company-level foi encerrado no commit `4d7f17f9478f7e958e86cf8f15fac3b7f46033a8`, run #113 `37062697600`: 120 gate; 878 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes; 35 tools inalteradas.

O projetor agora consegue criar/reutilizar issuers para ações correntes por raiz B3 e a ingestão setorial oficial persiste por `issuer_id` sem exigir CNPJ artificial.

Próximo gate estrutural: o acervo ainda não projeta `is_in_universe`. Design canônico: `.ai/FQ5_6_UNIVERSE_POLICY_DESIGN.md`. Recomendação: carteira vigente IBrA B3 -> `market.index_weights` -> projeção auditável do universo.


## FQ5.6 — fonte IBrA atual materializada — 2026-10-02

Três arquivos oficiais B3 de índices foram auditados. O CSV diário IBrA de 02/10/2026 é a fonte canônica do universo atual: 148 componentes e pesos fechando em 100%. Os outros dois arquivos confirmam exatamente os mesmos 148 membros.

Cross-check com classificação B3: 146/148 tickers e 142/144 company codes têm setor/subsetor; gaps `RIAA3` e `SAUD3` permanecem explícitos.

Próxima implementação: migration 0064 + parser/ingestão IBrA + projeção atual de `is_in_universe`. Sem histórico inventado.


## FQ5.6 — IBrA universe shadow candidate — 2026-10-02

Implementação candidata publicada: migration 0064 registra `ibra`; `app/market/b3_index_source.py` parseia o CSV diário B3; `app/market/index_portfolios.py` ingere `market.index_weights` somente com matching exato completo e projeta `is_in_universe` apenas para ações. O arquivo real foi validado localmente em 148 componentes, 100,000% de peso, 107.192.487.383 de quantidade teórica e referência 2026-10-02. Nenhuma tool pública foi alterada. Aguardar CI PostgreSQL 18.


## FQ5.6 — IBrA universe GREEN — 2026-10-02

O universo operacional atual de ações está implementado sobre a carteira oficial IBrA de 02/10/2026. Run #131 `37067155192` success: 124 gate; **882 passed, 52 skipped, 19 warnings, 0 failed**; prompts/tools sync verdes; 35 tools inalteradas.

A fonte atual tem 148 componentes. Cross-check setorial B3: 146/148 tickers classificados; gaps RIAA3/SAUD3. O snapshot não cria histórico retroativo.

Checkpoint: `.ai/checkpoints/2026-10-02_FQ5_6_IBRA_UNIVERSE_GREEN.md`.

Próximo gate: benchmark performance/payload de `quant.comparaveis_setor`.


## FQ5.6 — benchmark de peers aberto — 2026-10-02

IBrA universe está GREEN. O próximo e último gate técnico antes da preparação de promoção é medir performance/payload de `quant.comparaveis_setor` shadow. Design: `.ai/FQ5_6_PEERS_PERFORMANCE_BENCHMARK.md`.


## FQ5.6 — benchmark baseline instrumentado — 2026-10-02

Adicionado benchmark PostgreSQL 18 de `quant.comparaveis_setor` para 2/8/20 peers, medindo query count, latência de preparo/cálculo, resolved bytes e output bytes. Ainda não houve otimização; a intenção é observar o custo real primeiro.


## FQ5.6 — benchmark baseline confirmou N+1 — 2026-10-02

Run #145 mediu 38/98/218 queries para 2/8/20 peers, com output estável em ~4 KB. O custo cresce como 18 + 10×N; o cálculo puro é barato. Decisão: criar batch loader isolado antes de promoção, reutilizando engines existentes e preservando as outras tools.


## FQ5.6 — peer batch loader shadow candidate — 2026-10-03

Após baseline #145 confirmar N+1 material, foi implementado `app/market/peer_company_metrics.py`. O batch carrega catálogo/classes, fallback de CNPJ, DFP PIT e preços em lote; depois reutiliza `FundamentalsLoader` e `FundamentalHistoryLoader` em memória. `quant.comparaveis_setor` continua 1.0.0 oculta. Foi adicionado E2E de equivalência resolved+output contra `quant.valor_mercado` e `quant.tendencias_fundamentais`. Aguardar CI antes de considerar GREEN.


## FQ5.6 — performance GREEN / promoção candidata — 2026-10-03

Batch loader validado no run #157 `37132733373`: gate explícito 125 passed; suíte completa 886 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes. Benchmark pós-otimização: 10/10/10 queries em 2/8/20 peers, contra 38/98/218 no baseline #145. Output público permaneceu ~4 KB e equivalência resolved/output contra as tools canônicas passou.

Promoção candidata publicada: `quant.comparaveis_setor` 1.0.1 pública, planner com comparação descritiva e bloco compacto. Aguardar CI pós-promoção antes de considerar FQ5.6 encerrada.


## FQ5.6 encerrada — comparáveis por setor — 2026-10-03

`quant.comparaveis_setor` **1.0.1** está pública. Fonte setorial B3 e universo atual IBrA estão GREEN; coverage cruzada atual = 146/148 tickers e 142/144 company codes, com gaps RIAA3/SAUD3 explícitos.

Performance final: 10 queries constantes para 2/8/20 peers; output ~4 KB. Run #170 `37133499914`: 128 gate; 889 passed, 52 skipped, 19 warnings, 0 failed; PostgreSQL 18, prompts e tools sync verdes.

Checkpoint: `.ai/checkpoints/2026-10-03_FQ5_6_PEERS_PROMOTION_GREEN.md`.


## FQ5.7 aberta — fundação de curva de juros — 2026-10-03

Após FQ5.6 encerrada, nova auditoria reuse-before-build confirmou que `market.yield_curve` e source `anbima` já existem, mas não há consumer Python. A ANBIMA documenta ETTJ diária com vértices em d.u. e taxas prefixada/IPCA/inflação implícita. Design: `.ai/FQ5_7_YIELD_CURVE_DESIGN.md`.

Primeira tranche é somente fundação shadow (ingestão semântica + loader PIT), sem tool pública/OAuth/fórmula nova.


## FQ5.7 — curva de juros foundation shadow candidate — 2026-10-03

Implementada a fundação shadow sobre o schema existente `market.yield_curve`, sem migration e sem tool nova. `app/market/yield_curve_ingest.py` expande vértices ANBIMA para `ettj_pre`, `ettj_ipca` e `inflacao_implicita`; `app/market/yield_curves.py` resolve curvas PIT por `ingestion_batches.finished_at`. Taxas são normalizadas à precisão `numeric(12,6)` antes do gate append-only. Testes puros e PostgreSQL foram adicionados ao gate explícito. Aguardar CI PostgreSQL 18 antes de considerar GREEN.


## FQ5.7 — curva de juros foundation GREEN — 2026-10-03

A fundação de curva ANBIMA está GREEN em shadow, sem tool pública. Commit validado `bbb0ae0be7c01ffbd693c441188bd7363ca3d0d5`; run #192 / `37135247818` success; gate 135 passed; suíte 896 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes; 35 tools inalteradas.

`yield_curve_ingest.py` faz ingestão semântica append-only; `yield_curves.py` resolve latest/reference_date com strict PIT por `ingestion_batches.finished_at`. Não há interpolação, slope, DV01, cenário de curva ou adapter HTTP/OAuth. Próximo gate = payload real ANBIMA/export oficial equivalente + auditoria de cobertura histórica.


## FQ5.7 — auditoria de fonte pública ANBIMA — 2026-10-03

Após foundation GREEN, a página pública oficial de fechamento foi auditada. Snapshot 02/10/2026 observado com 65 vértices IPCA e 19 PRE/inflação implícita. A UI informa últimos cinco dias úteis e oferece XLS/CSV/TXT/XML. Nenhum arquivo ANBIMA/ETTJ existe entre os anexos atuais do usuário. Como os bytes do download não foram materializados nesta sessão, adapter físico permanece bloqueado; não haverá scraper HTML de produção.


## SNAPSHOT CANÔNICO ATUAL — 2026-10-03

Fonte de verdade: `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`.

- código funcional validado: `c3d7cc95f6ef896a5463397b6a323a0325f3c9f0`;
- run #202 / `37135725129`: success;
- gate explícito: 135 passed;
- suíte: 896 passed, 52 skipped, 19 warnings, 0 failed;
- benchmark peers: 10/10/10 queries para 2/8/20;
- prompts/tools sync verdes;
- 35 tools registradas; 32 expostas, 3 ocultas;
- FQ5.6 comparáveis está pública/encerrada;
- FQ5.7 yield-curve foundation está GREEN sem tool pública;
- bloqueio atual = bytes oficiais ANBIMA para adapter físico;
- Portfolio Analytics/cliente continua fora desta frente.

Seções históricas deste arquivo registram evolução e podem conter estados já supersedidos. Não reabrir itens sem conferir checkpoints posteriores.


## HANDOFF FINAL PARA NOVO CHAT — 2026-10-03

Estado canônico funcional:
- FQ0.5–FQ4 encerrados;
- FQ5.1–FQ5.6 encerrados;
- `quant.tendencias_fundamentais` 1.0.1 pública/GREEN;
- `quant.comparaveis_setor` 1.0.1 pública/GREEN;
- peers otimizados para 10/10/10 queries em 2/8/20;
- FQ5.7 yield-curve foundation GREEN/shadow/sem tool pública;
- próximo gate real = payload físico oficial ANBIMA -> parser/fixture -> coverage histórica -> design client-facing.

Base revalidada pré-handoff: `f568d1dd2a228216537a600debd7c83a569aeb27`, run #216 `37139839922` success: 135 directed; 896 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes.

Documentos mestres:
- `.ai/NEXT_CHAT_HANDOFF_FINAL.md`;
- `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`;
- `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`;
- `.ai/NEW_CHAT_PROMPT_2026-10-03.md`.

Seções anteriores deste arquivo são histórico e podem conter estados intermediários supersedidos.


## FQ5.7 source gate GREEN / first capability shadow — 2026-10-03
O payload físico oficial ANBIMA foi materializado e congelado (`CurvaZero_.csv`, 2.899 bytes, SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`). Parser físico fail-closed criado. Cobertura do snapshot 02/10/2026: 65 vértices IPCA, 19 PRE e 19 inflação implícita. A superfície pública declara últimos cinco dias úteis; não assumir histórico ilimitado.

`reuse-before-build` mostrou que não há matemática nova necessária. `dados.curva_juros` 1.0.0 foi implementada em shadow sobre `load_yield_curve()`, retornando somente vértices oficiais exatos e provenance. Próximo gate: PostgreSQL 18 + suíte + prompts/tools sync antes de qualquer promoção pública.


## FQ5.7 physical ingest shadow GREEN — run #234
A ponte de bytes oficiais ANBIMA até `market.yield_curve` está fechada e GREEN. `ingest_anbima_yield_curve_csv()` calcula/valida SHA-256, usa o parser físico congelado e delega à ingestão semântica existente. O run #234 (`37145970504`) passou com 142 directed e 903 passed / 52 skipped / 19 warnings. `dados.curva_juros` continua 1.0.0 shadow. Próxima etapa aprovada: preparação de promoção pública restrita a leitura exata de uma curva/data.


## FQ5.7 promotion candidate — aguardando CI
`dados.curva_juros` foi preparada como 1.0.1 pública, com planner restritivo, bloco determinístico e readiness. Catálogo esperado: 36 tools / 33 públicas / 3 legacy ocultas. Payload da curva IPCA completa fica abaixo de 5 KB. Este estado é candidato até o CI pós-promoção ficar GREEN.


## FQ5.7 dados.curva_juros 1.0.1 pública/GREEN — run #249
A capability de leitura exata da ETTJ oficial está encerrada. `dados.curva_juros` 1.0.1 está pública; catálogo = 36 tools, 33 expostas e 3 ocultas/replay. Fonte física ANBIMA, parser fail-closed, bridge de ingestão e strict PIT estão GREEN. Run #249 (`37146548276`): 145 directed; 906 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync GREEN. Não há FQ5.8 congelada; antes de nova feature, retomar capability audit/roadmap dentro de Company & Market Analytics.

## Composição oficial de índice — shadow candidate — 2026-10-03
Reauditoria pós-FQ5.7 selecionou a leitura PIT de `market.index_weights` como próxima lacuna real. `dados.composicao_indice` 1.0.0 foi implementada em shadow (`exposed_to_llm=False`) sobre loader read-only, sem migration ou matemática nova. Estado ainda candidato até CI PostgreSQL 18.

## Estado atual — composição oficial de índice encerrada
- `dados.composicao_indice` 1.0.1 está pública/GREEN;
- fonte/snapshot: B3/IBrA persistido em `market.index_weights`;
- leitura strict PIT por lote succeeded/finished_at;
- sem inferência de membership histórico, nearest, performance, recomendação ou análise de carteira do cliente;
- HEAD funcional validado: `d431fa91d5e2e39eb6e2ad0db7be2cecab2c7ffa`;
- run #283 / `37153499452`: 153 directed; 914/52/19/0; prompts/tools sync GREEN;
- catálogo atual: 37 total / 34 expostas / 3 ocultas.

Próximo passo: reauditoria de Company & Market Analytics no estado pós-composição e seleção por `reuse-before-build`.

## Estado atual — quant.risco_retorno 1.1.0
- `quant.risco_retorno` **1.1.0** pública/GREEN;
- mantém retorno acumulado/anualizado, vol anualizada e max drawdown;
- adiciona downside deviation anualizada com target periódico 0% explícito;
- duração/recovery do pior episódio permanecem em intervalos observados;
- não há rolling vol pública, Sharpe/Sortino/Calmar, VaR/ES, stress ou forecast;
- HEAD funcional: `687966a22053136000f39542bb7f1feebcde71cf`;
- run #296 / `37154531785`: 175 directed; 918/52/19/0; prompts/tools sync GREEN;
- catálogo: 37 total / 34 expostas / 3 ocultas.

Próximo passo: reauditar lacunas restantes; não assumir automaticamente rolling volatility.

## 2026-10-03 — pós-risco 1.1: rolling volatility selecionada para design

`quant.risco_retorno` 1.1.0 permanece pública/GREEN no run #296. A reauditoria pós-risco classificou rolling volatility como gap de contrato/policy/compactação, pois a matemática já existe no Quant Core.

Design congelado para evolução eventual 1.2.0, sem tool paralela. Nenhum código público foi alterado nesta tranche. O próximo gate é shadow interno não registrado + equivalência 1.1.0; PostgreSQL/cutover ficam para tranche posterior.

Brent permanece bloqueado por source audit oficial. Fair value/reverse DCF permanece bloqueado por premissas governadas. Portfolio Analytics continua fora do escopo.

## 2026-10-03 — rolling volatility shadow interno GREEN

Implementado `app/tools/analista/_risco_retorno_rolling_shadow.py`, sem registro público. O candidato delega integralmente o cálculo-base à `quant.risco_retorno` 1.1.0 e compõe somente a evolução rolling reutilizando o Quant Core.

Commit funcional `bef38e7d2bc44e69bfc931f4d12ee9d7df3a00bd`; run #311 / `37161330785` GREEN: 175 directed; peers 10/10/10; full suite 925 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync GREEN.

A 1.1.0 continua pública, catálogo 37/34/3 e sem cutover. O próximo gate é integração PostgreSQL específica do shadow + adjusted/raw semantics + payload/provenance/readiness. Só depois replay/policy/cutover 1.2.0.

## 2026-10-03 — rolling volatility CI/readiness GREEN

Commit funcional `3794088a0cd9e6a0b0e00ae1e8cb1ca634a3f38d`, run #319 / `37162064025` GREEN.

Fechado:
- integração PostgreSQL específica do shadow;
- adjusted_close -> `retrospective_as_known_now` / `market.v_precos_ajustados`;
- raw_close -> `observation_date_cutoff` / `market.prices`;
- provenance/ingestion batch/policy metadata preservados;
- payload candidato representativo <5 KB;
- golden/replay explícito da `quant.risco_retorno` 1.1.0;
- directed gate 188 passed;
- full suite 931 passed, 52 skipped, 19 warnings, 0 failed;
- prompts/tools sync GREEN.

`quant.risco_retorno` continua 1.1.0 pública e o catálogo segue 37/34/3. Próximo gate: policy governada + cutover único 1.2.0 + planner/bloco/evals.

## 2026-10-03 — quant.risco_retorno 1.2.0 pública/GREEN

`quant.risco_retorno` 1.2.0 está pública e encerrada no run #334 / `37162747600`, commit funcional `3786af082eba5e99e14908340bd3bc649872fbdb`.

Fechado:
- evolução opcional de volatilidade rolling na mesma tool canônica;
- default governado `ANALISE_PARAMS.risco_janela_movel_observacoes=21`;
- janela explícita do usuário prevalece;
- nenhuma conversão automática de dias corridos em observações;
- replay 1.1.0 congelado em módulo legacy + golden;
- adjusted/raw semantics e provenance preservados;
- payload representativo <5 KB;
- planner, bloco e eval atualizados;
- shadow promovido removido do caminho ativo;
- PostgreSQL 18/migrations/invariantes GREEN;
- directed 186 passed;
- full suite 929 passed, 53 skipped, 19 warnings, 0 failed;
- prompts/tools sync GREEN;
- catálogo 37/34/3.

Próximo passo: reabrir o capability audit restante de Company & Market Analytics. Brent continua bloqueado por source audit oficial; fair value/reverse DCF por premissas governadas; Portfolio Analytics segue fora do escopo.

## 2026-10-03 — capability audit pós-risco 1.2 / Brent selecionado

Base funcional segue `quant.risco_retorno` 1.2.0 pública/GREEN, HEAD `bf16dfd561f97e136060d77d80f50092cdc4538d`, run #341 success.

A reauditoria restante selecionou **Brent spot/EIA** como próxima frente, começando por fundação de fonte/série/fator, sem nova tool pública.

Fonte candidata: EIA `RBRTE` — Europe Brent Spot Price FOB, USD/barril, série diária pública desde 1987. O source identity está identificado, mas o gate ainda exige payload machine-readable físico e metadata de copyright/licença específico antes de qualquer implementação.

O repo não possui hoje unidade USD/barril em `market.index_definitions` nem `FactorKind=commodity`; portanto o gap foi reclassificado como fonte + schema/fundação + loader/factor contract. A matemática quantitativa existente será reutilizada.

Fair value/reverse DCF continua bloqueado por matemática contratual e premissas governadas. Portfolio Analytics permanece fora do escopo.

## 2026-10-03 — Codex onboarding handoff criado / CI temporal pendente

Criado `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md` para transferir ao Codex o contexto completo de arquitetura, tools, gates, estado de Brent/fair value e protocolo de auditoria read-only da base grande do usuário.

Baseline funcional confiável permanece HEAD `bf16dfd561f97e136060d77d80f50092cdc4538d`, run #341 GREEN: 186 directed; 929 passed, 53 skipped, 19 warnings, 0 failed; catálogo 37/34/3.

O HEAD documental `2f962de8a2800480bf2800cf41b04d01298cfb05` falhou no run #347 depois da virada UTC para 2026-10-04: 184 directed passed / 2 failed. As falhas são fixtures strict-PIT de yield curve e index composition que ingerem snapshot histórico com `finished_at=clock_timestamp()` e consultam cutoff fixo 2026-10-03. Com o runner em 2026-10-04, o loader corretamente esconde o lote. Não enfraquecer strict PIT; tornar disponibilidade temporal dos testes explícita/determinística antes de adotar novo baseline GREEN.

Para onboarding da base externa: primeira entrega obrigatória do Codex é audit read-only + matriz de mapping/reuse; nenhum adapter/tool deve ser criado antes desse audit.

