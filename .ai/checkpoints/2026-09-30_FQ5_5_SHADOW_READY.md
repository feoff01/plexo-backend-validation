# Checkpoint — FQ5.5 Shadow Ready

Data: 2026-09-30
Estado: shadow pronta para gate PostgreSQL 18.

## Implementado
- histórico DFP anual PIT em módulo novo;
- último vintage por `reference_date` conhecido no cutoff;
- até 2..10 períodos por série;
- engine puro de mudança absoluta/YoY e margens EBITDA/líquida;
- EBITDA reportado preferido a `ebitda_derived` no mesmo período;
- sem ITR, CAGR, forecast, fair value ou imputação;
- `quant.tendencias_fundamentais` 1.0.0 oculta do LLM.

## Isolamento
Registry baseline 33; shadow 34. Única adição: `quant.tendencias_fundamentais`. Nenhuma das 33 specs anteriores alterou semver, exposição ou source fingerprint.

## Validação local
- 5 testes focados iniciais: passed;
- 29 testes puros relevantes: passed;
- PostgreSQL local indisponível neste runtime; CI real é gate obrigatório.

## Próximo passo
Publicar shadow no branch autorizado e rodar PostgreSQL 18. Não promover planner/blocos antes do gate verde.
