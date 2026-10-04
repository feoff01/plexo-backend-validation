# Checkpoint — FQ5.6A fonte oficial B3 GREEN

Data: 2026-10-01

## Fonte
- arquivo oficial B3 recebido: `ClassifSetorial(20261002-005309).xlsx`;
- SHA-256: `14c3c9e4bc7c4f13594ac66f33f700138806cb284287df6e3d76a7466e2369c8`;
- 373 códigos únicos;
- 11 setores;
- 41 pares setor/subsetor;
- sem CNPJ/segmento no XLSX.

## Implementação
- parser XLSX oficial;
- adapter company code -> único issuer -> CNPJ;
- persistência reutiliza `ingest_sector_records`;
- ambiguidade entre issuers falha fechado;
- issuer sem CNPJ não é ingerido;
- sem migration;
- sem tool pública.

## Validação
Run #81 / `36949418008`: success.
- gate: 116 passed;
- suíte: 874 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18, migrations, invariantes, validador, prompts e tools sync verdes;
- 34 tools inalteradas.

## Próximo passo
FQ5.6B pode iniciar em **shadow** usando `subsetor`/ `setor`. Promoção pública continua bloqueada até coverage real do catálogo Plexo.
