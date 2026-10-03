# FQ5.6 — Batch loader de métricas de peers

Data: 2026-10-03
Estado: design aprovado pelo comando do usuário para corrigir N+1 antes da promoção.

## Baseline

Run #145 / 37068258563:
- 2 peers: 38 queries;
- 8 peers: 98 queries;
- 20 peers: 218 queries;
- fórmula observada: aproximadamente 18 + 10 × N;
- output público ~4 KB e praticamente constante;
- cálculo puro não é gargalo.

Conclusão: o gap é carregamento/orquestração, não matemática.

## Regra reuse-before-build

Nenhuma fórmula de valuation, crescimento, margens ou estatística será copiada.

O batch deve reutilizar:
- FundamentalsLoader;
- FundamentalHistoryLoader;
- valuation/calculadores das tools canônicas;
- MarketPriceSnapshot e a mesma regra de múltiplas fontes;
- FundamentalRecord/Provenance existentes.

## Arquitetura

Novo módulo: app/market/peer_company_metrics.py.

Ele recebe company requests já resolvidos pelo universo setorial:
- issuer_id;
- representative_ticker.

Faz em lote:
1. instruments + issuer/CNPJ de todos os issuers;
2. fallback de CNPJ via fundamentals para representantes cujo issuer ainda não tenha CNPJ;
3. linhas DFP PIT de todos os CNPJs em uma query;
4. últimos preços brutos de todas as classes em uma query.

Depois:
- um FundamentalsReader em memória entrega as mesmas linhas aos loaders canônicos;
- FundamentalsLoader.load_latest_annual produz o mesmo ResolvedFundamentals;
- FundamentalHistoryLoader.load_annual_history produz o mesmo ResolvedFundamentalHistory.

O módulo NÃO calcula múltiplos nem tendências.

## Semântica de preços

O batch deve reproduzir read_latest_raw_price:
- escolher a última price_date <= cutoff por instrumento;
- manter todas as fontes nessa data;
- se fontes tiverem valores/moedas divergentes, value=None + preco_multiplas_fontes_sem_prioridade;
- provenance source_codes/ingestion_batch_ids igual ao loader canônico.

## Identidade

- representative ticker precisa existir exatamente dentro do issuer solicitado;
- classes = todas as ações daquele issuer;
- company_cnpj = issuer.cnpj quando disponível;
- fallback = company_cnpj mais recente conhecido nos fundamentos ligados ao instrumento representante até cutoff;
- não inventar CNPJ;
- sem fuzzy matching.

## Integração na tool shadow

quant.comparaveis_setor continua 1.0.0 e exposed_to_llm=false.

preparar_comparaveis_setor:
- continua usando instrumento_por_termo + sectors.peer_issuers;
- envia target + peers ao batch;
- converte os dados batch para os mesmos ValorMercadoResolvido e TendenciasFundamentaisResolvida;
- calcular_comparaveis_setor permanece reutilizando calcular_valor_mercado e calcular_tendencias_fundamentais.

Nenhuma outra tool passa a depender do batch.

## Equivalência obrigatória

Com os mesmos fixtures:
- resolved valuation batch == preparar_valor_mercado canônico;
- resolved trends batch == preparar_tendencias_fundamentais canônico;
- outputs calculados idênticos para target e peers;
- warnings/provenance/availability/source batches equivalentes.

## Performance gate

Rerodar 2/8/20 peers.

Critério arquitetural:
- prepare_query_count não pode crescer linearmente por peer;
- diferença 20 peers - 2 peers deve ser pequena/constante, não ~180 queries;
- output público continua compacto;
- resolved payload pode crescer com N porque é interno/auditável, mas não vai ao prompt final.

## Fingerprints

O novo módulo entra somente em source_dependencies de quant.comparaveis_setor shadow.
As outras 34 tools devem manter semver/exposição/source SHA.

## Promoção

Só depois:
1. equivalência GREEN;
2. benchmark pós-otimização GREEN;
3. coverage IBrA/B3 já GREEN;
4. planner/bloco/golden;
5. promoção 1.0.1 pública;
6. CI pós-promoção completo.
