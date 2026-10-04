# FQ5.6 — Auditoria dos arquivos B3 de índices / universo atual

Data: 2026-10-02
Estado: fonte materializada; implementação de ingestão IBrA autorizada em shadow.

## Arquivos recebidos

### IBRADia_02-10-26.csv
SHA-256: `4bd5a18a2cdc4d4f23d737aa1ac3ca8d213845b06ee32cd240cf9497367eaa04`

Contrato observado:
- título: `IBRA - Carteira do Dia 02/10/26`;
- colunas: Código, Ação, Tipo, Qtde. Teórica, Part. (%);
- 148 componentes;
- soma dos pesos = 100,000%;
- quantidade teórica total = 107.192.487.383;
- data de referência explícita: 2026-10-02.

**Decisão:** este é o arquivo canônico para o universo atual IBrA.

### AcoesIndices_2026-10-02.csv
SHA-256: `c0cfd2fed3afc02c065763d3e38a40b9ff0c29c8c48a2d6e82683944ec2594ed`

Contrato observado:
- relação ação -> índices dos quais participa;
- 469 tickers listados;
- 148 marcados como integrantes do IBrA.

Os 148 tickers coincidem exatamente com `IBRADia_02-10-26.csv`.

**Uso:** validação cruzada de membership; não persistir peso a partir deste arquivo.

### 052503e151e55ee20469d4d86a01d164.xlsx
SHA-256: `44d8a7b280e2f03083ec0363fa0f985de9267c850fd5de59a6db0fe11f1fa1f1`

Contrato observado:
- 40 worksheets de índices B3;
- inclui IBOV, IBRA, IFIX, SMLL e outros;
- aba IBRA tem 148 componentes;
- componentes coincidem exatamente com os dois arquivos acima;
- título da aba IBRA indica virada para setembro de 2026;
- pesos diferem levemente do arquivo diário de 02/10/2026, como esperado para snapshots diferentes.

**Uso nesta tranche:** validação cruzada. Não usar como snapshot de 02/10/2026 e não inferir data diária que o arquivo não declara.

## Limitação histórica

Os três arquivos são snapshots/contratos atuais. Eles NÃO fornecem histórico de membership do IBrA.

Regra:
- podem definir `is_in_universe` operacional atual;
- podem ser persistidos em `market.index_weights` apenas na data explicitamente conhecida;
- não podem responder "quem estava no IBrA em 2022/2024/etc.";
- análises históricas de membership devem consultar snapshots históricos reais quando existirem.

Semântica: `known_at_ingestion_current_snapshot`.

## Cross-check com classificação setorial B3

Usando o XLSX oficial de classificação setorial já fornecido:
- IBrA: 148 tickers;
- 144 raízes/company codes distintas;
- 146/148 tickers têm raiz classificada = **98,65%**;
- 142/144 company codes têm classificação = **98,61%**;
- gaps observados: `RIAA3` e `SAUD3`.

Não preencher esses gaps com Economatica ou heurística. B3 continua source canônica; ausência vira warning/coverage.

## Implementação autorizada

1. migration 0064 registra `ibra` em `market.index_definitions`;
2. parser determinístico do CSV diário B3;
3. ingestão append-only em `market.index_weights`;
4. matching por ticker exato;
5. arquivo com ticker ausente NÃO pode produzir snapshot parcial succeeded;
6. projeção explícita de `market.instruments.is_in_universe` a partir do último snapshot IBrA succeeded;
7. somente `kind='acao'` é afetado;
8. `is_in_universe` é estado operacional atual; histórico fica em `index_weights`;
9. nenhum raw file B3 será versionado no repo.

## Gate

- parser validado contra o arquivo real: 148 componentes / 100%;
- PostgreSQL 18;
- migrations do zero;
- idempotência;
- fail-closed em ticker ausente/conflito;
- projeção true/false apenas para ações;
- 35 tools sem drift;
- coverage setorial observada registrada;
- depois benchmark de `quant.comparaveis_setor`.
