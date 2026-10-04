# Prompt pronto para o próximo chat

Quero continuar o backend Plexo exatamente do snapshot anexado.

Antes de alterar qualquer código, leia nesta ordem:
1. `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
2. `.ai/NEW_CHAT_MASTER_CONTEXT_2026-10-03.md`
3. `.ai/CURRENT_PROJECT_MAP_2026-10-03.md`
4. `.ai/PROJECT_STATE.md`
5. `.ai/DECISIONS.md`
6. `.ai/TASKS.md`
7. `.ai/CHANGELOG.md`
8. `.ai/WORKING_PROTOCOL.md`
9. os checkpoints citados.

Trate `.ai/` como memória persistente e atualize esses documentos em cada etapa. Não dependa da memória da conversa.

Preserve:
- LLM interpreta/roteia/explica;
- código determinístico carrega/calcula/valida;
- semver, fingerprint, provenance, replay, cache, outputs compactos e gates;
- reuse-before-build antes de matemática/loader/tabela/tool nova.

Escopo: empresa + mercado. Não abrir Portfolio Analytics, suitability ou análise da carteira/vida financeira do cliente.

Confirme:
- FQ0.5–FQ4 encerrados;
- quant.dependencia 2.0.0 pública;
- FQ5.1–FQ5.6 encerrados;
- quant.tendencias_fundamentais 1.0.1 pública/GREEN;
- quant.comparaveis_setor 1.0.1 pública/GREEN;
- peers 10/10/10 queries;
- FQ5.7 foundation GREEN/shadow/sem tool pública;
- 35 tools, 32 expostas, 3 ocultas;
- migrations até 0064;
- run #216: 135 directed, 896 passed, 52 skipped, 19 warnings, 0 failed, prompts/tools sync verdes.

Próximo gate: materializar payload físico oficial ANBIMA, congelar parser/fixture, medir cobertura histórica e só depois desenhar capability pública de curva.

Não leia .env/segredos, não edite migrations históricas, não use banco remoto destrutivamente, não toque em outro repo, não crie scraper HTML/contrato não oficial, não recrie matemática existente, não trate snapshot atual como histórico e não use Economatica como B3/CVM.

Faça best effort sem perguntar coisas que os arquivos já respondem. Corrija inconsistências reais e registre tudo em `.ai/`.


Confirme também que o snapshot anexado contém a revalidação run #216 e que qualquer commit posterior à base `f568d1dd2a228216537a600debd7c83a569aeb27` é documental antes de começar. Se houver um CI mais novo no próprio snapshot, use o mais novo.
