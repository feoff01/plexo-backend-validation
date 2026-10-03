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
