# Checkpoint — FQ4.2 Statistical Estimates Foundation

Data: 2026-09-21

## Estado

Fundação de estimativa/incerteza concluída. Nenhuma regressão foi implementada.

## Arquivos novos

- `app/market/analytics/estimates.py`
- `app/tools/analista/evidencia_estatistica.py`
- `tests/test_fq4_statistical_estimates.py`
- `.ai/FQ4_2_STATISTICAL_ESTIMATES_DESIGN.md`

## Arquivo alterado de runtime

- `app/agents/analysis.py`: finding quantitativo inclui `estimativas` apenas quando presentes.

## Contrato

`MetricEstimate`: estimate, unit, n, standard_error, confidence_interval, method, warnings.
`ConfidenceInterval`: lower, upper, level, method opcional.

Estimate indefinido não pode carregar SE/CI e exige warning. Sem NaN/inf. Sem p-value/significant no envelope.

## Compatibilidade

- `Evidencia` base não mudou;
- `_comum.py` não mudou;
- `analytics/models.py` não mudou;
- 27/27 tool specs mantiveram semver/exposição/source SHA do FQ4.1.

## Testes

- 13 testes específicos do contrato: verdes;
- FQ4.1 + foundation: 32 verdes;
- regressão sem DB: 356 passed, 16 skipped, 355 deselected, 0 failed;
- compileall/py_compile: verdes.

## Próximo passo

Desenhar `quant.sensibilidade`/Regression Engine sem ainda expor tool: resposta, driver, transformações, unidade do slope, OLS/covariance estimator, CI, amostra mínima e linguagem não causal.
