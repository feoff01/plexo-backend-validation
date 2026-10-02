# FQ5.6 — Política objetiva do universo de ações

Data: 2026-10-02
Estado: design proposto; implementar somente após contrato de fonte oficial materializado.

## 1. Problema

A fonte setorial B3 e a identidade company-level já estão resolvidas, mas o catálogo projetado deixa `market.instruments.is_in_universe=false` por padrão.

Marcar todas as ações como analisáveis seria uma lista implícita e não auditável. Usar o arquivo de classificação setorial como proxy de universo também mistura duas semânticas diferentes.

O schema F22 já definiu a direção correta: `market.index_weights` existe para tornar o universo objetivo e auditável.

## 2. Regra recomendada para ações

Para a família de análise de ações brasileiras, usar a carteira vigente do **Índice Brasil Amplo (IBrA B3)** como baseline de universo.

Motivos:
- índice amplo da B3;
- critérios objetivos de liquidez e presença em pregão;
- carteira oficial e rebalanceada periodicamente;
- representa melhor o objetivo do Analista do que IBOV/IBrX100 isolados;
- encaixa diretamente no schema `market.index_weights`.

Esta regra vale para `kind='acao'`. ETFs, FIIs, BDRs e outras famílias precisam de regras próprias e não entram por herança.

## 3. Fonte

Não fazer scraping de HTML como contrato de produção.

Antes de código:
1. materializar arquivo oficial B3 da carteira definitiva vigente dos índices;
2. capturar fixture sanitizada do layout real;
3. identificar explicitamente a coluna/código do IBrA;
4. registrar hash/provenance;
5. parsear ticker, peso e quantidade teórica quando disponíveis.

## 4. Schema / migration

`market.index_weights` já existe; não criar tabela nova.

Hoje `market.index_definitions` não possui `ibra`. Se confirmado o contrato oficial do arquivo, criar **migration nova 0064** apenas para registrar:
- code = `ibra`;
- display_name = `Índice Brasil Amplo B3`;
- unit = `pontos`;
- source_code = `b3`.

Não editar migrations históricas.

## 5. Ingestão

Novo parser/source deve produzir registros imutáveis:
- index_code;
- ticker;
- weight_pct;
- theoretical_qty;
- reference_date explícita.

Matching:
- ticker exato -> `market.instruments`;
- sem fuzzy/root matching;
- instrumentos ausentes entram no relatório;
- lote append-only via `market.ingestion_batches`;
- persistência em `market.index_weights`.

## 6. Projeção de is_in_universe

Após ingestão GREEN:
- selecionar a última carteira IBrA `succeeded` conhecida;
- para ações correntes, `is_in_universe=true` se o instrumento integra a carteira vigente IBrA;
- `false` para demais ações;
- atualização deve ser uma operação operacional explícita e auditável, nunca efeito colateral de leitura;
- registrar referência da carteira usada e contagens no log/checkpoint.

A regra não apaga instrumentos nem preços/fundamentos; apenas define cobertura analítica ativa.

## 7. Temporalidade

`is_in_universe` é estado operacional atual. Análises históricas não devem assumir que o booleano atual era verdadeiro no passado.

Para histórico de membership, consultar `market.index_weights` pelo `reference_date`/lote apropriado.

## 8. Coverage setorial após universo

Só após a regra IBrA:
1. medir issuers do universo;
2. medir quantos resolvem no XLSX setorial oficial B3;
3. medir subsetor/setor;
4. registrar unmatched/ambiguous;
5. decidir se `quant.comparaveis_setor` pode ser promovida.

## 9. Performance da tool de peers

Além de coverage:
- benchmark com subsetores pequenos/médios/grandes;
- contar chamadas/queries por peer;
- medir tamanho serializado do output;
- se N+1 for material, criar preparação batch que reutilize os engines existentes — nunca copiar fórmulas;
- manter payload do LLM apenas com distribuições + exemplos compactos.

## 10. Gate

Promoção pública de `quant.comparaveis_setor` exige:
- issuer bridge GREEN;
- fonte/ingestão IBrA GREEN;
- projeção de universo GREEN;
- coverage setorial real registrada;
- benchmark performance/payload GREEN;
- planner/blocos/golden;
- semver/fingerprint/replay;
- PostgreSQL 18 + suíte + prompts/tools sync.

Até lá a tool permanece `exposed_to_llm=false`.
