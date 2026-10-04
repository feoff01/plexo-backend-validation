# FQ5.6A2 — Ingestão setorial semântica em shadow

Data: 2026-09-30  
Estado: **implementação shadow; parser físico UP2DATA continua bloqueado até fixture oficial real**

## 1. Motivo

A B3 publica oficialmente o canal UP2DATA **Empresas Listadas**, com o subcanal `SummaryData`, e a página oficial de dados disponíveis expõe um link de amostra `Listed_Companies.zip`.

Nesta execução o link oficial foi identificado, mas o ambiente não conseguiu materializar o ZIP binário. O Catálogo de Taxonomia da B3 confirma campos de identidade/classificação de emissor como `IssuerCNPJ` e `EconomicActivityName`, porém isso **não é prova suficiente** de que o layout observado no catálogo seja exatamente o `SummaryData` atual da amostra.

Portanto o gate anterior continua válido: nenhum parser CSV/JSON/XML será inventado sem bytes reais de uma amostra oficial.

## 2. Fontes oficiais verificadas

- Dados disponíveis UP2DATA: https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/up2data/dados-disponiveis/
- Amostra oficial apontada pela página acima: https://www.b3.com.br/data/files/DE/41/55/00/A0A9C910F37907C9AC094EA8/Listed_Companies.zip
- Catálogo de Taxonomia UP2DATA: https://www.b3.com.br/data/files/1E/F0/54/58/FADF371045F0BD37AC094EA8/Catalogo_de_Taxonomia_UP2DATA_-_Portugues.pdf
- Monitor UP2DATA: https://up2data.b3.com.br/

O monitor confirma atividade recente do subcanal `Listed Companies > Summary Data`, mas não substitui a necessidade de validar o layout real do arquivo.

## 3. Decisão arquitetural

Separar definitivamente:
1. **source parser** — transforma bytes oficiais B3 em registros semânticos;
2. **sector ingest** — recebe registros semânticos já validados e grava o schema;
3. **sector loader** — lê PIT para análises;
4. **peer analytics** — só depois de coverage gate.

O parser permanece bloqueado. A ingestão semântica pode avançar porque não depende do formato físico do fornecedor.

## 4. Contrato semântico shadow

Novo módulo: `app/market/sector_ingest.py`.

`SectorSourceRecord` contém somente:
- `issuer_cnpj` — exatamente 14 dígitos já normalizados;
- `economic_sector`;
- `subsector`;
- `segment`;
- `listing_segment`.

Ele não conhece nomes físicos de colunas/tags da B3.

## 5. Regras de ingestão

- fonte v1 fixa = `b3`;
- dataset fixo = `b3.sector_classification@1`;
- snapshot vazio falha antes de abrir lote;
- `reference_date` futura falha;
- `file_hash` deve ser SHA-256 hex de 64 caracteres;
- idempotência usa `market.ingestion_batches` existente;
- matching é **somente CNPJ -> market.issuers.cnpj**;
- não há fuzzy match por nome nem prefixo/root code de ticker;
- um emissor casado é expandido para todas as suas classes `kind='acao'`;
- mesma PK já existente com conteúdo igual é tratada como já presente;
- mesma PK com conteúdo diferente falha fechado antes de inserir;
- corrida concorrente materialmente conflitante marca lote `partial` e falha fechado;
- `storage_key` pode ser persistido no lote enquanto ele ainda está `running`;
- gravação em `market.sector_classification` continua append-only.

## 6. Coverage gate

`measure_sector_coverage()` mede, por cutoff e por nível explícito (`segmento`, `subsetor`, `setor`):
- emissores elegíveis com ação `is_in_universe=true`;
- emissores com classificação PIT `succeeded` disponível até o cutoff;
- percentual factual de cobertura;
- exemplos limitados de emissores/tickers sem classificação.

Não existe limiar automático nesta etapa. O valor mínimo aceitável deve ser decidido depois de medir dados reais, não inventado no código.

## 7. Reuse-before-build

A implementação reutiliza:
- `app.market.ingest.abrir_lote`;
- `app.market.ingest.lote_existente`;
- `app.market.ingest.fechar_lote`;
- schema `market.ingestion_batches`;
- schema `market.issuers` / `market.instruments`;
- schema `market.sector_classification`;
- loader PIT `app/market/sectors.py`.

Não cria migration, tabela, math engine ou tool.

## 8. O que permanece bloqueado

- parser de `Listed_Companies.zip` / SummaryData;
- job HTTP/UP2DATA;
- fixture real do arquivo;
- coverage real do universo;
- `quant.comparaveis_setor`.

Esses itens só avançam após materialização autorizada de bytes oficiais (amostra pública ou arquivo UP2DATA obtido por acesso autorizado).
