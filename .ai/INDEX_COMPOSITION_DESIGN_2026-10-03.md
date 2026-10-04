# Company & Market Analytics — composição oficial de índice · design

Data: 2026-10-03
Estado: **design aprovado para shadow; sem promoção pública**

## 1. Pergunta / intenção

Ler a composição oficial de um índice em um snapshot disponível:
- membros;
- pesos oficiais;
- quantidade teórica quando publicada;
- presença/peso de tickers explicitamente pedidos.

Não é:
- série histórica do nível do índice;
- performance;
- recomendação/ranking de investimento;
- composição de carteira do cliente;
- inferência de membership histórico onde não existe snapshot.

## 2. Reuse-before-build

Reutilizar:
- `market.index_definitions`;
- `market.index_weights`;
- `market.ingestion_batches`;
- identidade de `market.instruments`;
- ingestão B3/IBrA já GREEN.

Não criar:
- migration;
- tabela paralela;
- matemática;
- scraper/download de produção;
- snapshot retroativo derivado de `is_in_universe`.

## 3. Loader shadow

Módulo novo somente leitura: `app/market/index_compositions.py`.

Contrato:
- `index_code`;
- `cutoff`;
- `reference_date` opcional;
- `strict_pit=True`.

Semântica:
- se `reference_date` omitida: maior snapshot <= cutoff pertencente a lote `succeeded` com `finished_at::date <= cutoff`;
- se explícita: usar somente essa data; nunca nearest/fallback silencioso;
- cada linha retorna ticker, nome, peso e quantidade teórica;
- validar ticker único no snapshot, peso finito/faixa [0,100] e soma do snapshot próxima de 100%;
- provenance inclui source, batch, reference_date, availability_date/cutoff e warnings.

Coverage atual conhecida: IBrA B3, referência 02/10/2026, 148 componentes. O contrato é genérico para qualquer `index_code` que venha a ter snapshot validamente ingerido; não prometer índices sem dados.

## 4. Tool shadow

Candidata: `dados.composicao_indice` 1.0.0, `exposed_to_llm=False`.

Parâmetros:
- `indice`: código do índice;
- `em`: snapshot econômico exato opcional;
- `data_referencia`: cutoff PIT;
- `tickers`: até 20 tickers exatos opcionais;
- `limite`: default 10, máximo 25 quando `tickers` ausente.

Saída compacta:
- índice/display name;
- data do snapshot;
- `n_componentes_total`;
- `peso_total_pct`;
- componentes retornados;
- `truncado`;
- provenance/warnings.

Sem `tickers`, ordenar apenas para apresentação por peso oficial desc + ticker, com limite. Isso é ordenação factual do snapshot, não recomendação.
Com `tickers`, retornar somente correspondências exatas e warnings para ausentes.

## 5. Gates

Antes de qualquer promoção:
- testes puros do contrato;
- PostgreSQL E2E com ingestão -> loader -> tool shadow;
- strict PIT/look-ahead;
- data explícita sem fallback;
- missing ticker warning;
- payload < 5 KB no limite máximo;
- registry permanece com somente a nova tool shadow;
- suíte completa;
- prompts check;
- tools sync --check;
- checkpoint em `.ai/`.

Planner/bloco client-facing só depois do shadow GREEN.
