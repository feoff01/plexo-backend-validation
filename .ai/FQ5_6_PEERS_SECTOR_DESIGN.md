# FQ5.6 — Peers / Setor: design da fundação setorial e comparação

Data: 2026-09-30
Estado: **design aprovado para orientar a próxima implementação; nenhuma tool pública criada nesta etapa**
Pré-requisitos: `.ai/WORKING_PROTOCOL.md`, `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md`, FQ5.5 GREEN.

## 1. Pergunta que queremos responder

Cobrir perguntas de empresa/mercado como:
- "quem são os pares da Petrobras?";
- "como Petrobras negocia contra empresas do mesmo segmento?";
- "o P/L, EV/EBITDA ou margem da empresa estão acima/abaixo dos comparáveis?";
- "como os fundamentos da companhia se comparam ao setor?".

Não inclui recomendação de investimento, carteira do cliente, suitability, alocação ou score subjetivo.

## 2. Resultado do gate reuse-before-build

### Já existe
- schema `market.sector_classification` desde F22;
- identidade de emissor em `market.issuers` e vínculo `market.instruments.issuer_id`;
- `market.ingestion_batches` com source, dataset, reference_date, hash, status e `finished_at`;
- market cap, EV, P/L, EV/EBITDA, P/VP e FCF yield no engine de valuation existente;
- tendências/margens YoY anuais PIT no FQ5.5;
- estatística descritiva `describe` no Quant Core.

### Não existe
- coletor/projetor que preencha `market.sector_classification`;
- loader Python canônico de classificação setorial;
- cobertura comprovada dessa tabela em ambiente real;
- tool de peers/comparáveis.

### Conclusão
O gap primário é **dados + loader/provenance**, não matemática. Criar `quant.comparaveis_setor` antes da fundação de ingestão seria erro arquitetural.

## 3. Fonte autoritativa

A v1 deve aceitar **somente B3** como fonte de classificação setorial.

Verificação pública em 2026-09-30:
- a B3 mantém uma consulta oficial de classificação setorial e informa que a base é atualizada semanalmente no último dia útil da semana, no processamento noturno;
- a B3 descreve a classificação como baseada principalmente nos produtos/serviços que contribuem para as receitas e informa revisões periódicas;
- páginas oficiais de empresas listadas exibem CNPJ, códigos de negociação e classificação setor/subsetor/segmento.

A URL/contrato técnico de download/API **não é considerado validado apenas por código de terceiros**. Antes de escrever o coletor de rede, deve existir fixture capturada de resposta oficial B3 e teste de parser sobre o contrato observado.

## 4. Identidade: companhia antes de ticker

A classificação econômica é de **companhia/emissor**, enquanto o schema atual está projetado por `instrument_id`.

Regra canônica de matching da ingestão:
1. CNPJ oficial da B3 -> `market.issuers.cnpj`;
2. localizar todos os instrumentos `kind='acao'` ligados ao mesmo `issuer_id`;
3. projetar o mesmo snapshot setorial para cada classe de ação desse emissor;
4. registrar o mesmo `ingestion_batch_id` e `reference_date` em todas as classes.

É proibido inferir classe de ação por prefixo do código raiz da companhia. Ex.: código de companhia `PETR` não identifica sozinho PETR3/PETR4.

Se CNPJ não casar com um emissor de forma única, a linha fica fora da ingestão e entra no relatório de cobertura. Não fazer fuzzy match silencioso por nome.

## 5. Temporalidade e PIT sem migration nova

`market.sector_classification` tem `reference_date`, mas não `availability_date`. Não criar migration apenas por isso: a linha já referencia `market.ingestion_batches`, cujo `finished_at` registra quando o snapshot foi efetivamente incorporado.

Para snapshots novos:
- `sector_classification.reference_date` = data do snapshot/coleta oficial;
- `ingestion_batches.reference_date` = a mesma data de referência do dataset;
- disponibilidade conhecida pelo Plexo = `ingestion_batches.finished_at` do lote `succeeded`;
- source = `b3`;
- dataset proposto = `b3.sector_classification@1`.

### Leitura PIT
Para cutoff `D`, uma linha é elegível somente se:
- `source_code='b3'`;
- `ingestion_batch_id IS NOT NULL`;
- lote associado está `succeeded`;
- `finished_at` conhecido e `finished_at::date <= D`;
- `reference_date <= D`.

Selecionar o maior `reference_date` elegível para o emissor/instrumento.

### Limitação explícita
Isto reconstrói **o snapshot que o Plexo conhecia**, não a data jurídica exata em que uma reclassificação econômica passou a valer. Enquanto a B3 não fornecer effective date/vintage próprio, não afirmar semântica mais forte.

Linhas legadas sem `ingestion_batch_id` não entram em leitura PIT estrita. Podem existir para compatibilidade administrativa, mas não devem sustentar uma resposta client-facing "como era conhecido naquela data".

## 6. Fundação FQ5.6A — antes de qualquer tool

### 6.1 Parser puro
Módulo sugerido: `app/market/sector_source.py`.

Responsabilidades:
- parsear payload/arquivo oficial B3 já baixado;
- normalizar CNPJ somente para 14 dígitos;
- normalizar strings vazias para `None`;
- extrair economic_sector, subsector, segment e listing_segment sem reinterpretar nomenclatura;
- produzir registros imutáveis;
- rejeitar linha sem identidade suficiente;
- nenhuma conexão com banco e nenhuma heurística de investimento.

O parser só deve ser implementado depois de fixture real oficial validada.

### 6.2 Ingestão
Módulo sugerido: `app/market/sector_ingest.py` ou extensão pequena de `app/market/ingest.py` apenas se isso não afetar fingerprints públicos.

Preferência: módulo novo para reduzir raio de fingerprint.

Responsabilidades:
- abrir lote idempotente usando a infraestrutura existente;
- casar CNPJ -> issuer;
- expandir para classes `acao` do mesmo issuer;
- inserir append-only em `market.sector_classification`;
- `ON CONFLICT DO NOTHING` somente na chave existente;
- fechar lote com cobertura detalhada: empresas recebidas, casadas, sem issuer, sem ação, linhas inseridas e conflitos;
- preservar hash do bruto/canônico e `storage_key` quando disponível.

### 6.3 Loader
Módulo sugerido: `app/market/sectors.py`.

Modelos propostos:
- `SectorClassification`;
- `SectorProvenance`;
- `ResolvedSectorClassification`;
- `PeerUniverse`.

API conceitual:
- `classification_for_instrument(conn, instrument_id, cutoff, strict_pit=True)`;
- `peer_issuers(conn, instrument_id, cutoff, level, strict_pit=True)`.

O loader deve:
- deduplicar por `issuer_id`;
- detectar classificações divergentes entre classes do mesmo emissor no mesmo snapshot e falhar fechado;
- retornar provenance do lote/source/reference_date/availability;
- nunca ampliar automaticamente segmento -> subsetor -> setor.

## 7. Universo de peers FQ5.6B

Primeira versão aceita `level` explícito:
- `segmento`;
- `subsetor`;
- `setor`.

Default recomendado: `segmento` por ser a comparação econômica mais próxima.

Regras:
- target deve ser instrumento `kind='acao'` e `is_in_universe=true`;
- pares são emissores distintos com ao menos uma ação `is_in_universe=true`;
- excluir o próprio issuer do target;
- deduplicar múltiplas classes do mesmo emissor;
- mesma classificação B3 no nível escolhido, usando snapshot elegível no mesmo cutoff;
- sem auto-widen quando N é pequeno; retornar warning/insuficiência e deixar usuário/LLM escolher outro nível explicitamente;
- BDRs, fundos, ETFs e FIIs ficam fora da v1.

## 8. Reuso de métricas — não duplicar matemática

A futura comparação deve reutilizar:
- valuation existente para market cap, EV, P/L, EV/EBITDA, P/VP e FCF yield;
- FQ5.5 para margens e crescimento anual PIT;
- `app/market/analytics/statistics.describe` para count/mean/median/std/min/max.

Não reimplementar fórmulas de valuation ou crescimento dentro da tool de peers.

Antes de implementação, escolher a composição com menor N+1 e menor impacto de fingerprint. É aceitável criar um preparador interno batch que **chame engines existentes**; não é aceitável copiar as fórmulas.

## 9. Métricas candidatas da v1

Valuation:
- market_cap;
- price_earnings;
- ev_ebitda;
- price_book;
- free_cash_flow_yield.

Fundamentos/tendência:
- revenue_yoy;
- ebitda_yoy;
- net_income_yoy;
- ebitda_margin;
- net_margin.

Cada métrica deve carregar sua unidade e N válido. Não misturar empresas com unidade/moeda incompatível em estatísticas monetárias.

## 10. Output compacto proposto

A futura `quant.comparaveis_setor` não deve despejar todo o peer table no LLM.

Output:
- target e classificação resolvida;
- level escolhido;
- `peer_count_total`;
- para cada métrica: target, `n_valid`, median, mean, min, max e unidade;
- delta target-vs-median calculado deterministicamente quando semanticamente válido;
- lista curta de peers de exemplo, com critério de seleção explícito;
- provenance do snapshot setorial e warnings.

A distribuição usa **todos os peers válidos**. A lista detalhada pode ser limitada (ex.: maiores market caps), mas deve declarar esse critério para não parecer amostra aleatória.

## 11. Delta vs mediana

Não usar uma fórmula universal para todas as unidades.

- múltiplos/razões adimensionais: diferença absoluta; premium/discount percentual apenas se mediana != 0 e com sinal semanticamente válido;
- margens/yields/percentuais: diferença em pontos percentuais;
- valores monetários: diferença absoluta; comparação relativa opcional somente se mesma moeda/unidade e mediana positiva.

Se a semântica não for segura, retornar somente target + distribuição e não inventar "premium".

## 12. Quality gates e warnings

Warnings candidatos:
- `classificacao_setorial_indisponivel`;
- `classificacao_setorial_sem_vintage_pit`;
- `classificacao_setorial_divergente_entre_classes`;
- `pares_insuficientes`;
- `peer_sem_fundamentos`;
- `peer_sem_preco`;
- `metrica_peer_unidade_incompativel`;
- `metrica_peer_amostra_insuficiente`.

Nenhum missing deve ser imputado como zero.

## 13. Source fingerprint / semver / replay

FQ5.6A é infraestrutura, sem tool pública.

FQ5.6B, quando pronta:
- nova intenção => candidata `quant.comparaveis_setor` 1.0.0 shadow;
- promoção exige patch bump para 1.0.1 se a exposição mudar no mesmo arquivo, seguindo padrão FQ5.5;
- source dependencies devem incluir loader setorial e engines/loaders efetivamente usados;
- nenhuma tool atual deve ter fingerprint alterado por refactor cosmético.

## 14. Testes obrigatórios FQ5.6A

Parser:
- fixture real oficial B3;
- CNPJ com máscara/sem máscara;
- campos vazios;
- classificação completa/incompleta;
- payload inesperado falha fechado.

Matching/ingestão:
- emissor com PETR3/PETR4 recebe mesmo snapshot;
- CNPJ desconhecido não usa prefix/fuzzy match;
- idempotência por hash;
- append-only;
- relatório de cobertura;
- lote failed não entra em leitura;
- lote sem `finished_at` não entra em strict PIT.

Loader:
- cutoff antes/depois de snapshot;
- restatement/reclassificação entre snapshots;
- dedupe por issuer;
- inconsistência entre classes falha fechado;
- level segmento/subsetor/setor;
- sem auto-widen.

## 15. Testes obrigatórios FQ5.6B

- target multi-classe não duplica peer company;
- target excluído do universo;
- todas as métricas reutilizam calculadores canônicos;
- missing/unidade incompatível reduz `n_valid`, nunca vira zero;
- estatística da distribuição usa todos os peers válidos;
- output detalhado respeita limite compacto;
- planner distingue "peers/setor" de "tendência própria", "valuation próprio" e "correlação";
- registry audit prova zero drift nas tools existentes;
- PG18 E2E + suíte + prompts/tools sync.

## 16. Gate de dados antes de codar coletor

FQ5.6A só pode avançar para rede/ingestão depois de confirmar:
1. endpoint/download oficial B3 acessível de forma estável;
2. fixture real salva em teste sem segredos;
3. campos suficientes para CNPJ + classificação + listing segment/códigos;
4. política de hash/storage do bruto;
5. cadência semanal e tratamento de falhas/retry;
6. cobertura medida contra `market.issuers`/ações do universo.

Se o feed oficial não oferecer CNPJ em bulk, o design deve prever uma etapa oficial de enriquecimento por company detail; não substituir isso por prefixo de ticker.

## 17. Sequência recomendada

### FQ5.6A1 — source contract
- validar oficialmente download/API;
- salvar fixture real sanitizada;
- documentar campos e hash.

### FQ5.6A2 — shadow data foundation
- parser;
- ingestão;
- loader PIT usando `ingestion_batches.finished_at`;
- testes e CI;
- **sem tool pública**.

### FQ5.6A3 — coverage gate
- medir universo real: matched/unmatched/ambiguous;
- só prosseguir se cobertura for suficiente e explicável.

### FQ5.6B — comparação em shadow
- engine de distribuição/comparação reutilizando valuation/tendências/statistics;
- tool oculta;
- E2E;
- registry/fingerprint audit.

### Promoção
- somente após coverage + CI + planner/blocos + replay/fingerprint verdes.

## 18. Decisão desta etapa

Não criar `quant.comparaveis_setor` agora.

O próximo trabalho implementável é **FQ5.6A1: validar o contrato de fonte oficial B3**. O schema já existe e não precisa de migration neste momento. A disponibilidade PIT de novos snapshots pode ser derivada do `ingestion_batch.finished_at`, preservando o histórico conhecido pelo Plexo.
