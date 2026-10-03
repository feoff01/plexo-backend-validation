# Plexo — Protocolo de continuidade e memória persistente

Data de adoção: 2026-09-30
Status: canônico

## Objetivo

O desenvolvimento do Plexo não deve depender da memória de uma conversa. Toda decisão relevante, mudança de escopo, implementação, validação e próximo passo aprovado deve ficar registrada em `.ai/`.

## Regras obrigatórias

1. Antes de implementar uma etapa nova, ler:
   - `.ai/NEXT_CHAT_HANDOFF_FINAL.md`
   - `.ai/PROJECT_STATE.md`
   - `.ai/DECISIONS.md`
   - `.ai/TASKS.md`
   - `.ai/CHANGELOG.md`
   - checkpoints citados;
   - documentos de design/capability audit pertinentes.

2. Toda decisão arquitetural aprovada deve entrar em `.ai/DECISIONS.md`.

3. Toda mudança de estado do projeto deve entrar em `.ai/PROJECT_STATE.md`.

4. Todo trabalho pendente/concluído deve ser refletido em `.ai/TASKS.md`.

5. Toda alteração relevante de código/schema/tool/semver/exposição/replay deve entrar em `.ai/CHANGELOG.md`.

6. Toda etapa grande deve produzir checkpoint próprio em `.ai/checkpoints/`.

7. O handoff final deve sempre apontar para o estado mais recente e para os documentos canônicos a ler.

8. Recomendações ainda não aprovadas devem ser registradas como **propostas**, não como decisões implementadas.

9. Não criar nova matemática/tool/schema antes de aplicar o gate `reuse-before-build` de `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md`.

10. Se uma inconsistência documental for encontrada, corrigi-la na mesma etapa, sem reescrever histórico de migrations ou apagar trilhas de replay.

## Ordem recomendada após a auditoria arquitetural

### Etapa A — Consolidar fatores/dependência
Objetivo: remover a necessidade de tools por fonte sem reabrir a matemática FQ3/FQ4.

Design deve cobrir:
- contrato de `ResolvedFactor`/factor loader;
- asset/index/FX na mesma abstração;
- extensão futura para commodity/Brent e yield curve;
- reuso de loaders/Quant Core;
- plano de semver/source fingerprint/replay;
- cutover de `quant.dependencia_macro` para uma interface canônica;
- testes de equivalência numérica.

### Etapa B — Executar o cutover controlado
Somente depois da aprovação do design:
- implementar infraestrutura compartilhada;
- preservar versões históricas;
- não alterar matemática FQ3/FQ4;
- validar PostgreSQL 18, E2E, suíte completa, prompts e tools sync;
- atualizar `.ai/` e checkpoint.

### Etapa C — Retomar Fundamentals + Valuation
Após a consolidação:
1. tendências fundamentais multi-período PIT;
2. peers/setor sobre `market.sector_classification`;
3. membership/pesos de índice sobre `market.index_weights`;
4. curva de juros sobre `market.yield_curve`;
5. commodities/Brent somente após confirmar fonte/cobertura;
6. fair value/reverse DCF apenas quando forecasts, WACC, ERP e crescimento estiverem governados e auditáveis.

Portfolio Analytics, suitability e análise da carteira/cliente permanecem fora desta frente.


## Snapshot atual do protocolo — 2026-10-03

Depois de `.ai/NEXT_CHAT_HANDOFF_FINAL.md`, ler `.ai/CURRENT_PROJECT_MAP_2026-10-03.md` antes de implementar.

O próximo gate funcional é a fonte física ANBIMA da FQ5.7. Não reabrir FQ5.6, não criar matemática de curva antes de materializar a fonte e não iniciar Portfolio Analytics nesta frente.
