# Primeira mensagem para o Codex — integração no backend/LLM real

Use este texto ao iniciar a sessão Codex que terá acesso ao backend existente e ao banco real/staging.

---

Quero integrar ao backend e à LLM já existentes as tools e metodologias de Company & Market Analytics validadas neste repositório.

Este NÃO é um projeto para criar uma nova LLM nem para conectar tabelas diretamente ao modelo.

Seu objetivo é portar/adaptar os contratos, loaders e métodos deste repo ao backend real que já existe, usando o banco real como fonte, e provar que cada resultado está correto ponta a ponta.

Antes de alterar código:

1. leia `AGENTS.md`;
2. leia `.ai/CODEX_START_HERE_2026-10-03.md`;
3. leia `.ai/LLM_BACKEND_PRODUCTION_INTEGRATION_MASTER_PLAN_2026-10-04.md`;
4. leia `.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`;
5. leia `.ai/TOOL_INTEGRATION_CERTIFICATION_MATRIX_2026-10-04.md`;
6. leia `.ai/CODEX_PRODUCTION_INTEGRATION_RUNBOOK_2026-10-04.md`;
7. leia `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`;
8. siga os documentos canônicos/checkpoints citados.

A `.ai/` é a memória canônica.

### Primeira responsabilidade: descobrir o backend real

Não assuma que este repo de validação é exatamente o repo deployado.

Identifique:
- qual repo/worktree é produção;
- branch/HEAD;
- entrypoint API;
- orquestrador LLM;
- provider abstraction;
- function/tool calling;
- prompt/version system;
- registry;
- executor;
- DB access;
- RLS/tenant;
- tool audit;
- evidence;
- cache;
- blocks/UI;
- deploy/CI.

Grave:
`.ai/PRODUCTION_BACKEND_DISCOVERY_2026-10-04.md`.

Crie uma matriz entre os componentes deste repo e o backend real:
REUSE_AS_IS / PORT / ADAPT / ALREADY_EQUIVALENT / GAP.

Não copie o projeto inteiro cegamente.

### Segunda responsabilidade: auditar o banco real

Comece read-only.

Mapeie:
- instrumentos;
- aliases;
- preços;
- corporate actions;
- índices/taxas;
- FX;
- calendário;
- fundamentos;
- share counts;
- dívida/caixa;
- setores/subsetores;
- expectations;
- curvas;
- index membership;
- possíveis commodities;
- forecasts/valuation inputs;
- sources/vendors;
- units/currencies;
- observation/reference/publication/availability/ingestion dates;
- vintages/revisions.

Grave:
`.ai/EXTERNAL_DATA_BASE_AUDIT_2026-10-04.md`.

Não faça DDL/DML de produção nesta fase.

### Terceira responsabilidade: corrigir o baseline

Existe uma falha conhecida em dois testes strict-PIT após rollover UTC.

Não afrouxe strict PIT.
Torne as fixtures temporais determinísticas e obtenha novo baseline totalmente GREEN antes de usar o HEAD atual como referência de produção.

### Quarta responsabilidade: mapear as 18 tools

Use `.ai/TOOL_INTEGRATION_CERTIFICATION_MATRIX_2026-10-04.md`.

Para cada tool, mapear:
- params/output;
- data real;
- loader;
- policy;
- temporal semantics;
- oracle;
- tests;
- LLM route;
- production status.

Comece com vertical slice:

1. `dados.resolver_instrumento`;
2. `dados.serie_precos`;
3. `quant.risco_retorno`.

Quero provar primeiro o caminho:

LLM
→ tool call
→ param validation
→ DB real
→ resolved input
→ cálculo determinístico
→ output hash/provenance
→ JSON de tool
→ LLM synthesis
→ resposta correta.

### Validação é obrigatória

Uma tool NÃO está pronta porque retornou um número.

Ela precisa provar:
- DATA CORRECTNESS;
- METHOD/NUMERICAL CORRECTNESS;
- TEMPORAL/PIT CORRECTNESS;
- PROVENANCE;
- CONTRACT/REPLAY;
- LLM ROUTING;
- LLM OUTPUT FIDELITY;
- E2E;
- SHADOW PROD.

Use oracle independente: não valide uma função chamando ela própria ou o mesmo core.

Se houver divergência entre a implementação de referência e o backend real, pare e classifique:
- mapping;
- unit;
- source;
- vintage;
- calendar;
- algorithm;
- precision;
- bug.

Não escolha silenciosamente.

### Regra da LLM

A LLM:
- interpreta;
- escolhe tool;
- parametriza;
- explica.

A LLM NÃO:
- calcula retorno/volatilidade/fair value por conta própria;
- executa SQL livre para produzir número financeiro;
- escolhe source-priority;
- inventa premissa;
- corrige output numericamente.

Números materiais devem vir da tool.

### Próximas capabilities

Não comece fair value/DCF ou outras tools antes de integrar e auditar o banco.

Depois que a camada atual estiver funcionando, gere:
`.ai/POST_INTEGRATION_CAPABILITY_AUDIT_2026-10-04.md`.

Brent:
- primeiro verificar se o banco real já possui série confiável e qual tipo.

Fair value:
- só desbloquear se forecasts/WACC/ERP/risk-free/beta/debt/tax/terminal assumptions forem governáveis e tiverem provenance.

Não inventar defaults.

### Entrega da primeira tranche

Pare depois de produzir:

1. `PRODUCTION_BACKEND_DISCOVERY`;
2. `EXTERNAL_DATA_BASE_AUDIT`;
3. primeira versão da `PRODUCTION_TOOL_PARITY_MATRIX`;
4. diagnóstico da falha temporal do CI e correção proposta/implementada;
5. plano do vertical slice resolver → preços → risco;
6. riscos/bloqueios.

Não migre as 18 tools de uma vez.
Não ative em produção sem shadow e certificação.
