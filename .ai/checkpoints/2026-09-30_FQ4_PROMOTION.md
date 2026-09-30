# Checkpoint — FQ4 Promotion

Data: 2026-09-30

## Base validada

GitHub repository: `feoff01/plexo-backend-validation`  
Branch: `bootstrap/plexo-project`

Run pré-promoção: `36754171560` — **success**.

O run provou em PostgreSQL 18 real:

- migrations do zero;
- seeds/tools/policies/prompts;
- validador sem erros/avisos;
- invariantes SQL;
- FQ1 + F5 + F22 + FQ4 E2E;
- suíte Python completa;
- prompts sem drift;
- tools sem drift.

## Promoção aplicada

- `quant.analise_condicional`: 1.0.0 shadow -> 1.0.1 pública;
- `quant.sensibilidade`: 1.0.0 shadow -> 1.0.1 pública;
- `quant.regimes`: 1.0.0 shadow -> 1.0.1 pública;
- `quant.event_study`: implementação canônica passa para FQ4.4 v2, semver 2.0.0;
- alias `quant.event_study_v2` removido do registry;
- legacy event study preservado sem decorator para golden/replay;
- blocos `quant.event_study` roteados para o mapper v2.

## Testes atualizados

- readiness agora exige as quatro capacidades públicas;
- FQ4 DB E2E executa o código canônico `quant.event_study`;
- testes de condicional/sensibilidade/regimes esperam 1.0.1 e exposição;
- testes de event study esperam 2.0.0 e ausência do alias.

## Gate de fechamento — concluído

Run pós-promoção: `36760273363` (#39) — **success**.

O estado promovido passou novamente em PostgreSQL 18 real:

- migrations do zero;
- seeds/tools/policies/prompts;
- validador sem erros/avisos;
- invariantes SQL;
- FQ1 + F5 + F22 + FQ4 E2E;
- suíte completa: **806 passed, 52 skipped, 19 warnings**;
- `prompts check` verde;
- `tools sync --check` verde.

Durante o fechamento, o CI encontrou dois contratos F5 ainda presos ao catálogo/shape legacy e um golden visual de Event Study. Todos foram atualizados para o contrato promovido. O golden mudou apenas na representação do bloco (indicadores + CAR + AR); os números históricos permaneceram preservados.

**FQ4 está encerrado no branch de validação.**
