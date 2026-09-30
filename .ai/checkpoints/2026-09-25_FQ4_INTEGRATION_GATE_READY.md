# Checkpoint — FQ4 Integration Gate Ready

Data: 2026-09-25

## Pedido

Fechar integração real das quatro FQ4 shadows com PostgreSQL, tools sync, planner e testes E2E antes
de abrir outra família quantitativa.

## Implementado

- novo `tests/test_fq4_integration_db.py`;
- E2E usa `executar_tool()` real para as quatro shadows;
- massa de preços/índice passa por schema/views/loaders reais;
- assert de `tools.tool_executions` e cache do executor;
- `verify.yml` inclui FQ4 E2E no gate PostgreSQL 18;
- teste da própria CI exige presença desse gate;
- planner preparado com regras FQ4 condicionais ao catálogo, sem expor shadows;
- teste de readiness prova que shadows continuam invisíveis;
- plano de promoção documentado em `.ai/FQ4_INTEGRATION_PROMOTION_PLAN.md`.

## Validação local

Sem PostgreSQL:

- 429 passed;
- 16 skipped legítimos;
- 357 DB-deselected;
- 0 failed.

A diferença contra o checkpoint FQ4.4 anterior (426/16/355/0) é exatamente:

- +1 teste puro no arquivo E2E (registro/shadow);
- +2 testes puros de promotion readiness;
- +2 testes DB novos, que explicam 355 -> 357 deselected.

Registry:

- 30 tools;
- 30 códigos únicos;
- quatro FQ4 shadows permanecem `exposed_to_llm=False`;
- canônicas FQ3 permanecem visíveis;
- `quant.event_study` 1.0.2 continua visível;
- `quant.event_study_v2` 1.0.0 continua shadow.

Estática:

- `compileall` verde;
- workflow isolado continua sem deploy/segredos de produção;
- `.env` temporário removido;
- planner não cita `quant.event_study_v2`.

## Bloqueio real

O runtime atual não possui PostgreSQL, Docker/Podman nem pacote PostgreSQL instalável em cache; DNS
externo também falha. Portanto não foi possível executar os dois testes DB novos nem `tools sync
--check` contra um servidor real nesta sessão.

Isso é um gate pendente, não um teste aprovado.

## Próximo passo operacional

Executar `.github/workflows/verify.yml` num runner GitHub/PostgreSQL 18. Se ficar totalmente verde,
aplicar o plano de promoção FQ4 documentado. Se falhar, corrigir antes de qualquer exposição à LLM.
