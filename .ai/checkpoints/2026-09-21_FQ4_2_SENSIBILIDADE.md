# Checkpoint — FQ4.2 `quant.sensibilidade`

Data: 2026-09-21
Estado: código + testes locais concluídos; tool shadow; PostgreSQL/sync pendentes.

## Implementado
- `analytics/regression.py`: OLS univariada com intercepto + HAC/Newey-West Bartlett, correção `n/(n-k)`.
- bandwidth automático `floor(4*(n/100)^(2/9))`, limitado a `n-2`.
- CI bilateral 95% por `statistics.NormalDist`; sem p-value/significant.
- covariance/resíduos centrados para estabilidade numérica com grandes offsets.
- `analytics/sensitivity.py`: driver taxa por mudança de nível; ativo/índice em pontos por retorno; resposta em retorno simples no mesmo intervalo.
- frequência auditável: min/mediana/max dias; lags HAC em observações.
- missing sem imputação; outliers sem winsor/trimming.
- `quant.sensibilidade` 1.0.0 `exposed_to_llm=False`.
- `EvidenciaEstatistica` com `sensibilidade` + `intercepto`; output compacto.
- bloco determinístico e warnings client-facing.

## Edge cases
- n<2: beta indefinido;
- n=2: beta/intercepto definidos, sem SE/CI;
- driver constante: beta/intercepto `None`;
- no look-ahead nos endpoints;
- nenhum NaN/inf.

## Testes
- 27 testes novos FQ4.2 regression/sensitivity;
- 500 regressões sintéticas vs fórmula OLS independente;
- HAC comparado a fórmula de influência independente;
- HAC lag0 comparado ao HC1 de regressão simples;
- invariâncias de escala/translação;
- offset `1e12`;
- tool, output, evidence, block, shadow/fingerprint;
- regressão ampla: 383 passed / 16 skipped / 355 DB-deselected / 0 failed.

## Registry
- base FQ4.2 foundation: 27 tools;
- atual: 28 tools;
- adicionada apenas `quant.sensibilidade`;
- 27 anteriores: 0 mudanças de semver/exposição/source SHA.

## Próximo passo
FQ4.3 `quant.regimes`, com design de regimes explícitos/versionados antes de código. Antes de promoção das tools FQ4: executar PostgreSQL CI + tool/prompt sync.
