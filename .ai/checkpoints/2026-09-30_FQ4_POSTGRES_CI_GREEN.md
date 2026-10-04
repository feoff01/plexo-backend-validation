# FQ4 — PostgreSQL CI Green

Data: 2026-09-30
Repositório de validação: `feoff01/plexo-backend-validation`
Branch: `bootstrap/plexo-project`
Run verde: `36753446081`
Commit validado: `7a634ef22d1700635ffbfa6cf383be213de10171`

## Resultado

O gate FQ4 foi executado em PostgreSQL 18 real e descartável no GitHub Actions.

Passaram:

- migrations do zero;
- preparação de seeds/tools/policies/prompts;
- validador estático;
- invariantes SQL;
- invariantes SQL sob `plexo_service`;
- gate explícito FQ1 + F5 + F22 + FQ4 E2E;
- suíte Python completa;
- `prompts check`;
- `tools sync --check`.

Suíte completa: **806 passed, 52 skipped, 19 warnings**.

## Problemas encontrados e corrigidos pelo gate real

1. Fixture FQ4 usava `executemany` em um wrapper async que não expõe esse método; foi substituído por `execute` iterativo.
2. Testes F5/F6 ainda esperavam `final`, mas o comportamento auditável correto após a Data Foundation é `final_with_warnings` quando existem warnings metodológicos como `adjusted_close_retrospective` e fallback de calendário.
3. O E2E de `quant.analise_condicional` confundia `n_total` com a amostra condicional; o contrato real preserva ambos e `evidencia.n_observacoes == n_condicional`.
4. O E2E de `quant.sensibilidade` esperava campos fictícios `beta/n_pares`; o contrato público real usa `n` + `MetricEstimate` em `sensibilidade`/evidência.
5. O E2E de `quant.regimes` esperava `regime_a/regime_b`; o contrato real usa `grupos` tipados, com `alta` e `queda` para critério de direção.
6. Research pipeline passou a provar que `final_with_warnings` corresponde a warnings persistidos, não apenas a uma string de status.

Nenhuma correção alterou a matemática dos engines FQ4.

## Estado de promoção

O gate PostgreSQL exigido em `.ai/FQ4_INTEGRATION_PROMOTION_PLAN.md` está verde.

Ainda NÃO promovidas:

- `quant.analise_condicional` 1.0.0;
- `quant.sensibilidade` 1.0.0;
- `quant.regimes` 1.0.0;
- `quant.event_study_v2` 1.0.0.

Próxima fase: aplicar promoção controlada em branch/PR separado, com patch semver das três primeiras e cutover versionado de event study para o código canônico `quant.event_study`.
