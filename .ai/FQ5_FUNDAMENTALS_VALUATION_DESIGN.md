# FQ5 — Fundamentals + Valuation + Market Scenarios

Data: 2026-09-30
Status: **FQ5.1–FQ5.4 implementado, promovido e validado em PostgreSQL 18**

## Escopo
O Analista cobre empresa e mercado. Ficam fora: Portfolio Analytics, suitability, `wealth.*` e análise da carteira/cliente.

## Pergunta de referência
“Quanto Petrobras está valendo, quanto ela pode valer se os juros subirem X e qual a correlação com câmbio?”

Decomposição:
1. `quant.valor_mercado`: preço bruto, market cap multi-classe, dívida líquida, EV e múltiplos;
2. `quant.cenario_sensibilidade`: cenário mecânico apenas quando o choque é explícito;
3. `quant.dependencia_macro`: correlação/dependência com USD/BRL ou outro fator macro.

Sem magnitude de choque, o planner usa `quant.sensibilidade` e não inventa 1 p.p.

## Regra “quanto vale”
Separar:
- preço da ação;
- valor de mercado;
- enterprise value;
- valor intrínseco/fair value.

FQ5.1–FQ5.4 **não produz fair value**. Fair value exige modelo e premissas explícitas (forecasts, WACC/ERP/growth ou comparáveis), nunca defaults inventados pelo LLM.

## Data Foundation
`market.fundamentals` usa:
- `reference_date <= cutoff`;
- `availability_date <= cutoff`;
- scope explícito, default consolidated;
- último DFP anual disponível;
- `value_unit` + currency explícitos;
- `raw` preserva legado, mas não entra em valuation monetário.

Migration nova 0062, sem editar 0061. A chave de vintage inclui `instrument_id` com `NULLS NOT DISTINCT` para suportar shares por classe e manter company-level único.

## Valuation Engine
Cálculos determinísticos:
- market cap = soma preço bruto × shares por classe, somente com cobertura completa;
- net debt direto ou gross debt − cash;
- EV = market cap + net debt;
- P/E apenas com lucro > 0;
- EV/EBITDA apenas com EBITDA > 0;
- P/B apenas com equity > 0;
- FCF yield.

Falha fechada em unidade raw/incompatível, classe sem preço/shares ou denominador inadequado.

## Scenario Engine
Reutiliza FQ4.2:
- impacto incremental = slope × choque explícito;
- preço-cenário = preço bruto base × (1 + impacto/100);
- intercepto não entra;
- CI do slope é propagado deterministicamente;
- cenário que implica preço não positivo falha fechado;
- output declara: associação histórica, não causalidade/forecast/fair value/preço-alvo.

## FX / Macro Factors
`quant.dependencia_macro` reutiliza Returns/Dependence Core.
`market.fx_rates` é adaptado como nível positivo (ex.: USD/BRL).
Como o schema atual de FX não possui availability/vintage completo, a evidência declara `fx_observation_date_cutoff_sem_vintage`.

## Outputs
Compactos, com provenance e warnings. Séries completas e demonstrativos inteiros não entram no contexto do LLM. Blocos só apresentam números já calculados pelas tools.

## Gates
Shadow run #47 `36783804502`: verde.
Promoção inicial run #48 encontrou apenas gate de catálogo desatualizado.
Run pós-promoção #49 `36784983441`: verde.
- E2E 74 passed;
- full suite 816 passed / 52 skipped / 19 warnings;
- prompts check e tools sync --check verdes;
- validador 0/0;
- invariantes SQL verdes.

## Próximas tranches
- FQ5.5 tendências fundamentais PIT;
- FQ5.6 peers/setor;
- fatores adicionais (Brent/petróleo/commodities);
- FQ5.7 fair value/reverse DCF somente após contrato explícito de forecasts e premissas.
