# Plexo Backend — Handoff Final para Novo Chat

Atualizado em: 2026-09-30

## Fonte de verdade

Use este arquivo como ponto inicial. Ele supersede qualquer trecho histórico antigo em outros documentos que ainda diga que o FQ4 está pendente.

Repositório autorizado: `feoff01/plexo-backend-validation`  
Branch atual: `bootstrap/plexo-project`

Não tocar em outros repositórios sem autorização explícita do usuário.

## Estado executivo

O núcleo Quant do Analista de Mercado foi construído de FQ0.5 até FQ4 e o **FQ4 está encerrado com CI PostgreSQL 18 totalmente verde**.

Run mais recente confirmado:
- GitHub Actions run #44
- run id: `36775645782`
- commit: `ac935bb14b44be42d0258fe613f1297a1ca5ed98`
- conclusão: `success`
- suíte completa: **806 passed, 52 skipped, 19 warnings, 0 failed**
- FQ1 + F5 + F22 + FQ4 E2E: verde
- `prompts check`: verde
- `tools sync --check`: verde
- migrations PostgreSQL 18 do zero: verdes
- invariantes SQL admin + `plexo_service`: verdes

O golden de blocos de `quant.event_study` que havia falhado num run intermediário já foi corrigido conscientemente para o contrato v2 e passou nos runs posteriores.

## Arquitetura que deve ser preservada

Princípio:
```
usuário -> LLM -> tool call JSON -> registry/executor -> cálculo determinístico -> output estruturado -> LLM explica
```

O LLM:
- entende;
- escolhe a tool;
- preenche parâmetros;
- explica o resultado.

O código:
- carrega dados;
- calcula;
- valida;
- versiona;
- registra provenance;
- produz evidência auditável.

Não transferir cálculo financeiro importante para o LLM.

## Infraestrutura central

Arquivos:
- `app/tools/registry.py`
- `app/tools/executor.py`
- `app/tools/sync.py`
- `app/tools/hashing.py`
- `app/agents/turn.py`
- `app/analysis/compiler.py`

Conceitos:
- `exposed_to_llm` separa replay/executável de tool ofertada ao modelo;
- fingerprint composto inclui dependencies relevantes;
- mesma semver + source alterado é conflito;
- cache é content-addressed;
- execução persiste `tools.tool_executions`;
- replay histórico deve ser preservado.

## Data Foundation

Arquivo principal:
- `app/market/series.py`

Conceitos:
- `MarketSeriesLoader`
- `ResolvedMarketSeries`
- `SeriesQuality`
- `SeriesProvenance`
- `PriceBasis.RAW_CLOSE`
- `PriceBasis.ADJUSTED_CLOSE`
- `TemporalSemantics.OBSERVATION_DATE_CUTOFF`
- `TemporalSemantics.RETROSPECTIVE_AS_KNOWN_NOW`

Regra crítica:
- adjusted close é retrospectivo com corporate actions conhecidas hoje;
- não prometer strict historical point-in-time;
- strict vintage exige availability/announcement metadata que ainda não existe de forma suficiente.

## Quant Core já construído

Diretório:
- `app/market/analytics/`

Engines principais:
- `models.py`
- `returns.py`
- `statistics.py`
- `risk.py`
- `dependence.py`
- `conditional.py`
- `estimates.py`
- `regression.py`
- `sensitivity.py`
- `regimes.py`
- `event_study.py`

Já existem:
- retornos simples/log;
- composição/anualização;
- estatística descritiva;
- volatilidade;
- rolling volatility;
- downside deviation;
- drawdown;
- Pearson/Spearman;
- lag/alinhamento;
- análise condicional;
- OLS;
- HAC/Newey-West;
- CI estruturado;
- sensibilidade;
- regimes;
- event study.

Não criar novas funções matemáticas apenas para “completar biblioteca”. Só adicionar quando uma capacidade real exigir.

## Catálogo canônico atual

### Públicas
- `quant.risco_retorno` — 1.0.1
- `quant.dependencia` — 1.0.1
- `quant.analise_condicional` — 1.0.1
- `quant.sensibilidade` — 1.0.1
- `quant.regimes` — 1.0.1
- `quant.event_study` — 2.0.0

### Legacy/replay
- `quant.retorno_volatilidade` — oculto
- `quant.correlacao` — oculto

### Event Study
Arquivo da implementação canônica:
- `app/tools/analista/event_study_v2.py`

Apesar do nome do arquivo, ele registra:
- code `quant.event_study`
- semver `2.0.0`
- público

Não registrar novamente `quant.event_study_v2`.

Legacy:
- `app/tools/analista/event_study.py` permanece sem decorator para compatibilidade/golden/replay;
- `app/tools/analista/event_study_legacy_1_0_1.py` é replay congelado.

## Event Study — regra temporal crítica

Não calcular retornos de ativo e benchmark em calendários diferentes e depois apenas casar data final.

V2:
1. intersecta datas dos níveis de preço;
2. forma caminhos sincronizados;
3. calcula retornos com endpoints idênticos.

A data efetiva é o primeiro retorno sincronizado >= data civil do evento.

Janelas:
- contam observações sincronizadas;
- estimation window não sobrepõe event window;
- `truncada_pre` e `truncada_pos` são separadas;
- CAR parcial pode existir;
- janela truncada torna a evidência insuficiente.

Inferência:
- default `none`;
- opcional `classic_iid_normal`;
- sem p-value;
- sem booleano de significância;
- sem alegação causal/preditiva.

## Sensibilidade

Engine:
- OLS univariada com intercepto;
- HAC/Newey-West Bartlett;
- correção finita;
- CI 95% normal assintótico;
- sem SciPy/statsmodels;
- sem imputação/winsorização/trimming.

Taxa:
- mudança de nível em pontos percentuais.

Ativo/índice em pontos:
- retorno.

A resposta é alinhada ao mesmo intervalo do driver.

## Regimes

Critérios:
- `level`
- `direction`

`level` usa nível do driver no começo do intervalo.

Default sem limiar:
- mediana retrospectiva da amostra válida.

Não existe no v1:
- HMM;
- clustering;
- threshold otimizado;
- drawdown em regime descontínuo.

## Planner

Arquivo:
- `prompts/analista.planner.j2`

Roteamento:
- comportamento de X quando Y sobe/cai -> `quant.analise_condicional`
- quanto X varia por 1 p.p./1% de Y -> `quant.sensibilidade`
- comparação alto/baixo/subindo/caindo -> `quant.regimes`
- evento datado -> `quant.event_study`

Não usar `quant.event_study_v2`.

Não substituir pergunta especializada por simples correlação quando a tool especializada responde melhor.

## Blocos

Arquivo:
- `app/agents/blocos.py`

`quant.event_study` aponta para o mapper v2.

Golden visual do Event Study foi atualizado explicitamente para o contrato 2.0.0 e já passou no CI.

## CI

Workflow:
- `.github/workflows/verify.yml`

Fluxo:
1. PostgreSQL 18 descartável;
2. Python 3.12;
3. dependências;
4. `.env` local descartável;
5. Alembic do zero;
6. preparação de ambiente;
7. validador;
8. SQL invariants;
9. SQL invariants como `plexo_service`;
10. FQ1/F5/F22/FQ4 E2E;
11. pytest completo;
12. prompts drift check;
13. tools drift check.

Nunca usar Aiven/produção para esse gate.

## Memória persistente

Sempre atualizar, conforme necessário:
- `.ai/PROJECT_STATE.md`
- `.ai/DECISIONS.md`
- `.ai/TASKS.md`
- `.ai/CHANGELOG.md`
- `.ai/PROMPT_LOG.md`
- `.ai/checkpoints/`

Ler também:
- `.ai/FQ4_INTEGRATION_PROMOTION_PLAN.md`
- `.ai/checkpoints/2026-09-30_FQ4_POSTGRES_CI_GREEN.md`
- `.ai/checkpoints/2026-09-30_FQ4_PROMOTION.md`

## Pendências reais agora

FQ4 não é mais pendência.

Antes da próxima grande família, revisar os gates transversais:

1. storage histórico:
   - Parquet;
   - PostgreSQL;
   - híbrido;
   - evitar carregar milhões de preços indiscriminadamente no Postgres remoto.

2. múltiplas fontes:
   - prioridade explícita;
   - conflitos;
   - provenance.

3. temporalidade real:
   - availability/vintage para corporate actions;
   - macro revisável;
   - revisões/backfills.

4. payload/artifacts:
   - outputs longos devem ficar fora do payload enviado ao LLM;
   - LLM deve receber resumo estruturado compacto.

5. integração final:
   - decidir destino do código validado;
   - não mexer em outros repositórios sem autorização.

## Próxima camada funcional

Não abrir mais matemática base por enquanto.

Duas direções naturais:
- **Fundamentals + Valuation**
- **Portfolio Analytics**

A escolha deve ser feita pelo objetivo do produto.

Antes de codar:
- escrever design em `.ai/`;
- definir perguntas que a camada responderá;
- definir fontes;
- definir contratos;
- definir engines;
- definir tools;
- definir edge cases;
- definir semver/fingerprint;
- definir testes/E2E.

## Regras de segurança e continuidade

- não ler/publicar `.env` real;
- não commitar segredos;
- não resetar/drop banco remoto;
- não editar migrations históricas;
- não mexer em repositórios antigos;
- não reexpor legacy;
- não recriar `quant.event_study_v2`;
- não chamar adjusted retrospective de PIT estrito;
- não declarar CI verde sem run real;
- não desfazer major bump só para preservar golden antigo.

## Observação GitHub

O repositório de validação apareceu como público nesta sessão. O snapshot não deve conter `.env` nem segredos. Se o usuário quiser restringir acesso, alterar o repo para Private no GitHub.

## Prompt para o próximo chat

Anexe o ZIP completo e envie:

> Quero continuar o desenvolvimento do backend Plexo exatamente do ponto em que o chat anterior terminou.
>
> Antes de alterar qualquer código, leia nesta ordem:
> 1. `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
> 2. `.ai/PROJECT_STATE.md`
> 3. `.ai/DECISIONS.md`
> 4. `.ai/TASKS.md`
> 5. `.ai/CHANGELOG.md`
> 6. os checkpoints citados no handoff.
>
> Trate `.ai/` como memória persistente do projeto e atualize esses arquivos a cada etapa relevante.
>
> Preserve a arquitetura do Plexo: o LLM interpreta, roteia e explica; código determinístico carrega dados e calcula. Preserve semver, source fingerprint, provenance, replay e gates.
>
> Não leia/publique `.env` ou segredos. Não altere migrations históricas. Não use banco remoto destrutivamente. Não mexa em nenhum repositório antigo. O único repo de validação autorizado é `feoff01/plexo-backend-validation`, branch `bootstrap/plexo-project`.
>
> Estado que você deve confirmar:
> - FQ0.5–FQ4 já foram construídos;
> - `quant.risco_retorno` 1.0.1 pública;
> - `quant.dependencia` 1.0.1 pública;
> - `quant.analise_condicional` 1.0.1 pública;
> - `quant.sensibilidade` 1.0.1 pública;
> - `quant.regimes` 1.0.1 pública;
> - `quant.event_study` 2.0.0 pública e usa a implementação FQ4.4;
> - `quant.event_study_v2` não está registrado;
> - replay legacy está preservado;
> - FQ4 está encerrado;
> - GitHub Actions run #44 / id `36775645782` ficou totalmente verde;
> - suíte completa: 806 passed, 52 skipped, 19 warnings, 0 failed;
> - FQ1/F5/F22/FQ4 E2E, prompts check e tools sync --check estão verdes.
>
> Sua primeira tarefa é fazer uma revisão de integridade curta do snapshot e me apresentar as pendências transversais reais e a recomendação de próxima camada funcional. Não reabra o FQ4 nem crie matemática nova sem necessidade. Se eu aprovar a próxima camada, crie primeiro o design em `.ai/`, depois implemente com testes e registre tudo.
>
> Não faça perguntas que os arquivos já respondem. Faça best effort e mantenha-me informado em trabalhos longos.

## Definição de sucesso do handoff

O novo chat deve conseguir apenas com este ZIP + prompt:
- entender a arquitetura;
- entender todo o Quant Core;
- saber o catálogo atual;
- saber o estado real do CI;
- saber o que já foi encerrado;
- saber o que ainda falta;
- não repetir trabalho;
- continuar com disciplina de versionamento/auditoria.


---

# Atualização de handoff — FQ5.1–FQ5.4 encerrado em 2026-09-30

Company / Market Analytics está pública e verde; Portfolio Analytics e análise de carteira/cliente continuam fora do escopo.

Tools novas:
- `dados.fundamentos_empresa` 1.0.0;
- `quant.valor_mercado` 1.0.0;
- `quant.cenario_sensibilidade` 1.0.0;
- `quant.dependencia_macro` 1.0.0.

Pergunta de referência Petrobras:
1. valuation → `quant.valor_mercado`;
2. choque explícito de juros → `quant.cenario_sensibilidade`; sem magnitude → `quant.sensibilidade`, sem inventar choque;
3. câmbio USD/BRL → `quant.dependencia_macro`.

Nunca chamar market cap/EV de fair value. DCF/fair value ainda não existe.

Estado verde de código: commit `14c522cba2ebabaa95e32e6937879be1557b3256`, run #49 `36784983441`.
- E2E: 74 passed;
- full suite: 816 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18/migrations/invariantes: verdes;
- prompts check / tools sync --check: verdes.

Próximo foco recomendado: FQ5.5 tendências fundamentais + FQ5.6 peers/setor, depois fatores como petróleo/commodities; fair value/reverse DCF somente com contrato explícito de forecasts/WACC/ERP/growth.


---

# Atualização canônica — auditoria de capacidades — 2026-09-30

**Esta seção substitui a recomendação anterior de iniciar diretamente FQ5.5/FQ5.6.**

Antes de qualquer nova feature, ler `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md` e o checkpoint `.ai/checkpoints/2026-09-30_ARCHITECTURE_CAPABILITY_AUDIT.md`.

Achado principal: `quant.dependencia_macro` reutiliza a mesma matemática de `quant.dependencia` e duplicou parte relevante da orquestração; o gap real era carregar FX. Não criar variantes por fonte no futuro.

Próxima etapa obrigatória: design de um factor resolver/loader compartilhado (asset/index/FX e fatores futuros) e plano de cutover versionado da dependência canônica, preservando replay/fingerprint. Não reabrir matemática FQ3/FQ4.

Mapa importante de reuso antes de qualquer nova matemática:
- rolling volatility, downside deviation, drawdown duration/recovery já existem;
- rolling dependence e up/down-market dependence já existem;
- `sector_classification`, `index_weights`, `yield_curve` já existem no schema;
- `class_correlations`/simulação de carteira pertencem ao domínio de planejamento do cliente e não são estatística histórica do Analista.

Estado remoto confirmado antes desta auditoria documental: HEAD `efd27727615cb9fdffa00ac250813798dbbd38e5`; run #50 `36785509026` totalmente verde; 74 E2E, 816 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes.


## Protocolo obrigatório de continuidade

Além da ordem de leitura já definida, ler `.ai/WORKING_PROTOCOL.md` antes de qualquer implementação nova.

Regra permanente: não depender de memória de chat. Decisões, estado, tarefas, changelog e checkpoints devem ser atualizados em `.ai/` a cada etapa relevante.

Próxima sequência recomendada (proposta, não implementada): consolidar factor resolver/dependência primeiro; depois retomar FQ5.5/FQ5.6.


## Design pronto — consolidação de fatores/dependência

Antes de implementar qualquer nova análise, ler `.ai/FACTOR_DEPENDENCY_CONSOLIDATION_DESIGN.md`.

O design está concluído, mas **não autoriza implementação até revisão/aprovação**.

Resumo:
- resolver compartilhado `FactorRef`/`ResolvedFactor` para ativo/índice/FX;
- transformação estatística continua específica de cada análise;
- proposta: `quant.dependencia` 2.0.0 com `serie_b={tipo,codigo}`;
- macro atual vira compatibilidade/replay oculta após cutover;
- sem alteração de FQ3/FQ4;
- sem migration;
- sem migração conjunta de sensibilidade/condicional/regimes;
- commodity/yield curve fora desta etapa.

Estado anterior confirmado: commit `fe268e2213a5c8524f7bb4baa852f2a6ecd5739e`, run #52 `36789531777` verde.


---

# Atualização canônica — factor/dependence cutover GREEN — 2026-09-30

A consolidação de `.ai/FACTOR_DEPENDENCY_CONSOLIDATION_DESIGN.md` está implementada e encerrada.

- `quant.dependencia` 2.0.0 é a única interface pública de dependência;
- `serie_b={tipo,codigo}` aceita ativo, indice e cambio;
- `quant.dependencia_macro` 1.0.1 está oculta e existe apenas para compatibilidade;
- replay de dependência 1.0.1 e macro 1.0.0 está congelado em módulos legacy + goldens;
- planner usa `quant.dependencia` para USD/BRL;
- não houve alteração de matemática FQ3/FQ4, migration ou schema;
- sensibilidade/condicional/regimes não devem ser migrados automaticamente.

Isolamento: 33 tools antes/depois; somente dependência e macro mudaram.

Gate de referência: código `60bad205666e5cc5c5d0e2b2b8e643f41e2ac322`; run #54 `36793672760` success; 87 E2E; 831 passed, 52 skipped, 19 warnings, 0 failed; validador 0/0; PostgreSQL 18, invariantes, prompts e tools sync verdes.

Próxima frente possível, ainda não iniciada: Fundamentals + Valuation. Aplicar primeiro `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md` e `.ai/WORKING_PROTOCOL.md`.


---

# Atualização canônica — FQ5.5 tendências fundamentais GREEN — 2026-09-30

FQ5.5 está encerrado.

- `quant.tendencias_fundamentais` **1.0.1** pública;
- DFP anual point-in-time por `availability_date <= cutoff`;
- YoY/margens determinísticos e compactos;
- EBITDA reportado preferido ao derivado;
- sem ITR/trimestre, CAGR, forecast ou fair value na v1;
- catálogo total: 34 tools; as 33 pré-existentes preservaram semver/exposição/fingerprint.

Promoção: commit `a8eb2bfeee7c77361fbefffe4d689b4328c70122`; run #57 `36796184892` success; 93 gate; **838 passed, 52 skipped, 19 warnings, 0 failed**; PostgreSQL 18, invariantes, prompts e tools sync verdes.

Checkpoint: `.ai/checkpoints/2026-09-30_FQ5_5_PROMOTION_GREEN.md`.

Próxima frente: FQ5.6 peers/setor. Antes de código, auditar ingestão/cobertura de `market.sector_classification`, reconhecer que ela possui `reference_date` mas não `availability_date`, deduplicar múltiplas classes por emissor e provar reuso dos engines/loaders existentes.


---

# Atualização canônica — FQ5.6 Peers/Setor — design/data gate — 2026-09-30

FQ5.5 está GREEN e encerrado; run documental #58 também está verde (93 gate; 838 passed, 52 skipped, 19 warnings, 0 failed).

Antes de qualquer código de peers, ler `.ai/FQ5_6_PEERS_SECTOR_DESIGN.md`.

Achado principal: `market.sector_classification` existe, mas o repo não possui ingestão real para essa tabela. Portanto `quant.comparaveis_setor` **não deve ser criada ainda**.

FQ5.6 foi dividido:
- FQ5.6A: validar fonte oficial B3, parser, ingestão, loader PIT e coverage gate;
- FQ5.6B: comparação company-level reutilizando valuation, tendências fundamentais e estatística existente.

Regras fixadas:
- fonte v1 = B3;
- identidade = CNPJ -> issuer; sem inferência por prefixo/root code;
- dedupe por issuer para múltiplas classes;
- strict PIT usa lote `succeeded` e `ingestion_batches.finished_at`; não foi criada migration de availability;
- linhas legadas sem lote não sustentam strict PIT.

Próxima ação: FQ5.6A1 — validar o contrato técnico oficial de download/API B3 e capturar fixture real antes de escrever parser de rede.


---

# Atualização canônica — FQ5.6A1 source audit / loader shadow

Antes de continuar FQ5.6, ler `.ai/FQ5_6A1_B3_SOURCE_AUDIT.md` e o checkpoint `.ai/checkpoints/2026-09-30_FQ5_6A1_SOURCE_AUDIT_AND_SECTOR_LOADER_SHADOW.md`.

Decisão de fonte:
- B3 UP2DATA / Empresas Listadas / SummaryData é o contrato estruturado oficial preferido;
- acesso recorrente é autenticado/contratual;
- não usar `listedCompaniesProxy` como API de produção sem contrato oficial;
- parser/ingestão só depois de fixture real oficial.

Shadow de código: `08bda53fa47eeef576a5fa525260f69d7818d906`. Existe apenas loader setorial PIT sobre o schema atual; nenhuma tool pública foi criada.


## FQ5.6A2a loader setorial — GREEN

HEAD validado: `e039d771c1b086e0f425d73d6c73822e688d3faa`. Run #61 / `36799893075`: success.

- gate explícito: 98 passed;
- suíte: 849 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18, invariantes, validador, prompts e tools sync verdes;
- nenhuma tool nova ou drift de catálogo.

**Não iniciar FQ5.6B ainda.** O bloqueio real é dados: obter fixture oficial B3/UP2DATA (ou export oficial equivalente), implementar parser/ingestão e medir cobertura antes de qualquer tool de comparáveis.


---

# Atualização canônica — FQ5.6A2 ingestão setorial shadow — 2026-09-30

Ler `.ai/FQ5_6A2_SECTOR_INGEST_SHADOW.md` antes de continuar FQ5.6.

Estado:
- loader PIT setorial já estava GREEN;
- amostra oficial B3 `Listed_Companies.zip` foi localizada, mas os bytes não foram materializados neste runtime;
- parser físico SummaryData **continua bloqueado** e não deve ser inventado;
- `app/market/sector_ingest.py` implementa apenas ingestão de registros semânticos validados;
- matching CNPJ->issuer, expansão multi-classe, idempotência e conflito fail-closed;
- coverage PIT pode ser medido por segmento/subsetor/setor, sem threshold automático;
- nenhuma tool de peers foi aberta.

Próximo gate imediato: PostgreSQL 18 para a ingestão shadow. Depois, obter bytes oficiais reais para parser + coverage real antes de FQ5.6B.


## FQ5.6A2 GREEN — fechamento
- shadow: `36ffa05f9cbacd51c04b7887f74be7036c972489`;
- CI #63 / `36801883060`: 103 gate; 861 passed, 52 skipped, 19 warnings, 0 failed;
- checkpoint: `.ai/checkpoints/2026-09-30_FQ5_6A2_SECTOR_INGEST_SHADOW_GREEN.md`;
- parser físico e coverage real continuam pendentes;
- FQ5.6B peers continua bloqueado até o coverage gate real.


## Dados Economatica fornecidos pelo usuário — 2026-10-01

Ler `.ai/ECONOMATICA_DATA_AUDIT_2026-10-01.md` antes de usar esses arquivos.

Regras:
- Economatica é fonte auxiliar, não `b3`;
- não retrodata setor pelo ano do workbook;
- não há CNPJ/segmento suficiente para substituir SummaryData B3;
- match futuro, se aprovado, deve ser ticker exato -> instrument -> issuer;
- não misturar preços/fundamentos vendor-derived ao acervo canônico sem policy própria.

FQ5.6B continua dependente de uma decisão explícita: aguardar SummaryData B3 ou criar uma integração auxiliar Economatica para classificação corrente/subsetor.


## FQ5.6 — Economatica auxiliar

Design aprovado em `.ai/FQ5_6_ECONOMATICA_AUX_SOURCE_DESIGN.md`.
Implementar somente shadow: parser XLSX + source próprio + ingestão corrente por ticker exato. Não abrir FQ5.6B antes do gate GREEN e da decisão explícita de source policy.


## FQ5.6 Economatica shadow candidate

Código shadow implementado conforme `.ai/FQ5_6_ECONOMATICA_AUX_SOURCE_DESIGN.md`. Aguardar CI PostgreSQL 18 antes de considerar GREEN. FQ5.6B continua bloqueada.


## FQ5.6 Economatica auxiliar — GREEN

Checkpoint: `.ai/checkpoints/2026-10-01_FQ5_6_ECONOMATICA_AUX_GREEN.md`.

Source auxiliar está implementado e testado, mas nenhuma tool pública usa Economatica automaticamente. Próximo passo: coverage dry-run por ticker exato contra o universo real do Plexo. FQ5.6B permanece bloqueada até esse gate.
