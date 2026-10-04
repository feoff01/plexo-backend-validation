# Checkpoint — FQ4.1 Análise Condicional

Data: 2026-09-21
Base: FQ3.3
Estado: implementação local concluída em shadow; produção não alterada.

## Entregue

- `app/market/analytics/conditional.py` puro;
- `ConditionMeasure`, `ConditionDirection`, `ConditionChangeObservation`, `ConditionalResponsePair`, `ReturnSampleSummary`, `ConditionalReturnAnalysis`;
- `quant.analise_condicional` 1.0.0, `exposed_to_llm=False`;
- condicionante ativo/índice em pontos -> retorno simples;
- condicionante taxa/percentual -> mudança do nível;
- retorno simples do ativo no mesmo intervalo da condicionante, endpoints as-of backward sem look-ahead;
- baseline vs condicional; alta/queda/neutro;
- output sem série/pairs;
- métricas preservadas com `serie_curta`; `sem_eventos_condicao` quando não há eventos;
- bloco determinístico específico.

## Validação

- 19/19 testes FQ4.1;
- 400 cenários sintéticos de partição/alinhamento sem look-ahead;
- invariância à escala dos preços da resposta;
- shadow fora do catálogo do Analista;
- fingerprint cobre tool + Data Foundation + models/returns/statistics/conditional;
- regressão ampla sem DB: 343 passed, 16 skipped, 355 DB-deselected, 0 failed;
- `compileall`: verde;
- registry: 27 tools únicas, 8 visíveis no Analista;
- sem `.env` no working copy e sem conflict markers.

## Decisões que não podem ser esquecidas

1. Intervalos vêm da condicionante; não comparar série esparsa com um único retorno diário.
2. Taxa condiciona por mudança do nível, nunca pelo carry convertido em retorno.
3. Resposta usa retorno simples por intervalo.
4. Analysis é descritiva; não usar linguagem de causalidade/significância.
5. Amostra curta mantém números, mas é marcada insuficiente.
6. Tool permanece shadow até PostgreSQL CI/sync.

## Próximo ponto exato

1. Rodar PostgreSQL verify + tool/prompt sync pendente do FQ3.
2. Incluir FQ4.1 no gate DB completo.
3. Se verde, promover `quant.analise_condicional` com semver patch e atualizar planner/evals.
4. Depois desenhar FQ4.2 `quant.sensibilidade` e um contrato de estimativa/incerteza antes da regressão.
