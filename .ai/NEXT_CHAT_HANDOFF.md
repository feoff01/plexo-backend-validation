# Plexo Backend — Handoff Completo para Continuação em Outro Chat

Atualizado em: 2026-09-30

## 0. Leia isto primeiro

Este documento é a fonte de continuidade para outro chat/agente continuar o backend do Plexo sem reconstruir o contexto do zero.

Repositório de validação autorizado pelo usuário:
- GitHub: `feoff01/plexo-backend-validation`
- Branch de trabalho atual: `bootstrap/plexo-project`
- Não tocar em outros repositórios.
- Não assumir que `main` contém o projeto completo: o projeto completo foi trabalhado na branch `bootstrap/plexo-project`.
- O usuário quer que toda etapa técnica relevante seja registrada em `.ai/`.

IMPORTANTE:
- Nunca ler, copiar ou publicar `.env` com credenciais reais.
- Nunca usar/destruir banco Aiven/produção para validação.
- Migrations devem ser append-only; não reescrever migrations históricas.
- O GitHub Actions de validação usa PostgreSQL 18 descartável e é a referência de integração.
- O repositório de validação foi criado especificamente para este trabalho. Não mexer nos projetos antigos do usuário.

## 1. O que é o Plexo

Plexo é um Copilot financeiro com arquitetura orientada a tools determinísticas.

Princípio central:

```
usuário
  ↓
LLM entende a pergunta
  ↓
LLM escolhe tool + parâmetros estruturados
  ↓
registry/router
  ↓
tool versionada e determinística
  ↓
dados + cálculo em código
  ↓
resultado estruturado + evidência/proveniência
  ↓
LLM explica
```

Regra de produto/arquitetura:
- o LLM interpreta, roteia e explica;
- código determinístico faz contas;
- resultados devem ser auditáveis, reproduzíveis e compactos;
- minimizar tokens;
- evitar mandar séries longas ao modelo;
- preservar provenance, quality, warnings, cutoff e metodologia;
- nenhuma inferência causal/preditiva deve ser inventada por tools descritivas.

## 2. Escopo atual

A frente ativa até este checkpoint é o **Analista de Mercado / Quant Core**.

Não misturar com:
- planejamento financeiro pessoal;
- orçamento;
- suitability;
- objetivos de vida;
- recomendação personalizada.

A intenção foi construir primeiro uma fundação quantitativa robusta para análises de mercado.

## 3. Infraestrutura do backend que deve ser preservada

Arquitetura já existente e usada pelo Quant:

### Registry

`app/tools/registry.py`

Tools são registradas por decorator `@tool` com:
- code;
- family;
- semver;
- schemas Pydantic;
- `preparar`;
- `calcular`;
- source fingerprint;
- `requires_market_data`;
- `exposed_to_llm`.

### Executor

`app/tools/executor.py`

Fluxo real:
1. valida parâmetros;
2. resolve/prepara insumos;
3. registra provenance/policies;
4. calcula content hash;
5. verifica cache;
6. executa cálculo determinístico;
7. persiste `tools.tool_executions`;
8. retorna output tipado.

### Sync

`app/tools/sync.py`

Regra importante:
- mesma semver + source alterado é conflito;
- promoção que altera source auditado deve receber bump de versão;
- DB mantém versão corrente da tool;
- não adulterar histórico.

### Exposição ao LLM

`exposed_to_llm` separa:
- tool executável/replay;
- tool ofertada ao LLM em novas execuções.

`app/agents/turn.py::filtrar_tools` filtra tools ocultas.
`app/analysis/compiler.py` rejeita tools ocultas em novos planos.

## 4. Versionamento/fingerprint — FQ0.5

Foi implementado fingerprint composto:
- tool;
- helpers/engines explicitamente declarados;
- módulo de `preparar` quando separado.

Arquivos importantes:
- `app/tools/hashing.py`
- `app/tools/registry.py`
- `app/tools/sync.py`

Objetivo: alteração matemática em helper não pode ficar invisível ao versionamento da tool.

## 5. Quant Data Foundation — FQ1

Arquivo principal:
- `app/market/series.py`

Principais componentes:
- `SeriesReader`
- `PostgresSeriesReader`
- `MarketSeriesLoader`
- `MarketPoint`
- `ResolvedMarketSeries`
- quality/provenance

Dimensões explícitas:

### PriceBasis
- `RAW_CLOSE`
- `ADJUSTED_CLOSE`

### TemporalSemantics
- `OBSERVATION_DATE_CUTOFF`
- `RETROSPECTIVE_AS_KNOWN_NOW`

Regras:
- `adjusted_close` usa visão retrospectiva com corporate actions conhecidas hoje;
- não chamar isso de strict point-in-time;
- `raw_close` respeita cutoff pela data da observação;
- strict vintage histórico de adjusted price ainda não existe porque corporate actions não possuem availability/announcement metadata suficiente;
- não prometer PIT estrito onde o schema não suporta.

Calendário:
- usa `market.trading_calendar` quando cobertura é adequada;
- senão fallback explícito derivado de preços;
- fallback deve gerar provenance/warning.

A view `market.v_precos_ajustados` é retrospectiva, não historical-vintage PIT.

## 6. Quant Core — FQ2

Diretório:
- `app/market/analytics/`

### Retornos / modelos / estatística
- `models.py`
- `returns.py`
- `statistics.py`

### Risco
- `risk.py`

Inclui:
- volatilidade anualizada;
- rolling volatility;
- downside deviation;
- drawdown;
- max drawdown;
- duração;
- recovery.

### Dependência
- `dependence.py`

Inclui:
- Pearson;
- Spearman;
- alignment;
- lag assinado;
- rolling;
- up/down conditional dependence.

Regra: esses engines não devem depender de DB/LLM/policy.

## 7. Tools canônicas FQ3

Já existiam como canônicas:

### `quant.risco_retorno`
- canônica;
- atualmente versão 1.0.1;
- pública.

### `quant.dependencia`
- canônica;
- atualmente versão 1.0.1;
- pública.

Legacy preservado para replay:
- `quant.retorno_volatilidade`
- `quant.correlacao`

Legacy deve permanecer oculto para novas execuções.

## 8. FQ4 — Análises econômicas avançadas

### 8.1 `quant.analise_condicional`

Engine:
- `app/market/analytics/conditional.py`

Tool:
- `app/tools/analista/analise_condicional.py`

Semântica:
- driver define intervalos;
- taxa/percentual usa mudança de nível;
- ativo/índice em pontos usa retorno;
- resposta do ativo é medida nos mesmos endpoints;
- alinhamento as-of backward;
- nunca future lookup;
- amostra baseline x condicional;
- não implica causalidade, significância ou previsão.

Estado atual após promoção:
- code: `quant.analise_condicional`
- semver: **1.0.1**
- `exposed_to_llm=True`

### 8.2 Statistical Estimates Foundation

Arquivos:
- `app/market/analytics/estimates.py`
- `app/tools/analista/evidencia_estatistica.py`

Modelos:
- `ConfidenceInterval`
- `MetricEstimate`
- `EvidenciaEstatistica`

Fail closed:
- nada de NaN/inf;
- undefined estimate deve ter warning;
- não criar `p_value`;
- não criar flag booleana de significância.

### 8.3 `quant.sensibilidade`

Engines:
- `app/market/analytics/regression.py`
- `app/market/analytics/sensitivity.py`

Regressão:
- OLS univariada com intercepto;
- HAC/Newey-West Bartlett;
- correção HC1;
- lag automático;
- CI 95% normal assintótico;
- sem numpy/scipy/statsmodels;
- sem winsorization/imputation/trimming.

Tool:
- `app/tools/analista/sensibilidade.py`

Semântica:
- taxa -> mudança de nível;
- pontos -> retorno;
- resposta no mesmo intervalo;
- outputs compactos;
- beta/CI/R²/n/lags;
- associacional, não causal.

Estado atual após promoção:
- code: `quant.sensibilidade`
- semver: **1.0.1**
- `exposed_to_llm=True`

### 8.4 `quant.regimes`

Engine:
- `app/market/analytics/regimes.py`

Critérios v1:
- `level`
- `direction`

Level:
- nível do driver no INÍCIO do intervalo;
- limiar explícito ou mediana retrospectiva da amostra.

Direction:
- taxa -> mudança de nível;
- ativo/índice em pontos -> retorno;
- up/down/neutral;
- threshold simétrico.

Não existe:
- HMM;
- clustering;
- threshold otimizado;
- drawdown em observações descontínuas.

Tool:
- `app/tools/analista/regimes.py`

Estado atual após promoção:
- code: `quant.regimes`
- semver: **1.0.1**
- `exposed_to_llm=True`

### 8.5 Event Study v2

Engine:
- `app/market/analytics/event_study.py`

Implementação nova:
- arquivo: `app/tools/analista/event_study_v2.py`

Atenção: o nome do arquivo ainda contém `_v2`, mas após o cutover ele registra o código canônico:

- code: `quant.event_study`
- semver: **2.0.0**
- `exposed_to_llm=True`

O alias `quant.event_study_v2` **não deve estar registrado**.

Implementação legacy:
- `app/tools/analista/event_study.py`
- continua no código para testes/golden/replay;
- decorator antigo foi removido;
- não deve registrar `quant.event_study`.

Replay congelado:
- `app/tools/analista/event_study_legacy_1_0_1.py`

Ele reproduz o golden histórico 1.0.1.

#### Semântica crítica do v2

Nunca calcular retornos de ativo e benchmark independentemente e só depois alinhar por data final quando existem gaps.

V2 faz:
1. interseção das datas dos NÍVEIS de preço;
2. calcula retornos sobre caminhos sincronizados;
3. garante endpoints idênticos.

Função:
- `synchronized_returns_from_prices(...)`

Data efetiva do evento:
- primeiro retorno sincronizado >= data civil solicitada.

Janelas:
- contam observações sincronizadas;
- event window é inclusiva `[-pre,+post]`;
- estimation window termina antes do início da event window;
- sem overlap;
- `truncada_pre` e `truncada_pos` separados;
- CAR parcial pode existir descritivamente;
- se janela de evento truncada, `evidencia.suficiente=False`.

Métodos:
- `market_model`
- `market_adjusted`

Market model:
```
R_asset = alpha + beta * R_benchmark + epsilon
```

Market adjusted:
```
alpha = 0
beta = 1
AR = R_asset - R_benchmark
```

Inferência:
- default `none`;
- opcional `classic_iid_normal`;
- sem p-value;
- sem flag de significância;
- sem alegação causal.

Market-model CAR variance:
```
Var(CAR) = sigma² * [
  L
  + L²/T
  + (sum(x_event) - L*xbar_est)² / Sxx_est
]
```

Market-adjusted:
```
SE(CAR) = sample_sd(estimation residuals) * sqrt(L)
```

Hipóteses do CI clássico:
- resíduos iid;
- homoscedasticidade;
- aproximação normal;
- modelo corretamente especificado;
- ausência de event-induced variance.

## 9. Planner

Arquivo:
- `prompts/analista.planner.j2`

Regras preparadas:
- “como X se comportou quando Y subiu/caiu?” -> `quant.analise_condicional`;
- “quanto X varia por 1 p.p./1% de Y?” -> `quant.sensibilidade`;
- “X muda em regime alto/baixo/subindo/caindo?” -> `quant.regimes`;
- event study usa somente código canônico `quant.event_study`;
- não usar `quant.event_study_v2`;
- não substituir pergunta condicional/sensibilidade/regime por simples correlação quando tool especializada responde melhor.

## 10. Blocos

Arquivo:
- `app/agents/blocos.py`

Após o cutover:
- `quant.event_study` deve apontar somente para `_event_study_v2`;
- não deixar chave duplicada;
- mapper legacy `_event_study` pode continuar existindo para compatibilidade interna, mas não deve estar ligado ao código canônico atual.

## 11. Gate PostgreSQL / GitHub Actions

Workflow:
- `.github/workflows/verify.yml`

Ambiente:
- PostgreSQL 18 descartável;
- sem produção;
- sem Aiven;
- sem secrets reais.

Passos:
1. checkout;
2. Python 3.12;
3. dependencies;
4. cria `.env` isolado com DB local;
5. `alembic upgrade head`;
6. `tools/preparar_ambiente.py`;
7. validador;
8. invariantes SQL;
9. invariantes sob `plexo_service`;
10. gate FQ1 + F5 + F22 + FQ4;
11. pytest completo;
12. `prompts check`;
13. `tools sync --check`.

## 12. Resultados de CI que importam

### Run pré-promoção totalmente verde

GitHub Actions run:
- **36754171560**
- commit: `55410c43126171941f5b26f2bcb3ca8baed1336a`
- conclusion: **success**

Passou:
- PostgreSQL 18;
- migrations;
- preparação;
- validador;
- SQL invariants;
- FQ1/F5/F22/FQ4;
- suíte completa;
- prompts check;
- tools sync --check.

Isso autorizou tecnicamente a promoção controlada.

### Promoção aplicada depois desse run

Mudanças:
- analise_condicional 1.0.0 shadow -> 1.0.1 pública;
- sensibilidade 1.0.0 shadow -> 1.0.1 pública;
- regimes 1.0.0 shadow -> 1.0.1 pública;
- event study v2 -> `quant.event_study` 2.0.0;
- alias `quant.event_study_v2` removido do registry;
- legacy `quant.event_study` antigo deixou de registrar tool.

### Run pós-promoção mais relevante até este handoff

Run:
- **36759920474**
- commit: `bbd34122fe4d60e9a908be5d0a26910ebea43efe`
- run number: 38

Resultado:
- PostgreSQL 18: verde;
- migrations: verde;
- preparação: verde;
- validador: verde;
- SQL invariants: verde;
- **gate FQ1 + F5 + F22 + FQ4 E2E: verde**;
- suíte Python completa: **1 falha**;
- summary: **805 passed, 52 skipped, 19 warnings, 1 failed**;
- prompts/tools drift não rodaram porque pytest completo falhou.

### ÚNICA FALHA CONHECIDA NO RUN #38

Teste:
- `tests/test_f11_blocos.py::test_blocos_batem_com_o_golden[quant_event_study]`

Causa:
- o mapper canônico agora produz representação v2;
- o golden `blocos_quant_event_study.json` ainda representa o bloco legacy.

Diferenças esperadas do v2:
- adiciona bloco `indicadores` com CAR/desvio/CI quando houver;
- IDs dos blocos mudam porque há bloco adicional;
- título de barras muda de “por pregão” para “por observação”;
- nota metodológica v2 é mais explícita;
- pode haver subtítulo diferente.

Isto é uma mudança intencional de representação associada ao major bump 2.0.0. O próximo chat deve atualizar o golden de blocos de forma consciente, não tentar voltar o mapper ao legacy apenas para fazer o teste passar.

## 13. Próximo passo exato

A prioridade NÃO é criar nova matemática.

### Passo 1 — fechar o golden do Event Study v2

Abrir:
- `tests/test_f11_blocos.py`
- `tests/golden/blocos_quant_event_study.json`
- `app/agents/blocos.py`

Gerar/inspecionar a saída determinística atual de `blocos_de("quant.event_study", ...)`.

Atualizar o golden para a representação v2 apenas depois de conferir:
- CAR correto;
- série cumulativa correta;
- AR bars corretas;
- anotação do evento correta;
- provenance preservada;
- warning text correto;
- não contém “significativo” como conclusão;
- nenhuma alegação causal/preditiva;
- CI só aparece quando existe no payload.

### Passo 2 — rodar CI novamente

Esperar:
- FQ1/F5/F22/FQ4 gate verde;
- suíte completa verde;
- prompts check verde;
- tools sync --check verde.

### Passo 3 — confirmar catálogo final

Esperado:
- `quant.risco_retorno` 1.0.1 pública;
- `quant.dependencia` 1.0.1 pública;
- `quant.analise_condicional` 1.0.1 pública;
- `quant.sensibilidade` 1.0.1 pública;
- `quant.regimes` 1.0.1 pública;
- `quant.event_study` 2.0.0 pública;
- `quant.event_study_v2` ausente;
- legacy retorno/correlação ocultos.

### Passo 4 — registrar CI verde em `.ai/`

Atualizar:
- `.ai/PROJECT_STATE.md`
- `.ai/TASKS.md`
- `.ai/CHANGELOG.md`
- `.ai/PROMPT_LOG.md`
- checkpoint da promoção.

### Passo 5 — somente depois encerrar FQ4

Depois de CI pós-promoção 100% verde:
- marcar FQ4 como concluído;
- não abrir mais estatística “por biblioteca”;
- próxima camada recomendada: Fundamentals + Valuation OU Portfolio Analytics, conforme prioridade do usuário.

## 14. Arquivos críticos para ler no começo do próximo chat

Ordem sugerida:

1. `.ai/NEXT_CHAT_HANDOFF.md`
2. `.ai/PROJECT_STATE.md`
3. `.ai/DECISIONS.md`
4. `.ai/TASKS.md`
5. `.ai/CHANGELOG.md`
6. `.ai/FQ4_INTEGRATION_PROMOTION_PLAN.md`
7. `.ai/checkpoints/2026-09-30_FQ4_PROMOTION.md`
8. `.github/workflows/verify.yml`
9. `app/tools/registry.py`
10. `app/tools/executor.py`
11. `app/market/series.py`
12. `app/market/analytics/`
13. `app/tools/analista/analise_condicional.py`
14. `app/tools/analista/sensibilidade.py`
15. `app/tools/analista/regimes.py`
16. `app/tools/analista/event_study_v2.py`
17. `app/tools/analista/event_study.py`
18. `app/tools/analista/event_study_legacy_1_0_1.py`
19. `app/agents/blocos.py`
20. `prompts/analista.planner.j2`
21. `tests/test_fq4_integration_db.py`
22. `tests/test_fq4_event_study_v2.py`
23. `tests/test_fq4_promotion_readiness.py`
24. `tests/test_f11_blocos.py`
25. `tests/golden/blocos_quant_event_study.json`

## 15. Coisas que o próximo chat NÃO deve fazer

- não recriar Quant Core do zero;
- não substituir cálculo determinístico por LLM;
- não adicionar p-values/significance só porque parecem convenientes;
- não chamar adjusted-close retrospectivo de strict point-in-time;
- não carregar milhões de preços históricos indiscriminadamente para Aiven;
- não resetar/drop banco remoto;
- não alterar migrations históricas;
- não expor tools legacy ao LLM;
- não renascer `quant.event_study_v2` como API pública;
- não esconder truncamento de event window;
- não fazer promoção sem semver/fingerprint correto;
- não mexer em outros repositórios do usuário;
- não declarar CI verde sem run real.

## 16. Histórico resumido de testes locais antes do GitHub

Checkpoint FQ4.4:
- 426 passed;
- 16 skipped;
- 355 DB-deselected;
- 0 failed.

Depois do integration gate:
- 429 passed;
- 16 skipped;
- 357 DB-deselected;
- 0 failed.

CI PostgreSQL pré-promoção:
- 806 passed;
- 52 skipped;
- 19 warnings;
- 0 failed.

CI pós-promoção run #38:
- gate DB/FQ4 específico verde;
- suíte completa: 805 passed, 52 skipped, 19 warnings, 1 golden de blocos falhando.

## 17. GitHub e segurança

O repositório de validação observado nesta sessão está configurado como público no GitHub. O código enviado não deve conter `.env` ou segredos. Se o usuário não quiser o código público, orientar a trocar a visibilidade para Private.

Mesmo no repo privado:
- nunca commitar `.env`;
- nunca commitar API keys/tokens;
- GitHub Actions de verificação deve continuar usando credenciais locais descartáveis.

## 18. Prompt recomendado para iniciar o próximo chat

O usuário deve anexar o ZIP completo de handoff e enviar este prompt:

---

Quero continuar o desenvolvimento do backend Plexo exatamente de onde o chat anterior parou.

Estou anexando o ZIP completo do projeto. Antes de alterar qualquer código:

1. leia primeiro `.ai/NEXT_CHAT_HANDOFF.md`;
2. depois leia `.ai/PROJECT_STATE.md`, `.ai/DECISIONS.md`, `.ai/TASKS.md`, `.ai/CHANGELOG.md` e os checkpoints citados;
3. inspecione os arquivos de código/teste mencionados no handoff;
4. trate `.ai/` como memória persistente do projeto e atualize essa pasta a cada etapa relevante;
5. não leia nem publique `.env`/segredos;
6. não mexa em nenhum repositório antigo; o único repositório GitHub autorizado para validação é `feoff01/plexo-backend-validation`;
7. preserve a arquitetura: LLM interpreta/roteia/explica, código determinístico calcula;
8. preserve semver, source fingerprint, replay e provenance.

Estado que você deve confirmar antes de prosseguir:
- Quant Core FQ0.5–FQ4 já está construído;
- `quant.analise_condicional` 1.0.1 está promovida;
- `quant.sensibilidade` 1.0.1 está promovida;
- `quant.regimes` 1.0.1 está promovida;
- Event Study v2 registra o código canônico `quant.event_study` 2.0.0;
- `quant.event_study_v2` não deve estar no registry;
- replay legacy está preservado;
- PostgreSQL 18 + FQ1/F5/F22/FQ4 E2E já passaram pós-promoção;
- o último CI completo conhecido (#38 / run 36759920474) ficou com apenas 1 falha: golden de blocos de `quant.event_study`;
- não reverta o Event Study para legacy para satisfazer o golden. Atualize conscientemente o golden para o contrato v2, valide a representação e rode o CI completo novamente.

Sua primeira tarefa é:
1. reproduzir/inspecionar a falha do golden de `quant.event_study`;
2. atualizar `tests/golden/blocos_quant_event_study.json` para o bloco v2 somente se os valores/proveniência/notas estiverem corretos;
3. executar os testes relevantes;
4. rodar/acompanhar `.github/workflows/verify.yml`;
5. só declarar FQ4 concluído se suíte completa, prompts check e tools sync --check ficarem verdes;
6. registrar o resultado em `.ai/`;
7. depois me apresentar o estado final e o próximo roadmap, sem abrir nova matemática antes de fechar o FQ4.

Não faça perguntas que os arquivos já respondem. Faça best effort, corrija os problemas encontrados e mantenha o usuário informado durante trabalhos longos.

---

## 19. Definição de pronto do handoff

Outro chat deve conseguir, somente com o ZIP + prompt acima:
- entender a arquitetura;
- saber o que já foi construído;
- saber por que cada decisão importante foi tomada;
- identificar o branch/repo certo;
- entender o estado de versionamento;
- saber qual CI passou e qual falhou;
- reproduzir o próximo passo sem inventar contexto;
- continuar documentando em `.ai/`.


## Estado atual

Este arquivo é legado. Para qualquer continuação use exclusivamente:
- `.ai/NEXT_CHAT_HANDOFF_FINAL.md`;
- `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`.

Não use estados históricos deste arquivo como fonte de verdade.
