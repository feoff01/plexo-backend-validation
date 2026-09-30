# Plexo — Prompt / Work Log

Objetivo: preservar continuidade por solicitação sem transformar `PROJECT_STATE.md` em diário.
Cada entrada registra pedido, decisões, arquivos, validação e próximo passo. Código/testes continuam sendo a fonte executável.

## 2026-09-21 — FQ2.2 Risk Engine + disciplina de memória

### Pedido do usuário
Continuar pelo bloco FQ2.2 `risk.py` de forma muito bem pensada e manter documentação atualizada a cada novo prompt/etapa para permitir retomada exata no futuro.

### Decisões desta entrada
- Criar `risk.py` como módulo matemático puro: sem banco, LLM, policy, registry ou constantes de negócio escondidas.
- Preservar semântica legacy de volatilidade anualizada: desvio-padrão amostral × sqrt(`periods_per_year`).
- Drawdown será medido sobre níveis de preço positivos e cronologicamente ordenados.
- O detalhe de drawdown terá episódio explícito (pico, fundo, recuperação, duração em observações), evitando inferir duração a partir de um único número.
- Downside deviation terá definição explícita de semidesvio-alvo: `sqrt(mean(min(r-target, 0)^2))`, usando todas as observações no denominador; anualização, quando pedida, exige `periods_per_year` explícito.
- Sharpe/Sortino/Calmar/VaR/ES não entram neste bloco.
- Primeiro escrever testes que falham por ausência do módulo, depois implementar, comparar com legacy e rodar bateria ampla.

### Estado ao iniciar
FQ2.1 concluído: `models.py`, `returns.py`, `statistics.py`; `quant.retorno_volatilidade` já usa returns/statistics e mantém golden legacy.

### Próximo passo
Escrever o contrato/testes vermelhos de FQ2.2 e somente depois implementar `app/market/analytics/risk.py`.

### Resultado concluído desta solicitação
- contrato FQ2.2 registrado antes do código em `.ai/FQ2_2_RISK_DESIGN.md`;
- testes vermelhos confirmaram ausência inicial do módulo;
- `risk.py` implementado e conectado à tool legacy;
- semver `quant.retorno_volatilidade` -> `1.0.3`;
- golden atual permaneceu idêntico;
- 17 testes diretos de risco verdes;
- 500 caminhos de property checks + 750 comparações de maximum drawdown legacy + 750 comparações de volatilidade legacy;
- bateria ampla: 280 passed, 16 skipped, 355 DB-deselected, 0 failed;
- checkpoint persistido em `.ai/checkpoints/2026-09-21_FQ2_2_RISK.md`.

### Arquivos alterados nesta solicitação
- `app/market/analytics/models.py`
- `app/market/analytics/returns.py`
- `app/market/analytics/risk.py`
- `app/tools/analista/retorno_volatilidade.py`
- `tests/test_fq2_risk.py`
- `tests/test_fq2_quant_core.py`
- `.ai/*` conforme papéis de memória.

### Próximo passo recomendado
FQ2.3 `dependence.py`; ainda não criar `quant.risco_retorno` pública até Dependence + fechamento do Quant Core base.

## 2026-09-21 — FQ2.3 Dependence Engine

### Pedido do usuário
Continuar exatamente do checkpoint FQ2.2 e implementar `dependence.py` de forma bem estruturada, incluindo Pearson, Spearman, rolling dependence, lagged dependence, up/down-market e migração de `quant.correlacao`, mantendo a memória documental atualizada.

### Decisões antes do código
- Dependence Engine será puro: sem DB, LLM, policy, registry ou thresholds ocultos.
- Lag será assinado internamente; positivo significa X antecede Y. A tool legacy continua restrita a lag >= 0.
- O pareamento preservará datas de X e Y e `as_of_date` para não esconder deslocamento temporal.
- Spearman usará ranks médios em empates.
- Rolling será por número de pares alinhados, sem padding/interpolação.
- Up/down-market condiciona pelo retorno do market após alinhamento; retornos neutros são excluídos.
- Correlação indefinida (amostra curta/constante) retorna `None`, nunca zero.
- A nova tool `quant.dependencia` não será criada nesta etapa.

### Próximo passo
Escrever testes vermelhos de FQ2.3; somente depois implementar `app/market/analytics/dependence.py` e migrar `quant.correlacao`.


### Resultado concluído — FQ2.3
- contrato persistido em `.ai/FQ2_3_DEPENDENCE_DESIGN.md` antes do código;
- testes vermelhos confirmaram ausência inicial dos modelos/módulo;
- `dependence.py` implementado com Pearson, Spearman, lag assinado, rolling e up/down-market;
- `quant.correlacao` migrada para Returns + Dependence Core, sem mudar schema/output/golden;
- semver `quant.correlacao` -> `1.0.2`;
- 14 testes diretos verdes;
- 750 casos de equivalência com algoritmo legacy Pearson+lag;
- 250 checks de simetria de lag assinado;
- bateria ampla: 294 passed, 16 skipped, 355 DB-deselected, 0 failed;
- decisão de escopo: Event Study permanece em FQ4; FQ2 base fecha aqui.

### Arquivos alterados nesta solicitação
- `app/market/analytics/models.py`
- `app/market/analytics/dependence.py`
- `app/market/analytics/__init__.py`
- `app/tools/analista/correlacao.py`
- `tests/test_fq2_dependence.py`
- `.ai/FQ2_3_DEPENDENCE_DESIGN.md`
- `.ai/PROJECT_STATE.md`
- `.ai/DECISIONS.md`
- `.ai/TASKS.md`
- `.ai/CHANGELOG.md`
- `.ai/ANALISTA_MARKET_PLAN.md`
- `.ai/PROMPT_LOG.md`

### Próximo passo recomendado
FQ3 — antes de escrever as tools canônicas, desenhar contratos de entrada/saída/compactação para `quant.risco_retorno` e `quant.dependencia`, decidindo como resultados ricos entram em `Evidencia`/`output_payload` sem explodir tokens.

## 2026-09-21 — FQ3.1 início: semântica de cutoff + `quant.risco_retorno`

### Pedido do usuário
Corrigir as melhorias conceituais pendentes antes do FQ3 e iniciar o FQ3 de forma estruturada,
mantendo toda mudança documentada para retomada futura.

### Decisões antes do código
- `dados.serie_precos` deixará de prometer "point-in-time"; a linguagem passa a dizer explicitamente
  "cutoff pela data da observação" e que isso não prova vintage histórico.
- `quant.risco_retorno` será a primeira tool canônica do FQ3, inicialmente shadow
  (`exposed_to_llm=False`) para não competir com a legacy durante a migração.
- Default da nova tool: `adjusted_close`, por ser a base econômica apropriada para retorno/risco
  retrospectivos; `raw_close` somente quando explicitamente pedido.
- `adjusted_close` deriva automaticamente `retrospective_as_known_now`; `raw_close` deriva
  `observation_date_cutoff`. A semântica temporal não será parâmetro livre.
- O output será compacto: métricas centrais + episódio de maximum drawdown + Evidencia, sem série
  inteira/rolling no payload da LLM.
- O contrato está documentado em `.ai/FQ3_CANONICAL_TOOLS_DESIGN.md` antes da implementação.

### Próximo passo
Escrever testes vermelhos da nova tool e da correção de descrição; depois implementar apenas o
contrato aprovado e validar contra o Quant Core existente.

### Resultado concluído — FQ3.1
- `dados.serie_precos` 1.0.2: removida a promessa "point-in-time" do schema/description; agora
  descreve observation-date cutoff e limitações de vintage.
- `quant.risco_retorno` 1.0.0 criada em shadow mode (`exposed_to_llm=False`).
- default `adjusted_close -> retrospective_as_known_now`; `raw_close -> observation_date_cutoff`;
  sem parâmetro livre de temporal semantics.
- cálculo usa diretamente `ResolvedMarketSeries` + Returns/Risk Core; output não inclui série longa.
- maximum drawdown ganhou detalhe estruturado (pico, fundo, recuperação e intervalos) no output.
- warnings de adjusted retrospectivo e fallback de calendário preservados e preparados para UI.
- 12 testes FQ3.1 verdes; bateria ampla sem PostgreSQL: 306 passed, 16 skipped, 355 deselected,
  zero falhas.
- registry após FQ3.1: 25 registradas / 24 expostas / 1 shadow.

### Arquivos principais alterados
- `app/tools/analista/serie_precos.py`
- `app/tools/analista/risco_retorno.py`
- `app/tools/analista/__init__.py`
- `app/tools/__init__.py`
- `app/agents/blocos.py`
- `tests/test_fq3_risco_retorno.py`
- `.ai/FQ3_CANONICAL_TOOLS_DESIGN.md`
- `.ai/PROJECT_STATE.md`, `DECISIONS.md`, `TASKS.md`, `CHANGELOG.md`, `ANALISTA_MARKET_PLAN.md`,
  `PROMPT_LOG.md`.

### Próximo passo recomendado
FQ3.2 `quant.dependencia` em shadow mode; não alterar o catálogo/planner antes de FQ3.3.

## 2026-09-21 — FQ3.2 + FQ3.3 Dependência canônica e cutover

### Pedido do usuário
Executar o FQ3.2 (`quant.dependencia` em shadow mode) e, se validado, fazer o FQ3.3 com cutover conjunto das duas tools canônicas.

### Decisões antes do código
- contrato de `quant.dependencia` congelado em `.ai/FQ3_2_DEPENDENCIA_DESIGN.md`;
- Pearson e Spearman serão expostos; rolling/up-down ficam fora do schema inicial;
- `defasagem_observacoes` é assinada e medida sobre observações comuns, não dias;
- default de ativos = `adjusted_close`; índice/taxa não recebe price basis;
- output compacto, sem pares/séries;
- shadow primeiro; cutover apenas após regressão verde.


### Resultado concluído — FQ3.2/FQ3.3
- `quant.dependencia` implementada e validada primeiro em shadow mode;
- após 12/12 testes shadow verdes, cutover atômico aplicado;
- canônicas: `quant.risco_retorno` 1.0.1 e `quant.dependencia` 1.0.1 expostas;
- legacy: `quant.retorno_volatilidade` 1.0.4 e `quant.correlacao` 1.0.3 ocultas, mas executáveis para replay/auditoria;
- planner/evals/Research/blocos migrados para canônicas;
- regra de base/semântica movida de tool para `app/market/series.py`;
- regressão ampla: 324 passed, 16 skipped, 355 DB-deselected, 0 failed;
- registry: 26 códigos únicos, fingerprints válidos;
- produção ainda NÃO sincronizada: PostgreSQL CI, `tools sync` e governança do prompt planner seguem pendentes.

### Arquivos principais desta solicitação
- `app/tools/analista/dependencia.py`
- `app/tools/analista/risco_retorno.py`
- `app/tools/analista/retorno_volatilidade.py`
- `app/tools/analista/correlacao.py`
- `app/tools/analista/_comum.py`
- `app/market/series.py`
- `app/agents/blocos.py`
- `prompts/analista.planner.j2`
- `tests/test_fq3_dependencia.py`
- `tests/test_fq3_cutover.py`
- testes F5/F6/F7/evals ajustados para novas execuções canônicas
- documentação `.ai/` e checkpoints FQ3.2/FQ3.3.

### Próximo passo recomendado
Rodar o gate PostgreSQL isolado e os syncs de tools/prompt. Com o cutover validado no banco, encerrar FQ3 para produção e abrir FQ4.

## 2026-09-21 — FQ4.1 início: análise condicional

### Pedido do usuário
Continuar o desenvolvimento de forma bem pensada a partir do FQ3.3.

### Decisões antes do código
- abrir FQ4 pela `quant.analise_condicional`, não por regressão/event study;
- separar semântica da condição da resposta;
- ativo/índice em pontos condiciona por retorno; taxa/percentual condiciona por mudança de nível;
- usar os intervalos da condicionante como relógio, medindo o retorno simples do ativo no mesmo intervalo;
- endpoints do ativo usam somente último preço em ou antes da data da condição, nunca preço futuro;
- resultado é descritivo e compara amostra condicional com baseline, sem significância/causalidade;
- amostra curta continua retornando métricas calculáveis, mas `Evidencia.suficiente=false`;
- tool nasce shadow (`exposed_to_llm=False`);
- contrato completo congelado em `.ai/FQ4_1_ANALISE_CONDICIONAL_DESIGN.md` antes do código.

### Próximo passo
Escrever testes vermelhos do engine condicional e do contrato da tool; somente depois implementar.

### Resultado concluído — FQ4.1
- criado Conditional Engine puro em `app/market/analytics/conditional.py`;
- condição por retorno para ativos/índices em pontos e por mudança de nível para taxas/percentuais;
- intervalos da condicionante viraram o relógio da resposta; endpoints usam as-of backward, nunca look-ahead;
- `quant.analise_condicional` 1.0.0 criada em shadow mode;
- output compacto, baseline vs condicional, alta/queda/neutro, amostra curta preservada com warning;
- novo warning `sem_eventos_condicao` + tradução cliente;
- mapeador de bloco específico;
- 19 testes específicos verdes, incluindo 400 cenários property, invariância à escala e stale-endpoint/overlap;
- regressão ampla sem PostgreSQL: 343 passed, 16 skipped, 355 DB-deselected, 0 failed;
- registry: 27 tools, 8 visíveis no catálogo do Analista, a nova FQ4 fora do catálogo;
- nenhum planner/eval de produção foi alterado; promoção fica pendente do gate PostgreSQL/sync.

### Arquivos principais alterados nesta solicitação
- `app/market/analytics/models.py`
- `app/market/analytics/conditional.py`
- `app/tools/analista/analise_condicional.py`
- `app/tools/analista/_comum.py`
- `app/tools/__init__.py`
- `app/agents/blocos.py`
- `tests/test_fq4_conditional.py`
- `.ai/FQ4_1_ANALISE_CONDICIONAL_DESIGN.md`
- `.ai/PROJECT_STATE.md`
- `.ai/DECISIONS.md`
- `.ai/TASKS.md`
- `.ai/CHANGELOG.md`
- `.ai/ANALISTA_MARKET_PLAN.md`
- `.ai/PROMPT_LOG.md`
- `.ai/checkpoints/2026-09-21_FQ4_1_ANALISE_CONDICIONAL.md`

### Próximo passo recomendado
Executar o PostgreSQL CI/sync pendente do FQ3 e incluir o FQ4.1 nesse gate. Se verde, promover `quant.analise_condicional` com patch semver + planner/eval. Em paralelo, o próximo design de código é FQ4.2 `quant.sensibilidade`, mas sem expor regressão até definir contrato de estimativa/incerteza.

## 2026-09-21 — FQ4.2 foundation: structured statistical estimates

### Pedido do usuário
Implementar o contrato estruturado de estimativas/incerteza antes de escrever regressões, mantendo a documentação persistente por prompt.

### Decisões antes do código
- criar `ConfidenceInterval` e `MetricEstimate` como modelos internos do Quant Core;
- não transformar `Evidencia.metricas` em `Any`;
- não adicionar `estimativas={}` ao `Evidencia` base, para não alterar o JSON/goldens de todas as tools atuais;
- criar `EvidenciaEstatistica(Evidencia)` somente para futuras tools inferenciais;
- fazer o pipeline de `analysis.evidence_findings` carregar `estimativas` somente quando elas existirem e não estiverem vazias;
- ainda não implementar OLS, p-value, escolha de covariance estimator ou `quant.sensibilidade` nesta etapa;
- contrato completo congelado em `.ai/FQ4_2_STATISTICAL_ESTIMATES_DESIGN.md` antes do código.

### Próximo passo
Escrever testes vermelhos para validação do modelo, retrocompatibilidade de `Evidencia` e serialização do finding quantitativo; só depois implementar.

### Refinamento após os testes vermelhos
A revisão de fingerprint mostrou que `analytics/models.py` já é source dependency de tools existentes. Para evitar alterar hashes/semver sem mudança de comportamento, `ConfidenceInterval`/`MetricEstimate` serão isolados em `app/market/analytics/estimates.py`.

### Segundo refinamento de fingerprint
`EvidenciaEstatistica` também foi isolada de `_comum.py` em `app/tools/analista/evidencia_estatistica.py`. `_comum.py` é source dependency compartilhada por várias tools; mantê-la intacta evita bumps/fingerprints artificiais.

### Resultado concluído — FQ4.2 foundation
- criado `analytics/estimates.py` com `ConfidenceInterval`/`MetricEstimate`;
- criado `evidencia_estatistica.py` como subclasse isolada de `Evidencia`;
- findings quantitativos ganharam suporte opcional a `estimativas`;
- `Evidencia` legacy continua serializando sem campo `estimativas`;
- estimate indefinido exige warning e não aceita SE/CI; NaN/inf, SE negativo e CI inválido falham fechado;
- envelope deliberadamente não possui p-value/significant;
- comparação de registry confirmou 27/27 tools existentes com semver/exposição/source SHA idênticos ao FQ4.1;
- 13 testes específicos verdes; 32 testes FQ4.1+foundation verdes; regressão ampla: 356 passed, 16 skipped, 355 DB-deselected, 0 failed.

### Próximo passo recomendado
Desenhar a regressão mínima de `quant.sensibilidade`: variável resposta/driver, transformação/unidade, método de estimação, covariance estimator, CI, amostra mínima e edge cases. Só depois escrever o Regression/Sensitivity Engine.

## 2026-09-21 — FQ4.2 regression/sensitivity engine

### Pedido do usuário
Implementar a próxima etapa: decidir e construir cuidadosamente OLS vs erro robusto, autocorrelação, frequência, unidade do slope, amostra mínima e tratamento de outliers/missing antes da primeira regressão de `quant.sensibilidade`.

### Decisões antes do código
- OLS univariada com intercepto para a estimativa pontual;
- covariance HAC/Newey–West Bartlett + correção n/(n-k) por padrão;
- lag automático `floor(4*(n/100)^(2/9))`, limitado por n e sempre exposto no resultado;
- CI 95% bilateral por aproximação normal assintótica da stdlib;
- driver define os intervalos; sem look-ahead, sem imputação;
- driver taxa/percentual usa mudança de nível; driver ativo/índice em pontos usa retorno;
- resposta e driver de retorno são escalados para pontos percentuais antes da regressão;
- nenhuma winsorização/trimming na v1;
- `min_observacoes` é gate de suficiência de produto, não pré-condição para esconder estimativa calculável;
- `quant.sensibilidade` nascerá shadow e sem parâmetros LLM de covariance/outlier/lag.

### Próximo passo
Escrever testes vermelhos para o Regression/Sensitivity Engine e o contrato shadow da tool; somente depois implementar.


### Resultado concluído — FQ4.2 sensibilidade
- `analytics/regression.py`: OLS + HAC/Newey-West Bartlett com correção `n/(n-k)`;
- `analytics/sensitivity.py`: escala/unidades + frequência;
- `quant.sensibilidade` 1.0.0 criada em shadow mode;
- `EvidenciaEstatistica` usada pela primeira vez em uma tool real;
- output compacto sem pares/pontos/resíduos; bloco mostra slope/CI/R²/n/lags;
- nenhuma imputação/winsorização/trimming;
- testes detectaram cancelamento numérico em `X'X` com offset grande; implementação foi substituída por funções de influência/resíduos centrados;
- 27 testes novos específicos; 500 regressões sintéticas; fórmulas HAC independentes; offset `1e12`;
- regressão ampla: 383 passed, 16 skipped, 355 DB-deselected, 0 failed;
- registry: 28 tools, com 0 mudanças de semver/exposição/SHA nas 27 anteriores.

### Próximo passo recomendado
FQ4.3 `quant.regimes`: definir regimes por regras explícitas/auditáveis antes de implementar. Não promover FQ4.1/FQ4.2 até PostgreSQL CI + sync.

## 2026-09-21 — FQ4.3 regimes: início

### Pedido do usuário
Implementar `quant.regimes` de forma bem pensada, reutilizando a fundação construída em conditional/risk/dependence/estimates.

### Decisões antes do código
- dois critérios explícitos: `nivel` e `direcao`;
- `nivel` usa o nível do driver no INÍCIO do intervalo; default de corte = mediana retrospectiva da amostra;
- `direcao` usa retorno para ativos/índices em pontos e mudança de nível para taxas/percentuais;
- limiar de direção exposto em unidades humanas e convertido internamente;
- resposta medida nos mesmos intervalos do driver, sem look-ahead e com freshness gate;
- não calcular drawdown sobre regimes não contíguos;
- comparar média/mediana/desvio/taxa positiva e cobertura por regime;
- tool nascerá shadow;
- contrato congelado em `.ai/FQ4_3_REGIMES_DESIGN.md` antes do código.

### Próximo passo
Escrever testes vermelhos do Regimes Engine e do contrato shadow da tool; somente depois implementar.

### Resultado concluído — FQ4.3 regimes
- `analytics/regimes.py` implementado com `level` e `direction`;
- classificação de nível usa informação do início do intervalo;
- mediana automática é retrospectiva e fica explicitamente marcada como `sample_median`;
- direção usa limiar simétrico e transformação correta por unidade;
- `quant.regimes` 1.0.0 criada em shadow mode;
- output traz dois grupos + cobertura/diferenças, sem pares/séries longas;
- não há drawdown/inferência forçada sobre regimes descontínuos;
- bloco e warnings cliente implementados;
- 21 testes específicos/property, 1.100 cenários sintéticos;
- regressão ampla: 404 passed, 16 skipped, 355 DB-deselected, 0 failed;
- registry: 29 tools; 28 anteriores sem qualquer mudança de semver/exposição/SHA.

### Próximo passo recomendado
FQ4.4 `quant.event_study` v2: migrar o legacy para MarketSeriesLoader/Quant Core, revisar semântica temporal e só então decidir se a inferência estatística entra no contrato v2. Manter FQ4.1/FQ4.2/FQ4.3 shadow até PostgreSQL CI + sync.

## 2026-09-25 — FQ4.4 event study v2: início

### Pedido do usuário
Implementar o próximo bloco técnico: migrar `quant.event_study` para `MarketSeriesLoader + Quant Core`, preservar replay da 1.0.1 e definir cuidadosamente a inferência estatística.

### Decisões antes do código
- preservar `quant.event_study` 1.0.1 literalmente durante a fase shadow;
- criar `quant.event_study_v2` 1.0.0 shadow;
- default `adjusted_close`, com `raw_close` opt-in;
- data efetiva = primeiro retorno comum ativo×benchmark >= data do evento;
- janelas em observações alinhadas, não dias corridos;
- `market_model` usa Regression Core para alpha/beta pontuais;
- inferência default `none`;
- inferência opt-in `classic_iid_normal` com CI do CAR sob hipóteses clássicas explícitas;
- sem p-value/significant/causalidade;
- contrato congelado em `.ai/FQ4_4_EVENT_STUDY_V2_DESIGN.md` antes do código.

### Próximo passo
Escrever testes vermelhos do Event Study Engine e da tool shadow; somente depois implementar.

### Resultado concluído — FQ4.4 event study v2
- criado Event Study Engine puro em `analytics/event_study.py`;
- descoberta/correção estrutural: níveis de ativo e benchmark são alinhados primeiro; retornos são calculados depois, evitando intervalos diferentes sob lacunas;
- criada `quant.event_study_v2` 1.0.0 shadow, default adjusted_close;
- inferência default none; opt-in classic_iid_normal com CI do CAR e hipóteses fortes explícitas, sem p-value/significant;
- replay 1.0.1 congelado em módulo autocontido e golden bit a bit;
- tool legacy visível corrigida apenas na linguagem temporal e bumpada para 1.0.2;
- 22 testes específicos + 500 cenários property;
- regressão ampla: 426 passed, 16 skipped, 355 DB-deselected, 0 failed;
- registry: 30 tools; somente `quant.event_study` mudou entre as anteriores e somente `quant.event_study_v2` foi adicionada.

### Próximo passo recomendado
Rodar PostgreSQL CI/sync para FQ3/FQ4 e depois fazer um cutover FQ4 controlado: decidir promoção conjunta de `analise_condicional`, `sensibilidade`, `regimes` e event study v2, incluindo planner/evals. Não promover event study v2 isoladamente antes desses gates.

## 2026-09-25 — Fechar integração real FQ4 antes de nova camada

### Pedido do usuário
Fechar PostgreSQL/dados, tools sync, planner e testes end-to-end das quatro FQ4 shadows antes de
seguir para fundamentals/valuation/portfolio ou outras famílias.

### Implementação
- escrito E2E DB real das quatro shadows via `executar_tool()`;
- workflow PostgreSQL 18 passou a executar esse gate explicitamente;
- cache e `tool_executions` fazem parte do contrato de integração;
- planner preparado para condicional/sensibilidade/regimes somente quando presentes no catálogo;
- event study v2 continua fora do planner pelo nome de migração; cutover futuro preserva `quant.event_study`;
- criado plano operacional de promoção.

### Resultado local
429 passed, 16 skipped, 357 DB-deselected, 0 failed. Registry 30/30 único e shadows ainda ocultas.

### Limitação
Este runtime não possui PostgreSQL/Docker e não resolve DNS externo; portanto o gate DB não foi
executado e não é considerado aprovado.

### Próximo passo
Rodar `.github/workflows/verify.yml` em runner com PostgreSQL 18. Só após verde fazer bumps de
promoção, tools sync/prompt sync e cutover controlado.


## 2026-09-30 — GitHub/PostgreSQL real: fechamento do gate FQ4

### Pedido do usuário
Usar somente o novo repositório `plexo-backend-validation` para testar livremente e validar o backend de forma melhor, sem tocar em projetos antigos.

### Execução
- conteúdo do checkpoint foi expandido numa branch dedicada `bootstrap/plexo-project`;
- PR #1 aberto para `main`;
- PostgreSQL 18 descartável executou migrations, invariantes, FQ1/F5/F22/FQ4 E2E, suíte completa, prompts check e tools sync --check;
- falhas de integração/testes encontradas pelo ambiente real foram corrigidas sem alterar a matemática FQ4;
- run verde final: `36753446081`, commit `7a634ef22d1700635ffbfa6cf383be213de10171`;
- suíte: 806 passed, 52 skipped, 19 warnings;
- FQ4 continua shadow; promoção fica para branch/PR separado.

### Próximo passo
Limpar artefatos temporários do bootstrap, confirmar um CI final de PR limpo e então abrir a fase de promoção controlada.

## 2026-09-30 — continuar validação via GitHub

Pedido do usuário: usar livremente apenas o novo repositório `plexo-backend-validation` para testar e prosseguir corretamente.

Execução:
- conexão GitHub confirmada;
- projeto completo localizado em `bootstrap/plexo-project`;
- run 36754171560 confirmado verde de ponta a ponta;
- promoção FQ4 aplicada somente nesse repositório/branch;
- main e demais repositórios não foram alterados.
