# FQ5.5 — Tendências Fundamentais PIT

Data: 2026-09-30  
Estado: **design aprovado para implementação pela autorização do usuário neste chat**

Pré-requisitos canônicos:
- `.ai/WORKING_PROTOCOL.md`
- `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md`
- `.ai/FQ5_FUNDAMENTALS_VALUATION_DESIGN.md`
- `.ai/checkpoints/2026-09-30_FACTOR_DEPENDENCY_CUTOVER_GREEN.md`

## 1. Intenção nova

Responder perguntas como:
- “como a receita/lucro/EBITDA da empresa evoluíram?”;
- “o crescimento acelerou ou desacelerou?”;
- “a margem EBITDA/líquida melhorou?”;
- “como dívida, caixa, patrimônio e FCF mudaram nos últimos anos?”

Isto é uma intenção analítica distinta do snapshot `dados.fundamentos_empresa`, que mostra apenas o último DFP disponível por métrica.

## 2. Reuse-before-build

### Já existe e será reutilizado
- tabela `market.fundamentals` com vintages append-only;
- `availability_date <= cutoff` para point-in-time real dos fundamentos;
- modelos `FundamentalRecord`, unidades, scope e provenance em `app/market/fundamentals.py`;
- `PostgresFundamentalsReader.read_fundamentals()` para ler todos os DFP elegíveis;
- resolução empresa/ticker por `company_identity_for_instrument` + `_comum.instrumento_por_termo`;
- `Evidencia`, executor/cache/registry, planner, blocos e gates existentes.

### Não será duplicado
- não criar tabela/migration;
- não criar segunda tool de histórico bruto;
- não alterar `dados.fundamentos_empresa`;
- não alterar `quant.valor_mercado`;
- não criar fair value/DCF;
- não usar ITR nesta tranche.

## 3. Decisão crítica de fingerprint

`app/market/fundamentals.py` já participa do `source_fingerprint` de:
- `dados.fundamentos_empresa` 1.0.0;
- `quant.valor_mercado` 1.0.0.

Adicionar `load_annual_history()` diretamente nesse arquivo mudaria o hash das duas tools mesmo sem mudar seu comportamento. Para evitar bump artificial/cascata:

**o histórico anual será implementado em um novo módulo**:
- `app/market/fundamental_history.py`.

Esse módulo consumirá `PostgresFundamentalsReader` e os modelos já existentes, sem editar `fundamentals.py`.

Gate obrigatório: fingerprints das 33 tools existentes devem permanecer idênticos; a única nova spec esperada é FQ5.5.

## 4. Semântica temporal

Somente linhas que satisfazem:
- `document_type = DFP`;
- `scope` explícito;
- `reference_date <= cutoff`;
- `availability_date <= cutoff`.

Para cada coordenada histórica:
`(metric, instrument_id, reference_date, period_label)`
selecionar o **último vintage que já estava disponível no cutoff** (`max availability_date <= cutoff`).

Isso impede look-ahead por republicação/restatement posterior.

## 5. Por que somente DFP anual agora

ITR pode conter fluxos acumulados no ano e exige normalização específica por demonstração/período para derivar trimestre isolado. Misturar ITR sem esse contrato pode produzir crescimento e margem errados.

Portanto FQ5.5 v1:
- usa apenas DFP anual;
- não anualiza trimestre;
- não subtrai ITR acumulado;
- não chama resultado anual de “trailing twelve months”.

ITR/trimestre fica para design próprio futuro.

## 6. Novo loader interno

Arquivo: `app/market/fundamental_history.py`.

Modelos propostos:
- `ResolvedFundamentalHistory`:
  - `company_cnpj`;
  - `scope`;
  - `document_type=DFP`;
  - `records` (vintage já colapsado por período);
  - `provenance` reutilizando `FundamentalProvenance`.

API:
`load_annual_history(company_cnpj, cutoff, scope, metrics, periods)`.

Regras:
1. ler via `PostgresFundamentalsReader.read_fundamentals`;
2. filtrar invariantes PIT novamente defensivamente;
3. escolher último vintage por coordenada histórica;
4. manter até `periods` referências mais recentes por métrica/instrumento;
5. preservar source_code, ingestion_batch_id, unidade, moeda e `is_derived`.

Default `periods=5`, mínimo 2, máximo 10.

## 7. Escopo de métricas v1

Default company-level:
- `revenue`;
- `ebitda` com fallback `ebitda_derived` apenas dentro do mesmo período;
- `net_income`;
- `total_equity`;
- `cash_and_equivalents`;
- `gross_debt`;
- `net_debt` quando reportado;
- `free_cash_flow`.

`shares_outstanding` fica fora da v1 de tendências porque é coordenada por classe/instrumento e exigiria contrato explícito de diluição por classe.

Métricas com `value_unit=raw` não participam dos cálculos derivados e geram warning.

## 8. Engine analítico puro

Novo arquivo: `app/market/analytics/fundamental_trends.py`.

Não há matemática equivalente hoje no Quant Core; somente cálculos necessários à nova intenção:

### Por métrica
Para cada par de períodos consecutivos:
- mudança absoluta = atual − anterior;
- crescimento % somente quando o valor anterior é **estritamente positivo**;
- se anterior <= 0, crescimento percentual fica `None` e warning explícito evita leitura enganosa.

Não haverá CAGR nesta tranche: datas fiscais, gaps de períodos e bases negativas tornam o número fácil de interpretar incorretamente; YoY explícito cobre a intenção inicial com menos suposições.

### Margens
Quando `revenue > 0` no mesmo `reference_date`:
- margem EBITDA = EBITDA / revenue × 100;
- margem líquida = net_income / revenue × 100.

Mudança de margem entre períodos = diferença em **pontos percentuais**.

Nunca misturar métricas de reference_dates diferentes para a mesma margem.

### EBITDA
Por período:
1. preferir `ebitda` reportado canônico;
2. se ausente, usar `ebitda_derived`;
3. marcar `is_derived/source_metric` no ponto.

Não somar nem combinar os dois.

## 9. Tool pública proposta

Código: `quant.tendencias_fundamentais`  
Semver inicial: `1.0.0`  
Família: `quant`  
`requires_market_data=True`  
Fase inicial: shadow (`exposed_to_llm=False`).

Params:
- `ticker`;
- `data_referencia?`;
- `scope = consolidated|standalone`;
- `periodos = 5` (2..10);
- `metricas?` (subconjunto company-level canônico, max 12).

Output compacto:
- ticker/CNPJ/scope;
- por métrica: até N pontos anuais + latest/previous/absolute_change/growth_pct;
- margens EBITDA e líquida por período + change_pp;
- evidence/provenance/warnings.

Não enviar demonstrações completas nem dezenas de contas ao LLM.

## 10. Warnings/fail-closed

Previstos:
- `instrumento_desconhecido`;
- `fora_da_cobertura`;
- `company_cnpj_indisponivel`;
- `sem_dados`;
- `fundamental_unit_raw`;
- `fundamental_unit_incompativel`;
- `historico_fundamental_insuficiente` (<2 pontos válidos para qualquer tendência);
- `crescimento_percentual_base_nao_positiva`;
- `margem_receita_nao_positiva`;
- `fundamental_metrica_classe_nao_suportada` se tentativa futura/inválida chegar à tool.

## 11. Planner

Roteamento pretendido após promoção:
- “quais os fundamentos/lucro atual?” -> `dados.fundamentos_empresa`;
- “como evoluiu/cresceu/caiu nos últimos anos?” -> `quant.tendencias_fundamentais`;
- “quanto vale / market cap / EV / múltiplos?” -> `quant.valor_mercado`;
- fair value/preço justo continua **não suportado**.

## 12. Blocos

Mapper novo:
- tabela-resumo por métrica: atual, anterior, mudança absoluta, crescimento %;
- série temporal compacta apenas quando houver pontos suficientes;
- margens em percentual sem misturar escala BRL e %. 

Máximo de pontos respeita o limite global de blocos.

## 13. Testes antes de promoção

### Loader/PIT
- dois vintages do mesmo DFP: cutoff antes/depois do restatement;
- último vintage por reference_date, sem apagar histórico;
- scope sem fallback;
- limite de períodos;
- unidade/provenance/batch preservados.

### Engine
- crescimento positivo;
- queda;
- base zero/negativa -> growth_pct None + warning;
- EBITDA reportado preferido sobre derived;
- fallback derived;
- margem EBITDA/líquida alinhada no mesmo reference_date;
- revenue <= 0 -> margem None + warning;
- dados faltantes não são imputados.

### Registry/fingerprint
- 33 specs atuais inalteradas;
- nova tool = única adição;
- shadow não entra no catálogo do LLM.

### E2E PostgreSQL
- DFP 3+ anos com restatement posterior ao cutoff;
- output usa somente o vintage conhecido naquele cutoff;
- executor/cache/tool_executions;
- após promoção: planner, blocos, catalog tests;
- suíte completa, prompts check, tools sync --check.

## 14. Promoção

Fases:
1. design (este documento);
2. loader + engine + tool shadow;
3. testes locais/equivalência de fingerprints;
4. PostgreSQL 18 shadow gate;
5. promoção para 1.0.0 pública + planner/blocos;
6. CI pós-promoção;
7. checkpoint e atualização completa de `.ai/`.

Não abrir FQ5.6 peers/setor até FQ5.5 ficar verde.
