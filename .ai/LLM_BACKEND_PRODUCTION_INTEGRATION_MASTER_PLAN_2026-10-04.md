# Plexo — Master Plan de Integração no Backend/LLM Existente

Data: 2026-10-04
Status: **CANÔNICO PARA MIGRAÇÃO / INTEGRAÇÃO**
Escopo: Company & Market Analytics / Analista de Mercado

## 1. Objetivo real

O trabalho a partir de agora NÃO é simplesmente "conectar uma base externa".

O objetivo é integrar ao **backend e à LLM já existentes em produção** o conjunto de:
- contratos de tools;
- loaders/resolvers;
- métodos quantitativos;
- políticas;
- provenance;
- semver/replay;
- testes/gates;
- planner;
- renderização de blocos;

que foram construídos e validados neste repositório de referência.

A integração só é considerada concluída quando a LLM real consegue:

1. interpretar corretamente a intenção do usuário;
2. selecionar a tool correta;
3. parametrizar corretamente;
4. buscar os dados corretos no banco real;
5. respeitar cutoff/vintage/source-priority;
6. executar o método determinístico correto;
7. devolver um resultado numericamente validado;
8. registrar provenance/auditoria;
9. entregar o output à LLM sem ela recalcular números;
10. sintetizar uma resposta fiel ao output;
11. funcionar ponta a ponta no backend real;
12. passar os gates de produção.

Este repo é a **referência validada de comportamento e contratos**. O Codex deve primeiro descobrir como o backend real já implementa essas responsabilidades e então adaptar/portar, não substituir a arquitetura real cegamente.

---

## 2. Arquitetura de referência já existente neste repo

### Entrada da LLM
`app/api/routes/copilot.py`
-> cria `TurnoCopiloto`
-> recebe user/scope/conversation/mode.

### Orquestração do turno
`app/agents/turn.py`

Responsabilidades existentes:
- routing;
- prompt aprovado;
- contexto;
- catálogo de tools filtrado por família/plano;
- function/tool calling;
- execução das chamadas;
- entrega do output da tool ao modelo;
- síntese;
- guardrails;
- blocos;
- provenance da conversa.

A definição enviada ao provedor é construída diretamente do registry:

`ToolDef(name=spec.code, description=spec.description, parameters=spec.param_schema)`.

Não existe schema duplicado manualmente no prompt.

### Registry
`app/tools/registry.py`

Cada tool possui duas metades:

1. `preparar(params, ctx)`
   - assíncrona;
   - pode ler DB;
   - resolve identidades;
   - carrega séries;
   - lê policies;
   - aplica cutoff;
   - produz objeto resolvido auditável.

2. `calcular(resolvido)`
   - pura;
   - determinística;
   - sem DB;
   - sem relógio;
   - sem LLM;
   - golden-testável.

Esse limite deve ser preservado no backend real.

### Executor
`app/tools/executor.py`

O executor atualmente:
- valida params via Pydantic;
- cria `ToolContext`;
- resolve dados/policies;
- registra `requested_params`;
- registra `resolved_params`;
- registra policies usadas;
- registra inputs;
- calcula `input_hash`;
- usa semver;
- usa content-addressed cache;
- grava `tools.tool_executions`;
- calcula output puro;
- grava `output_payload` e `output_hash`.

Isso é parte do contrato de auditabilidade, não detalhe descartável.

### Sync/versionamento
`app/tools/sync.py`

O código é a fonte de verdade do contrato; o banco espelha:
- tool code;
- schemas;
- semver;
- git SHA;
- source SHA;
- versão corrente/deprecated.

Mudança de fonte com a mesma semver é erro.
Não reescrever versão publicada.

### Prompts
`app/llm/prompts.py`

Prompt vigente precisa estar aprovado.
Prompt/code drift deve continuar sendo gate.

### Evidence
`app/agents/analysis.py`

Findings quantitativos/documentais preservam tool execution e provenance.

### Blocos
`app/agents/blocos.py`

A visualização é derivada do output tipado; não deve recalcular o domínio financeiro.

---

## 3. Primeira missão do Codex no backend real

Antes de portar qualquer arquivo, descobrir o backend/LLM já existente.

Gerar:
`.ai/PRODUCTION_BACKEND_DISCOVERY_2026-10-04.md`

O documento deve responder:

### Repositório/runtime
- qual repo é efetivamente deployado;
- branch de produção;
- linguagem/framework;
- processo de deploy;
- workers/background jobs;
- cache;
- observabilidade.

### LLM
- endpoint da conversa;
- provider/model abstraction;
- como function calling é montado;
- onde os tool schemas vivem;
- como prompts são versionados;
- como tool results voltam ao modelo;
- limites de tool calls;
- streaming;
- retry;
- guardrails;
- logging de model calls.

### Banco
- banco usado pela LLM;
- schemas;
- RLS/tenant/scope;
- policies;
- tool execution audit;
- analysis/evidence;
- market datasets;
- fontes;
- vintages;
- production/staging/replica.

### Integração
Para cada componente deste repo, localizar o equivalente no backend real:
- `TurnoCopiloto`;
- `ToolSpec/registry`;
- `ToolContext`;
- `executar_tool`;
- tool sync/version table;
- prompt loader;
- analysis/evidence;
- blocks/rendering;
- market loaders;
- analytics core.

Classificar cada componente como:
- REUSE_AS_IS;
- PORT;
- ADAPT;
- ALREADY_EQUIVALENT;
- NOT_NEEDED;
- GAP.

Nenhum port antes desta matriz.

---

## 4. Regra de migração

O Codex NÃO deve copiar o projeto inteiro sobre o backend real.

A unidade de migração é o **contrato**, não o arquivo.

Para cada capability:
1. preservar tool code;
2. preservar semântica de params;
3. preservar output;
4. preservar cálculo;
5. mapear loaders para o DB real;
6. preservar temporalidade;
7. preservar provenance;
8. preservar semver/replay;
9. ligar ao catálogo da LLM real;
10. validar ponta a ponta.

Se o backend real já possui uma abstração equivalente melhor, adaptar a tool a ela sem perder esses invariantes.

---

## 5. Arquitetura alvo no sistema real

```
Usuário
  ↓
Backend/LLM existente
  ↓
Router / agente Analista
  ↓
Catálogo versionado de tools
  ↓
LLM escolhe tool + params
  ↓
Executor determinístico
  ↓
preparar()
  ↓
Identity Resolver
  ↓
Loaders / Source Priority / PIT
  ↓
Banco real
  ↓
Resolved Input + Provenance
  ↓
calcular() puro
  ↓
Output tipado + hash
  ↓
Tool Execution / Evidence
  ↓
JSON volta à LLM
  ↓
LLM explica sem recalcular
  ↓
Resposta / blocos / citações
```

O banco real é a fonte dos fatos.
A LLM não consulta tabelas livremente para calcular.

---

## 6. Paridade obrigatória entre referência e backend real

Criar:
`.ai/PRODUCTION_TOOL_PARITY_MATRIX_2026-10-04.md`

Para cada uma das 18 tools de mercado registrar:
- code/semver de referência;
- implementação de referência;
- endpoint/orquestrador real;
- schema real;
- loader real;
- tabelas/views reais;
- source/vendor;
- policy usada;
- temporal semantics;
- status de replay;
- status de teste;
- status de integração LLM;
- status de certificação numérica;
- status de produção.

Estados:
- NOT_MAPPED;
- MAPPED;
- PORTED;
- DATA_VALIDATED;
- NUMERICALLY_CERTIFIED;
- E2E_CERTIFIED;
- SHADOW_PROD;
- PROD_GREEN.

Nenhuma tool é "integrada em produção" antes de `PROD_GREEN`.

---

## 7. Integração do banco real

O banco do backend real pode já conter dados suficientes.
Portanto o default é **mapear antes de ingerir duplicado**.

Para cada tabela/fonte real:
- identificar conceito econômico;
- unidade;
- moeda;
- identidade;
- data econômica;
- data de publicação;
- disponibilidade;
- vintage/revisão;
- source/vendor;
- qualidade;
- coverage;
- licença.

Depois decidir:
- usar diretamente via loader canônico;
- criar view/adaptor;
- materializar no schema canônico;
- rejeitar por semântica inadequada.

Não duplicar B3/CVM/ANBIMA/Bacen se o banco real já possui uma versão confiável e auditável.
Não assumir equivalência apenas pelo nome da coluna.

---

## 8. Integração LLM

O comportamento desejado é o padrão já validado em `app/agents/turn.py`:

1. o agente recebe apenas tools permitidas;
2. tool schema vem do contrato tipado;
3. o modelo escolhe tool e argumentos;
4. backend valida os argumentos;
5. backend executa;
6. resultado tipado volta como mensagem `role=tool`;
7. LLM apenas interpreta;
8. evidência e execution id ficam registradas.

Proibido:
- prompt ensinar fórmula para o modelo calcular;
- modelo executar SQL financeiro livre;
- modelo escolher source priority;
- modelo preencher premissa numérica ausente;
- modelo modificar resultado da tool.

Quando o dado for insuficiente:
- tool devolve insuficiência/warning ou erro tipado;
- LLM explica a ausência;
- nunca estimar silenciosamente.

---

## 9. Integração em produção por fases

### Fase 0 — higiene da referência
Corrigir os dois testes strict-PIT não determinísticos atuais sem alterar produção semantics.
Novo baseline deve ficar integralmente GREEN.

### Fase 1 — discovery
Somente leitura dos repos/backend/DB reais.
Gerar discovery + parity matrix.

### Fase 2 — DB mapping
Gerar audit da base.
Para cada tool, apontar os dados reais necessários.

### Fase 3 — primeiro vertical slice
Escolher UMA tool representativa, preferencialmente:
- `dados.resolver_instrumento`;
- depois `dados.serie_precos`;
- depois `quant.risco_retorno`.

Motivo: isso valida identidade -> loader -> cálculo -> LLM antes de abrir toda a superfície.

### Fase 4 — shadow
Tool real executa contra o DB real sem ser usada para responder produção.
Registrar:
- input;
- output;
- tempo;
- provenance;
- divergência contra oracle/referência.

### Fase 5 — E2E controlado
Pergunta real de teste:
LLM -> tool -> DB -> cálculo -> resposta.

### Fase 6 — ampliar por família
Depois do vertical slice:
- séries;
- fatores;
- eventos;
- fundamentos;
- valuation atual;
- comparáveis.

### Fase 7 — produção
Ativação controlada por feature flag/plan/allowlist quando possível.
Monitorar.

---

## 10. Não migrar tudo de uma vez

Ordem recomendada para as 18 tools:

### Grupo A — identidade e dados brutos
1. `dados.resolver_instrumento`
2. `dados.serie_precos`
3. `dados.serie_indice`
4. `dados.fundamentos_empresa`

### Grupo B — cálculo direto
5. `quant.risco_retorno`
6. `dados.historico_comparado`
7. `quant.tendencias_fundamentais`
8. `quant.valor_mercado`

### Grupo C — múltiplas séries/fatores
9. `quant.dependencia`
10. `quant.sensibilidade`
11. `quant.analise_condicional`
12. `quant.regimes`

### Grupo D — estruturas específicas
13. `quant.event_study`
14. `dados.expectativas_mercado`
15. `dados.curva_juros`
16. `dados.composicao_indice`

### Grupo E — composição
17. `quant.cenario_sensibilidade`
18. `quant.comparaveis_setor`

A ordem pode mudar após o audit do DB, mas a dependência deve ser explícita.

---

## 11. Definição de "funciona"

Não basta:
- endpoint 200;
- JSON válido;
- teste unitário passar;
- LLM citar um número.

Uma tool funciona apenas se:
- dado correto;
- identidade correta;
- unidade correta;
- cutoff correto;
- fórmula correta;
- amostra correta;
- output correto;
- provenance correto;
- LLM escolheu a tool correta;
- LLM não alterou o número;
- resposta comunica limites corretamente.

O standard detalhado está em:
`.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`.

---

## 12. Próximas tools depois da integração

NÃO continuar roadmap de novas capabilities antes de descobrir o que o DB real já contém.

Após o mapping, gerar:
`.ai/POST_INTEGRATION_CAPABILITY_AUDIT_2026-10-04.md`

Esse audit deve reavaliar:

### Brent/commodity
Se o DB real já tiver Brent:
- confirmar source;
- spot/future;
- unidade;
- coverage;
- licensing;
- vintage.

Talvez o source gate EIA deixe de ser necessário ou vire apenas fallback.

### Fair value / reverse DCF
Só desbloquear se o DB fornecer ou permitir governar:
- forecasts;
- risk-free;
- ERP;
- beta;
- WACC/cost of capital;
- dívida/custo;
- tax;
- terminal assumptions.

Ter dados não basta: cada premissa precisa de provenance e contrato.

### Outras capabilities
Só propor depois de responder:
- qual pergunta nova o usuário poderá fazer;
- qual dado real sustenta a resposta;
- qual cálculo determinístico falta;
- por que nenhuma tool atual cobre isso.

---

## 13. Entregáveis obrigatórios do Codex antes de produção

1. `PRODUCTION_BACKEND_DISCOVERY`;
2. `EXTERNAL_DATA_BASE_AUDIT`;
3. `PRODUCTION_TOOL_PARITY_MATRIX`;
4. `TOOL_CERTIFICATION_MATRIX`;
5. novo baseline CI GREEN;
6. pelo menos um vertical slice E2E;
7. shadow results;
8. numeric oracle comparison;
9. PIT/look-ahead tests;
10. source/provenance tests;
11. LLM routing tests;
12. production rollout plan;
13. rollback plan;
14. monitoring plan.

Sem esses itens, não declarar migração encerrada.
