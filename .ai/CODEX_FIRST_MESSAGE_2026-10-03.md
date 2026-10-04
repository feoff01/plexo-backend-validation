# Primeira mensagem para o Codex — Plexo + onboarding da base

Use este texto como a primeira mensagem da sessão Codex no VS Code.

---

Estou continuando o backend Plexo neste repositório e vou conectar uma base de dados grande para ampliar a cobertura das tools existentes.

Antes de fazer qualquer alteração:

1. leia o `AGENTS.md` da raiz;
2. leia `.ai/CODEX_START_HERE_2026-10-03.md`;
3. siga a ordem de leitura indicada nesse manifesto;
4. para a base externa, leia integralmente `.ai/CODEX_DATA_ONBOARDING_HANDOFF_2026-10-03.md`.

A `.ai/` é a memória canônica do projeto. Não use apenas o histórico do chat como fonte de verdade.

Primeiro confirme:
- repo e branch atuais;
- HEAD atual;
- último baseline integralmente GREEN;
- estado do CI atual;
- catálogo de 37 tools / 34 públicas / 3 ocultas;
- estado de `quant.risco_retorno` 1.2.0;
- próximos gaps aprovados;
- a causa conhecida das duas falhas strict-PIT após rollover UTC.

Não enfraqueça strict PIT para corrigir os testes atuais. Torne as fixtures temporais determinísticas preservando a semântica de produção.

Depois, para a base que eu conectar, trabalhe inicialmente em modo READ-ONLY.

NÃO:
- crie migrations;
- altere tools;
- faça INSERT/UPDATE/DELETE;
- crie adapters;
- mude source priority;
- crie novas tools;
antes de concluir a auditoria.

Faça primeiro uma auditoria completa da base e grave o resultado em `.ai/EXTERNAL_DATA_BASE_AUDIT_<data>.md`.

A auditoria deve incluir:
- schemas;
- tabelas/views;
- volumes aproximados;
- PKs, uniques, FKs e índices;
- coverage temporal;
- identifiers disponíveis;
- timezone;
- currencies;
- units;
- origem/source/vendor;
- raw vs derivado;
- observation_date;
- reference_date;
- publication_date;
- availability_date;
- ingestion timestamp;
- revisions/vintages;
- histórico real vs snapshot;
- licensing/restrições relevantes;
- duplicações com B3/CVM/ANBIMA/Bacen/EIA/Economatica;
- divergências entre fontes;
- proposta de source priority;
- riscos de look-ahead/retrodatação;
- performance/query patterns;
- risco de N+1;
- necessidade de batch loaders.

Crie uma matriz para cada dataset/tabela:

A = encaixa diretamente no modelo canônico Plexo;
B = precisa somente adapter/normalização;
C = precisa novo tipo canônico/schema;
D = precisa governança temporal/source-priority/vintage;
E = representa nova intenção analítica.

Para cada item, responda explicitamente:

"Isso adiciona DADOS para uma capability existente, exige uma nova FUNDAÇÃO canônica, ou representa uma nova INTENÇÃO ANALÍTICA?"

Somente a categoria E pode justificar uma nova tool, depois de provar que as tools existentes não cobrem a pergunta.

Quero maximizar o reaproveitamento das tools já existentes, em especial as 18 públicas de Company & Market Analytics listadas em `.ai/CODEX_START_HERE_2026-10-03.md`.

A arquitetura alvo é:

base externa
-> source onboarding / adapter
-> modelo canônico Plexo
-> ingestion batches
-> loaders/resolvers
-> tools existentes
-> LLM

Não conecte cada tool diretamente às tabelas externas.

Ao terminar a auditoria, apresente:
1. mapa da base;
2. matriz tabela -> conceito canônico;
3. coverage;
4. gaps de identidade/unidade/temporalidade;
5. duplicações e conflitos;
6. source-priority proposta;
7. tools existentes que a base já consegue alimentar;
8. adapters/loaders mínimos;
9. schemas realmente novos;
10. novas tools que NÃO são necessárias;
11. capabilities genuinamente novas, se houver;
12. riscos;
13. proposta de tranches curtas.

Pare aí. Não implemente a integração antes de eu revisar esse diagnóstico.

Depois de cada decisão, gate, implementação ou teste futuro, atualize a memória canônica em `.ai/`.
