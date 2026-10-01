# FQ5.6 — Integração auxiliar Economatica para classificação corrente

Data: 2026-10-01
Estado: **design aprovado pelo comando do usuário para prosseguir; implementar somente em shadow**

## 1. Motivo

Os arquivos Economatica fornecidos pelo usuário cobrem setor/subsetor de ações B3 ativas com alta completude, mas não possuem CNPJ/segmento B3 e não representam vintages históricos de cadastro.

Eles podem ajudar o Plexo sem substituir B3/CVM se forem tratados como uma fonte independente e explicitamente corrente.

## 2. Escopo permitido

A primeira integração Economatica cobre somente:
- classificação econômica corrente;
- ações B3/Bovespa marcadas como ativas;
- Setor Econômico Bovespa;
- Subsetor Bovespa;
- identidade por ticker exato.

Fora:
- preços;
- fundamentos;
- múltiplos vendor-derived;
- ativos cancelados como universo de peers atual;
- histórico setorial retroativo;
- segmento B3;
- fallback automático entre fontes;
- tool pública.

## 3. Provenance

Nova fonte:
- code: `economatica`;
- cadence: `eventual`;
- raw files nunca versionados no repo;
- uso/redistribuição sujeitos à licença Economatica do usuário.

Dataset:
`economatica.sector_classification.current@1`.

## 4. Temporalidade

O ano do workbook NÃO é reference_date da classificação.

A ingestão recebe `observed_at`: data em que aquele export passou a ser conhecido pelo Plexo. Essa data é gravada como `reference_date` e a availability continua sendo `ingestion_batches.finished_at`.

Semântica:
`known_at_ingestion_not_historical_vintage`.

É proibido usar workbook 2009 como setor em 2009.

## 5. Identidade

Economatica não fornece CNPJ no export auditado.

Matching permitido:
1. normalizar ticker para uppercase;
2. match exato em `market.instruments.ticker`;
3. exigir `kind='acao'` e `issuer_id` não nulo;
4. obter issuer pelo instrumento;
5. exigir consistência de classificação entre classes encontradas do mesmo issuer;
6. expandir a classificação para todas as classes `acao` do issuer.

Proibido:
- fuzzy match;
- root code;
- remover `-old`;
- casar por nome.

## 6. Parser

Novo módulo:
`app/market/economatica_sector_source.py`.

Parser XLSX somente stdlib ZIP/XML. Não adicionar openpyxl/pandas ao backend.

Headers obrigatórios:
- Bolsa / Fonte;
- Ativo / Cancelado;
- Código;
- Setor Econômico Bovespa;
- Subsetor Bovespa.

`Tipo de Ativo` é opcional porque exports antigos não possuem o campo. Quando presente, somente `Ação`.

Saída:
`EconomaticaSectorRecord(ticker, economic_sector, subsector)`.

Fail-closed:
- xlsx inválido;
- worksheet/header ausente;
- nenhum registro elegível;
- ticker duplicado com classificação divergente.

## 7. Ingestão

Novo módulo:
`app/market/sector_ingest_economatica.py`.

Não alterar `sector_ingest.py` B3.

Reutilizar:
- `market.ingestion_batches`;
- `market.sector_classification`;
- `app.market.ingest.abrir_lote/lote_existente/fechar_lote`.

Campos não disponíveis:
- segment = NULL;
- listing_segment = NULL.

## 8. Source policy

Não existe prioridade automática B3 vs Economatica nesta tranche.

Cada consumer deve escolher a fonte explicitamente. FQ5.6B permanece bloqueada até decidir a política de consumo.

A existência da fonte Economatica não altera a decisão de que B3/UP2DATA é o contrato preferido para segmento/strict PIT oficial.

## 9. Testes

Parser:
- layout 2025;
- layout legado sem Tipo de Ativo;
- filtros Bovespa/ativo;
- header ausente;
- duplicata divergente;
- execução no arquivo real do usuário apenas localmente, sem commit dos bytes.

DB:
- migration registra source;
- ticker exato;
- expansão PETR4 -> todas classes do issuer;
- unmatched reportado;
- idempotência por hash;
- source_code economatica;
- segment/listing NULL;
- divergência no mesmo issuer fail-closed.

Registry:
- 34 tools antes/depois;
- zero semver/exposição/fingerprint drift.

## 10. Critério de avanço

Após CI GREEN:
- integração continua shadow;
- medir coverage contra universo real quando houver snapshot ingerido no ambiente autorizado;
- não liberar `quant.comparaveis_setor` automaticamente;
- decisão de FQ5.6B deve declarar qual source é usada e nível disponível.


## 11. Implementação / validação — 2026-10-01

Design executado em shadow:
- commit `432965518a59d8e2308d7034806d0f36be60701b`;
- run #71 `36887239117` success;
- gate 108 passed;
- full suite 866 passed, 52 skipped, 19 warnings, 0 failed;
- tools sync confirmou 34 tools inalteradas.

Estado: GREEN em shadow. Próximo gate = coverage dry-run no universo real. Não autoriza promoção de peers automaticamente.
