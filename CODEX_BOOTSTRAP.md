# Plexo — Codex Bootstrap

Este é o único arquivo que precisa ser citado manualmente ao iniciar uma nova sessão Codex.

## Instrução

Antes de alterar qualquer arquivo, executar código, consultar o banco ou propor implementação:

1. leia integralmente `AGENTS.md`;
2. leia integralmente `.ai/CODEX_START_HERE_2026-10-04.md`;
3. leia integralmente `.ai/CODEX_PACKAGE_MANIFEST_2026-10-04.md`;
4. siga, na ordem, todos os documentos obrigatórios apontados por esses arquivos;
5. leia especialmente:
   - `.ai/LLM_BACKEND_PRODUCTION_INTEGRATION_MASTER_PLAN_2026-10-04.md`;
   - `.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`;
   - `.ai/TOOL_INTEGRATION_CERTIFICATION_MATRIX_2026-10-04.md`;
   - `.ai/PRODUCTION_TOOL_PARITY_MATRIX_2026-10-04.md`;
   - `.ai/CODEX_PRODUCTION_INTEGRATION_RUNBOOK_2026-10-04.md`;
   - `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`.

A `.ai/` é a memória canônica do projeto.

## Missão atual

Integrar ao backend e à LLM realmente existentes as tools/metodologias validadas neste repo, usando o banco real como fonte e certificando cada capability antes de produção.

Não criar outra LLM.
Não conectar as tools diretamente às tabelas externas sem mapping.
Não copiar o repo inteiro cegamente sobre o backend real.
Não migrar as 18 tools de uma vez.
Não criar novas tools antes de auditar o backend e o banco.

## Primeira tranche obrigatória

Faça somente:

1. descobrir o backend/LLM realmente deployado;
2. produzir `.ai/PRODUCTION_BACKEND_DISCOVERY_2026-10-04.md`;
3. auditar o banco real em modo read-only;
4. produzir `.ai/EXTERNAL_DATA_BASE_AUDIT_2026-10-04.md`;
5. preencher a primeira versão de `.ai/PRODUCTION_TOOL_PARITY_MATRIX_2026-10-04.md`;
6. corrigir os dois testes strict-PIT temporais conhecidos sem enfraquecer PIT;
7. rodar os gates e registrar o novo baseline;
8. propor o vertical slice:
   `dados.resolver_instrumento -> dados.serie_precos -> quant.risco_retorno`;
9. listar riscos, bloqueios, arquivos que pretende alterar e plano de testes/shadow/rollback;
10. parar para revisão antes de portar o catálogo restante.

## Regra de certificação

Nenhuma tool é considerada pronta apenas porque retorna JSON ou um número.

Para chegar a `PROD_GREEN`, exigir:
- dado correto;
- identidade/unidade corretas;
- temporalidade/PIT/vintage corretos;
- oracle numérico independente;
- provenance;
- semver/replay;
- LLM routing correto;
- fidelidade da resposta da LLM ao output;
- E2E;
- shadow;
- monitoring;
- rollback.

Se houver divergência entre referência, banco e backend real, pare e classifique a causa antes de decidir.

## Frase para iniciar

Depois de abrir a raiz do workspace no VS Code, envie ao Codex somente:

`Leia CODEX_BOOTSTRAP.md integralmente e execute apenas a primeira tranche definida nele. Antes de começar, confirme os arquivos canônicos lidos e o baseline que você considera válido.`

Não é necessário colar nenhum prompt longo.
