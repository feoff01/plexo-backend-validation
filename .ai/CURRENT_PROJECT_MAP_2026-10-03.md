# Plexo — Mapa Canônico Atual do Projeto

Atualizado em: 2026-10-03
Código funcional validado: `c3d7cc95f6ef896a5463397b6a323a0325f3c9f0`
HEAD documental validado: `f568d1dd2a228216537a600debd7c83a569aeb27`
CI do HEAD documental: run #216 / `37139839922` — success

## Projeto e arquitetura
Plexo é um backend de copiloto financeiro: o LLM interpreta/roteia/explica; código determinístico carrega dados, resolve identidade, calcula, valida, versiona e registra provenance.

Fluxo: usuário -> LLM -> tool JSON -> registry/executor -> preparar(I/O/cutoff/provenance) -> calcular(puro) -> output estruturado -> LLM explica.

Preservar semver, source fingerprint, replay, cache content-addressed, outputs compactos, PostgreSQL gates e `reuse-before-build`.

## Escopo
Frente ativa: Analista de Mercado / Company & Market Analytics.
Fora: Portfolio Analytics, suitability e análise da carteira/vida financeira do cliente.

## Reuse-before-build
Antes de nova matemática/tabela/loader/tool: conferir Quant Core, schema/fonte, loader/adapter e tool existente; separar fonte nova de matemática nova; preservar replay/semver/fingerprint. Não criar variantes por fonte.

## Catálogo público do Analista
Dados:
- dados.resolver_instrumento 1.0.0
- dados.serie_precos 1.0.2
- dados.historico_comparado 1.1.1
- dados.serie_indice 1.1.1
- dados.expectativas_mercado 1.0.0
- dados.fundamentos_empresa 1.0.0

Quant:
- quant.risco_retorno 1.0.1
- quant.dependencia 2.0.0
- quant.analise_condicional 1.0.1
- quant.sensibilidade 1.0.1
- quant.regimes 1.0.1
- quant.event_study 2.0.0
- quant.valor_mercado 1.0.0
- quant.cenario_sensibilidade 1.0.0
- quant.tendencias_fundamentais 1.0.1
- quant.comparaveis_setor 1.0.1

Ocultas/replay: quant.retorno_volatilidade 1.0.4, quant.correlacao 1.0.3, quant.dependencia_macro 1.0.1.
quant.event_study_v2 não está registrado.
Repo inteiro: 35 tools, 32 expostas, 3 ocultas.

## Quant Core já existente
app/market/analytics contém returns, statistics, risk, dependence, conditional, regression/HAC, sensitivity, regimes, event_study, valuation, fundamental_trends e scenario.
Já existem rolling vol, downside deviation, drawdown duration/recovery, rolling dependence e up/down-market dependence; não recriar.

## Data Foundation
- app/market/series.py: preços/índices/calendário/quality/provenance
- factor_resolution.py + factors.py: ativo/índice/FX
- fundamentals.py + fundamental_history.py: DFP PIT
- snapshots.py: preço bruto atual
- sectors.py: classificação/peer universe
- peer_company_metrics.py: batch de peers
- index_portfolios.py: IBrA/index_weights/universe
- yield_curve_ingest.py + yield_curves.py: ETTJ ANBIMA foundation

## Temporalidade
- raw close: observation cutoff
- adjusted close: retrospectivo as-known-now; não chamar strict PIT
- fundamentos: availability_date <= cutoff
- FX: rate_date cutoff, vintage incompleto
- setor/IBrA atuais: known-at-ingestion, não histórico retroativo
- curva: reference_date + lote succeeded/finished_at <= cutoff

## FQ5 concluído até FQ5.6
FQ5.1–5.4: fundamentos, valuation/múltiplos, cenário mecânico, dependência unificada.
valor_mercado não é fair value; cenário não é forecast e não inventa choque.

FQ5.5: tendencias_fundamentais 1.0.1 pública, DFP anual PIT, YoY/margens, sem forecast/CAGR/fair value.

FQ5.6: comparaveis_setor 1.0.1 pública.
- classificação B3 oficial
- issuer bridge sem CNPJ sintético
- universo atual IBrA 02/10/2026: 148 componentes
- coverage setor: 146/148 tickers; gaps RIAA3/SAUD3
- subsetor default, setor opt-in, sem terceiro nível segmento
- sem ranking/recomendação/fair value
- performance: baseline 38/98/218 queries -> batch 10/10/10; output ~4 KB; gate <=12 queries e <5 KB

## FQ5.7 atual
Foundation GREEN, sem tool pública:
- market.yield_curve reutilizado
- source anbima
- dataset anbima.yield_curve.ettj@1
- ettj_pre, ettj_ipca, inflacao_implicita
- business_days=vertice_du, day_count=du_252
- loader latest/reference_date com strict PIT
- sem interpolação/extrapolação/slope/DV01/forecast

Fonte oficial ANBIMA Developers confirma API diária curvas-juros. Página pública oferece XLS/CSV/TXT/XML e em 03/10/2026 mostrava referência 02/10/2026 com 65 vértices IPCA e 19 PRE/inflação implícita.

Bloqueio: não há fixture física congelada de bytes oficiais CSV/XML/XLS/JSON. Não criar scraper HTML nem contrato de terceiros. Próximo gate é receber/materializar payload oficial, congelar parser e medir cobertura histórica; só depois desenhar capability pública.

## Fontes
B3 canônica onde validada; CVM para fundamentals; Bacen/SGS/Focus existente; ANBIMA foundation de curva; Economatica somente validação auxiliar, nunca B3/CVM e nunca retrodatada.

## Migrations recentes
0061 acervo; 0062 unidades fundamentals; 0063 source Economatica; 0064 IBrA. Nunca editar migrations históricas.

## CI atual
Run #216 / 37139839922, HEAD documental f568d1dd2a228216537a600debd7c83a569aeb27 (código funcional igual ao head c3d7cc95f6ef896a5463397b6a323a0325f3c9f0):
- 135 directed passed
- peers benchmark 10/10/10 queries
- 896 passed, 52 skipped, 19 warnings, 0 failed
- PostgreSQL 18/migrations/invariantes verdes
- prompts check verde
- tools sync --check verde

## Pendências reais
Imediata: payload físico ANBIMA -> parser/fixture -> histórico -> design da primeira intenção client-facing de curva.

Transversais: source priority/conflicts, storage histórico Parquet/Postgres/híbrido, vintages corporate actions/FX/macro, artifacts genéricos, histórico B3 quando necessário, integração/deploy.

Futuro: Brent/commodities somente com fonte; fair value/reverse DCF somente com forecasts/WACC/ERP/growth governados; ITR/trimestre só com contrato contábil explícito.

## Erros a não repetir
Não criar tool por fonte; não chamar correlação de causalidade; não chamar market cap/EV de fair value; não inventar choque/WACC/ERP/growth; não tratar snapshot atual como histórico; não chamar adjusted retrospective de PIT; não reexpor legacy; não registrar event_study_v2; não usar Economatica como B3/CVM; não aceitar snapshot parcial IBrA; não reintroduzir N+1; não editar migrations antigas; não ler .env/segredos; não tocar em outros repos.

## Leitura no próximo chat
1. .ai/NEXT_CHAT_HANDOFF_FINAL.md
2. .ai/CURRENT_PROJECT_MAP_2026-10-03.md
3. .ai/PROJECT_STATE.md
4. .ai/DECISIONS.md
5. .ai/TASKS.md
6. .ai/CHANGELOG.md
7. .ai/WORKING_PROTOCOL.md
8. checkpoints citados


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


## FQ5.7 — atualização pós source gate
- payload físico oficial ANBIMA: GREEN;
- fixture/parser físico: GREEN;
- snapshot 02/10/2026: 65 IPCA / 19 PRE / 19 inflação implícita;
- `dados.curva_juros` 1.0.0: shadow / não exposta;
- sem interpolation/extrapolation/slope/forecast/choque;
- próximo gate: PostgreSQL 18 + suíte completa + prompts/tools sync antes de promoção.


## FQ5.7 — estado final
- `dados.curva_juros` 1.0.1: pública/GREEN;
- fonte: ANBIMA first-party física;
- parser/fixture/hash/bridge/strict PIT: GREEN;
- coverage física 02/10/2026: 65 IPCA / 19 PRE / 19 inflação implícita;
- sem interpolation/extrapolation/delta/slope/DV01/choque/forecast;
- run #249: 145 directed; full 906/52/19/0; prompts/tools sync GREEN;
- catálogo: 36 total / 33 expostas / 3 ocultas;
- próxima tranche ainda não numerada: capability audit de Company & Market Analytics + reuse-before-build.

## Atualização pós-composição oficial de índice
- `dados.curva_juros` 1.0.1 pública/GREEN;
- `dados.composicao_indice` 1.0.1 pública/GREEN;
- catálogo: 37 tools / 34 expostas / 3 ocultas-replay;
- composição reutiliza `market.index_weights` e strict PIT; nenhuma matemática/schema novo;
- IBrA operacional atual permanece snapshot B3 de 02/10/2026, 148 componentes;
- run #283 / `37153499452`: 153 directed; 914 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync GREEN;
- benchmark peers permanece 10/10/10;
- não usar composição para performance, ranking/recomendação ou carteira do cliente.

Próximo gate: reabrir o capability audit pós-composição e escolher a próxima lacuna por `reuse-before-build`.

## Atualização pós-risco histórico compacto
- `quant.risco_retorno` atual: **1.1.0 pública/GREEN**;
- downside deviation anualizada usa Risk Core existente e target periódico 0% explícito;
- duração/recovery do pior drawdown são intervalos observados, não dias corridos;
- replay `quant.retorno_volatilidade` continua oculto e seu golden foi preservado;
- run #296 / `37154531785`: 175 directed; 918 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18.6/migrations/invariantes, prompts e tools sync GREEN;
- peers seguem 10/10/10;
- catálogo segue 37 / 34 públicas / 3 ocultas.

Rolling volatility permanece somente no Quant Core; para expô-la será obrigatório definir janela, default/premissa e compactação de série antes de código.

## Atualização pós-risco 1.1 — rolling volatility

- `quant.risco_retorno` 1.1.0 segue pública/GREEN;
- reauditoria pós-risco concluída;
- rolling volatility selecionada como próximo gap de contrato/apresentação;
- Quant Core já possui `rolling_volatility()`;
- target eventual 1.2.0, sem nova tool;
- design congelado em `.ai/RISK_ROLLING_VOLATILITY_DESIGN_2026-10-03.md`;
- próximo gate = shadow interno + equivalência 1.1.0;
- Brent/fair value continuam bloqueados por seus respectivos source/governance gates.

## Atualização — rolling volatility shadow GREEN
- shadow interno implementado em `_risco_retorno_rolling_shadow.py`;
- sem tool nova, sem semver público novo e sem policy/planner/bloco;
- `quant.risco_retorno` segue 1.1.0 pública;
- run #311 / `37161330785` GREEN;
- full suite: 925 passed / 52 skipped / 19 warnings / 0 failed;
- rolling reutiliza Quant Core e exige janela explícita;
- próximo gate = PostgreSQL específico do shadow + adjusted/raw + payload/provenance/readiness;
- target 1.2.0 ainda não promovido.

## Atualização — rolling volatility CI/readiness GREEN
- commit funcional: `3794088a0cd9e6a0b0e00ae1e8cb1ca634a3f38d`;
- run #319 / `37162064025`: GREEN;
- 188 directed;
- 931 passed / 52 skipped / 19 warnings / 0 failed;
- PostgreSQL adjusted/raw end-to-end GREEN;
- payload <5 KB e provenance/readiness GREEN;
- golden/replay 1.1.0 congelado;
- `quant.risco_retorno` ainda 1.1.0 pública;
- próximo gate = policy governada + cutover 1.2.0 + planner/bloco/evals;
- Brent/fair value continuam bloqueados pelos gates já documentados.

## Atualização final — risco rolling encerrado em 1.2.0
- `quant.risco_retorno`: **1.2.0 pública/GREEN**;
- rolling histórico opcional na mesma tool; nenhuma tool paralela;
- policy: `ANALISE_PARAMS.risco_janela_movel_observacoes=21` (observações de retorno);
- janela explícita do cliente prevalece;
- replay 1.1.0 congelado em módulo legacy + golden;
- adjusted/raw semantics preservadas;
- compactação mensal + cap 60; payload <5 KB;
- planner/bloco/evals atualizados;
- commit funcional: `3786af082eba5e99e14908340bd3bc649872fbdb`;
- run #334 / `37162747600`: GREEN;
- 186 directed;
- peers 10/10/10;
- full suite 929 passed / 53 skipped / 19 warnings / 0 failed;
- prompts/tools sync GREEN;
- catálogo 37 / 34 públicas / 3 ocultas.

Próximo gate: reauditar gaps restantes de Company & Market Analytics e escolher uma única tranche por reuse-before-build. Brent e fair value continuam bloqueados pelos gates já documentados.

## Atualização — próxima tranche pós-risco 1.2: Brent source/factor foundation
- risco rolling encerrado em `quant.risco_retorno` 1.2.0;
- próxima frente selecionada: Brent spot / EIA;
- série candidata: `RBRTE` = Europe Brent Spot Price FOB, USD/barril;
- source identity tecnicamente identificado;
- payload machine-readable físico e metadata específica de copyright/licença ainda pendentes;
- gap corrigido: fonte + schema/fundação + loader/factor contract;
- `FactorKind` atual não possui commodity;
- `market.index_definitions` não comporta USD/barril sem abuso semântico;
- matemática de retornos/dependência/sensibilidade/regimes já existe;
- próxima ação = materializar payload EIA + hash + copyright metadata; não implementar antes;
- fair value/reverse DCF continua bloqueado por governança/matemática;
- Portfolio Analytics fora do escopo.

