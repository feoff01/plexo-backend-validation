# Plexo — Pacote para Codex / VS Code

Este diretório deve ser sobreposto na RAIZ do workspace/repositório em que o Codex trabalhará.

## Estrutura esperada

```
<repo-root>/
  AGENTS.md
  CODEX_PACKAGE_README.md
  .ai/
    CODEX_START_HERE_2026-10-04.md
    CODEX_PACKAGE_MANIFEST_2026-10-04.md
    ...
```

## Se o Codex vai trabalhar no repo de referência

Use:
- repo `feoff01/plexo-backend-validation`;
- branch `bootstrap/plexo-project`.

Faça pull e abra a RAIZ do repo no VS Code.

Não precisa copiar o código `app/`, `tests/`, `prompts/` etc.; ele já existe.

## Se o backend de produção estiver em outro repo

O Codex deve ter acesso simultâneo a:
1. este repo de referência;
2. o repo/backend realmente deployado.

Copie este pacote de instruções para o workspace principal ou mantenha o repo de referência aberto, mas NÃO copie cegamente toda a implementação para produção.

A primeira atividade é discovery/parity.

## Primeira mensagem

Não cole o prompt longo.

Envie apenas:

`Leia CODEX_BOOTSTRAP.md integralmente e execute apenas a primeira tranche definida nele. Antes de começar, confirme os arquivos canônicos lidos e o baseline que você considera válido.`

O arquivo `CODEX_BOOTSTRAP.md` aponta para toda a documentação canônica.

O prompt longo permanece disponível, se necessário, em:
`.ai/CODEX_PRODUCTION_INTEGRATION_FIRST_MESSAGE_2026-10-04.md`

## Arquivo principal

O Codex deve começar lendo:

`.ai/CODEX_START_HERE_2026-10-04.md`

O `AGENTS.md` também aponta automaticamente para ele.

## Regra crítica

Nenhuma tool está certificada no backend real apenas porque foi validada neste repo.

A certificação no alvo precisa comprovar:
- dado correto;
- método correto;
- PIT/vintage;
- provenance;
- replay/contrato;
- LLM routing;
- LLM fidelity;
- E2E;
- shadow;
- monitoring/rollback.

Leia:
`.ai/FINANCIAL_TOOL_CORRECTNESS_STANDARD_2026-10-04.md`.

## Estado de CI

Último baseline funcional integralmente GREEN:
`bf16dfd561f97e136060d77d80f50092cdc4538d`, run #341.

O pacote documental mais recente observado no run #367 ainda reproduz 2 falhas de fixture strict-PIT por rollover de relógio. Corrigir a fixture, nunca afrouxar PIT.
