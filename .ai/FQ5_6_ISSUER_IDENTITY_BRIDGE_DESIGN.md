# FQ5.6 — Ponte de identidade issuer para catálogo B3

Data: 2026-10-02
Estado: design aprovado pelo usuário para implementação em shadow.

## Achado

O projetor de acervo já popula `market.instruments` a partir do COTAHIST, porém não cria `market.issuers` nem preenche `instruments.issuer_id`. Por isso o download setorial oficial B3 pode ser parseado, mas não consegue fechar coverage real num catálogo projetado apenas pelo acervo.

## Regra reuse-before-build

Não criar catálogo paralelo e não inventar CNPJ.

O COTAHIST já traz ticker B3, nome do emissor, ISIN e kind. Para ações com ticker validado pelo contrato de `app.market.acervo`, os quatro primeiros caracteres são a raiz B3 usada no arquivo setorial oficial.

## Ponte no projetor

Ao executar `tools/projetar_acervo.py instrumentos`:

1. manter a projeção atual de `market.instruments`;
2. agrupar somente `kind='acao'` por raiz B3 de quatro caracteres;
3. procurar `issuer_id` já ligado a instrumentos da mesma raiz;
4. se não houver issuer, criar `market.issuers(kind='empresa', cnpj=NULL)` usando o nome de emissor mais recente do COTAHIST;
5. se houver exatamente um issuer, reutilizar;
6. se houver mais de um issuer para a mesma raiz, falhar fechado e reportar conflito;
7. preencher `issuer_id` apenas onde estiver NULL nas ações daquela raiz;
8. nunca sobrescrever issuer diferente já existente;
9. rerun deve ser idempotente.

CNPJ continua desconhecido até fonte oficial apropriada fornecê-lo.

## Ingestão setorial B3

O adapter do download oficial não deve exigir CNPJ se já resolveu um issuer único.

Refatorar `sector_ingest.py` para ter um core interno company-level por `issuer_id`:
- rota CNPJ: CNPJ -> issuer_id -> core comum;
- rota download B3: company code -> issuer_id -> core comum.

Toda persistência continua append-only em `market.sector_classification` com `market.ingestion_batches`.

## Temporalidade

A ponte é identidade do catálogo corrente. Não usar a raiz para afirmar identidade histórica em backtests anteriores sem uma fonte temporal própria.

## Gates

- projetor idempotente;
- duas classes da mesma raiz -> um issuer;
- issuer existente preservado;
- conflito multi-issuer falha fechado;
- download B3 setorial funciona com issuer sem CNPJ;
- PostgreSQL 18 completo;
- 35 tools sem drift (`quant.comparaveis_setor` continua shadow);
- depois: coverage real + benchmark de performance/payload.

## Promoção

`quant.comparaveis_setor` continua oculta até coverage real e benchmark GREEN.
