# Checkpoint — FQ5.7 cobertura física ANBIMA e cleanup

Data: 2026-10-03
Status: **GREEN / fonte física revalidada / workflows temporários removidos**

## Fonte física oficial

A superfície first-party ANBIMA foi auditada diretamente no runner do repositório autorizado.

Arquivo-base congelado:
- endpoint oficial: `https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp`;
- referência: 02/10/2026;
- `Content-Type: text/csv`;
- arquivo: `CurvaZero_02102026.csv`;
- tamanho: 2.899 bytes;
- SHA-256: `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`;
- parser/fixture canônicos já presentes no repo.

## Cobertura física da janela pública

O formulário first-party define `Dt_Ref_Ver=20260925` no estado auditado. O fluxo de download oficial é POST direto para `CZ-down.asp`.

Foram materializados arquivos distintos e válidos para:
- 02/10/2026 — `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`;
- 01/10/2026 — `a8fabca0c437e6520b84939b7c074121ba973cd77b61955cd04a9ae3ae6f9a87`;
- 30/09/2026 — `550d7fc277333ce8d4e88d4a43ab856ce84778f1eed163935e52a9d2adf4d9f4`;
- 29/09/2026 — `bfd3686b19793209cd5248c275f33ea938e9fe1348587f4e9734816517895ca1`;
- 28/09/2026 — `54b15c0b6a12455e97b1e97b5bfda4c66c2573f6f8a1d92a53f0d2a196620ab5`;
- 25/09/2026 — `9794c267c2934af72bfc5d29046c454d9caa52cca77247b5e8b5cf3d2be9c220`.

O parser canônico aceitou as seis datas; em cada uma a tabela ETTJ observada tem 65 vértices IPCA, 19 PRE e 19 inflação implícita.

O servidor também respondeu para 24/09/2026. Esse fato **não** amplia o contrato suportado: a UI first-party auditada delimitava 25/09/2026 e a página pública anuncia uma janela curta. Não retroagir retenção do servidor como histórico garantido.

## Capability pública

`dados.curva_juros` 1.0.1 permanece pública e sem mudança de código desde o head validado pelo run #249 / `37146548276`:
- 145 directed passed;
- 906 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18.6/migrations/invariantes GREEN;
- prompts/tools sync GREEN;
- catálogo 36 total / 33 públicas / 3 ocultas.

A comparação do head validado `75535846a77ce0fe3def304d5bacfc62c53d38f8` com a branch após a auditoria mostrou somente documentação e workflows temporários; nenhum código de produto posterior.

## Cleanup

Os workflows temporários usados exclusivamente para materialização/auditoria first-party foram removidos da branch. Nenhum cliente HTTP/scraper ANBIMA foi incorporado ao produto.

## Próximo gate

Reabrir o capability audit de Company & Market Analytics com o estado atual e aplicar reuse-before-build. Não assumir uma FQ5.8 nem criar nova tool antes de provar a lacuna real.
