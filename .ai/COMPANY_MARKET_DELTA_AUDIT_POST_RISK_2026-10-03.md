# Company & Market Analytics — delta-audit pós-risco 1.1

Data: 2026-10-03
Estado: **audit concluído; uma única tranche selecionada para design**
Base pública: `quant.risco_retorno` 1.1.0 GREEN
Referência funcional: run #296 / `37154531785`

## 1. Objetivo
Reabrir o capability audit depois da promoção de `quant.risco_retorno` 1.1.0, descontando capacidades já encerradas e classificando somente lacunas reais remanescentes.

Regras mantidas:
- Company & Market Analytics / Analista de Mercado apenas;
- `reuse-before-build` antes de nova tool, fonte, loader, schema ou matemática;
- não abrir Portfolio Analytics, suitability ou carteira do cliente;
- não criar tool por métrica ou por fonte.

## 2. Lacunas remanescentes classificadas
### A. Evolução de volatilidade histórica / rolling volatility
Classificação: **contrato/apresentação**.
Já existe `quant.risco_retorno` 1.1.0, `quant_returns.calculate_returns()`, `quant_risk.rolling_volatility()`, `amostrar_mensal()` e a preparação canônica de série/cutoff/base/semântica/provenance.
Falta contrato explícito de janela móvel, default governado, compactação client-facing, payload/provenance/readiness e planner/bloco/evals.
Conclusão: não requer nova matemática, fonte, tabela, migration, loader nem tool paralela.

### B. Commodity / Brent
Classificação: **fonte + loader**.
Bloqueada até source audit oficial com cobertura, identidade, temporalidade e prioridade de fonte suficientes para produção.

### C. Fair value / reverse DCF
Classificação: **governança de premissas + composição determinística**.
Bloqueada até forecast, WACC, ERP e growth possuírem contrato governado, versionado e auditável.

### D. Histórico B3 de setor/membership
Classificação: **fonte + loader temporal**.
Snapshots correntes oficiais existem; histórico retroativo não deve ser inferido.

### E. Source priority/conflicts + vintages corporate actions/FX/macro
Classificação: **infraestrutura transversal**.
Não é uma tool; vira gate quando uma capability depender explicitamente dela.

### F. Artifacts genéricos / storage histórico / integração-deploy
Classificação: **infraestrutura/ops**, não nova capability analítica.

## 3. Tranche selecionada
Selecionada: **evolução de volatilidade histórica dentro de `quant.risco_retorno`**, sem nova tool.

Motivos:
1. única lacuna conhecida não bloqueada por fonte externa ou premissas de valuation;
2. matemática já existe no Quant Core;
3. preparação de dados e temporalidade já estão resolvidas;
4. gap é de contrato, policy, compactação e apresentação;
5. preserva uma capability canônica de risco.

Target eventual, somente se os gates forem GREEN: `quant.risco_retorno` **1.2.0**.

## 4. Próximo gate
Congelar design em `.ai/RISK_ROLLING_VOLATILITY_DESIGN_2026-10-03.md`.

Depois:
1. shadow interno não registrado;
2. equivalência integral das métricas 1.1.0;
3. PostgreSQL 18 + semantics/payload/provenance/readiness;
4. replay/golden 1.1.0;
5. somente então cutover único 1.2.0 + policy/planner/bloco/evals;
6. suíte completa + prompts/tools sync;
7. promoção/checkpoint GREEN.

Não abrir Brent, fair value ou outra frente em paralelo.
