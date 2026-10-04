# FQ5.7 — Curva de juros ANBIMA · design da fundação

Data: 2026-10-03
Estado: **design aprovado pelo comando do usuário para implementação em shadow da fundação**

## 1. Reuse-before-build

O schema já possui `market.yield_curve`, append-only, com:
- `curve_name`;
- `reference_date`;
- `business_days`;
- `calendar_days`;
- `rate_pct`;
- `day_count`;
- `source_code`;
- `ingestion_batch_id`.

A source `anbima` também já existe no catálogo.

Não criar tabela/migration nova nesta tranche.

Auditoria de código: não existe consumer Python de `market.yield_curve` e não existe engine/tool de curva hoje.

## 2. Contrato oficial da fonte

ANBIMA Developers documenta:
- endpoint: `GET /feed/precos-indices/v1/titulos-publicos/curvas-juros`;
- periodicidade diária;
- divulgação a partir das 20h;
- parâmetro opcional `data=AAAA-MM-DD`;
- `data_referencia`;
- bloco ETTJ com `vertice_du`, `taxa_prefixadas`, `taxa_ipca`, `taxa_implicita`;
- taxas em % a.a./252 dias úteis.

A consulta pública legacy de ETTJ também expõe os últimos cinco dias úteis e os mesmos três conjuntos de taxas.

A API autenticada usa client_id/access_token via OAuth2. Credenciais NÃO entram no repo, .ai, fixtures ou logs.

## 3. Curvas canônicas no Plexo

Mapeamento v1:
- `ettj_pre` <- `taxa_prefixadas`;
- `ettj_ipca` <- `taxa_ipca`;
- `inflacao_implicita` <- `taxa_implicita`.

Para as três:
- `business_days = vertice_du`;
- `day_count = du_252`;
- `calendar_days = NULL`;
- `source_code = anbima`.

Não guardar os parâmetros Svensson nesta tabela nesta tranche; eles não são necessários para consumir os vértices oficiais publicados.

## 4. Temporalidade

`reference_date` é a data econômica da curva.

Strict PIT deve usar também o lote:
- ingestion_batch_id não nulo;
- batch status = succeeded;
- finished_at não nulo;
- finished_at <= cutoff.

Uma curva histórica baixada hoje com `reference_date=2020` NÃO deve aparecer em uma consulta strict PIT de 2020, porque ela só ficou disponível ao Plexo no momento da ingestão.

Semântica: `ingestion_finished_at_cutoff`.

## 5. Fundação shadow

### 5.1 Ingestão semântica

Novo módulo recomendado:
`app/market/yield_curve_ingest.py`.

Modelo:
`AnbimaYieldCurvePoint(reference_date, business_days, pre_rate_pct, ipca_rate_pct, implied_inflation_pct)`.

O módulo NÃO faz HTTP/OAuth. Recebe registros já validados pelo adapter físico futuro.

Regras:
- source fixa = anbima;
- dataset = `anbima.yield_curve.ettj@1`;
- mesma reference_date em todo snapshot;
- business_days > 0 e únicos;
- taxas finitas;
- ao menos uma taxa por vértice;
- expandir cada ponto em até 3 linhas canônicas;
- append-only/idempotência via ingestion_batches;
- conflito de mesma chave com valor diferente falha fechado;
- lote só `succeeded` após todas as linhas estarem consistentes.

### 5.2 Loader PIT

Novo módulo:
`app/market/yield_curves.py`.

Modelos:
- `YieldCurvePoint`;
- `YieldCurveProvenance`;
- `ResolvedYieldCurve`.

API:
`load_yield_curve(conn, curve_name, cutoff, reference_date=None, strict_pit=True)`.

Comportamento:
- se reference_date ausente, escolhe a curva mais recente economicamente <= cutoff e disponível no cutoff;
- retorna todos os vértices daquela data;
- fail-closed se houver múltiplas linhas conflitantes para o mesmo vértice;
- não interpola;
- não extrapola;
- não converte day-count;
- provenance inclui source, batch, reference_date, availability/finished_at, cutoff.

## 6. Physical adapter / credenciais

Não implementar cliente de produção nesta tranche.

Motivo:
- a documentação oficial define campos e endpoint, mas a API requer credenciais OAuth;
- segredos não podem entrar no repo;
- o parser físico deve ser congelado contra payload real obtido em ambiente autorizado/sandbox antes de promoção.

Permitido:
- testes sintéticos do contrato semântico;
- loader e ingestão no PostgreSQL descartável;
- depois, quando houver payload real autorizado, adicionar adapter físico separado.

## 7. Não objetivos FQ5.7A

Não criar ainda:
- tool pública;
- slope 2y10y/curvature;
- interpolação Svensson;
- cenário de choque de curva;
- duration/DV01;
- fair value;
- forecast de juros;
- uso da curva intradiária.

Essas capacidades só são avaliadas depois do loader GREEN e de uma nova auditoria reuse-before-build.

## 8. Gates

- testes puros de validação do snapshot;
- ingestão append-only/idempotente;
- conflito fail-closed;
- loader latest + reference_date;
- strict PIT por finished_at;
- unit/day_count explícito;
- PostgreSQL 18 completo;
- tools registry sem drift;
- prompts sem drift;
- checkpoint em .ai.

## 9. Próxima decisão após GREEN

Depois da fundação:
1. materializar um payload real autorizado da API ANBIMA ou export oficial equivalente;
2. medir cobertura histórica disponível;
3. decidir primeira intenção client-facing:
   - leitura da curva atual;
   - comparação de vértices;
   - mudança de curva entre datas;
   - só depois sensibilidade do ativo a um ponto específico da curva via Factor adapter.

Não criar uma `correlacao_curva`/ `sensibilidade_curva` separada se os engines existentes puderem consumir um ponto de curva como fator.
