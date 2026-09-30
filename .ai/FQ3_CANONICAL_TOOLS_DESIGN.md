# FQ3 — Canonical Quant Tools Design

Data: 2026-09-21
Estado: FQ3.3 concluído no código; ativação de produção pendente dos gates DB/sync.

## Objetivo

Expor contratos canônicos ao Analista sem duplicar matemática. As novas tools devem orquestrar
`MarketSeriesLoader` + Quant Core e devolver um payload compacto, auditável e semanticamente
explícito. As tools legacy continuam executáveis durante a migração.

## Estratégia de migração

FQ3 será feito em três passos:

1. **FQ3.1 `quant.risco_retorno` shadow**: implementar e testar a nova tool com
   `exposed_to_llm=False`, sem competir com `quant.retorno_volatilidade` no catálogo.
2. **FQ3.2 `quant.dependencia` shadow**: mesmo processo sobre Dependence Core.
3. **FQ3.3 cutover atômico**: expor as duas canônicas, ocultar as duas legacy, atualizar planner,
   blocos/evals/goldens necessários e rodar integração. O executor continua capaz de reproduzir
   execuções legacy deliberadas.

Isso evita duas tools semanticamente sobrepostas visíveis à LLM durante a migração.

## Decisão: RAW_CLOSE vs ADJUSTED_CLOSE em `quant.risco_retorno`

### Default canônico: `adjusted_close`

Para métricas econômicas de desempenho e risco histórico, o default será `adjusted_close` porque
splits, grupamentos, bonificações e proventos podem produzir saltos mecânicos em `raw_close` que
não representam perda/ganho econômica equivalente.

No schema atual, adjusted close é **retrospectivo**. Portanto a combinação é fixa:

- `adjusted_close` -> `retrospective_as_known_now`

A tool sempre devolve `price_basis` e `temporal_semantics`, além do warning
`adjusted_close_retrospective` vindo da provenance.

### `raw_close` somente quando explicitamente pedido

`raw_close` existe para perguntas sobre a trajetória da cotação publicada, auditoria de preço
oficial ou comparação com resultados legacy. Sua combinação é:

- `raw_close` -> `observation_date_cutoff`

`observation_date_cutoff` significa somente que observações com data posterior ao cutoff não
entram. Não é vintage point-in-time: backfills/revisões históricas podem ter sido ingeridos depois.

### Não expor `temporal_semantics` como parâmetro livre

A LLM escolhe apenas `price_basis`. A semântica temporal é derivada deterministicamente da base.
Assim não existe combinação inválida como `adjusted_close + observation_date_cutoff` e reduzimos o
schema/tokens.

## Contrato inicial de `quant.risco_retorno`

### Input

- `ticker` obrigatório;
- `janela_dias` opcional, com default vindo de `ANALISE_PARAMS`;
- `de` / `ate` opcionais;
- `data_referencia` opcional: cutoff pela **data da observação**, nunca promessa de vintage PIT;
- `price_basis`: `adjusted_close` (default) ou `raw_close`.

### Output compacto

A tool não devolve a série inteira. O payload contém somente:

- ticker e período efetivamente usado;
- `price_basis` e `temporal_semantics`;
- retorno acumulado;
- retorno anualizado;
- volatilidade anualizada;
- máximo drawdown;
- detalhe compacto do episódio de maximum drawdown;
- `Evidencia` existente com qualidade/proveniência essencial.

Rolling series, distribuição completa e dados ponto a ponto ficam fora deste contrato inicial para
não explodir tokens. Podem ser blocos/artifacts específicos no futuro.

## Drawdown detalhado

Quando houver episódio de drawdown, devolver:

- pico/fundo/recuperação;
- profundidade percentual;
- intervalos até o fundo;
- intervalos de recuperação;
- duração total em intervalos observados;
- flag `recovered`.

A tool não chama intervalos de "dias" nem "pregões"; essa conversão pertence ao calendário.

## Suficiência e warnings

- `min_observacoes` e `max_dias_defasagem` continuam vindo da policy;
- instrumento desconhecido -> `instrumento_desconhecido`;
- conhecido mas fora do universo -> `fora_da_cobertura`;
- warnings do loader (`calendar_fallback_from_prices`, `adjusted_close_retrospective`) são
  preservados na evidência;
- série insuficiente não inventa zero: métricas permanecem `None`.

## Versionamento/exposição

- `quant.risco_retorno` nasceu em `1.0.0` shadow e está em `1.0.1` com `exposed_to_llm=True` após o cutover;
- `quant.retorno_volatilidade` está em `1.0.4`, registrada porém `exposed_to_llm=False`;
- a source fingerprint da nova tool cobre `_comum.py`, `series.py`, `models.py`, `returns.py`,
  `risk.py` e `statistics.py`.

## Pendência de evidência rica

`Evidencia.metricas` permanece `dict[str, float | None]` neste bloco. O drawdown estruturado vive no
output canônico, evitando alargar `Evidencia` prematuramente. A evolução para `MetricEstimate`
(intervalo de confiança, erro-padrão etc.) será feita antes das análises econométricas de FQ4.


## Estado final FQ3.2/FQ3.3

- `quant.dependencia` foi implementada com Pearson/Spearman, lag assinado e ativo×ativo/ativo×índice, sem rolling/regimes no schema inicial.
- `quant.dependencia` está em `1.0.1`, exposta após shadow validation.
- `quant.correlacao` está em `1.0.3`, oculta para novos turnos/planos e preservada para replay.
- Planner, evals e Research usam apenas os códigos canônicos para novas análises.
- Blocos possuem mapeadores canônicos e mantêm mapeadores legacy para histórico.
- A regra de temporal semantics derivada de price basis vive na Data Foundation (`app/market/series.py`).
- Código-level cutover validado com 324 passed / 16 skipped / 355 DB-deselected / 0 failed.
- Produção permanece pendente de PostgreSQL CI, `tools sync` e sync/aprovação do prompt planner.
