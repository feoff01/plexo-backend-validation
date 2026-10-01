# Plexo — Decisions

## 2026-09-19 — Escopo do roadmap do Analista de Mercado

**Decisão:** esta frente cobre somente análise de mercado e instrumentos. Planejamento financeiro pessoal e análise da vida do cliente ficam fora.

**Motivo:** essa frente é estruturada separadamente pelo usuário.

**Consequências:** novas tools/engines desta trilha não devem depender de renda, objetivos, orçamento ou suitability individual.

---

## 2026-09-19 — Preservar infraestrutura, redesenhar catálogo Quant

**Decisão:** preservar registry/executor/cache/gates/Research/evidence/blocos atuais; não preservar nomes de tools do MVP quando uma abstração melhor existir.

**Motivo:** a infraestrutura já implementa corretamente o princípio LLM interpreta / código calcula; o gargalo é capacidade quantitativa e taxonomia.

**Alternativas consideradas:** reconstruir router/registry/executor; apenas incrementar indefinidamente as três tools atuais.

**Consequências:** migração deve ser incremental e compatível com execuções históricas.

---

## 2026-09-19 — Catálogo Quant canônico inicial

**Decisão:** catálogo-alvo inicial:
- `quant.risco_retorno`;
- `quant.dependencia`;
- `quant.analise_condicional`;
- `quant.sensibilidade`;
- `quant.regimes`;
- `quant.event_study`.

**Motivo:** cada tool representa uma intenção analítica distinta, enquanto fórmulas permanecem internas.

**Consequências:** `quant.retorno_volatilidade` e `quant.correlacao` entram em migração legacy; `quant.event_study` permanece como conceito.

---

## 2026-09-19 — Engines internos abaixo das tools

**Decisão:** matemática reutilizável deve viver em engines/módulos internos. Tools são facades que resolvem inputs/policies e adaptam resultados para os contratos atuais.

**Motivo:** reduzir catálogo exposto ao LLM, reutilizar matemática e tornar funções testáveis sem LLM.

**Consequências:** o versionamento da tool precisa cobrir as dependências de implementação compartilhadas.

---

## 2026-09-19 — Fingerprint deve cobrir implementação transitiva declarada

**Decisão:** antes da extração para engines, o `source_sha256` de uma tool deve poder incluir arquivos de implementação declarados, mantendo compatibilidade com ferramentas atuais de arquivo único.

**Motivo:** hoje uma alteração em `_comum.py` ou em um futuro engine pode mudar números sem mudar o hash/semver da tool.

**Alternativas consideradas:** hashear o repositório inteiro (gera bumps por mudanças irrelevantes); confiar apenas no git SHA (não troca `tool_version_id`/cache em mudanças de helper); manter cálculos dentro de cada tool (duplica lógica).

**Consequências:** engines usados por uma tool devem ser declarados no fingerprint; mudança material exige bump de semver da tool afetada.

---

## 2026-09-19 — Legacy deve poder ficar executável sem ser oferecido à LLM

**Decisão:** separar "registrada/executável" de "exposta ao LLM/planner" no `ToolSpec`.

**Motivo:** permitir migração segura de tools antigas sem mantê-las no catálogo de decisão do modelo.

**Consequências:** turno e Research planner filtram tools não expostas; executor continua apto a executar código legacy durante a janela de migração.

---

## 2026-09-19 — Dados corretos antes de econometria

**Decisão:** não lançar regressão/regimes avançados antes de fechar carregamento de série, corporate actions, calendário, cutoff e semântica de preço/retorno.

**Motivo:** evitar precisão estatística sobre série incorreta.

---

## 2026-09-19 — Storage histórico continua decisão aberta

**Decisão:** NÃO decidir PostgreSQL, Parquet+object storage/DuckDB ou outro analytical store sem benchmark.

**Motivo:** o repositório confirma que o acervo normalizado já existe em Parquet e que projetá-lo integralmente para o PostgreSQL hospedado causou incidente operacional.

**Consequências:** expansão para milhares de instrumentos permanece bloqueada até benchmark/custo/operabilidade.

---

## 2026-09-21 — FQ1: base de preço e semântica temporal são dimensões separadas

**Decisão revisada após property/review tests:** `MarketSeriesLoader` separa `PriceBasis` (`raw_close`, `adjusted_close`) de `TemporalSemantics` (`observation_date_cutoff`, `retrospective_as_known_now`).

**Motivo:** `price_date/value_date <= cutoff` impede observações futuras, mas o schema de preços/índices não armazena vintage/availability suficiente para afirmar “strict point-in-time”. Backfills históricos e revisões podem ter sido ingeridos posteriormente. Além disso, `market.v_precos_ajustados` é explicitamente retroativa e `market.corporate_actions` não registra announcement/availability date.

**Consequências:**
- `raw_close + observation_date_cutoff` é permitido, sem alegação de vintage PIT;
- índices/taxas atuais também usam `observation_date_cutoff`; séries macro revisáveis exigirão vintage/availability antes de análises PIT fortes;
- `adjusted_close + retrospective_as_known_now` é permitido e explicitamente rotulado;
- `adjusted_close + observation_date_cutoff` falha fechado com `AdjustedCloseRequiresRetrospective`;
- não existe fallback silencioso de adjusted para raw;
- um futuro `strict_as_known_then` só poderá existir para datasets que consigam provar disponibilidade/vintage;
- `TOTAL_RETURN` não é tratado como uma terceira base de preço neste estágio.

---

## 2026-09-19 — FQ1: um reader desacoplado da fonte física

**Decisão:** engines futuros dependem do contrato `SeriesReader`/`MarketSeriesLoader`, não de SQL direto.

**Motivo:** permitir PostgreSQL hoje e Parquet/object storage depois sem reescrever Risk/Dependence/Conditional engines.

**Consequências:** a primeira implementação é `PostgresSeriesReader`; histórico Parquet continua decisão de infraestrutura separada.

---

## 2026-09-19 — FQ1: calendário oficial somente com cobertura completa

**Decisão:** `market.trading_calendar` só é tratado como fonte canônica de uma janela quando há uma linha para cada data civil da janela (dias úteis e não úteis). Caso contrário, usa-se explicitamente o fallback histórico derivado de preços do universo.

**Motivo:** uma carga parcial do calendário não pode esconder lacunas de negociação.

**Consequências:** o fallback permanece compatível com F5, mas aparece em `SeriesQuality`/`SeriesProvenance` como `calendar_fallback_from_prices`.

---

## 2026-09-21 — PostgreSQL de integração deve rodar em CI isolada antes do merge

**Decisão:** manter um workflow de verificação separado de deploy (`.github/workflows/verify.yml`) para PR/manual, com PostgreSQL 18 descartável e sem segredos de produção.

**Motivo:** o runtime de desenvolvimento desta sessão não possui servidor PostgreSQL/Docker nem acesso de rede ao banco remoto. A suíte DB não pode depender de Aiven para provar FQ1/F5/F22 e não deve exigir push na `main` que potencialmente aciona deploy.

**Consequências:**
- PRs podem executar migrations + invariantes SQL + pytest completo sem tocar produção;
- FQ1 só é considerado integrado quando esse workflow passar;
- `tests/test_fq1_ci_verify.py` falha se o workflow perder Postgres 18/gates críticos ou adquirir referências a segredos/deploy;
- FQ2 não deve ser tratado como liberado para merge até o primeiro run verde desse gate.


## 2026-09-21 — FQ2.1: Quant Core não contém premissas de negócio ocultas

**Decisão:** `app/market/analytics` é uma camada matemática pura. Bases como `periods_per_year` entram como parâmetros; o core não fixa 252/12, não acessa policy e não conhece LLM/banco.

**Motivo:** a mesma matemática deve ser reutilizável e golden-testável em tools diferentes sem copiar premissas do produto para o engine.

**Consequências:** tools resolvem policies em `preparar()` e passam os valores ao core; mudança de engine entra no fingerprint das tools dependentes.

---

## 2026-09-21 — FQ2.1: contratos matemáticos falham fechado

**Decisão:** o Quant Core não propaga NaN/inf nem aceita preço não positivo, datas duplicadas/fora de ordem ou retornos simples abaixo de -100%. Estatística indefinida por falta de amostra devolve `None`, não zero.

**Motivo:** evitar números aparentemente válidos em casos em que a matemática não está definida.

**Consequências:** erros de qualidade/contrato são detectados antes de virar `Evidencia` client-facing.

---

## 2026-09-21 — FQ2.1: desvio-padrão permanece amostral

**Decisão:** volatilidade usa desvio-padrão amostral (`n-1`), preservando a semântica histórica de `statistics.stdev` da tool legacy.

**Motivo:** impedir drift numérico silencioso durante a migração para engines.

**Consequências:** o golden de `quant.retorno_volatilidade` permanece idêntico na migração FQ2.1.

---

## 2026-09-21 — FQ2.2: duração de drawdown é medida em intervalos observados

**Decisão:** o Risk Engine não converte duração de drawdown em dias corridos/pregões. O episódio expõe `time_to_trough_intervals`, `recovery_intervals` e `duration_intervals`.

**Motivo:** o engine matemático não possui calendário de negociação e não deve inventar semântica temporal que pertence à camada de mercado.

**Consequências:** uma futura tool pode converter intervalos para pregões/dias usando `MarketSeriesLoader`/calendário explícito; o core continua reutilizável.

---

## 2026-09-21 — FQ2.2: downside deviation usa todas as observações no denominador

**Decisão:** `downside_deviation` segue `sqrt(mean(min(r-target, 0)^2))`, com todas as observações no denominador. O target é por período e na mesma convenção dos retornos de entrada.

**Motivo:** existem variantes incompatíveis de downside deviation; a fórmula precisa ser explícita antes de uma futura Sortino ratio.

**Consequências:** série sem shortfall retorna `0.0`; amostra vazia retorna `None`; anualização exige `periods_per_year` explícito.

---

## 2026-09-21 — FQ2.2: empate de maximum drawdown preserva o episódio mais antigo

**Decisão:** quando dois episódios têm exatamente a mesma profundidade, `maximum_drawdown_episode` mantém o primeiro cronologicamente. Em picos consecutivos de mesmo nível antes da queda, o pico mais recente inicia o episódio, reduzindo a duração ao período efetivamente underwater.

**Motivo:** comportamento determinístico e semanticamente consistente para duração/recovery.


## 2026-09-21 — FQ2.3: lag é definido sobre observações comuns e preserva ambas as datas

**Decisão:** `lag_observations` é aplicado depois da interseção temporal das duas séries. Lag positivo significa X antecede Y; lag negativo significa Y antecede X. Cada par guarda `x_date`, `y_date` e `as_of_date=max(x_date,y_date)`.

**Motivo:** a implementação legacy já deslocava sobre a sequência de datas comuns; tornar a semântica explícita preserva compatibilidade e evita chamar de “dias/pregões” algo que pode pular lacunas. Guardar as duas datas evita esconder informação temporal em análises lead/lag.

**Consequências:** a tool legacy continua aceitando apenas defasagem >= 0; a futura `quant.dependencia` pode oferecer lag assinado com nomenclatura correta.

---

## 2026-09-21 — FQ2.3: Spearman usa ranks médios em empates

**Decisão:** Spearman = Pearson aplicado a ranks crescentes 1-based; empates recebem rank médio.

**Motivo:** a definição precisa ser determinística e auditável antes de ser exposta em tool pública.

**Consequências:** série/rank constante retorna `None`, nunca zero.

---

## 2026-09-21 — FQ2.3: up/down-market condiciona pelo retorno do mercado após alinhamento

**Decisão:** up-market seleciona pares com `market_return > threshold`; down-market usa `< threshold`; observação exatamente no threshold é neutra e fica fora. O condicionamento ocorre depois de interseção/lag.

**Motivo:** impedir ambiguidade sobre qual série define o regime e evitar classificação silenciosa de retornos zero.

**Consequências:** threshold precisa ser explícito/finito; default matemático é 0.0 no engine, enquanto thresholds de produto futuros podem vir de policy.

---

## 2026-09-21 — Quant Core base fecha no FQ2.3; Event Study permanece em FQ4

**Decisão:** FQ2 base é composto por `returns`, `statistics`, `risk` e `dependence`. A evolução estrutural de `quant.event_study` permanece na FQ4 junto de condicional/sensibilidade/regimes.

**Motivo:** event study é investigação econômica/event-driven, não pré-requisito para as tools canônicas básicas de risco/retorno e dependência. Mantê-lo fora do FQ2 reduz escopo e permite validar primeiro o catálogo canônico.

**Consequências:** próximo bloco após FQ2.3 é FQ3 (`quant.risco_retorno` / `quant.dependencia`), enquanto `quant.event_study` atual continua operando até sua evolução futura.

## 2026-09-21 — FQ3.1: base de preço canônica e migração shadow

**Decisão:** `quant.risco_retorno` usa `adjusted_close` como default canônico para análise histórica
de risco/retorno. `raw_close` só é usado quando explicitamente pedido.

**Mapeamento temporal obrigatório:**
- `adjusted_close` -> `retrospective_as_known_now`;
- `raw_close` -> `observation_date_cutoff`.

A LLM não recebe `temporal_semantics` como parâmetro livre. Isso reduz o schema e impede
combinações semanticamente inválidas.

**Motivo:** retorno/risco econômico não deve interpretar splits/proventos como saltos mecânicos da
cotação. Porém a view ajustada atual é retrospectiva e não prova vintage histórico, então essa
limitação precisa viajar no output/provenance. O fechamento bruto continua útil para trajetória da
cotação e auditoria/compatibilidade legacy.

**Migração:** tools canônicas FQ3 nascem `exposed_to_llm=False`. O cutover de exposição só ocorre
quando `quant.risco_retorno` e `quant.dependencia` estiverem ambos prontos, evitando tools
sobrepostas no catálogo da LLM/Research.


---

## 2026-09-21 — FQ3.2: `quant.dependencia` expõe dependência global, não toda a capacidade do engine

**Decisão:** o contrato canônico inicial expõe Pearson/Spearman e `defasagem_observacoes` assinada. Rolling dependence e up/down-market continuam internos no Dependence Core para análises especializadas do FQ4.

**Motivo:** evitar uma tool “canivete suíço”, reduzir schema/tokens e manter cada tool alinhada a uma intenção analítica completa.

**Consequências:** a LLM recebe um contrato pequeno e auditável; capacidades condicionais/temporais serão expostas por tools próprias.

---

## 2026-09-21 — FQ3.2: semântica de base de preço pertence à Data Foundation, não a uma tool

**Decisão:** `temporal_semantics_for_price_basis()` vive em `app/market/series.py`. `quant.risco_retorno` e `quant.dependencia` dependem dessa regra comum, sem dependência direta entre tools.

**Motivo:** RAW/ADJUSTED e sua semântica temporal são propriedades da série de mercado; acoplar uma tool à outra criaria dependência arquitetural errada e fingerprint indireto difícil de auditar.

**Consequências:** a regra fica centralizada, testável e reutilizável por futuras tools canônicas.

---

## 2026-09-21 — FQ3.3: cutover de catálogo é atômico, legacy permanece runtime-only

**Decisão:** após ambas as canônicas passarem em shadow mode, expor `quant.risco_retorno` e `quant.dependencia` simultaneamente e ocultar `quant.retorno_volatilidade` e `quant.correlacao`. Legacy permanece registrada/executável para replay e auditoria, mas não entra em novos turnos/planos.

**Motivo:** impedir sobreposição semântica no catálogo da LLM e evitar que planner/Research escolham aleatoriamente entre contratos antigos e novos.

**Consequências:** mudanças de exposição recebem patch semver; planner/evals/blocos apontam para códigos canônicos; compiler continua recusando hidden tools em novos planos. O cutover só é considerado ativo em produção após PostgreSQL CI, tool sync e governança do prompt planner.

---

## 2026-09-21 — FQ4.1: a condicionante define o relógio da análise

**Decisão:** cada mudança da série condicionante define um intervalo `[t_(i-1), t_i]`. O retorno do ativo-resposta é medido no mesmo intervalo usando o último preço disponível em ou antes de cada endpoint. Nunca se usa preço posterior para preencher uma data.

**Motivo:** séries macro/taxas podem ser esparsas. Comparar uma mudança mensal com apenas o retorno diário da data final criaria semântica falsa.

**Consequências:** o engine funciona tanto com condicionantes diárias quanto esparsas; intervalos sem dois preços distintos da resposta são descartados de forma explícita.

---

## 2026-09-21 — FQ4.1: taxa/percentual condiciona por mudança de nível, não por carry

**Decisão:** ativo e índice em pontos usam retorno simples como sinal da condição; `taxa_aa`, `taxa_am` e `percentual` usam `nivel_t - nivel_(t-1)`.

**Motivo:** converter Selic 14% a.a. em retorno diário produz carry positivo mesmo quando o nível da taxa caiu. Isso não responde “juros subiram ou caíram?”.

**Consequências:** para taxas a magnitude da condição é reportada em pontos percentuais; para ativos/índices em pontos é reportada como retorno percentual.

---

## 2026-09-21 — FQ4.1: resposta usa retorno simples e análise é descritiva

**Decisão:** o desempenho do ativo no intervalo condicional usa `P_fim/P_inicio - 1`, independentemente do `metodo_retorno` usado em correlação legacy/canônica. O output compara média/mediana/dispersão/taxa positiva contra a base, sem p-value ou linguagem causal.

**Motivo:** retorno simples é diretamente interpretável em percentual para intervalos arbitrários. Inferência e elasticidade pertencem à `quant.sensibilidade`.

---

## 2026-09-21 — FQ4.1: amostra curta não apaga métricas calculáveis

**Decisão:** se existem eventos mas `n_condicional < min_observacoes`, a tool mantém estatísticas matematicamente definidas e marca `Evidencia.suficiente=false` + `serie_curta`. Se não existe evento na direção, usa `sem_eventos_condicao`.

**Motivo:** cortes/altas de taxa podem ser raros; substituir informação observada por `None` em todas as métricas esconderia evidência útil. O warning separa “calculável” de “robusto”.

---

## 2026-09-21 — FQ4.1: primeira tool FQ4 nasce shadow

**Decisão:** `quant.analise_condicional` 1.0.0 fica `exposed_to_llm=False` até o gate PostgreSQL/sync ficar verde.

**Motivo:** FQ3 ainda não foi ativado em produção e esta é a primeira semântica econômica nova do FQ4. Validar em isolamento evita expandir planner/catalog antes da integração real.


## 2026-09-21 — FQ4.2 foundation: estimativas inferenciais não alargam `Evidencia.metricas`

**Decisão:** manter `Evidencia.metricas` como `dict[str, float | None]` para escalares simples e criar `MetricEstimate`/`ConfidenceInterval` + `EvidenciaEstatistica` para resultados inferenciais estruturados.

**Motivo:** transformar `metricas` em `Any` perderia contrato; adicionar `estimativas={}` ao `Evidencia` base mudaria o JSON/goldens de todas as tools existentes sem necessidade.

**Consequências:** tools legacy/descritivas continuam byte/JSON-compatíveis; futuras tools inferenciais podem carregar estimate, unidade, n, SE, CI, método e warnings de forma tipada. `analysis.evidence_findings` inclui `estimativas` somente quando presentes.

---

## 2026-09-21 — FQ4.2 foundation: contratos futuros ficam fora de arquivos já fingerprintados

**Decisão:** `MetricEstimate` vive em `analytics/estimates.py` e `EvidenciaEstatistica` em `analista/evidencia_estatistica.py`, em vez de `analytics/models.py` e `_comum.py`.

**Motivo:** `models.py` e `_comum.py` são `source_dependencies` de várias tools. Acrescentar capacidade futura nesses arquivos mudaria `source_sha256` e exigiria bumps de semver mesmo sem mudança matemática nas tools.

**Consequências:** as 27 tool specs do FQ4.1 mantêm exatamente semver, exposição e source SHA no FQ4.2 foundation. A futura `quant.sensibilidade` deve declarar explicitamente os dois novos arquivos em seu fingerprint.

---

## 2026-09-21 — FQ4.2 foundation: envelope não decide significância

**Decisão:** `MetricEstimate` não possui `p_value` nem `significant`. `estimate=None` nunca vira zero e exige warning; nesse estado SE/CI precisam ser ausentes.

**Motivo:** o envelope deve transportar resultado e incerteza, não decidir sozinho regra de teste, causalidade ou linguagem de significância antes de definirmos o método econométrico.


## 2026-09-21 — FQ4.2 sensibilidade: OLS + HAC/Newey-West

**Decisão:** slope/intercepto são OLS univariados com intercepto; a incerteza usa HAC/Newey-West Bartlett com correção `n/(n-k)`.

**Motivo:** point estimate OLS é simples/auditável; séries temporais podem ter heteroskedasticidade e autocorrelação, então HC1 isolado não é suficiente como default.

**Consequências:** covariance estimator não entra no schema LLM v1; o método e o número de lags ficam explícitos no resultado/evidência.

---

## 2026-09-21 — FQ4.2 sensibilidade: bandwidth e CI auditáveis

**Decisão:** Newey-West usa `L=floor(4*(n/100)^(2/9))`, limitado a `n-2`, em observações; CI padrão é bilateral de 95% por aproximação normal assintótica da stdlib.

**Motivo:** evitar threshold/frequência escondidos e não introduzir SciPy/statsmodels só para a primeira regressão.

**Consequências:** `hac_lags`, `confidence_level` e método aparecem no output; não há p-value/significant nesta versão.

---

## 2026-09-21 — FQ4.2 sensibilidade: sem imputação nem outlier deletion

**Decisão:** intervalos sem endpoints válidos são descartados pelo alinhamento; nenhum missing é imputado e nenhuma observação é winsorizada/trimmed por magnitude.

**Motivo:** regras de outlier e fill alteram a amostra e precisam ser explícitas/versionadas; não devem nascer como heurística silenciosa.

**Consequências:** robustez inicial atua na covariance, não apagando pontos. `n` é sempre a amostra efetivamente usada.

---

## 2026-09-21 — FQ4.2 sensibilidade: influência centrada para estabilidade numérica

**Decisão:** covariance HAC é calculada a partir das funções de influência centradas do slope/intercepto e resíduos em forma centrada, não por inversão bruta de `X'X`.

**Motivo:** testes com offset `1e12` detectaram cancelamento catastrófico na formulação inicial, apesar de o driver não ser constante.

**Consequências:** a regressão preserva slope/SE sob grandes translações de X e continua stdlib-only.

## D-FQ4.3-01 — Regimes v1 são regras explícitas, não clustering oculto
Para `quant.regimes`, a primeira versão usa apenas dois critérios auditáveis: `nivel` e `direcao`. Não usar HMM, clustering ou threshold otimizado implicitamente.

## D-FQ4.3-02 — Regime de nível usa informação do início do intervalo
Ao comparar o retorno da resposta no intervalo [t0,t1], o regime de nível é classificado pelo nível do driver em t0. O nível em t1 não deve classificar retroativamente o retorno iniciado antes dele.

## D-FQ4.3-03 — Mediana automática é retrospectiva e explícita
Se o usuário não fornecer limiar no critério `nivel`, usar a mediana histórica dos níveis de início dos intervalos válidos. Registrar o corte e `threshold_source=sample_median`; não tratar isso como threshold point-in-time de backtest.

## D-FQ4.3-04 — Não calcular drawdown em amostras de regime não contíguas
Retornos selecionados por regime podem vir de intervalos separados no tempo; concatená-los como trajetória criaria drawdown artificial. A v1 reporta estatísticas de distribuição, não drawdown por regime.

## D-FQ4.3-05 — Nível de ativo respeita a price basis e unidade da série
Quando um ativo é driver de regime `nivel`, o nível vem da mesma `price_basis` escolhida para ativos e a unidade reportada vem da série de preço (currency quando disponível). A tool deve explicitar adjusted retrospectivo quando aplicável; não chamar preço ajustado de cotação histórica bruta.

## 2026-09-25 — FQ4.4 Event Study v2

- `quant.event_study` 1.0.1 não foi reescrita diretamente; sua matemática/output foram congelados em `event_study_legacy_1_0_1.py` para replay de `resolved_params` históricos.
- A tool visível legacy recebeu apenas correção de linguagem temporal (`point-in-time` -> cutoff pela data da observação) e patch bump `1.0.1 -> 1.0.2`; cálculo/golden permanecem iguais.
- A nova implementação nasce como `quant.event_study_v2` 1.0.0 shadow. Cutover para o código canônico `quant.event_study` é etapa separada após gates DB/sync.
- Event study deve alinhar NÍVEIS de preço por datas comuns antes de calcular retornos. Alinhar retornos calculados separadamente só pela data final pode juntar intervalos diferentes quando uma série tem lacuna.
- Base default da v2: `adjusted_close` + `retrospective_as_known_now`; `raw_close` é opt-in e usa `observation_date_cutoff`.
- Data efetiva do evento = primeiro retorno sincronizado ativo×benchmark com data >= data civil pedida.
- Janelas v2 são contagens de observações alinhadas; a estimação termina antes do início da janela de evento e nunca sobrepõe o evento.
- Inferência default é `none`. `classic_iid_normal` é opt-in e produz SE/CI do CAR sob hipóteses iid/homoscedásticas, normalidade assintótica e variância estável no evento; sem p-value, sem `significant`, sem causalidade.
- Para market model, `Var(CAR)=sigma²[L + L²/T + (sum(x_evt)-L*xbar_est)²/Sxx_est]`, com `sigma²=SSE/(T-2)`.
- Para market adjusted, `SE(CAR)=sd(resíduos_estimação)*sqrt(L)`.
- A v2 carrega history correctness-first até o cutoff e não materializa calendário; otimização futura deve ser um reader com lookback por contagem de observações, não heurística escondida de dias corridos.

## 2026-09-25 — FQ4 integration: promoção exige E2E PostgreSQL pelo executor real

**Decisão:** nenhuma shadow FQ4 será exposta apenas com unit/property tests. O gate mínimo passa por
PostgreSQL 18, migrations, sync, `MarketSeriesLoader`, `executar_tool()`, `tool_executions` e cache.

**Motivo:** é possível ter matemática correta e integração quebrada em schema/view/gate/versionamento.
O caminho do produto precisa ser provado ponta a ponta.

---

## 2026-09-25 — Planner FQ4 é preparado condicionalmente ao catálogo

**Decisão:** o planner já conhece a semântica de condicional/sensibilidade/regimes, mas só deve usar
cada código quando ele estiver presente em `catalogo_tools`.

**Motivo:** preparar prompt/evals antes do cutover reduz risco operacional sem violar o shadow mode.
`exposed_to_llm=False` continua sendo a fonte de verdade do catálogo.

---

## 2026-09-25 — Cutover do Event Study v2 preserva o código canônico

**Decisão:** `quant.event_study_v2` é alias shadow de validação. Após gate verde, a implementação v2
deve assumir `quant.event_study` com major bump 2.0.0; o alias `_v2` deve ser desativado e o replay
1.0.1 permanece em módulo puro.

**Motivo:** o usuário/planner não deve carregar nomes de migração permanentes e o output v2 é
incompatível o suficiente para justificar major bump.


## 2026-09-30 — CI PostgreSQL verde autoriza promoção, não a executa

**Decisão:** o run verde do gate FQ4 é pré-condição satisfeita para abrir a fase de promoção, mas a exposição das shadows e o cutover de Event Study serão feitos em branch/PR separado.

**Motivo:** separar validação de integração de mudança de catálogo/versionamento torna o cutover reversível e auditável.

**Consequências:** o PR de bootstrap/validação permanece sem mudança de `exposed_to_llm`; semver/exposição serão alterados apenas na promoção controlada.

## 2026-09-30 — FQ4 promovido após gate PostgreSQL real

- O run GitHub Actions 36754171560 passou em PostgreSQL 18 com migrations, FQ1/F5/F22/FQ4 E2E, suíte completa, prompts check e tools sync --check.
- `quant.analise_condicional`, `quant.sensibilidade` e `quant.regimes` foram promovidas com patch bump 1.0.0 -> 1.0.1 e `exposed_to_llm=True`.
- A implementação FQ4.4 de Event Study tornou-se a tool canônica `quant.event_study` 2.0.0.
- O alias temporário `quant.event_study_v2` deixa de ser registrado.
- A implementação antiga de `quant.event_study` permanece como código legacy/golden/replay, sem decorator no catálogo atual.
- O mapper de blocos canônico de `quant.event_study` aponta exclusivamente para o bloco v2.
- O branch de validação continua sendo o único alvo desta promoção; nenhum outro repositório foi tocado.


## 2026-09-30 — FQ5.1–FQ5.4 encerrado; escopo permanece empresa/mercado
**Decisão:** não abrir Portfolio Analytics nem análise da carteira/cliente nesta frente. Próximas expansões são tendências fundamentais, peers/setor, fatores e depois fair value governado.

**Decisão:** fair value só nasce de engine determinístico com forecasts/premissas explícitas e provenance. O planner não pode inventar WACC, ERP, crescimento terminal, múltiplo-alvo ou choque macro.

**Decisão:** `market.fx_rates` sustenta observation-cutoff, mas não deve ser apresentado como vintage PIT perfeito enquanto faltar availability/ingestion provenance suficiente.


## 2026-09-30 — Reuse-before-build é gate arquitetural obrigatório

**Decisão:** antes de criar qualquer nova tabela, engine, cálculo ou tool do Analista, verificar nesta ordem: matemática existente no Quant Core; schema/fonte existente; loader/adapter existente; tool com a mesma intenção; necessidade real de composição determinística.

**Motivo:** a auditoria pós-FQ5 mostrou que `quant.dependencia_macro` resolveu uma lacuna real de FX, mas duplicou interface/orquestração de `quant.dependencia`. O projeto deve distinguir fonte nova de matemática nova.

**Consequências:**
- não criar tool por fonte/fator (`dependencia_fx`, `sensibilidade_macro`, `correlacao_petroleo` etc.);
- novos fatores entram por adapters/resolver compartilhado e reutilizam os engines existentes;
- legacy oculto continua preservado para replay e não deve ser escolhido como base de feature nova;
- uma tool composta só é justificada quando há uma intenção/output determinístico próprio ou quando o DSL não consegue transportar numericamente outputs entre nós; ainda assim deve reutilizar o core existente;
- refactors de módulos presentes em `source_dependencies` exigem planejamento de semver/fingerprint/replay e não podem ocorrer como cleanup silencioso.

## 2026-09-30 — Planning correlations não são market dependence

**Decisão:** `market.class_correlations` e a matemática de `app/engine/simulacao.py` permanecem no domínio de planejamento/portfolio do cliente. Não serão usadas como substituto de correlação empírica do Analista.

**Motivo:** são premissas aprovadas para projeção de carteira, enquanto `app/market/analytics/dependence.py` mede associação observada em séries históricas. Misturar as duas fontes quebraria provenance e semântica.


## 2026-09-30 — .ai é a memória operacional canônica do projeto

**Decisão:** o desenvolvimento não deve depender da memória de chats. Toda decisão, mudança de escopo, implementação relevante, validação/gate e próximo passo aprovado deve ser persistido em `.ai/`.

**Aplicação:** usar `.ai/WORKING_PROTOCOL.md` como protocolo canônico de continuidade. Recomendações ainda não aprovadas devem ser marcadas como propostas, não como decisões executadas.


## 2026-09-30 — Cutover canônico de dependência concluído

**Decisão implementada:** `quant.dependencia` passa a ser a única interface pública canônica de dependência para ativo × ativo, ativo × índice/taxa e ativo × câmbio.

- `quant.dependencia` = **2.0.0**, pública, com `serie_b={tipo,codigo}`;
- `quant.dependencia_macro` = **1.0.1**, executável porém `exposed_to_llm=false`, somente compatibilidade;
- as versões históricas 1.0.1/1.0.0 foram congeladas em módulos legacy para replay;
- `FactorRef`/`ResolvedFactor` compartilham somente resolução/carregamento/provenance;
- nenhum engine FQ3/FQ4, migration ou schema foi alterado;
- sensibilidade, condicional e regimes não foram migrados neste cutover.

Prova: commit `60bad205666e5cc5c5d0e2b2b8e643f41e2ac322`; run #54 `36793672760` success — 87 E2E; 831 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes.

## 2026-09-30 — FQ5.5 usa módulo novo para histórico, sem tocar no foundation fingerprintado

**Decisão:** tendências fundamentais anuais serão implementadas em `app/market/fundamental_history.py`, consumindo `PostgresFundamentalsReader`, sem editar `app/market/fundamentals.py`.

**Motivo:** `fundamentals.py` participa do fingerprint de `dados.fundamentos_empresa` e `quant.valor_mercado`; adicionar um método ali provocaria drift/bump artificial em duas tools já públicas.

**Escopo v1:** somente DFP anual point-in-time. ITR/trimestre fica fora até existir contrato explícito para fluxos acumulados. A tool analítica proposta é `quant.tendencias_fundamentais` 1.0.0; `dados.fundamentos_empresa` continua sendo snapshot.

## 2026-09-30 — Promoção FQ5.5 usa patch bump 1.0.0 shadow -> 1.0.1 pública

**Decisão:** `quant.tendencias_fundamentais` será promovida como 1.0.1, não como 1.0.0.

**Motivo:** alterar `exposed_to_llm` modifica o módulo da tool e, portanto, seu source fingerprint. O patch bump evita reutilizar a mesma semver para dois fontes diferentes. A 1.0.0 foi somente shadow de validação; a 1.0.1 é a primeira versão pública proposta.


## 2026-09-30 — FQ5.5 canônico: tendência anual PIT, não forecast

**Decisão implementada:** `quant.tendencias_fundamentais` 1.0.1 é a interface pública canônica para evolução histórica de fundamentos da companhia.

- usa somente DFP anual na v1;
- seleciona o vintage conhecido no cutoff por `availability_date`;
- crescimento percentual só é calculado com base anterior positiva;
- margens exigem receita positiva do mesmo `reference_date`;
- EBITDA reportado tem precedência sobre derivado;
- não expõe ITR/trimestre, CAGR, forecast, fair value ou `shares_outstanding` company-level;
- `dados.fundamentos_empresa` continua sendo snapshot atual, não histórico.

**Motivo:** evitar interpretação contábil silenciosa de fluxos trimestrais acumulados e manter separação entre histórico observado e projeção/valuation.

Prova: commit `a8eb2bfeee7c77361fbefffe4d689b4328c70122`; run #57 `36796184892` success — 93 gate; 838 passed, 52 skipped, 19 warnings, 0 failed; PostgreSQL 18, invariantes, prompts e tools sync verdes.


## 2026-09-30 — FQ5.6 será dividido em fundação setorial e comparação de peers

**Decisão:** não criar `quant.comparaveis_setor` sobre `market.sector_classification` enquanto a tabela não tiver ingestão oficial e cobertura medida.

FQ5.6 será dividido em:
- **FQ5.6A — Sector Data Foundation**: contrato oficial B3, parser, ingestão, loader PIT e coverage gate;
- **FQ5.6B — Peer Comparison**: universo company-level e comparação que reutiliza valuation, FQ5.5 e estatística existente.

**Temporalidade:** para novos snapshots, não criar `availability_date` redundante. A disponibilidade conhecida pelo Plexo será o `finished_at` do `market.ingestion_batches` associado, com lote `succeeded`; `reference_date` representa a data do snapshot. Linhas sem lote não são elegíveis para strict PIT.

**Identidade:** matching oficial por CNPJ -> issuer. É proibido inferir classes por prefixo/root code do ticker.

**Fonte v1:** somente B3. Não introduzir prioridade multi-source nesta tranche.
