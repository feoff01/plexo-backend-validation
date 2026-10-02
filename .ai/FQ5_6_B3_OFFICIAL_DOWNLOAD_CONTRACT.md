# FQ5.6A — Contrato do download oficial B3 de classificação setorial

Data: 2026-10-01  
Estado: **fonte oficial materializada; parser/adapter GREEN**

## Arquivo observado

`ClassifSetorial(20261002-005309).xlsx`

SHA-256: `14c3c9e4bc7c4f13594ac66f33f700138806cb284287df6e3d76a7466e2369c8`

O arquivo bruto não é versionado nem redistribuído pelo repositório.

## Estrutura real

- 1 planilha: `Planilha`;
- 375 linhas físicas;
- cabeçalho em duas linhas;
- colunas `SETOR`, `SUBSETOR`, `CÓDIGO`;
- 373 registros;
- 373 códigos únicos;
- 0 duplicatas;
- 0 conflitos;
- 11 setores;
- 41 pares setor/subsetor;
- todos os códigos têm 4 caracteres.

O XLSX não contém CNPJ, ticker completo, segmento econômico de terceiro nível, listing segment ou effective date explícita.

## Validação cruzada

Contra o export Economatica 2025 fornecido pelo usuário:
- 478 tickers B3 ativos;
- 349 códigos-raiz;
- 344/349 códigos-raiz presentes no B3 = **98,57%**;
- 473/478 tickers ativos com raiz presente = **98,95%**.

Isto comprova amplitude externa do download oficial, mas não substitui coverage contra o catálogo real do Plexo.

## Identidade por company code oficial

A regra histórica CNPJ-only é refinada para este contrato B3.

`CÓDIGO` pode resolver um issuer apenas assim:
1. uppercase e exatamente 4 caracteres alfanuméricos;
2. buscar instrumentos `kind='acao'` cuja raiz de quatro caracteres seja igual ao código;
3. considerar somente instrumentos com `issuer_id`;
4. todos os matches devem convergir para um único issuer;
5. o issuer deve possuir CNPJ válido;
6. converter para `SectorSourceRecord` baseado em CNPJ;
7. persistir somente por `ingest_sector_records`.

Fail-closed:
- nenhum issuer -> unresolved;
- mais de um issuer -> ambíguo;
- issuer sem CNPJ -> não ingerir;
- sem fuzzy/name match;
- sem inferir segmento.

Isto é adapter específico do company code oficial B3 observado, não heurística genérica de ticker.

## Temporalidade

O parser não infere `reference_date` do nome do arquivo ou metadata Office. A ingestão recebe a data explicitamente. Availability conhecida pelo Plexo continua sendo `ingestion_batches.finished_at`.

## Implementação

- `app/market/b3_sector_source.py`;
- `app/market/sector_ingest_b3_download.py`;
- sem migration;
- `source_code='b3'`;
- dataset canônico `b3.sector_classification@1`;
- `segment` e `listing_segment` ficam NULL;
- persistência reutiliza `ingest_sector_records`.

## Gate GREEN

Run #81 / `36949418008`:
- gate explícito: 116 passed;
- suíte: 874 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18/migrations/invariantes: verdes;
- prompts check: verde;
- tools sync --check: verde;
- 34 tools inalteradas.

## Consequência para FQ5.6B

A fonte oficial agora é suficiente para iniciar **peers em shadow** nos níveis:
- `subsetor` (default candidato);
- `setor`.

`segmento` permanece indisponível neste contrato e não deve ser inventado.

A promoção pública de FQ5.6B continua condicionada a coverage real do catálogo Plexo ou export equivalente.
