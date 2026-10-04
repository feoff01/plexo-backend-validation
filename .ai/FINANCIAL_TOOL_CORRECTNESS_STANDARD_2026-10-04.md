# Plexo — Standard de Correção e Certificação de Tools Financeiras

Data: 2026-10-04
Status: **gate obrigatório para integração/produção**
Escopo: Company & Market Analytics

## 1. Princípio

Uma tool financeira NÃO é considerada correta porque:
- compila;
- retorna JSON;
- passa um teste escrito com o mesmo código;
- o LLM produziu uma resposta plausível.

Uma tool só é certificada quando existe evidência independente de que:

1. o **dado de entrada** é o dado certo;
2. o **recorte temporal** é o certo;
3. a **unidade/moeda** é a certa;
4. a **fórmula/método** é o certo;
5. o **resultado** bate com um oracle independente;
6. o **contrato** está versionado;
7. a **provenance** permite reproduzir;
8. a **LLM** chamou a tool correta e não alterou o número.

A certificação tem três camadas obrigatórias:

```
DATA CORRECTNESS
      ↓
NUMERICAL / METHOD CORRECTNESS
      ↓
LLM / BACKEND ORCHESTRATION CORRECTNESS
```

Se qualquer uma falhar, a tool não é PROD_GREEN.

---

## 2. Estados de certificação

Cada tool deve ter um único estado:

- `UNMAPPED`
- `DATA_MAPPED`
- `DATA_VALIDATED`
- `NUMERICALLY_CERTIFIED`
- `E2E_CERTIFIED`
- `SHADOW_PROD`
- `PROD_GREEN`
- `BLOCKED`

Registrar em:
`.ai/TOOL_CERTIFICATION_MATRIX_2026-10-04.md`.

---

## 3. Gate D — Data Correctness

### D1. Identidade
Provar que:
- ticker -> instrumento correto;
- aliases corretos;
- CNPJ/issuer correto;
- benchmark correto;
- índice/fator correto;
- sem colisão silenciosa.

Casos obrigatórios:
- ticker exato;
- alias;
- nome parcial;
- ambiguidade;
- instrumento fora da cobertura;
- código inexistente.

### D2. Source identity
Para cada coluna/serie usada:
- publisher;
- vendor;
- dataset;
- table/view;
- source id;
- unit;
- currency;
- frequency.

Não aceitar descrição genérica "vem do banco".

### D3. Coverage
Medir:
- first observation;
- last observation;
- missing periods;
- duplicate keys;
- nulls;
- outliers estruturais;
- coverage por ticker/issuer.

### D4. Unidades
Exigir unidade explicitamente conhecida.

Exemplos:
- preço: BRL/share;
- market cap: BRL;
- fundamentos: unidade original/canônica;
- taxa: % a.a. / % a.m.;
- FX: BRL/USD ou USD/BRL;
- commodity: USD/barrel.

Conversão deve ser determinística e testada.

### D5. Temporalidade
Para cada dataset distinguir:
- observation_date;
- reference_date;
- publication_date;
- availability_date;
- ingestion finished_at;
- revision/vintage.

Teste obrigatório:
inserir/adicionar um dado que só ficou disponível DEPOIS do cutoff e provar que ele não aparece.

### D6. Reconciliation
Para amostra representativa, reconciliar contra a fonte de origem ou export oficial.

Exigir relatório:
- n comparado;
- n igual;
- divergências;
- tolerância;
- explicação.

---

## 4. Gate M — Mathematical / Method Correctness

### M1. Oracle independente

O oracle NÃO pode chamar:
- a mesma função de produção;
- o mesmo helper principal;
- a mesma pipeline de cálculo.

Exemplos válidos:
- cálculo manual explícito em teste;
- implementação de referência curta e separada;
- biblioteca estatística independente;
- planilha auditada;
- cálculo SQL independente;
- dataset com resultado conhecido/publicado.

O objetivo é detectar erro compartilhado no core.

### M2. Golden vectors

Para toda tool numérica:
- input fixo;
- resolved input fixo;
- output esperado;
- tolerância explícita;
- sem dependência de relógio/rede.

Golden deve cobrir:
- caso normal;
- limite;
- insuficiência;
- erro/ausência;
- condição temporal relevante.

### M3. Property/invariant tests

Além de exemplos, testar propriedades.

Exemplos:
- retorno de preço constante = 0;
- volatilidade não negativa;
- drawdown <= 0;
- correlação em [-1,1];
- Pearson(X,X)=1 quando variância > 0;
- composição de índice ~100%;
- market cap = preço × ações;
- EV = market cap + dívida líquida sob contrato adotado;
- min <= início/fim <= max quando aplicável;
- série não usa data futura.

### M4. Precision

Toda comparação numérica precisa de:
- precisão esperada;
- tolerância absoluta/relativa;
- regra de arredondamento client-facing.

Nunca usar igualdade exata de float quando matematicamente inadequado.

---

## 5. Gate específico por classe de tool

### Séries / dados
`dados.serie_precos`
`dados.serie_indice`
`dados.curva_juros`
`dados.composicao_indice`
`dados.expectativas_mercado`
`dados.fundamentos_empresa`

Provas:
- row-level reconciliation;
- source/date/unit;
- PIT;
- no silent interpolation;
- deterministic sampling;
- provenance/batch.

### Retorno / risco
`quant.risco_retorno`

Oracle independente deve recalcular:
- simple/log returns;
- acumulado;
- anualizado;
- sample stdev;
- annualized vol;
- downside deviation;
- drawdown path;
- max drawdown;
- duration/recovery;
- rolling volatility.

Casos:
- série crescente;
- série constante;
- perda/recuperação;
- janela insuficiente;
- adjusted vs raw.

### Dependência
`quant.dependencia`

Oracle:
- alinhamento por data;
- lag;
- Pearson;
- Spearman;
- constantes;
- missing pairs.

### Sensibilidade
`quant.sensibilidade`

Oracle separado:
- OLS coefficients;
- intercept/slope;
- residuals;
- HAC/Newey-West standard error conforme contrato;
- n observations;
- degenerate cases.

### Análise condicional
`quant.analise_condicional`

Provar:
- regra exata de condição;
- subset correto;
- base histórica correta;
- estatísticas do subset;
- não usar observação fora do cutoff.

### Regimes
`quant.regimes`

Provar:
- classificação de regime;
- threshold/regra explícita;
- grupos sem sobreposição indevida;
- retornos por regime;
- contagem.

### Event study
`quant.event_study`

Oracle:
- janela de estimação;
- data efetiva do evento;
- benchmark;
- alpha/beta;
- expected return;
- abnormal return;
- CAR;
- truncation;
- CI quando aplicável.

Não inferir causalidade/significância não contratada.

### Valor de mercado
`quant.valor_mercado`

Reconciliar:
- preço;
- shares outstanding;
- market cap;
- debt/cash/net debt;
- EV;
- earnings/book/EBITDA/FCF;
- múltiplos.

Testar escala/unidade rigorosamente:
milhares vs milhões é erro crítico.

### Cenário de sensibilidade
`quant.cenario_sensibilidade`

Provar:
- coeficiente histórico de origem;
- choque explícito;
- impacto incremental;
- preço-base;
- cálculo mecânico.

Não chamar de forecast/fair value.

### Tendências fundamentais
`quant.tendencias_fundamentais`

Oracle:
- anos selecionados;
- PIT availability;
- YoY;
- margens;
- null propagation;
- zero denominator.

### Comparáveis
`quant.comparaveis_setor`

Provar separadamente:
1. membership do peer set;
2. métricas de cada peer;
3. estatísticas agregadas.

Não validar apenas o agregado.

---

## 6. Gate T — Temporal / Look-ahead

Esse gate é obrigatório para TODO Company & Market.

### T1. Future observation
Dado com observation_date > cutoff não entra.

### T2. Late ingestion
Dado econômico antigo ingerido depois do cutoff:
- só entra se a semântica do dataset permitir retrospectivo;
- caso strict PIT, deve ficar oculto.

### T3. Revised fundamentals
Fundamento revisado depois do cutoff não pode aparecer como conhecido no passado sem contrato retrospectivo explícito.

### T4. Corporate actions
Adjusted prices precisam declarar:
- retrospective_as_known_now;
ou
- true historical vintage.

Nunca confundir os dois.

### T5. Tests must not depend on wall clock
Fixtures históricas devem controlar availability/finished_at.
O problema atual #349 é exatamente um exemplo do que este standard deve impedir.

---

## 7. Gate P — Provenance / Reproducibility

Todo output material deve permitir reconstruir:
- tool code;
- semver;
- source SHA;
- requested params;
- resolved params;
- source/dataset;
- instrument ids/index codes;
- ingestion batch ids quando aplicável;
- policy versions;
- cutoff;
- as_of;
- method;
- warnings;
- output hash.

O registro em `tools.tool_executions` ou equivalente do backend real deve continuar disponível.

---

## 8. Gate C — Contract / Replay

Para mudança pública:
- bump semver adequado;
- golden antigo continua reproduzível;
- legacy/replay preservado quando necessário;
- param/output schemas versionados;
- source fingerprint atualizado;
- tools sync sem drift.

Portar a implementação para outro backend sem mudar o contrato NÃO autoriza alteração silenciosa do resultado.

Se o resultado muda por causa do DB real:
- determinar se era bug da referência;
- diferença de source;
- diferença temporal;
- unidade;
- bug de port;
- nova metodologia.

Documentar antes de promover.

---

## 9. Gate O — LLM / Orchestration Correctness

### O1. Routing
Perguntas representativas devem escolher a tool esperada.

Manter um eval dataset:
- pergunta;
- agente esperado;
- tool esperada;
- params mínimos;
- tool proibida;
- resposta não deve conter determinada inferência.

### O2. Parametrização
Validar:
- ticker;
- datas;
- window;
- benchmark;
- factor type;
- price basis;
- explicit user assumptions.

LLM não inventa parâmetro financeiro ausente.

### O3. Tool result fidelity
Depois da tool:
- extrair os números do JSON;
- verificar que resposta final não mudou sinal, unidade ou magnitude;
- resposta deve mencionar warnings relevantes;
- não criar número que não existe no output.

### O4. No-calculation rule
Teste adversarial:
pedir ao modelo para calcular diretamente.
Ele deve usar tool quando a capability existir.

### O5. Insufficient data
Quando a tool disser insuficiente:
- resposta deve dizer que falta dado;
- não deve preencher número plausível.

---

## 10. Gate E2E — Backend real

Para cada tool antes de PROD_GREEN, executar:

```
HTTP/API real
→ auth/scope
→ agent routing
→ approved prompt
→ tool exposure
→ model tool call
→ executor
→ DB real/staging clone
→ resolved params
→ pure calculation
→ execution record
→ tool JSON
→ model synthesis
→ persisted conversation/evidence
```

Validar todos os ids/hashes/provenance no banco.

---

## 11. Differential testing referência × backend real

Quando possível, usar os MESMOS resolved inputs nos dois lados:

- reference implementation;
- production-integrated implementation.

Comparar outputs campo a campo.

Se divergir:
- nenhum deploy até explicar a diferença.

Classificar divergência:
- data mapping;
- unit;
- calendar;
- temporal;
- algorithm;
- precision;
- contract;
- bug.

---

## 12. Shadow production

Antes de expor:
- rodar a tool em paralelo para perguntas elegíveis;
- não usar o resultado shadow na resposta;
- armazenar output;
- comparar com versão/reference/oracle;
- monitorar latency/error/data insufficiency.

Definir amostra mínima por tool conforme uso/criticidade.

---

## 13. Production monitoring

Métricas mínimas:
- calls/tool;
- error rate;
- invalid params;
- insufficient data;
- cache hit;
- latency p50/p95;
- rows/query count quando disponível;
- output payload bytes;
- warning rate;
- source freshness;
- stale series;
- reconciliation failures;
- LLM tool-selection accuracy em evals.

Alertas:
- source stopped updating;
- output distribution jump;
- null rate jump;
- execution failures;
- prompt/tool drift;
- source fingerprint drift.

---

## 14. Critérios de severidade de erro

### P0 — bloquear imediatamente
- look-ahead;
- ticker errado;
- unidade errada;
- fórmula errada;
- sinal invertido;
- source errado;
- cross-tenant leak;
- LLM inventa resultado no lugar da tool.

### P1
- provenance incompleta;
- warning não propagado;
- replay quebrado;
- peer set incorreto;
- performance que inviabiliza produção.

### P2
- apresentação/bloco;
- copy;
- pequena diferença de arredondamento dentro de tolerância contratada.

---

## 15. Regra para fair value / valuation futuro

Fair value terá gate MAIS FORTE.

Antes da tool existir:
- data lineage de cada premissa;
- formula document;
- unit tests independentes;
- reference spreadsheet/model;
- scenario grid;
- accounting reconciliation;
- terminal value constraints;
- WACC components;
- explicit date/vintage;
- sensitivity;
- validation por empresas de casos conhecidos.

Nunca promover fair value com apenas "parece razoável".

---

## 16. Definition of Done

Uma tool é `PROD_GREEN` somente quando:

- [ ] data mapped;
- [ ] source validated;
- [ ] unit validated;
- [ ] identity validated;
- [ ] PIT validated;
- [ ] independent oracle passed;
- [ ] invariants passed;
- [ ] golden/replay passed;
- [ ] provenance complete;
- [ ] performance passed;
- [ ] LLM routing passed;
- [ ] LLM fidelity passed;
- [ ] E2E backend real passed;
- [ ] shadow passed;
- [ ] monitoring configured;
- [ ] rollback available;
- [ ] docs/.ai updated.
