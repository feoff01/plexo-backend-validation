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
