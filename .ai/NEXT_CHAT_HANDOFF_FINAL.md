# Plexo Backend — Handoff Final Canônico

Atualizado em: 2026-10-03
Repo autorizado: `feoff01/plexo-backend-validation`
Branch: `bootstrap/plexo-project`
Código funcional validado: `c3d7cc95f6ef896a5463397b6a323a0325f3c9f0`
CI funcional de referência: run #202 / `37135725129` — **success**
HEAD documental validado: `f568d1dd2a228216537a600debd7c83a569aeb27`
CI do HEAD documental: run #216 / `37139839922` — **success**

> Este arquivo substitui os handoffs antigos. A história detalhada permanece em CHANGELOG, DECISIONS e checkpoints.

## Ordem de leitura

1. `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
2. `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
3. `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`
4. `.ai/PROJECT_STATE.md`
5. `.ai/DECISIONS.md`
6. `.ai/TASKS.md`
7. `.ai/CHANGELOG.md`
8. `.ai/WORKING_PROTOCOL.md`
9. checkpoints citados abaixo.

## Estado executivo

- FQ0.5–FQ4: encerrados;
- consolidação factor/dependence: encerrada;
- FQ5.1–FQ5.4: encerrados;
- FQ5.5 tendências fundamentais: pública/GREEN;
- FQ5.6 peers/setor + issuer bridge + IBrA + batch/performance: pública/GREEN;
- FQ5.7 yield-curve foundation: GREEN/shadow/sem tool pública;
- próximo gate: payload físico oficial ANBIMA.

Gate funcional atual:
- 135 directed passed;
- peers 10/10/10 queries para 2/8/20;
- 896 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18/migrations/invariantes verdes;
- prompts/tools sync verdes.

## Escopo

Continuar somente empresa/mercado. Não abrir Portfolio Analytics, suitability ou análise da carteira/vida financeira do cliente nesta frente.

## Arquitetura

LLM interpreta/roteia/explica. Código determinístico carrega/calcula/valida/versiona/provenance.
Preservar semver, fingerprint, replay, content-addressed cache, outputs compactos e gates.
Aplicar reuse-before-build antes de qualquer capacidade nova.

## Catálogo público importante

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

Ocultas/replay:
- quant.retorno_volatilidade 1.0.4
- quant.correlacao 1.0.3
- quant.dependencia_macro 1.0.1

Não existe alias registrado quant.event_study_v2.

## FQ5.6 fechado

Checkpoint: `.ai/checkpoints/2026-10-03_FQ5_6_PEERS_PROMOTION_GREEN.md`.

- classificação B3 oficial;
- universo atual IBrA 02/10/2026, 148 componentes;
- coverage setor 146/148 tickers; gaps RIAA3/SAUD3;
- comparáveis company-level;
- subsetor default / setor opt-in;
- batch loader 10 queries constantes;
- sem ranking/recomendação/fair value.

## FQ5.7 — ponto exato

Checkpoint: `.ai/checkpoints/2026-10-03_FQ5_7_YIELD_CURVE_FOUNDATION_GREEN.md`.
Auditoria: `.ai/FQ5_7_ANBIMA_PUBLIC_SOURCE_AUDIT_2026-10-03.md`.

Já existe:
- ingestão semântica append-only;
- loader PIT;
- ettj_pre / ettj_ipca / inflacao_implicita;
- du_252;
- sem interpolação/extrapolação;
- sem tool pública.

Ainda falta:
- parser físico congelado contra bytes oficiais;
- medir cobertura histórica real;
- design da primeira intenção client-facing.

Próxima ação obrigatória: materializar CSV/XML/XLS oficial ANBIMA ou JSON real da API sem credenciais. Não usar scraper HTML nem contrato/form action descoberto por terceiros.

## Pendências transversais

- source priority/conflicts;
- storage histórico;
- vintages corporate actions/FX/macro;
- artifacts genéricos;
- histórico B3 se necessário;
- integração/deploy final.

## Segurança

Não ler/publicar .env/segredos; não editar migrations históricas; não usar banco remoto destrutivamente; não tocar em outros repositórios.

## Prompt pronto para o novo chat

Quero continuar o backend Plexo exatamente do snapshot anexado. Antes de alterar código, leia `.ai/NEXT_CHAT_HANDOFF_FINAL.md`, `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`, `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`, `.ai/PROJECT_STATE.md`, `.ai/DECISIONS.md`, `.ai/TASKS.md`, `.ai/CHANGELOG.md`, `.ai/WORKING_PROTOCOL.md` e checkpoints citados. Trate `.ai/` como memória persistente e atualize-a em cada etapa relevante. Preserve: LLM interpreta/roteia/explica; código determinístico carrega/calcula; semver, fingerprint, provenance, replay, outputs compactos e gates. Não leia .env/segredos, não altere migrations históricas, não use banco remoto destrutivamente e não toque em outro repo. Escopo: empresa/mercado; não abrir Portfolio Analytics/cliente. Estado: FQ0.5–FQ4 encerrados; quant.dependencia 2.0.0 pública; FQ5.5/FQ5.6 públicas/GREEN; FQ5.7 foundation GREEN sem tool pública. Primeiro confirme integridade e o gate de fonte física ANBIMA; não recrie matemática existente.


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


## Atualização FQ5.7 — source gate encerrado / shadow em validação
O source gate não está mais bloqueado. CSV oficial ANBIMA `CurvaZero_.csv` foi materializado via runner first-party e congelado com SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7` (2.899 bytes, referência 02/10/2026). Fixture + parser físico fail-closed existem.

Primeira capability desenhada/implementada: `dados.curva_juros` 1.0.0, ainda shadow e fora do catálogo LLM. Próximo gate é CI PostgreSQL/suíte/sync; não promover antes de GREEN.


## FQ5.7 — gate físico/shadow GREEN
Run #234 / `37145970504` validou o caminho completo bytes oficiais -> parser -> ingestão semântica -> PostgreSQL: 142 directed; 903 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync GREEN. `dados.curva_juros` permanece 1.0.0 shadow. Próximo gate: promoção controlada com bloco determinístico, planner restritivo e readiness; não incluir slope/delta histórico/DV01/choque/forecast.


## FQ5.7 encerrada — dados.curva_juros pública
`dados.curva_juros` 1.0.1 está pública/GREEN. Fonte oficial ANBIMA física, parser, ingestão e strict PIT estão fechados. Run #249 / `37146548276`: 145 directed; 906 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync GREEN. Catálogo: 36 tools, 33 públicas, 3 ocultas/replay.

A capability pública lê apenas vértices oficiais exatos de ETTJ PRE/IPCA/inflação implícita. Não interpolar/extrapolar, não calcular delta histórico/slope/DV01/choque/forecast/fair value por composição do LLM.

Não existe FQ5.8 canônica congelada. Próxima ação é reabrir o capability audit de Company & Market Analytics e escolher a próxima lacuna por reuse-before-build. Portfolio Analytics continua fora de escopo.

## Atualização canônica — composição oficial de índice encerrada
`dados.composicao_indice` 1.0.1 está pública/GREEN.

HEAD funcional validado: `d431fa91d5e2e39eb6e2ad0db7be2cecab2c7ffa`.
Run #283 / `37153499452`: **success**.
- 153 directed passed;
- 914 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18.6/migrations/invariantes GREEN;
- peers 10/10/10 preservados;
- prompts/tools sync GREEN;
- catálogo 37 total / 34 expostas / 3 ocultas.

A capability lê snapshots oficiais persistidos de composição/peso, sem nearest, sem inferir histórico ausente, sem performance, recomendação ou análise da carteira do cliente.

Próxima ação: reauditar lacunas restantes no estado atual; aplicar `reuse-before-build` e não assumir FQ nova automaticamente.

## Atualização canônica — quant.risco_retorno 1.1.0 GREEN
- `quant.risco_retorno` 1.1.0 pública;
- adiciona downside deviation anualizada com target periódico zero explícito;
- bloco mostra duração/recovery do pior drawdown em intervalos observados;
- nenhuma nova tool, fonte, schema, loader ou matemática;
- replay legacy preservado após correção de regressão cosmética detectada no run #295;
- HEAD funcional validado `687966a22053136000f39542bb7f1feebcde71cf`;
- run #296 / `37154531785`: **success**;
- 175 directed; 918 passed, 52 skipped, 19 warnings, 0 failed;
- prompts/tools sync GREEN; peers 10/10/10;
- catálogo 37 total / 34 expostas / 3 ocultas.

Próxima ação: reauditoria pós-risco. Rolling volatility não deve ser aberta sem design explícito de janela e compactação.

## OVERRIDE PÓS-RISCO 1.1 — rolling volatility selecionada / design congelado

A reauditoria exigida após o run #296 foi concluída.

Documentos canônicos novos:
- `.ai/COMPANY_MARKET_DELTA_AUDIT_POST_RISK_2026-10-03.md`;
- `.ai/RISK_ROLLING_VOLATILITY_DESIGN_2026-10-03.md`;
- `.ai/checkpoints/2026-10-03_POST_RISK_ROLLING_DESIGN_FROZEN.md`.

Estado:
- `quant.risco_retorno` 1.1.0 continua pública/GREEN;
- rolling volatility já existe no Quant Core;
- gap é contrato/policy/compactação, não matemática/fonte/schema;
- target eventual = 1.2.0;
- nenhuma alteração pública foi feita nesta tranche.

Próximo gate exato:
1. implementar shadow interno não registrado;
2. exigir janela rolling explícita no shadow;
3. preservar semver/exposure/fingerprint/catalog da 1.1.0;
4. provar equivalência integral das métricas 1.1.0;
5. encerrar a tranche;
6. somente depois PostgreSQL 18 + semantics/payload/provenance/readiness;
7. somente depois replay 1.1.0 + policy governada + cutover 1.2.0 + planner/bloco/evals.

Não abrir Brent, fair value ou Portfolio Analytics em paralelo.

## OVERRIDE — rolling volatility shadow GREEN

O shadow interno desenhado na tranche anterior foi implementado e validado.

Prova funcional:
- commit: `bef38e7d2bc44e69bfc931f4d12ee9d7df3a00bd`;
- run #311 / `37161330785`: success;
- 175 directed;
- peers 10/10/10;
- full suite 925 passed, 52 skipped, 19 warnings, 0 failed;
- prompts/tools sync GREEN;
- catálogo 37 / 34 públicas / 3 ocultas.

Implementação:
- `app/tools/analista/_risco_retorno_rolling_shadow.py`;
- sem `@tool`, sem alias, sem registry;
- 1.1.0 pública intacta;
- janela explícita;
- rolling do Quant Core;
- compactação mensal + cap 60;
- métricas-base 1.1.0 preservadas integralmente.

Checkpoint: `.ai/checkpoints/2026-10-03_RISK_ROLLING_SHADOW_GREEN.md`.

Próximo gate exato:
1. integração PostgreSQL específica do shadow usando preparação canônica;
2. adjusted/raw semantics end-to-end;
3. payload representativo <5 KB;
4. provenance/readiness;
5. replay/golden 1.1.0;
6. só então policy governada + cutover 1.2.0 + planner/bloco/evals.

Não promover 1.2.0 antes desse gate.

## OVERRIDE — rolling volatility pronta para cutover 1.2.0

O gate pós-shadow foi encerrado.

Prova:
- commit funcional: `3794088a0cd9e6a0b0e00ae1e8cb1ca634a3f38d`;
- run #319 / `37162064025`: success;
- directed: 188 passed;
- full suite: 931 passed, 52 skipped, 19 warnings, 0 failed;
- prompts/tools sync GREEN;
- catálogo ainda 37 / 34 / 3.

Fechado:
- PostgreSQL específico do candidato;
- adjusted/raw end-to-end;
- payload <5 KB;
- provenance/readiness;
- golden/replay 1.1.0.

Checkpoint: `.ai/checkpoints/2026-10-03_RISK_ROLLING_CI_GATES_GREEN.md`.

Próximo gate permitido:
1. adicionar/aprovar `ANALISE_PARAMS.risco_janela_movel_observacoes`;
2. cutover único `quant.risco_retorno` 1.2.0;
3. mover evolução rolling do shadow para o contrato canônico;
4. planner + bloco + evals;
5. manter replay/golden 1.1.0;
6. PostgreSQL 18 + suíte completa + prompts/tools sync;
7. somente após GREEN encerrar 1.2.0.

Não criar tool paralela; Brent/fair value continuam fora desta tranche.

## OVERRIDE FINAL — quant.risco_retorno 1.2.0 pública/GREEN

Estado funcional mais novo:
- commit funcional validado: `3786af082eba5e99e14908340bd3bc649872fbdb`;
- run #334 / `37162747600`: success;
- directed gate: 186 passed;
- peers: 10/10/10 queries;
- full suite: 929 passed, 53 skipped, 19 warnings, 0 failed;
- prompts check GREEN;
- tools sync --check GREEN;
- catálogo: 37 total / 34 públicas / 3 ocultas-replay.

`quant.risco_retorno` agora é **1.2.0 pública**.

Contrato:
- risco agregado continua default;
- rolling só é calculado com `incluir_evolucao_volatilidade=true`;
- `janela_volatilidade_observacoes` é em observações de retorno;
- janela explícita do usuário prevalece;
- sem janela explícita, policy governada `ANALISE_PARAMS.risco_janela_movel_observacoes=21`;
- sem conversão automática de dias corridos;
- adjusted = `retrospective_as_known_now`;
- raw = `observation_date_cutoff`;
- compactação mensal + cap 60; resumo usa série completa;
- payload representativo <5 KB.

Replay:
- `app/tools/analista/risco_retorno_legacy_1_1_0.py`;
- `tests/golden/quant_risco_retorno_1_1_0.json`.

Checkpoint final:
- `.ai/checkpoints/2026-10-03_RISK_ROLLING_1_2_GREEN.md`.

Próximo gate exato:
1. reabrir capability audit restante de Company & Market Analytics;
2. descontar risco rolling agora encerrado;
3. classificar gaps restantes;
4. escolher uma única próxima tranche por reuse-before-build;
5. congelar design antes de código.

Não assumir nova FQ. Brent/commodities continua dependente de source audit oficial. Fair value/reverse DCF continua dependente de premissas governadas. Portfolio Analytics continua fora do escopo.

## OVERRIDE — pós-risco 1.2: Brent/EIA selecionado para source foundation

Capability audit restante concluído.

Documentos novos:
- `.ai/COMPANY_MARKET_DELTA_AUDIT_POST_RISK_1_2_2026-10-03.md`;
- `.ai/BRENT_EIA_SOURCE_AUDIT_2026-10-03.md`;
- `.ai/BRENT_FACTOR_FOUNDATION_DESIGN_2026-10-03.md`;
- `.ai/checkpoints/2026-10-03_POST_RISK_1_2_BRENT_DESIGN_FROZEN.md`.

Decisão:
- próxima frente = Brent spot / EIA;
- começar por source + commodity-series foundation, sem nova tool;
- fonte candidata = EIA `RBRTE` / Europe Brent Spot Price FOB / USD por barril;
- não confundir com ICE futures/front-month/curva;
- gap real inclui schema/fundação porque `FactorKind` não possui commodity e `index_definitions` não representa USD/barril;
- Quant Core existente deve ser reutilizado.

Gate exato antes de código:
1. materializar payload machine-readable oficial EIA da RBRTE;
2. registrar SHA-256;
3. confirmar unit/frequency/coverage;
4. capturar metadata específica de copyright/licença;
5. congelar fixture/parser contract;
6. só depois source/schema/loader shadow.

Fair value/reverse DCF continua bloqueado. Portfolio Analytics continua fora do escopo.

## OVERRIDE — handoff para Codex / onboarding de base grande

Para uma sessão Codex que receberá acesso à base externa, ler adicionalmente:
`.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`.

Regra de início:
- NÃO conectar tabelas diretamente às tools;
- começar por auditoria read-only da base;
- produzir inventário + tabela->conceito canônico + identity/units/temporalidade/provenance/source-priority/performance;
- classificar cada dataset em: encaixa, adapter, novo tipo canônico, governança temporal ou nova intenção analítica;
- somente nova intenção analítica justifica nova tool.

Atenção de baseline:
- último GREEN integral: HEAD `bf16dfd561f97e136060d77d80f50092cdc4538d`, run #341;
- run #347 do HEAD documental posterior falhou em 2 testes strict-PIT após rollover UTC;
- causa: fixtures históricas fecham ingestion batch com `clock_timestamp()` e usam cutoff fixo 2026-10-03;
- não alterar strict PIT; corrigir determinismo temporal do teste/fixture como primeira higiene técnica.

Depois disso, usar a base grande para decidir o que alimenta tools existentes e só então selecionar uma tranche de integração.

