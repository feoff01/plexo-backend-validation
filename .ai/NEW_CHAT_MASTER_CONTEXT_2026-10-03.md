# Plexo Backend — Contexto Mestre para Continuação

Atualizado em: 2026-10-03
Status: **canônico para novo chat**
Repo autorizado: `feoff01/plexo-backend-validation`
Branch: `bootstrap/plexo-project`
HEAD documental validado antes desta consolidação: `f568d1dd2a228216537a600debd7c83a569aeb27`
CI do HEAD documental: run #216 / `37139839922` — **success**
Código funcional de referência: `c3d7cc95f6ef896a5463397b6a323a0325f3c9f0`
CI funcional de referência: run #202 / `37135725129` — **success**

> Este documento explica o projeto, o que foi feito, por que foi feito, como foi validado, o que não deve ser reaberto e qual é o próximo gate real. Histórico detalhado continua em `DECISIONS.md`, `CHANGELOG.md` e checkpoints.

## 1. O que é o Plexo

Plexo é um backend de copiloto financeiro orientado a tools determinísticas.

Fluxo canônico:

```
usuário
  -> LLM interpreta a pergunta
  -> LLM escolhe tool + parâmetros estruturados
  -> registry/executor
  -> preparar(): I/O, identidade, cutoff, quality, provenance
  -> calcular(): matemática determinística/pura
  -> output estruturado, versionado e auditável
  -> LLM explica o resultado
```

Regra central:
- LLM interpreta, roteia e explica;
- código determinístico carrega dados e calcula;
- o LLM não deve inventar números, choque, WACC, ERP, crescimento, causalidade ou previsão;
- outputs para o LLM devem ser compactos;
- provenance, cutoff, warnings, semver, replay e source fingerprint são parte do contrato.

## 2. Escopo da frente atual

A frente ativa é **Analista de Mercado / Company & Market Analytics**.

Fora desta frente:
- Portfolio Analytics;
- suitability;
- análise da carteira do cliente;
- planejamento financeiro pessoal;
- metas, aposentadoria e vida financeira do cliente.

O usuário possui outra frente/processo para carteira/cliente. Não misturar.

## 3. Protocolo permanente de desenvolvimento

Toda decisão relevante deve ser persistida em `.ai/`. Não depender da memória do chat.

Antes de qualquer feature:
1. aplicar `reuse-before-build`;
2. verificar se a matemática já existe no Quant Core;
3. verificar se a tabela/fonte já existe;
4. verificar se loader/adapter já existe;
5. distinguir nova fonte de nova matemática;
6. só criar tool nova quando houver intenção analítica realmente nova;
7. registrar design em `.ai/` antes do código;
8. implementar shadow;
9. provar equivalência/replay;
10. promover somente depois de CI PostgreSQL 18 completo.

Nunca:
- ler/publicar `.env` ou segredos;
- editar migrations históricas;
- usar banco remoto destrutivamente;
- tocar em outro repositório;
- usar Economatica como se fosse B3/CVM;
- tratar snapshot atual como histórico;
- reabrir FQ4 sem necessidade.

## 4. Fundação técnica já construída

### Versionamento / registry
- `exposed_to_llm` separa execução/replay de exposição ao planner;
- source fingerprint composto inclui `source_dependencies`;
- semver + source SHA protegem mudanças materiais;
- cache é content-addressed;
- `tool_executions` preserva auditabilidade/replay.

### Data Foundation
- `app/market/series.py`: preços, índices/taxas, calendário, quality/provenance;
- `raw_close` e `adjusted_close` são separados;
- adjusted close é retrospectivo as-known-now enquanto corporate actions não tiverem vintage/availability completo;
- `factor_resolution.py` + `factors.py`: ativo/índice/FX;
- `fundamentals.py` + `fundamental_history.py`: DFP PIT por `availability_date`;
- `sectors.py`: classificação setorial/peer universe;
- `index_portfolios.py`: IBrA/index_weights/universe;
- `peer_company_metrics.py`: batch loader de peers;
- `yield_curve_ingest.py` + `yield_curves.py`: fundação de ETTJ ANBIMA.

### Quant Core existente
`app/market/analytics/` já contém:
- returns;
- statistics;
- risk;
- dependence;
- conditional;
- regression/HAC;
- sensitivity;
- regimes;
- event_study;
- valuation;
- fundamental_trends;
- scenario.

Capacidades latentes que já existem e NÃO devem ser recriadas:
- rolling volatility;
- downside deviation;
- drawdown duration/recovery;
- rolling dependence;
- up/down-market dependence.

## 5. FQ0.5–FQ4 — encerrados

Estado canônico:
- `quant.risco_retorno` 1.0.1 pública;
- `quant.dependencia` 2.0.0 pública;
- `quant.analise_condicional` 1.0.1 pública;
- `quant.sensibilidade` 1.0.1 pública;
- `quant.regimes` 1.0.1 pública;
- `quant.event_study` 2.0.0 pública.

Legacy oculto/replay:
- `quant.retorno_volatilidade` 1.0.4;
- `quant.correlacao` 1.0.3;
- `quant.dependencia_macro` 1.0.1.

`quant.event_study_v2` **não está registrado**.

## 6. Auditoria arquitetural e correção de duplicação

Foi detectado que `quant.dependencia_macro` repetia a orquestração de `quant.dependencia`. A matemática já existia; o gap real era a fonte FX.

Decisão resultante:
- `FactorRef/ResolvedFactor` compartilha resolução de ativo/índice/FX;
- transformação estatística continua pertencendo à análise;
- não criar tools por fonte;
- `quant.dependencia` foi promovida para 2.0.0;
- macro ficou oculta para compatibilidade/replay;
- `reuse-before-build` virou gate permanente.

## 7. FQ5.1–FQ5.4 — empresa + valuation básico

`dados.fundamentos_empresa` 1.0.0:
- DFP PIT;
- availability_date;
- units/currency;
- provenance.

`quant.valor_mercado` 1.0.0:
- market cap multi-classe;
- net debt;
- EV;
- P/L;
- EV/EBITDA;
- P/VP;
- FCF yield.

Não é fair value.

`quant.cenario_sensibilidade` 1.0.0:
- reutiliza sensibilidade;
- aplica choque explícito ao slope;
- impacto incremental/preço mecânico;
- não é forecast;
- não inventa choque.

## 8. FQ5.5 — tendências fundamentais

`quant.tendencias_fundamentais` 1.0.1 pública/GREEN.

- histórico anual DFP PIT;
- YoY;
- margens;
- sem forecast;
- sem fair value.

## 9. FQ5.6 — setor/peers

### Fonte setorial B3
Arquivo oficial fornecido pelo usuário:
- 373 company codes;
- 11 setores;
- 39 subsetores;
- B3 = fonte canônica para setor/subsetor atual;
- Economatica = validação auxiliar;
- sem terceiro nível segmento no arquivo usado.

### Economatica
Auditoria dos arquivos do usuário:
- 478 ações B3 ativas com setor/subsetor no export 2025;
- útil para validação/cobertura;
- metadata setorial não é vintage histórico confiável;
- não retrodata;
- não substitui B3/CVM;
- preços/fundamentos vendor-derived não entram automaticamente no acervo canônico.

### Issuer bridge
O projetor COTAHIST criava instruments sem issuer company-level.
Foi criada ponte determinística:
- classes da mesma raiz B3 compartilham issuer;
- não inventa CNPJ;
- preserva issuer existente;
- conflito falha fechado.

### Universo IBrA
Arquivos oficiais B3 fornecidos:
- `IBRADia_02-10-26.csv`;
- `AcoesIndices_2026-10-02.csv`;
- XLSX multiíndice.

Contrato:
- IBrA 02/10/2026;
- 148 componentes;
- peso 100%;
- membership atual, não histórico retroativo;
- `market.index_weights` preserva snapshots;
- `is_in_universe` é projeção operacional atual.

Coverage:
- 146/148 tickers classificados;
- 142/144 company codes;
- gaps: RIAA3, SAUD3.

### Comparáveis
`quant.comparaveis_setor` 1.0.1 pública/GREEN.

- company-level;
- subsetor default;
- setor opt-in;
- segmento não suportado;
- sem ranking/recomendação/fair value;
- alvo vs mediana/distribuição.

### N+1 corrigido
Baseline:
- 2 peers = 38 queries;
- 8 peers = 98;
- 20 peers = 218.

Após batch loader:
- 2/8/20 = 10/10/10 queries;
- output público ~4 KB;
- regression gate <=12 queries e <5 KB;
- equivalência resolved/output contra preparadores canônicos GREEN.

Checkpoint: `.ai/checkpoints/2026-10-03_FQ5_6_PEERS_PROMOTION_GREEN.md`.

## 10. Catálogo público atual do Analista

Dados:
- `dados.resolver_instrumento` 1.0.0
- `dados.serie_precos` 1.0.2
- `dados.historico_comparado` 1.1.1
- `dados.serie_indice` 1.1.1
- `dados.expectativas_mercado` 1.0.0
- `dados.fundamentos_empresa` 1.0.0

Quant:
- `quant.risco_retorno` 1.0.1
- `quant.dependencia` 2.0.0
- `quant.analise_condicional` 1.0.1
- `quant.sensibilidade` 1.0.1
- `quant.regimes` 1.0.1
- `quant.event_study` 2.0.0
- `quant.valor_mercado` 1.0.0
- `quant.cenario_sensibilidade` 1.0.0
- `quant.tendencias_fundamentais` 1.0.1
- `quant.comparaveis_setor` 1.0.1

Repo: 35 tools; 32 expostas; 3 ocultas.

## 11. FQ5.7 — curva de juros

Estado: **foundation GREEN / shadow / sem tool pública**.

Já existe:
- source `anbima`;
- dataset `anbima.yield_curve.ettj@1`;
- ingestão semântica append-only;
- `ettj_pre`;
- `ettj_ipca`;
- `inflacao_implicita`;
- `business_days = vertice_du`;
- `day_count = du_252`;
- loader latest/reference_date;
- strict PIT por lote succeeded + finished_at;
- sem interpolação/extrapolação;
- sem slope/DV01;
- sem tool pública.

Checkpoint: `.ai/checkpoints/2026-10-03_FQ5_7_YIELD_CURVE_FOUNDATION_GREEN.md`.

### Bloqueio real atual
Falta materializar payload físico oficial ANBIMA:
- CSV/XML/XLS oficial;
- ou JSON real autorizado da API, sem credenciais.

Próxima sequência:
1. obter/materializar payload;
2. congelar parser/fixture;
3. medir coverage histórica;
4. aplicar reuse-before-build;
5. desenhar primeira intenção client-facing;
6. só então tool/semver/planner/bloco.

Não criar scraper HTML ou contrato de terceiros.

## 12. Temporalidade e fontes

- raw close: observation-date cutoff;
- adjusted close: retrospectivo as-known-now, não strict PIT;
- fundamentals: availability_date <= cutoff;
- FX: rate-date cutoff, vintage incompleto;
- setor/IBrA: known-at-ingestion/current snapshot;
- yield curve: reference_date + lote succeeded/finished_at <= cutoff.

Fontes:
- B3 canônica onde validada;
- CVM para fundamentals;
- Bacen/SGS/Focus onde existente;
- ANBIMA para yield curve;
- Economatica somente auxiliar.

## 13. Migrations recentes

- 0061 — acervo;
- 0062 — units/currency fundamentals;
- 0063 — source Economatica;
- 0064 — IBrA.

Nunca editar migrations históricas.

## 14. Gate atual

HEAD documental validado: `f568d1dd2a228216537a600debd7c83a569aeb27`
Run #216 / `37139839922` — **success**

- PostgreSQL 18/migrations/invariantes verdes;
- 135 directed passed;
- peers 10/10/10 queries;
- payload 4009 / 4171 / 4163 bytes;
- 896 passed;
- 52 skipped;
- 19 warnings;
- 0 failed;
- prompts check verde;
- tools sync --check verde.

## 15. Pendências reais

Imediata:
- payload físico ANBIMA;
- parser/fixture;
- coverage histórica;
- design da primeira pergunta client-facing de curva.

Transversais:
- source priority/conflicts;
- storage histórico Parquet/Postgres/híbrido;
- vintage corporate actions/FX/macro;
- artifacts genéricos;
- histórico B3 quando necessário;
- deploy/integração final.

Futuro:
- Brent/commodities somente com fonte auditada;
- fair value/reverse DCF somente com forecasts/WACC/ERP/growth governados;
- ITR/trimestre somente com contrato contábil explícito.

## 16. Erros a não repetir

- não criar tool por fonte;
- não duplicar matemática;
- não confundir correlação com causalidade;
- não chamar market cap/EV de fair value;
- não chamar cenário mecânico de forecast;
- não inventar choque/WACC/ERP/growth;
- não tratar snapshot atual como histórico;
- não chamar adjusted retrospective de PIT;
- não aceitar IBrA parcial;
- não reintroduzir N+1;
- não reexpor legacy;
- não registrar `quant.event_study_v2`;
- não usar Economatica como B3/CVM;
- não editar migrations antigas;
- não ler/publicar segredos;
- não tocar em outro repo.

## 17. Ordem de leitura no próximo chat

1. `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
2. `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
3. `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`
4. `.ai/PROJECT_STATE.md`
5. `.ai/DECISIONS.md`
6. `.ai/TASKS.md`
7. `.ai/CHANGELOG.md`
8. `.ai/WORKING_PROTOCOL.md`
9. checkpoints citados.

## 18. Primeira tarefa do próximo chat

Antes de código:
- confirmar integridade;
- confirmar FQ5.6 pública/GREEN;
- confirmar FQ5.7 foundation GREEN/shadow;
- procurar payload físico oficial ANBIMA nos anexos;
- se não existir, parar no source gate;
- se existir, congelar adapter físico + fixture e medir coverage histórica;
- registrar tudo em `.ai/`.


## Dados já recebidos do usuário e semântica permitida

### B3 — classificação setorial
Arquivo: `ClassifSetorial(20261002-005309).xlsx`.
- 373 company codes;
- 11 setores;
- 39 subsetores;
- fonte canônica para setor/subsetor corrente;
- sem CNPJ e sem terceiro nível de segmento no arquivo usado;
- snapshot atual/known-at-ingestion, não histórico retroativo.

### B3 — universo/índices
Arquivos:
- `IBRADia_02-10-26.csv`;
- `AcoesIndices_2026-10-02.csv`;
- `052503e151e55ee20469d4d86a01d164.xlsx` (multiíndice).

Uso:
- IBrA 02/10/2026 = 148 componentes;
- peso diário = 100%;
- `market.index_weights` preserva snapshots;
- `is_in_universe` é projeção operacional atual;
- não inferir membership histórico a partir destes arquivos.

Cross-check B3 setor × IBrA:
- 146/148 tickers classificados;
- 142/144 company codes;
- gaps: `RIAA3` e `SAUD3`.

### Economatica — auxiliar
Arquivos:
- `economatica com ativos cancelados.zip`;
- `arquivos economaticas preços.zip`.

Permitido: validação cruzada, cobertura auxiliar e investigação de cancelados.
Proibido: tratar como B3/CVM, retrodatação setorial, substituir fundamentos CVM ou misturar preços sem source-priority policy.

### ANBIMA
O snapshot ainda não contém um payload físico oficial congelado de ETTJ (CSV/XML/XLS/JSON real). A fundação semântica está GREEN, mas o adapter físico permanece bloqueado até bytes oficiais.


## Revalidação final pré-handoff

Base documental revalidada: `f568d1dd2a228216537a600debd7c83a569aeb27`.
CI: run #216 / `37139839922` — **success**.

Provas:
- PostgreSQL 18 + migrations até 0064: GREEN;
- invariantes admin/service: GREEN;
- gate dirigido: **135 passed**;
- benchmark peers: **10/10/10 queries** para 2/8/20 peers;
- output de peers: ~4 KB;
- suíte completa: **896 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: GREEN;
- tools sync --check: GREEN;
- catálogo: 35 tools; 32 expostas; 3 ocultas/replay.

O commit que contém estes documentos pode ser posterior a essa base por ser documental. No novo chat, confirmar HEAD + CI do snapshot anexado antes de qualquer código.


## 20. FQ5.7 source gate GREEN e primeira capability shadow
O payload físico ANBIMA foi materializado: `CurvaZero_.csv`, 2.899 bytes, SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`, referência 02/10/2026. Fixture e parser físico fail-closed estão versionados. Cobertura observada: 65 vértices IPCA, 19 PRE e 19 inflação implícita. A consulta pública informa janela dos últimos cinco dias úteis; não assumir histórico ilimitado.

`dados.curva_juros` 1.0.0 foi desenhada e implementada em shadow, compondo exclusivamente `load_yield_curve()`. Não interpola/extrapola e não faz forecast/choque/slope. Próximo gate: PostgreSQL 18 + suíte + prompts/tools sync; só depois decidir promoção pública.


## 21. FQ5.7 client-facing GREEN
`dados.curva_juros` 1.0.1 está pública/GREEN sobre `market.yield_curve`. O source gate físico ANBIMA foi fechado com `CurvaZero_.csv` (02/10/2026; 2.899 bytes; SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`), parser fail-closed e bridge para a ingestão semântica canônica. Coverage da fixture: 65 IPCA / 19 PRE / 19 inflação implícita.

Run #249 / `37146548276`: 145 directed; 906 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync GREEN. Catálogo: 36 total / 33 públicas / 3 ocultas.

A v1 pública não interpola, extrapola, compara datas, calcula slope/curvature, duration/DV01, choque, forecast ou fair value. Não existe próxima FQ numerada já congelada; usar capability audit + reuse-before-build para selecionar a próxima frente ainda dentro de Company & Market Analytics.

## Atualização canônica pós-composição e risco 1.1
Estado mais novo em 2026-10-03:
- `dados.curva_juros` 1.0.1 pública/GREEN;
- `dados.composicao_indice` 1.0.1 pública/GREEN;
- `quant.risco_retorno` **1.1.0 pública/GREEN**;
- catálogo: 37 tools / 34 expostas / 3 ocultas-replay;
- run funcional mais novo: #296 / `37154531785`, HEAD `687966a22053136000f39542bb7f1feebcde71cf`;
- gate: 175 directed; 918 passed, 52 skipped, 19 warnings, 0 failed; PostgreSQL 18.6; prompts/tools sync GREEN;
- peers continuam 10/10/10.

A 1.1.0 reutiliza downside deviation do Risk Core e apenas expõe duration/recovery já existentes. Rolling volatility continua interna e requer design de janela/compactação antes de qualquer exposição.

## Atualização pós-risco 1.1 — próximo design congelado

Após o run #296 GREEN, a reauditoria restante escolheu rolling volatility como próxima tranche por reuse-before-build. `quant_risk.rolling_volatility()` já existe; não haverá matemática nova nem tool paralela.

Target eventual: `quant.risco_retorno` 1.2.0. O contrato exige janela móvel explícita no shadow e, para uso público sem janela do usuário, uma policy governada `ANALISE_PARAMS.risco_janela_movel_observacoes` sem fallback escondido. Série client-facing será compactada deterministicamente e terá gate <5 KB.

Próximo passo: shadow interno não registrado + equivalência 1.1.0. PostgreSQL/cutover/promoção ficam para tranches posteriores.

## Atualização — rolling volatility shadow GREEN

O candidato rolling interno está implementado sem alterar a superfície pública. Commit funcional `bef38e7d2bc44e69bfc931f4d12ee9d7df3a00bd`; run #311 GREEN com 175 directed, 925 passed / 52 skipped / 19 warnings / 0 failed, prompts/tools sync GREEN.

`quant.risco_retorno` permanece 1.1.0 pública. O shadow exige janela explícita, reutiliza `quant_risk.rolling_volatility()`, preserva integralmente o payload-base e compacta a série exibida por mês + cap 60.

Próximo gate: integração PostgreSQL específica do shadow + semantics/payload/provenance/readiness. Cutover 1.2.0 continua bloqueado.

