# Checkpoint — FQ5.6 Peers / Setor — design e audit de dados

Data: 2026-09-30
Status: **design concluído; tool pública bloqueada por data readiness**

## Achados
- `market.sector_classification` já existe e é append-only;
- não existe coletor/projetor no repo que a preencha;
- a tabela já aponta para `market.ingestion_batches`, permitindo usar `finished_at` como disponibilidade conhecida para novos snapshots sem migration nova;
- B3 é a fonte autoritativa escolhida para a v1;
- B3 declara atualização semanal da base e páginas oficiais expõem CNPJ + classificação;
- classificação é company-level; o schema atual é instrument-level, então ingestão deve casar CNPJ -> issuer e projetar para todas as classes `acao` do emissor;
- root code/prefixo de ticker não é identidade segura;
- linhas legadas sem lote não podem sustentar strict PIT;
- comparação futura deve deduplicar por issuer e reutilizar valuation, FQ5.5 e `statistics.describe`.

## Decisão
Dividir FQ5.6:
1. **FQ5.6A — Sector Data Foundation**;
2. **FQ5.6B — Peer Comparison**.

Não criar `quant.comparaveis_setor` antes da fundação e do coverage gate.

## Próximo passo
Validar contrato técnico oficial B3 (download/API), capturar fixture real e só então implementar parser/ingestão/loader em shadow.

## Código
Nenhum código, migration, tool, semver ou fingerprint alterado nesta etapa.
