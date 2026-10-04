# Plexo — Auditoria arquitetural e inventário de capacidades do Analista

Data: 2026-09-30
Status: **canônico para decidir novas features depois do FQ5.1–FQ5.4**
Escopo: empresa + mercado. Portfolio Analytics, suitability e análise da carteira/cliente permanecem fora desta frente.

## 1. Motivo da auditoria

Após a promoção do FQ5.1–FQ5.4 foi detectado que `quant.dependencia_macro` resolveu uma lacuna real de **fonte** (FX em `market.fx_rates`), mas criou uma nova interface pública que repete grande parte da orquestração de `quant.dependencia`.

Isso mostrou um risco transversal: antes de criar qualquer nova tool precisamos distinguir rigorosamente entre:

1. matemática que já existe;
2. loader/adapter de uma nova fonte;
3. preparação/alinhamento que deveria ser compartilhado;
4. intenção analítica realmente nova;
5. composição determinística necessária porque o DAG não transfere outputs numéricos entre nós;
6. legacy deliberado que existe apenas para replay.

Esta auditoria congela o mapa atual para que o próximo desenvolvimento seja **reuse-before-build**.

---

## 2. Regra arquitetural canônica: REUSE BEFORE BUILD

Antes de criar tabela, engine, cálculo ou tool nova, a implementação deve passar por esta ordem:

1. **Existe a matemática no Quant Core?** Reutilizar; não reimplementar.
2. **Existe a fonte no schema?** Criar/estender loader sem criar tabela paralela.
3. **Existe loader/adapter compatível?** Estender a abstração de série/fator, não copiar preparação de tool.
4. **Existe tool com a mesma intenção e contrato?** Evoluir de forma versionada; não criar um nome por fonte (`*_macro`, `*_fx`, `*_petroleo` etc.).
5. **A nova pergunta é uma intenção analítica diferente?** Só então uma tool nova é candidata.
6. **O número depende deterministicamente do output de outro cálculo?** Como o DSL atual só expressa ordem (`depends_on`) e mantém `params` estáticos, uma tool composta pode ser legítima — mas deve chamar o core/tool existente, nunca copiar a matemática.
7. **Mudança toca source fingerprint de tool pública?** Fazer cutover versionado e preservar implementação histórica para replay.

Consequência: **não haverá tool por fonte**. Ativo, índice, taxa, FX, futura commodity e curva devem convergir para adapters/fatores canônicos consumidos pelos mesmos engines quando a matemática for a mesma.

---

## 3. Catálogo atual

O registry possui 33 tools no total. Para o Analista, as famílias autorizadas continuam sendo `quant` e `dados`; tools de planejamento/orçamento/produto pertencem a outra frente.

### 3.1 Tools públicas do Analista — dados

| Tool | Versão | Papel canônico | Observação |
|---|---:|---|---|
| `dados.resolver_instrumento` | 1.0.0 | resolver ticker/nome/alias | identidade, não cálculo |
| `dados.serie_precos` | 1.0.2 | série compacta de fechamento | leitura/apresentação, não Quant |
| `dados.historico_comparado` | 1.1.1 | comparação base 100 | visualização comparativa |
| `dados.serie_indice` | 1.1.1 | índice/taxa oficial | contexto de juros/inflação/benchmark |
| `dados.expectativas_mercado` | 1.0.0 | Focus/Bacen | projeção de terceiros, não forecast Plexo |
| `dados.fundamentos_empresa` | 1.0.0 | fundamentos DFP PIT | `availability_date`, unidade e provenance |

### 3.2 Tools públicas do Analista — Quant

| Tool | Versão | Matemática / intenção |
|---|---:|---|
| `quant.risco_retorno` | 1.0.1 | retorno, volatilidade, máximo drawdown |
| `quant.dependencia` | 1.0.1 | Pearson/Spearman + lag para ativo/ativo ou ativo/índice/taxa |
| `quant.analise_condicional` | 1.0.1 | retorno do ativo condicionado à alta/queda de driver |
| `quant.sensibilidade` | 1.0.1 | OLS univariado + HAC/Newey-West |
| `quant.regimes` | 1.0.1 | comparação entre regimes explícitos de nível/direção |
| `quant.event_study` | 2.0.0 | market model / market adjusted Event Study |
| `quant.valor_mercado` | 1.0.0 | market cap, EV e múltiplos; não fair value |
| `quant.cenario_sensibilidade` | 1.0.0 | choque explícito aplicado à sensibilidade histórica |
| `quant.dependencia_macro` | 1.0.0 | mesma dependência do Quant Core com índice/taxa/FX; **sobreposição a consolidar** |

### 3.3 Legacy oculto, intencional

| Tool | Versão | Motivo de existir |
|---|---:|---|
| `quant.retorno_volatilidade` | 1.0.4 | replay/golden anterior ao cutover para `quant.risco_retorno` |
| `quant.correlacao` | 1.0.3 | replay/golden anterior ao cutover para `quant.dependencia` |

Event Study também preserva código legacy/replay separado; `quant.event_study_v2` não está registrado.

**Regra:** legacy oculto não é candidato a base de feature nova. O caminho canônico é `app/market/analytics/*` + loaders atuais.

---

## 4. Quant Core já existente — NÃO recriar esta matemática

### 4.1 Retornos — `app/market/analytics/returns.py`

Já existe:
- validação de trajetória de preços;
- retornos simples e log;
- retorno acumulado por preço;
- retorno anualizado;
- composição de retornos simples;
- conversão de índices/taxas para observações compatíveis.

### 4.2 Estatística descritiva — `statistics.py`

Já existe:
- filtro de finitos;
- desvio-padrão amostral;
- resumo de distribuição.

### 4.3 Risco — `risk.py`

Já existe:
- volatilidade anualizada;
- **rolling volatility**;
- **downside deviation**;
- **downside deviation anualizado**;
- **drawdown series**;
- máximo drawdown;
- episódio de máximo drawdown;
- **duração de drawdown**;
- **tempo de recuperação**.

Hoje a tool pública `quant.risco_retorno` expõe só parte desse core. Portanto uma futura pergunta sobre downside risk, rolling vol ou recovery **não autoriza matemática nova**; primeiro deve-se decidir se o contrato atual deve evoluir ou se há uma intenção realmente distinta.

### 4.4 Dependência — `dependence.py`

Já existe:
- Pearson;
- Spearman com ranks médios;
- alinhamento de retornos com lag assinado;
- estimativa de dependência;
- **rolling dependence**;
- **up-market dependence**;
- **down-market dependence**.

Logo rolling correlation e correlação em mercado de alta/baixa **já têm engine**.

### 4.5 Condicional — `conditional.py`

Já existe:
- transformação da condicionante em mudanças;
- alinhamento por intervalos com a resposta;
- resumo da amostra condicional e baseline.

### 4.6 Regressão/sensibilidade — `regression.py` + `sensitivity.py`

Já existe:
- OLS univariado com intercepto;
- covariance HAC/Newey-West Bartlett com correção finita;
- lag NW automático;
- estimativas com SE/CI;
- contrato de sensibilidade sobre intervalos alinhados.

### 4.7 Regimes — `regimes.py`

Já existe:
- driver por nível ou direção;
- threshold explícito/mediana retrospectiva conforme contrato;
- alinhamento de intervalos da resposta;
- comparação descritiva entre regimes.

### 4.8 Event Study — `event_study.py`

Já existe:
- sincronização correta de níveis antes do retorno;
- market model e market adjusted;
- janelas de estimação/evento;
- retorno anormal/CAR;
- CI clássico opt-in sob hipóteses explícitas.

### 4.9 Cenário — `scenario.py`

Já existe:
- aplicação de choque explícito ao slope de sensibilidade;
- impacto incremental;
- preço mecânico de cenário.

Não é forecast, fair value nem causalidade.

### 4.10 Valuation de mercado — `valuation.py`

Já existe:
- market cap por classe;
- dívida líquida;
- enterprise value;
- P/L;
- EV/EBITDA;
- P/VP;
- FCF yield.

Não existe ainda DCF/fair value/reverse DCF.

---

## 5. Loaders / adapters existentes

### 5.1 `MarketSeriesLoader`

Fonte canônica para preços `raw_close`/`adjusted_close`, índices/taxas, calendário, quality/provenance e temporal semantics.

`adjusted_close` é retrospectivo as-known-now enquanto corporate actions não tiverem availability/vintage completo.

### 5.2 `FundamentalsLoader`

Fonte canônica de fundamentos anuais com `reference_date`, `availability_date`, vintages append-only, unidade/moeda explícita, source/batch provenance e company/instrumento/classe.

Hoje o método principal é `load_latest_annual`; tendência multi-período ainda é lacuna de loader/contrato, não justificativa para uma tabela nova.

### 5.3 `app/market/factors.py`

Adapter atualmente criado para FX: normalização de moeda, código canônico `BASE/QUOTE`, leitura de `market.fx_rates`, conversão para `ResolvedMarketSeries` e quality/provenance.

**Este adapter é uma adição legítima.** O problema foi criar ao redor dele uma segunda tool de dependência em vez de generalizar a resolução de fatores numa evolução controlada.

### 5.4 `app/market/snapshots.py`

Já fornece snapshot do último preço bruto até cutoff para valuation/cenário.

---

## 6. Dados que já existem no schema e não devem ser recriados

### Consumidos hoje

- `market.prices`;
- `market.index_values` / `index_definitions`;
- `market.trading_calendar`;
- `market.corporate_actions` via preços ajustados;
- `market.market_expectations`;
- `market.fundamentals`;
- `market.fx_rates`.

### Existentes, mas ainda sem consumer Python do Analista

#### `market.sector_classification`
Já guarda setor/subsetor/segmento por `reference_date` + source + ingestion batch. Peers/setor deve começar por loader/resolver sobre essa tabela.

#### `market.index_weights`
Já guarda carteira teórica e peso por índice/data/instrumento. Membership, peso no IBOV e universo objetivo devem reutilizar essa tabela.

#### `market.yield_curve`
Já guarda curva por nome, data, dias úteis/corridos, taxa, day-count, source e batch. Análise de curva/juros deve começar por loader desta tabela.

**Atenção:** existência do schema não prova cobertura populada. Antes de prometer cobertura client-facing é obrigatório verificar ingestão, fontes, histórico e disponibilidade real.

---

## 7. Sobreposições encontradas

### 7.1 DUPLICAÇÃO REAL — `quant.dependencia_macro` × `quant.dependencia`

As duas tools repetem resolução/carregamento da resposta, janela/cutoff, cálculo de retornos, alinhamento com lag, quality gates, evidência/provenance e chamada ao mesmo `quant_dependence.dependence_estimate`.

Para índice/taxa elas praticamente oferecem a mesma capacidade. O diferencial real da macro é o adapter de FX.

**Conclusão:** manter o adapter FX; planejar cutover controlado para uma dependência canônica que aceite fatores plugáveis. Não deletar a tool atual nem quebrar replay.

### 7.2 LEGACY INTENCIONAL

- `quant.correlacao` → legado de `quant.dependencia`;
- `quant.retorno_volatilidade` → legado de `quant.risco_retorno`;
- Event Study legacy → golden/replay anterior ao 2.0.0.

São duplicações históricas controladas e ocultas.

### 7.3 COMPOSIÇÃO LEGÍTIMA — `quant.cenario_sensibilidade`

Reutiliza `preparar_sensibilidade` e `calcular_sensibilidade`; não reimplementa OLS/HAC; somente aplica choque/preço mecânico via `scenario.py`.

Isso é justificável porque o DSL atual não injeta output numérico de um nó nos `params` do próximo nó; `depends_on` expressa ordem, não dataflow. O LLM também não deve fazer a multiplicação.

### 7.4 COMPOSIÇÃO LEGÍTIMA — `quant.valor_mercado` × `dados.fundamentos_empresa`

A tool de dados é inspeção; a Quant produz métricas derivadas. A Quant lê o mesmo loader diretamente porque não há dataflow numérico entre tools e o LLM não pode ser a calculadora.

### 7.5 OVERLAP DE DADOS, NÃO DE INTENÇÃO

- `dados.serie_precos` × `dados.historico_comparado`: mesma base, outputs diferentes;
- `dados.serie_indice` × loaders internos Quant: apresentação compacta vs cálculo full-resolution;
- `dados.resolver_instrumento` × resolução interna: desambiguação do diálogo vs resolução determinística.

---

## 8. Dívida técnica de compartilhamento identificada

### 8.1 Preparação de driver/fator repetida

`quant.dependencia`, `quant.analise_condicional`, `quant.sensibilidade`, `quant.regimes` e `quant.dependencia_macro` repetem partes de resolução de ticker/index, classificação da unidade, carregamento de janela/cutoff e provenance/quality.

**Falta uma abstração canônica de factor loader / `ResolvedFactor`** capaz de resolver asset/index/FX e futuramente commodity/yield-curve sem duplicar tools.

### 8.2 Preparação analítica repetida em `conditional.py` e `regimes.py`

Há duplicação interna de validação de level path, alinhamento de intervalos e return summary. As análises são diferentes; o problema é somente preparação compartilhável.

**Cuidado:** refatorar módulos presentes em `source_dependencies` altera fingerprints. Fazer apenas num cutover versionado, não como cleanup silencioso.

### 8.3 `_comum.py` contém matemática legacy

Ainda existem helpers antigos como `retornos`, `retornos_de_indice`, `alinhar`, `max_drawdown`, `desvio` e `correlacao_pearson`. Parte serve ao código legacy.

O caminho canônico para features novas é `app/market/analytics/*`. Não adicionar matemática nova em `_comum.py`.

---

## 9. Capacidades latentes que já temos

Antes de escrever fórmula nova, checar:
- rolling volatility;
- downside deviation / anualizado;
- drawdown series;
- duração e recovery de drawdown;
- rolling Pearson/Spearman;
- up/down-market dependence;
- estatísticas descritivas;
- OLS/HAC;
- sensibilidade;
- condicional;
- regimes;
- Event Study;
- cenário mecânico;
- market cap/EV/múltiplos;
- séries de preços, índices/taxas, FX e fundamentos PIT.

**Engine existir não implica criar uma tool para cada função.** Primeiro agrupar por intenção do usuário e contrato de output.

---

## 10. Fronteira com Portfolio/cliente

Há matemática em `app/engine/simulacao.py` para retorno/volatilidade de carteira, matriz de covariância, Monte Carlo e percentis, e existem `market.assumption_sets`, `market.class_assumptions` e `market.class_correlations`.

Esses números são **premissas aprovadas de planejamento**, não correlações empíricas calculadas de séries de mercado. Não devem alimentar o Analista como se fossem observações históricas.

---

## 11. Lacunas reais após descontar o que já existe

1. Factor resolver/loader canônico para asset/index/FX e futuras extensões.
2. Tendências fundamentais multi-período PIT.
3. Peers/setor: schema existe; falta loader/resolução/comparação.
4. Index membership/weights: schema existe; falta consumer/tool.
5. Yield curve: schema existe; falta loader/analytics e contrato.
6. Commodity/Brent: confirmar fonte/schema/cobertura antes de criar qualquer coisa.
7. Fair value/reverse DCF: não existe; exige forecasts/WACC/ERP/growth explícitos e governados.
8. Prioridade/conflito de múltiplas fontes.
9. Availability/vintage incompleto para FX e corporate actions.
10. Storage histórico e mecanismo de payload/artifact compacto.

---

## 12. Decisão sobre `quant.dependencia_macro`

A tool pública 1.0.0 já existe e foi validada. Não será removida/regravada destrutivamente.

Antes da próxima feature, deve existir um design de consolidação para:
- manter o adapter FX;
- generalizar fator/driver em camada compartilhada;
- fazer uma única interface canônica de dependência aceitar fontes suportadas;
- preservar semver/fingerprint/replay;
- ocultar/deprecar a interface redundante somente num cutover controlado;
- impedir novas variantes como `sensibilidade_macro`, `regimes_macro`, `condicional_fx` ou `dependencia_petroleo`.

Nenhuma matemática FQ3/FQ4 precisa ser reaberta.

---

## 13. Gate obrigatório para qualquer nova capacidade

Toda proposta futura deve declarar antes de código:
- pergunta/intenção nova;
- engine existente;
- dados/schema existentes;
- gap real: fonte, loader, contrato, composição ou matemática;
- reuso escolhido;
- por que uma tool nova é necessária, se for;
- impacto semver/fingerprint/replay;
- temporalidade/provenance;
- output compacto.

Se não houver gap real demonstrado, **não criar nova matemática/tool**.

---

## 14. Próxima ação recomendada

Não iniciar FQ5.5 ainda.

Primeiro criar design curto de **consolidação de fatores e dependência**, sem mudar matemática:
1. contrato factor loader / `ResolvedFactor`;
2. asset/index/FX sobre a mesma interface;
3. plano de versionamento/replay para remover duplicação pública futura;
4. testes de equivalência numérica com as interfaces atuais;
5. regra para Brent/commodity/yield curve entrarem como adapters, não novas famílias de correlação.

Depois do cutover, FQ5.5 tendências fundamentais e FQ5.6 peers/setor podem avançar sobre o inventário existente.
