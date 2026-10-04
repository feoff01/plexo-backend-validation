# Checkpoint — rolling volatility CI/readiness GREEN

Data: 2026-10-03
Estado: **pronto para policy/cutover 1.2.0; ainda sem promoção**
Commit funcional validado: `3794088a0cd9e6a0b0e00ae1e8cb1ca634a3f38d`
Run: #319 / `37162064025` — **success**

## Gate fechado
A evolução rolling de `quant.risco_retorno` passou pelo gate pós-shadow sem alterar a superfície pública 1.1.0.

Provas adicionadas:
- `tests/test_risk_rolling_shadow_db.py`: preparação canônica real contra PostgreSQL para adjusted/raw;
- `tests/test_risk_rolling_readiness.py`: contrato 1.1 congelado, ausência de registry drift e payload candidato <5 KB;
- `tests/golden/quant_risco_retorno_1_1_0.json`: golden/replay explícito da 1.1.0;
- workflow dirigido agora inclui os testes do shadow/readiness/DB.

## Semântica end-to-end
### adjusted_close
- dataset: `market.v_precos_ajustados`;
- semantics: `retrospective_as_known_now`;
- warning `adjusted_close_retrospective` preservado;
- provenance do ingestion batch preservada.

### raw_close
- dataset: `market.prices`;
- semantics: `observation_date_cutoff`;
- não recebe warning de adjusted retrospective;
- mesma preparação canônica e mesmo cutoff.

## Payload / provenance / replay
- payload candidato representativo: **< 5.000 bytes**;
- resumo rolling calculado sobre a série completa;
- pontos exibidos compactados separadamente;
- evidencia/provenance da 1.1.0 permanece intacta;
- policy `ANALISE_PARAMS` usada pela preparação aparece em metadata;
- golden 1.1.0 congela retorno, volatilidade, downside deviation, drawdown e metodologia;
- shadow continua fora de `source_files`/fingerprint da 1.1.0;
- catálogo permanece 37 / 34 públicas / 3 ocultas.

## Gate #319
- PostgreSQL 18 + migrations/invariantes: GREEN;
- directed gate: **188 passed**;
- peers: **10/10/10** queries;
- full suite: **931 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: GREEN;
- tools sync --check: GREEN.

## Próximo gate permitido
Preparar o cutover único para `quant.risco_retorno` **1.2.0**:
1. aprovar/adicionar policy governada `ANALISE_PARAMS.risco_janela_movel_observacoes`;
2. mover o contrato do shadow para a tool canônica;
3. preservar golden/replay 1.1.0;
4. planner: somente intenções de evolução temporal ativam rolling;
5. bloco determinístico da série rolling;
6. evals/readiness/payload;
7. PostgreSQL 18 + suíte completa + prompts/tools sync;
8. somente após GREEN considerar 1.2.0 pública encerrada.

Não criar tool paralela.
