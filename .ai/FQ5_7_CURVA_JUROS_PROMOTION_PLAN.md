# FQ5.7 — plano de promoção de `dados.curva_juros`

Data: 2026-10-03
Estado: **promoção autorizada para implementação após shadow + physical ingest GREEN**

## Pré-condições satisfeitas

### Fonte física
- CSV oficial first-party ANBIMA `CurvaZero_.csv` congelado;
- 2.899 bytes;
- SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`;
- parser fail-closed;
- 65 vértices IPCA / 19 PRE / 19 inflação implícita em 02/10/2026.

### Ingestão / PIT
- bridge físico -> semântico reutiliza `ingest_anbima_yield_curve()`;
- 103 linhas canônicas verificadas;
- idempotência por hash GREEN;
- hash inesperado falha antes de escrita;
- loader strict PIT por batch succeeded + finished_at.

### Shadow
- `dados.curva_juros` 1.0.0 registrada e oculta;
- leitura exata por `curve_name`/data/cutoff;
- sem interpolação/extrapolação;
- vértice solicitado e ausente vira warning;
- run #234 GREEN: 142 directed; 903 passed / 52 skipped / 19 warnings.

## Reuse-before-build

Não existe matemática nova necessária para a primeira pergunta client-facing. A capability é uma composição de dados sobre o loader já GREEN.

Não criar:
- migration/tabela;
- engine de curva;
- interpolador;
- Svensson;
- slope/curvature;
- duration/DV01;
- choque;
- forecast.

## Promoção

### Semver
Promover `dados.curva_juros` para **1.0.1** com `exposed_to_llm=True`.

Patch bump porque o contrato shadow 1.0.0 permanece; a mudança é exposição + apresentação/roteamento.

### Planner

Quando presente no catálogo:
- "curva prefixada", "ETTJ nominal" -> `curva="ettj_pre"`;
- "curva real", "curva IPCA" -> `curva="ettj_ipca"`;
- "inflação implícita" -> `curva="inflacao_implicita"`;
- pergunta genérica "curva de juros" -> usar prefixada e explicitar no objetivo que a leitura é da ETTJ prefixada oficial;
- `vertices_du` somente quando a pergunta trouxer vértice explicitamente em dias úteis; não inventar conversão/nearest;
- `em` somente quando houver data econômica explícita;
- Selic/IPCA como série temporal continuam em `dados.serie_indice`.

Não usar a tool para:
- "quanto mudou" entre duas datas;
- slope 2y10y/curvature;
- interpolação ou vértice mais próximo;
- choque de curva;
- duration/DV01;
- forecast de juros;
- fair value/recomendação.

Essas intenções permanecem fora da v1 até capability determinística própria.

### Bloco determinístico

- título identifica PRE/IPCA/inflação implícita e data;
- eixo x = vértice oficial em d.u.;
- eixo y = taxa em `% a.a./252 d.u.`;
- até 20 pontos pode ser tabela; curva completa usa série;
- provenance: ANBIMA, reference_date, cutoff, batch/availability semantics e warnings;
- nota explícita: somente vértices publicados, sem interpolação/extrapolação/forecast/choque.

### Payload

Medição sobre fixture oficial:
- `ettj_ipca` 65 vértices: ~3.326 bytes;
- `ettj_pre` 19: ~1.273 bytes;
- `inflacao_implicita` 19: ~1.267 bytes.

Gate: payload público completo < 5 KB.

## Gate pós-promoção

- registry/readiness;
- catálogo do Analista;
- planner static contract;
- bloco determinístico;
- payload < 5 KB;
- parser/bridge DB tests;
- PostgreSQL 18;
- directed gate;
- suíte completa;
- prompts check;
- tools sync --check;
- checkpoint final em `.ai/`.

Só considerar FQ5.7 client-facing encerrada após CI pós-promoção GREEN.
