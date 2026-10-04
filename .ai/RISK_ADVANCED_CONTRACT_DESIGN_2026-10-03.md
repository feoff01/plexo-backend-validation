# Company & Market Analytics — evolução compacta de risco histórico

Data: 2026-10-03
Estado: **design aprovado para implementação candidata / sem nova tool**

## 1. Reuse-before-build

Perguntas alvo:
- "qual o downside risk / semidesvio deste ativo?";
- "quanto tempo durou a maior queda?";
- "quanto tempo levou para recuperar depois do fundo?".

Já existe:
- `quant.risco_retorno` pública;
- `app/market/analytics/risk.py`;
- `annualized_downside_deviation()`;
- `maximum_drawdown_episode()` com duração e recuperação;
- `DrawdownDetail` já expõe `duration_intervals` e `recovery_intervals`.

Gap real:
- **contrato/apresentação**, não fonte, schema, loader ou matemática.

Decisão: evoluir a tool canônica existente. Não criar `quant.downside_risk`, `quant.drawdown_recovery` ou variante paralela.

## 2. Escopo 1.1.0

Adicionar ao output:
- `downside_deviation_anualizada_pct`;
- `downside_target_periodic_pct = 0.0`.

Definição já congelada no Quant Core:
`sqrt(mean(min(r_i - target, 0)^2)) * sqrt(periods_per_year)`.

A métrica usa o mesmo método de retorno já resolvido pela tool e target periódico zero. O target aparece explicitamente no output e na nota metodológica; não é forecast, benchmark ou hurdle de investimento.

Apresentação:
- bloco de `quant.risco_retorno` inclui downside deviation quando disponível;
- bloco inclui duração do pior drawdown em **intervalos observados**;
- se recuperado, inclui intervalos fundo -> recuperação;
- não converter intervalos em dias corridos/pregões sem calendário explícito.

Planner:
- retorno/volatilidade/max drawdown continuam roteando para a mesma tool;
- "downside risk", "semidesvio", "duração do drawdown" e "tempo de recuperação da maior queda" também roteiam para `quant.risco_retorno`.

## 3. Fora desta tranche

- rolling volatility / série móvel;
- Sharpe, Sortino, Calmar;
- VaR / Expected Shortfall;
- beta/correlação;
- stress/choque;
- previsão;
- recomendação;
- Portfolio Analytics;
- comparação com carteira do cliente.

Rolling volatility já existe no core, mas exige contrato de janela + compactação de série. Não será adicionada apenas porque a matemática existe.

## 4. Versionamento / replay

- `quant.risco_retorno`: **1.0.1 -> 1.1.0**;
- bump minor porque há funcionalidade pública aditiva, não apenas mudança de exposição;
- métricas 1.0.1 permanecem numericamente idênticas;
- source fingerprint continua cobrindo `risk.py` e dependências declaradas;
- execuções históricas continuam identificadas por semver/source fingerprint/output persistido.

## 5. Gates

Antes de considerar GREEN:
- testes puros preservando métricas 1.0.1;
- downside deviation = 0 em caminho sem retornos abaixo de zero;
- downside deviation numérica em caminho misto;
- série insuficiente não inventa métrica;
- bloco mostra intervalos sem chamá-los de dias;
- planner roteia as novas intenções sem criar tool paralela;
- payload continua compacto;
- PostgreSQL 18/migrations/invariantes;
- directed gate;
- suíte completa;
- prompts check;
- tools sync --check;
- checkpoint em `.ai/`.
