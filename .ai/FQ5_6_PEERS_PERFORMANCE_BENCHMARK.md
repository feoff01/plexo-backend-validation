# FQ5.6 — Benchmark de performance/payload de comparáveis

Data: 2026-10-02
Estado: design aprovado pelo comando do usuário; medir antes de otimizar.

## Objetivo

Medir o custo real de `quant.comparaveis_setor` 1.0.0 shadow antes de qualquer promoção pública.

O gate deve responder:
- quantas queries o preparo executa;
- como o número de queries cresce com o número de peers;
- tempo observado em PostgreSQL descartável;
- tamanho do output serializado que pode seguir para o LLM;
- tamanho do resolved payload persistido para auditoria/cache;
- se o desenho atual tem N+1 material.

## Regra reuse-before-build

Não criar batch loader por antecipação.

Primeiro medir a implementação atual, que compõe:
- `quant.valor_mercado`;
- `quant.tendencias_fundamentais`;
- `app.market.analytics.statistics.describe`;
- `app.market.sectors.peer_issuers`.

Se o N+1 for material, o gap é **carregamento/orquestração batch**, não matemática.

## Cenários

Usar fixtures PostgreSQL sintéticas, sem dados remotos:
- pequeno: 2 peers;
- médio: 8 peers;
- grande: 20 peers.

Todos no mesmo subsetor, company-level, uma ou mais classes quando útil.

A preparação deve ser medida depois da massa já estar inserida; queries de setup não contam.

## Métricas

Para cada cenário:
- `peer_count`;
- `prepare_query_count`;
- `prepare_elapsed_ms`;
- `calculate_elapsed_ms`;
- `resolved_payload_bytes`;
- `output_payload_bytes`;
- `metric_count`;
- `peer_examples_count`.

## Critérios

### Payload
O output público deve permanecer aproximadamente constante em relação ao número de peers:
- distribuições agregadas por no máximo 10 métricas;
- no máximo `max_exemplos` peers detalhados;
- nenhuma tabela completa de peers.

Se `output_payload_bytes` crescer materialmente com N, o contrato deve ser corrigido antes de promoção.

### Queries
Se o número de queries crescer linearmente por peer por causa das duas preparações canônicas, registrar N+1 como dívida material e substituir a preparação por um batch loader interno.

Não definir um teto arbitrário antes da medição. O benchmark primeiro produz a linha de base observada.

### Latência
Tempo de CI é evidência operacional, não contrato rígido de SLA. Usar para comparar antes/depois de uma eventual otimização, não como único gate.

## Otimização permitida se necessária

Criar módulo novo, recomendado `app/market/peer_company_metrics.py`, para carregar em lote:
- identidade/company classes;
- preços necessários;
- fundamentos PIT;
- histórico anual DFP.

O módulo deve então chamar os engines determinísticos já existentes:
- `valuation_engine.analyze_market_valuation`;
- `fundamental_trends.analyze_fundamental_trends`;
- statistics compartilhada.

É proibido copiar fórmulas de valuation/crescimento.

Evitar alterar `fundamentals.py`, `snapshots.py` e outros dependencies de tools públicas para não causar fingerprint drift desnecessário. O novo módulo deve ser dependency apenas de `quant.comparaveis_setor`.

## Versionamento

Enquanto `quant.comparaveis_setor` permanece shadow e não foi exposta, ajustes internos do candidato 1.0.0 podem ocorrer sem criar alias público.

Na promoção:
- exposição pública deve seguir o padrão do projeto;
- se a mudança de exposição alterar o source/spec, usar patch bump para 1.0.1;
- provar que as outras 34 tools preservam semver/exposição/fingerprint.

## Gate final

Antes de promoção pública:
1. benchmark baseline registrado;
2. otimização batch se o N+1 for material;
3. benchmark pós-otimização, quando aplicável;
4. output compacto comprovado;
5. coverage atual B3/IBrA já GREEN;
6. planner/bloco/golden;
7. CI PostgreSQL 18 + suíte completa + prompts/tools sync;
8. checkpoint em `.ai/`.


## Baseline observado — run #145

Run: #145 / `37068258563`.

| peers | queries preparo | preparo ms | cálculo ms | resolved bytes | output bytes |
|---:|---:|---:|---:|---:|---:|
| 2 | 38 | 118,585 | 1,810 | 20.493 | 4.009 |
| 8 | 98 | 261,056 | 3,384 | 57.477 | 4.171 |
| 20 | 218 | 348,989 | 6,569 | 131.446 | 4.163 |

Conclusões:
- query count observado = **18 + 10 × N peers**;
- há N+1 material na preparação;
- o output client-facing já é compacto e praticamente constante (~4 KB);
- o resolved payload interno cresce linearmente e chegou a ~131 KB com 20 peers;
- o cálculo puro não é o gargalo.

**Decisão:** implementar batch loader isolado antes da promoção. O gap é carregamento/orquestração, não matemática. O batch deve reutilizar os engines de valuation e tendências e preservar equivalência numérica contra as tools canônicas.
