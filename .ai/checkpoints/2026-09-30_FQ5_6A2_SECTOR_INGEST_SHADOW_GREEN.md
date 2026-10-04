# Checkpoint — FQ5.6A2 ingestão setorial shadow GREEN

Data local: 2026-09-30  
Estado: **GREEN / fundação semântica encerrada em shadow**

## Escopo validado
- `app/market/sector_ingest.py` recebe somente registros semânticos já validados;
- nenhuma dependência do formato físico do UP2DATA;
- idempotência por `market.ingestion_batches`;
- matching estrito CNPJ -> issuer;
- expansão de um emissor para todas as classes `kind='acao'`;
- conflito de mesma chave com conteúdo divergente falha fechado;
- snapshot vazio/hash inválido/source diferente de B3 falham antes de tocar o banco;
- coverage PIT factual por segmento/subsetor/setor;
- nenhuma tool pública criada;
- nenhuma migration/schema/Quant Core alterado.

## Fonte física
A B3 publica oficialmente o canal UP2DATA Empresas Listadas / SummaryData e aponta a amostra `Listed_Companies.zip`. Os bytes do ZIP não foram materializados neste runtime.

Consequência: **nenhum parser CSV/JSON/XML foi implementado**. O Catálogo de Taxonomia não é tratado como substituto do layout real do arquivo.

## Prova PostgreSQL 18
Commit shadow: `36ffa05f9cbacd51c04b7887f74be7036c972489`  
Run: #63 / `36801883060`  
Conclusão: success

- migrations do zero: verde;
- validador estático: verde;
- invariantes SQL admin: verdes;
- invariantes SQL `plexo_service`: verdes;
- gate FQ1/F5/F22/FQ4/FQ5/FQ5.5/factor/FQ5.6: **103 passed**;
- suíte completa: **861 passed, 52 skipped, 19 warnings, 0 failed**;
- `prompts check`: verde;
- `tools sync --check`: verde e catálogo inalterado.

## Bloqueios que permanecem
- materializar bytes reais da amostra/arquivo oficial;
- implementar parser físico fail-closed;
- executar ingestão com dataset oficial real;
- medir coverage real por nível;
- decidir gate de cobertura a partir da distribuição observada;
- somente depois abrir FQ5.6B / `quant.comparaveis_setor`.

Nenhum threshold de cobertura foi inventado nesta etapa.
