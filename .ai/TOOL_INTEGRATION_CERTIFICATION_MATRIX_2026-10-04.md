# Plexo — Matriz de Integração e Certificação das Tools de Company & Market

Data: 2026-10-04
Status: **CANÔNICO PARA PORT/MIGRAÇÃO**
Escopo: 18 tools públicas do Analista de Mercado

## 1. Regra de leitura

A referência atual foi validada no repo de validação, mas isso NÃO significa que já esteja integrada/certificada contra o backend e banco reais.

Estado de referência:
- último baseline funcional integralmente GREEN: `bf16dfd561f97e136060d77d80f50092cdc4538d`;
- run #341;
- 186 directed;
- 929 passed / 53 skipped / 19 warnings / 0 failed;
- catálogo 37 / 34 / 3.

Estado inicial de produção para as 18 tools abaixo:
**NOT_MAPPED** até o Codex provar o equivalente no backend real.

---

## 2. Matriz

| Tool | Versão referência | Dados/contratos necessários | Prova principal de correção | Status prod inicial |
|---|---:|---|---|---|
| `dados.resolver_instrumento` | 1.0.0 | instrumentos, aliases, issuer/universe, último preço | casos conhecidos de ticker/alias/nome/ambiguidade | NOT_MAPPED |
| `dados.serie_precos` | 1.0.2 | instrumentos, prices, calendar, source/batch | reconciliação row-level + cutoff | NOT_MAPPED |
| `dados.serie_indice` | 1.1.1 | index definitions/values, unit/source | série oficial + acumulado independente | NOT_MAPPED |
| `dados.historico_comparado` | 1.1.1 | duas séries de preço e calendário | interseção por data + base 100 independente | NOT_MAPPED |
| `dados.expectativas_mercado` | 1.0.0 | Focus/expectations, coleta/ref date | reconciliar coleta/mediana/dispersão/respondentes | NOT_MAPPED |
| `dados.fundamentos_empresa` | 1.0.0 | issuer/instrument, DFP PIT, units, availability | reconciliar DFP e availability | NOT_MAPPED |
| `dados.curva_juros` | 1.0.1 | ETTJ vertices, batch/availability | vértices exatos ANBIMA; sem interpolação | NOT_MAPPED |
| `dados.composicao_indice` | 1.0.1 | snapshot de membership/pesos | membros/pesos exatos + soma ~100% + PIT | NOT_MAPPED |
| `quant.risco_retorno` | 1.2.0 | série de preço, price basis, calendar, policy | oracle independente de retorno/vol/downside/drawdown/rolling | NOT_MAPPED |
| `quant.dependencia` | 2.0.0 | duas séries/fatores, alignment | Pearson/Spearman/lag independente | NOT_MAPPED |
| `quant.sensibilidade` | 1.0.1 | duas séries/fatores | OLS/HAC independente | NOT_MAPPED |
| `quant.analise_condicional` | 1.0.1 | duas séries/fatores | subset/condição + estatísticas independentes | NOT_MAPPED |
| `quant.regimes` | 1.0.1 | duas séries/fatores | regime assignment + retorno por regime | NOT_MAPPED |
| `quant.event_study` | 2.0.0 | ativo, benchmark, calendar, event date | alpha/beta/AR/CAR/janelas independentes | NOT_MAPPED |
| `quant.valor_mercado` | 1.0.0 | preço, shares, fundamentals, net debt | reconciliação contábil + fórmulas EV/múltiplos | NOT_MAPPED |
| `quant.cenario_sensibilidade` | 1.0.0 | sensibilidade, preço-base, choque explícito | cálculo mecânico independente | NOT_MAPPED |
| `quant.tendencias_fundamentais` | 1.0.1 | histórico anual PIT de fundamentos | YoY/margens e availability | NOT_MAPPED |
| `quant.comparaveis_setor` | 1.0.1 | classificação setorial + métricas peers | peer membership + métricas por peer | NOT_MAPPED |

---

## 3. Contrato de integração por tool

### `dados.resolver_instrumento`

#### Função
Transformar texto do usuário em identidade canônica.

#### Backend real precisa provar
- source de instrumentos;
- canonical instrument id;
- ticker;
- aliases;
- issuer;
- is_in_universe;
- data do último preço.

#### Casos mínimos
- `PETR4`;
- lowercase;
- código antigo;
- nome parcial;
- termo ambíguo;
- desconhecido;
- fora da cobertura.

#### P0
Resolver o ticker errado.

---

### `dados.serie_precos`

#### Função
Entregar a série de fechamento correta até o cutoff.

#### Dados
- prices;
- instrument id;
- source;
- ingestion batch;
- calendar;
- opcional adjusted/raw semantics conforme consumidor.

#### Validar
- sample de linhas contra source/export;
- preço em datas conhecidas;
- nenhum ponto > cutoff;
- missing trading dates;
- sampling não muda resumo/evidence.

#### P0
Preço, moeda ou data errados; look-ahead.

---

### `dados.serie_indice`

#### Função
Índice/taxa oficial.

#### Validar
- index code -> série correta;
- unidade;
- observações;
- regra de acumulado;
- daily/business-day semantics.

#### P0
Tratar taxa anual como retorno diário sem conversão contratada.

---

### `dados.historico_comparado`

#### Função
Comparar trajetórias em base 100.

#### Validar
- mesmas datas após alignment;
- ponto inicial = 100;
- original values preservados;
- benchmark correto;
- sampling simétrico.

---

### `dados.expectativas_mercado`

#### Função
Projetar a expectativa de terceiros publicada no Focus, não previsão Plexo.

#### Validar
- indicator;
- collection date;
- reference year;
- median;
- dispersion;
- respondents;
- source;
- latest-available semantics.

#### P0
Misturar data de coleta futura com cutoff passado.

---

### `dados.fundamentos_empresa`

#### Função
Snapshot de fundamentos que estavam disponíveis na data de referência.

#### Validar
- issuer mapping;
- statement/year;
- availability;
- unit;
- value;
- annual DFP semantics;
- revisions.

#### P0
Usar fundamento revisado futuro no passado.

---

### `dados.curva_juros`

#### Função
Vértices oficiais ANBIMA.

#### Validar
- curve code;
- reference date;
- business days;
- rate;
- day count;
- batch availability;
- sem interpolação/extrapolação.

#### P0
Mostrar batch disponível depois do cutoff.

---

### `dados.composicao_indice`

#### Função
Membership/pesos de snapshot oficial.

#### Validar
- snapshot date;
- members;
- weights;
- total;
- exact-date behavior;
- batch availability.

#### P0
Retrodatação de composição atual.

---

### `quant.risco_retorno`

#### Função
Risco/retorno histórico descritivo.

#### Dados
- resolved series;
- price basis;
- temporal semantics;
- policy `ANALISE_PARAMS`.

#### Oracle
Implementação independente para:
- return;
- annualized return;
- vol;
- downside deviation;
- max drawdown;
- drawdown path;
- rolling vol.

#### Replay
1.1.0 já congelada.
1.2.0 pública na referência.

#### P0
Adjusted/raw confundidos; fórmula errada; look-ahead.

---

### `quant.dependencia`

#### Função
Pearson/Spearman entre duas séries com lag.

#### Validar
- factor identity;
- aligned return dates;
- lag direction;
- n pairs;
- coefficient;
- constant series.

#### P0
Lag invertido ou séries desalinhadas.

---

### `quant.sensibilidade`

#### Função
Associação linear histórica OLS/HAC.

#### Validar
- X/Y;
- returns/change semantics;
- beta/slope;
- intercept;
- HAC standard errors;
- sample;
- missing data.

#### P0
Trocar variável dependente/independente.

---

### `quant.analise_condicional`

#### Função
Comportamento do ativo em intervalos condicionados ao fator.

#### Validar
- regra exata da condição;
- subset dates;
- comparação com base;
- statistics.

---

### `quant.regimes`

#### Função
Comparar retorno em regimes auditáveis.

#### Validar
- regra de classificação;
- dates;
- group counts;
- returns.

---

### `quant.event_study`

#### Função
AR/CAR versus benchmark em torno de evento.

#### Validar
- effective event date;
- estimation window;
- event window;
- benchmark;
- model coefficients;
- abnormal returns;
- CAR;
- truncation;
- CI, se solicitado.

#### P0
Evento/alinhamento/benchmark errado.

---

### `quant.valor_mercado`

#### Função
Market cap, EV e múltiplos observados.

#### Validar
- share count date;
- price date;
- unit/scaling;
- net debt composition;
- earnings/book/EBITDA/FCF period;
- formulas.

#### P0
Milhar/milhão, consolidated/parent ou share count errado.

---

### `quant.cenario_sensibilidade`

#### Função
Cenário mecânico baseado em sensibilidade histórica.

#### Validar
- coefficient provenance;
- user shock;
- base price;
- mechanical result.

Não usar como forecast.

---

### `quant.tendencias_fundamentais`

#### Função
YoY/margens ao longo do histórico anual disponível.

#### Validar
- ordered years;
- availability each year;
- numerator/denominator units;
- zero handling;
- YoY.

---

### `quant.comparaveis_setor`

#### Função
Peer comparison por subsetor/setor.

#### Validar
- target classification;
- complete peer set;
- exclusions;
- per-peer values;
- aggregate values.

#### P0
Peer set incorreto ou survivorship/retrodatação não declarada.

---

## 4. Certificação por ondas

### Onda 1 — plumbing real
- resolver;
- serie_precos;
- serie_indice;
- fundamentos.

Objetivo: provar identity, DB, PIT, provenance e LLM path.

### Onda 2 — matemática unitária
- risco_retorno;
- historico_comparado;
- tendencias;
- valor_mercado.

### Onda 3 — fatores
- dependencia;
- sensibilidade;
- condicional;
- regimes.

### Onda 4 — compostas/específicas
- event_study;
- expectativas;
- curva;
- composição;
- cenário;
- comparáveis.

Cada onda precisa ficar PROD_GREEN antes da próxima, salvo decisão explícita.

---

## 5. Matriz que o Codex deve preencher no backend real

Para cada tool, criar tabela com:

| Campo | Valor |
|---|---|
| tool | |
| semver ref | |
| production module | |
| exposed to LLM | |
| LLM tool schema source | |
| prepare/resolver | |
| DB tables/views | |
| source/vendor | |
| identity source | |
| unit | |
| currency | |
| observation date | |
| availability date | |
| vintage | |
| cutoff semantics | |
| policy versions | |
| oracle implementation | |
| golden | |
| replay | |
| targeted tests | |
| PostgreSQL/staging gate | |
| E2E question | |
| LLM expected call | |
| LLM forbidden inference | |
| shadow result | |
| monitoring | |
| certification status | |

---

## 6. Status de próximas capabilities

### Brent
Ainda não é uma tool decidida.
É uma fundação de fator/commodity.
O DB real pode resolver o source gate se tiver uma série confiável.

### Fair value / reverse DCF
Ainda não está liberado.
Depois da integração, auditar se o DB real possui todas as premissas necessárias com lineage.

### Qualquer outra
Somente após `POST_INTEGRATION_CAPABILITY_AUDIT`.

A existência de coluna/tabela nova não cria automaticamente uma nova tool.
