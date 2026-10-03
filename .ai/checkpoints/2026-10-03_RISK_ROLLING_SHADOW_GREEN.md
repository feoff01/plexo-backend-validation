# Checkpoint — rolling volatility shadow GREEN

Data: 2026-10-03
Estado: **shadow interno GREEN / sem promoção pública**
Commit funcional validado: `bef38e7d2bc44e69bfc931f4d12ee9d7df3a00bd`
Run: #311 / `37161330785` — **success**

## Implementado
- criado `app/tools/analista/_risco_retorno_rolling_shadow.py`;
- módulo interno, sem `@tool`, sem alias e sem registro;
- `quant.risco_retorno` pública permanece 1.1.0;
- cálculo-base 1.1.0 é delegado integralmente a `calcular_risco_retorno()`;
- rolling reutiliza `quant_returns.calculate_returns()` + `quant_risk.rolling_volatility()`;
- janela rolling é obrigatoriamente explícita no shadow;
- sem default numérico/policy escondida;
- resumo usa a série rolling completa;
- payload candidato usa último ponto mensal e cap estrutural de 60 pontos, sem recalcular métricas na amostra;
- adjusted/raw temporal semantics são preservadas;
- warnings do candidato permanecem separados do payload/evidência 1.1.0.

## Testes adicionados
`tests/test_risco_retorno_rolling_shadow.py` cobre:
1. equivalência integral do payload 1.1.0 antes dos campos candidatos;
2. equivalência numérica com o Quant Core;
3. janela explícita/inválida e insuficiência sem invenção;
4. raw_close / observation_date_cutoff;
5. compactação mensal + cap 60 preservando resumo da série completa;
6. caminho sem amostragem;
7. ausência de registro/fingerprint/catalog drift.

## Gate #311
- PostgreSQL 18 + migrations/invariantes: GREEN;
- gate dirigido existente: **175 passed**;
- benchmark peers: **10/10/10** queries;
- suíte completa: **925 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: GREEN;
- tools sync --check: GREEN;
- catálogo permanece **37 total / 34 públicas / 3 ocultas**.

Observação: o workflow usou PostgreSQL 18 para os gates do repo, mas os testes novos do shadow são puros. Portanto ainda falta um gate **específico** de preparação/semântica do candidato contra PostgreSQL antes de qualquer cutover.

## Próximo gate exato
1. adicionar/rodar integração PostgreSQL específica do shadow usando preparação canônica;
2. provar adjusted/raw semantics end-to-end;
3. medir payload representativo <5 KB;
4. revisar provenance/readiness;
5. congelar replay/golden da 1.1.0;
6. somente depois aprovar a policy de janela e preparar cutover 1.2.0 + planner/bloco/evals.

Não promover 1.2.0 nesta etapa.
