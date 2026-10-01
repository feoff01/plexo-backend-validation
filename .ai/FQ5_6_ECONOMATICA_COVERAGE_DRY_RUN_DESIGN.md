# FQ5.6 — Coverage dry-run Economatica × catálogo Plexo

Data: 2026-10-01
Estado: **design aprovado pelo comando do usuário; implementar somente leitura**

## 1. Objetivo

Medir, sem gravar dados, quanto do snapshot Economatica corrente consegue ser resolvido no catálogo market.instruments / market.issuers do Plexo por ticker exato.

O resultado serve para decidir se FQ5.6B peers pode avançar e para localizar gaps de cadastro.

## 2. Invariantes

- nenhuma escrita no banco;
- nenhuma ingestão implícita;
- nenhum fuzzy/root-code/remoção de -old;
- nenhuma retrodatação;
- raw XLSX não entra no repositório;
- Economatica continua fonte auxiliar;
- B3 continua fonte preferida para segmento/contrato oficial;
- relatório de CI/dev não pode ser apresentado como coverage de produção.

## 3. Entrada

- XLSX Economatica validado pelo parser economatica_sector_source.py;
- conexão PostgreSQL configurada pelo ambiente;
- opcionalmente somente registros já parseados em testes.

## 4. Métricas do relatório

### Fonte
- records_received: tickers únicos elegíveis do export;
- economic_sector_filled;
- subsector_filled.

### Match de ticker
- matched_tickers;
- unmatched_tickers;
- tickers_without_issuer;
- ambiguous_tickers (fail-closed se houver mais de um registro exato após normalização).

### Coverage company-level
- matched_issuers: issuers distintos resolvidos pelos tickers do arquivo;
- matched_issuers_in_universe: issuers resolvidos com pelo menos uma ação is_in_universe=true;
- eligible_universe_issuers: todos os issuers com ao menos uma ação no universo;
- covered_universe_issuers;
- uncovered_universe_issuers;
- universe_coverage_pct.

A unidade de decisão de peers é issuer, não ticker.

## 5. Classificação dos gaps

- ticker_not_found: código Economatica não existe em market.instruments;
- ticker_without_issuer: instrumento existe mas não tem vínculo company-level;
- issuer_outside_universe: issuer resolvido, porém sem ação is_in_universe;
- universe_issuer_not_in_export: issuer do universo não foi coberto pelo snapshot Economatica.

## 6. Implementação

Novo módulo recomendado: app/market/economatica_coverage.py.

Responsabilidades:
- receber EconomaticaSectorRecord;
- normalizar/deduplicar ticker;
- executar apenas SELECTs;
- construir relatório compacto;
- nunca abrir ingestion_batch.

CLI operacional recomendado: tools/economatica_sector_coverage.py --arquivo <xlsx>.

O CLI deve:
- abrir banco via configuração existente;
- colocar a transação em READ ONLY antes das consultas;
- calcular SHA-256 do arquivo apenas para auditoria local;
- imprimir resumo + exemplos limitados;
- não persistir o XLSX nem o relatório no banco.

## 7. Ambientes

### CI/dev
Serve apenas para provar query/contrato. O seed descartável possui universo reduzido e não pode fundamentar decisão de cobertura real.

### Produção/ambiente real
Coverage real só pode ser declarado quando o mesmo comando for executado sobre o catálogo real, em sessão somente leitura, ou contra export não sensível equivalente de ticker, kind, issuer_id, is_in_universe e issuer.

Nenhuma credencial deve ser colocada em .ai/, logs ou artefatos.

## 8. Gate

Antes de FQ5.6B:
1. código dry-run GREEN;
2. zero drift das 34 tools;
3. execução sobre catálogo real ou export equivalente;
4. relatório observado registrado em .ai/ sem dados sensíveis;
5. decisão explícita de source + nível (subsetor ou setor; segmento exige B3).

Sem item 3, FQ5.6B permanece bloqueada por coverage real desconhecida.