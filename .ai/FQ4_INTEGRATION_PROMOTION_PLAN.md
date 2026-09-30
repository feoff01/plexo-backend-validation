# FQ4 — Integration & Promotion Plan

Atualizado em: 2026-09-25

## Objetivo

Fechar a integração real das quatro capacidades FQ4 antes de expô-las ao LLM:

- `quant.analise_condicional` 1.0.0 shadow;
- `quant.sensibilidade` 1.0.0 shadow;
- `quant.regimes` 1.0.0 shadow;
- `quant.event_study_v2` 1.0.0 shadow.

A promoção não é autorizada por testes puros isoladamente. O gate exige PostgreSQL 18 real,
migrations, sync, executor, views/loaders e persistência de `tool_executions`.

## Gate PostgreSQL obrigatório

`.github/workflows/verify.yml` agora executa explicitamente:

1. PostgreSQL 18 descartável;
2. `alembic upgrade head` num banco vazio;
3. `tools/preparar_ambiente.py` (seeds/tools/policies/prompts);
4. validador estático;
5. regras invioláveis sob admin e `plexo_service`;
6. FQ1 + F5 + F22 + `tests/test_fq4_integration_db.py`;
7. suíte Python completa;
8. `prompts check`;
9. `tools sync --check`.

O workflow isolado não usa Aiven, EC2, DeepSeek ou segredos de produção.

## E2E FQ4

`tests/test_fq4_integration_db.py` usa o executor real e prova:

- sync das tool versions;
- policy `ANALISE_PARAMS` real no banco;
- ingestão COTAHIST de fixture;
- `market.prices`, `market.index_values` e views reais;
- `MarketSeriesLoader` / `preparar()`;
- `calcular()` puro;
- persistência `tools.tool_executions`;
- cache content-addressed do executor;
- outputs das quatro shadow tools.

A massa é sintética/controlada e toda execução ocorre dentro da transação externa dos testes, com
rollback total no fim.

## Planner preparado sem promoção prematura

`prompts/analista.planner.j2` contém orientação FQ4 condicionada à presença do `tool_code` em
`catalogo_tools`:

- comportamento quando X sobe/cai -> `quant.analise_condicional`;
- sensibilidade por 1 p.p./1% -> `quant.sensibilidade`;
- alto/baixo ou subindo/caindo -> `quant.regimes`.

Enquanto `exposed_to_llm=False`, essas tools não entram em `catalogo_tools`, portanto o planner não
pode usá-las. O prompt também orienta não substituir essas perguntas por mera dependência quando a
tool especializada estiver disponível.

`quant.event_study_v2` não aparece pelo nome no planner. O cutover deve preservar o código canônico
`quant.event_study`.

## Estratégia de promoção depois do gate verde

### Condicional / sensibilidade / regimes

Mudança de `exposed_to_llm` altera o fonte auditado. Portanto a promoção deve fazer patch bump:

- `quant.analise_condicional` 1.0.0 -> 1.0.1;
- `quant.sensibilidade` 1.0.0 -> 1.0.1;
- `quant.regimes` 1.0.0 -> 1.0.1.

Depois:

1. atualizar evals de roteamento;
2. sincronizar tools;
3. sincronizar/aprovar `analista.planner`;
4. executar Research/turn E2E;
5. verificar payload/token usage;
6. promover gradualmente ou em conjunto, conforme resultados.

### Event study v2

A v2 muda o contrato/output, portanto o cutover canônico deve ser tratado como mudança incompatível:

- manter replay puro da 1.0.1;
- `quant.event_study` canônico passa para implementação v2 com **major bump 2.0.0**;
- `quant.event_study_v2` deixa de ser necessário como alias shadow e deve ser removido do registry;
- `tools sync` com desativação de ausentes deprecia/desativa o alias sem apagar histórico;
- planner continua usando apenas `quant.event_study`.

## Critério de GO

Promoção só pode acontecer quando TODOS estiverem verdes:

- workflow PostgreSQL 18;
- FQ4 DB E2E;
- suíte completa;
- `tools sync --check`;
- `prompts check`;
- nenhum conflito de semver/source SHA;
- planner/evals coerentes;
- outputs compactos dentro do budget.

## Critério de NO-GO

Qualquer um bloqueia promoção:

- migration falha;
- view adjusted falha;
- shadow tool não executa pelo executor real;
- cache/hash divergente;
- tool/prompt drift;
- warning/coverage contraditório;
- payload cresce além do budget;
- regressão em FQ1/F5/F22.

## Limitação deste runtime

Neste ambiente de ChatGPT não existem binários PostgreSQL/Docker e DNS externo está bloqueado.
Portanto o gate DB foi escrito, ligado à CI e validado estaticamente, mas o run PostgreSQL não pode
ser declarado verde até ser executado por um runner com PostgreSQL 18 (ex.: GitHub Actions).
