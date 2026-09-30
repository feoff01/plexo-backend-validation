# Checkpoint — FQ5.1–FQ5.4 promoted green

Data: 2026-09-30

## Tools públicas
- `dados.fundamentos_empresa` 1.0.0 — SHA `6fddd2c296dc794de56db78a00730834a326195e64890d91e563705dcb37b487`
- `quant.valor_mercado` 1.0.0 — SHA `e92422cf0500b9c5392b4d6022c98104acb203ef581277f6b40e20179f58cc22`
- `quant.cenario_sensibilidade` 1.0.0 — SHA `68ec636f66c6c0cab0e837032a7f3388c3a7342f38225bb04b08925db630b2c1`
- `quant.dependencia_macro` 1.0.0 — SHA `f3178d0b9e14d4a57c36e1667c590a9a94ffdd1386b4d8d15343b814a800e75c`

## Gates
- shadow commit `3611b29a2d39af517eead9b599793b51404fed64`, run #47 `36783804502`: success;
- promoção `8271df65f4db7dbe945a7defc800f9705ed0c30d`;
- run #48: falha somente no teste de catálogo exato F5, corrigido;
- commit de correção `14c522cba2ebabaa95e32e6937879be1557b3256`;
- run #49 `36784983441`: **success**;
- E2E: 74 passed;
- full suite: 816 passed / 52 skipped / 19 warnings / 0 failed;
- validador 0 erros / 0 avisos;
- invariantes SQL normal + plexo_service: verdes;
- prompts check / tools sync --check: verdes.

## Semântica
- market cap/EV/múltiplos ≠ fair value;
- cenário = slope × choque explícito, sem intercepto e sem linguagem de previsão;
- FX dependence ≠ causalidade e não alega vintage PIT perfeito;
- LLM roteia/explica; código carrega/calcula.

## Escopo
Sem Portfolio Analytics, suitability ou análise da carteira/cliente. Próximo foco: tendências fundamentais, peers/setor e fatores; fair value só com premissas explícitas.
