# FQ5.7 — primeira capability client-facing de curva · design

Data: 2026-10-03
Estado: **design aprovado para shadow; promoção pública ainda pendente de gates**

## 1. Reuse-before-build

Gap após o source gate: não existe matemática nova a construir.

Já existem:
- `market.yield_curve` append-only;
- source `anbima`;
- ingestão semântica `anbima.yield_curve.ettj@1`;
- loader PIT `load_yield_curve()`;
- curvas `ettj_pre`, `ettj_ipca`, `inflacao_implicita`;
- provenance por lote/cutoff;
- proibição explícita de interpolação/extrapolação.

Portanto a primeira capability é composição fina sobre o loader existente. Não criar migration, engine quantitativa ou tabela nova.

## 2. Source gate físico encerrado

Payload oficial first-party materializado em 2026-10-03:
- endpoint: `https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp`;
- `Content-Type: text/csv`;
- `Content-Disposition: attachment; filename=CurvaZero_.csv`;
- tamanho: 2.899 bytes;
- encoding observado: ISO-8859/cp1252;
- SHA-256: `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`;
- data econômica no arquivo: 02/10/2026.

Fixture congelada: `tests/fixtures/market/anbima_ettj_2026-10-02.csv`.
Parser físico: `app/market/anbima_yield_curve_source.py`.

Cobertura observada no arquivo:
- ETTJ IPCA: 65 vértices, 252 a 8.316 d.u.;
- ETTJ PRE: 19 vértices, 252 a 2.520 d.u.;
- inflação implícita: 19 vértices, 252 a 2.520 d.u.

A superfície pública ANBIMA declara consulta aos últimos cinco dias úteis. A API Developers aceita parâmetro opcional `data=AAAA-MM-DD`; períodos mais longos dependem do acesso autorizado. Não assumir histórico ilimitado no produto.

## 3. Primeira intenção client-facing

Pergunta coberta: leitura da curva oficial em uma data disponível, opcionalmente em vértices exatos.

Tool proposta:
- code: `dados.curva_juros`;
- family: `dados`;
- semver inicial: `1.0.0`;
- estado inicial: `exposed_to_llm=False` (shadow).

Parâmetros:
- `curva`: `ettj_pre | ettj_ipca | inflacao_implicita`;
- `em`: data econômica exata opcional; ausente = última disponível até cutoff;
- `data_referencia`: cutoff PIT opcional;
- `vertices_du`: lista opcional de até 20 vértices exatos.

Saída:
- curva;
- unidade `% a.a./252 d.u.`;
- data da curva;
- pares `vertice_du` + `taxa_pct_aa_252`;
- contagem total/retornada;
- provenance do loader;
- warnings para vértices pedidos e ausentes.

## 4. Restrições

A tool não:
- interpola;
- extrapola;
- escolhe vértice "mais próximo";
- calcula slope/curvature;
- cria choque de curva;
- calcula duration/DV01;
- prevê juros;
- chama a curva de forecast;
- mistura fechamento com curva intradiária.

## 5. Gate de shadow

Antes de promoção pública:
- parser/fixture oficial GREEN;
- teste de mapeamento físico -> contrato semântico GREEN;
- tool shadow registrada e fora do catálogo LLM;
- PostgreSQL 18 + migrations/invariantes GREEN;
- testes FQ5.7 DB GREEN;
- suíte completa GREEN;
- `prompts check` GREEN;
- `tools sync --check` GREEN;
- revisão de payload compacto/provenance;
- checkpoint `.ai/`.

Somente depois disso decidir promoção `1.0.1` ou equivalente, planner e bloco determinístico.
