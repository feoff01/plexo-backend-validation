# Plexo · Camada de Agentes IA — migrations 17–21

> Estado atual do projeto: `../ESTADO_DO_PROJETO.md`. Validação em PG real: `README.md` §1.2.
> **Implementação:** o backend em `app/` (F0–F4) executa esta camada para o **Assessor** e o
> **Educador** (turno, tools, gates, custo, API) e o agente de **Contexto** (F3) — ver
> `../PLANO_AGENTES_IA.md` §0. O Analista standard existe desde a F5 (2026-08-25): preços oficiais B3/Bacen em
> `market.*` (gate de imutabilidade na migration 31, T58–T62), tools `dados.*`/`quant.*` e toda pergunta registrada em
> `analysis.analyses` + `evidence_findings`; o modo research (DAG) existe desde a F6 (2026-08-25): `app/analysis/` roda plano →
> tasks → relatório por job, com os gates da migration 32 (T63–T67). O conteúdo do Educador tem gate próprio na
> migration 30 (`content.v_education_approved`, T54–T57).

Extensão do schema Plexo (migrations 00–16) para os quatro agentes:
**Analista IA**, **Assessor IA**, **Educador** e o agente interno de
**Contexto Pessoal**. Um núcleo conversacional único, um registro único de
tools, um razão único de LLM/custo — e especialização só onde os agentes
realmente diferem.

## Ordem e conteúdo

| Arquivo | Schema | O que entrega |
|---|---|---|
| `17_agents.sql` | `agents` | Definição dos agentes, conversas, mensagens (append-only), cota mensal via `AGENT_QUOTAS`, guardrails |
| `18_tools.sql` | `tools` | Catálogo de códigos prontos (param_schema = tool definition do LLM), versões com git_sha + hash (padrão CVM), execuções imutáveis + **gate de família por agente** |
| `19_llm.sql` | `llm` | Prompts versionados com aprovação de compliance + **gate: sem prompt aprovado, sem conversa**, model_calls (tokens/custo), cost_ledger (§18.1) |
| `20_analysis.sql` | `analysis` | Profundidade do Analista: analyses, plans (imutáveis), tasks (= checkpoints do executor), evidence_findings (**material exige provenance**), reports imutáveis |
| `21_context.sql` | `context` | O 4º agente: extraction_runs (**só conversa encerrada**), signals (**só com evidência real**), change_proposals com a **regra-estrela** |
| `test_regras_invioláveis_agentes.sql` | — | T15–T24, continuação da numeração do conjunto original |

A ordem 17 → 21 é obrigatória (FKs cruzadas são adicionadas por `ALTER TABLE`
no arquivo mais tardio da dependência circular: messages→tools em 18,
messages→llm e agent→prompt em 19, model_calls→analysis em 20).

## A regra-estrela (21_context)

O agente de Contexto **nunca aplica mudança sozinho**:

1. Toda proposta só chega a `aplicada` com `confirmed_at` + `confirmed_by`;
2. `confirmed_by` tem que ser **o próprio usuário** (constraint, não convenção);
3. Proposta de **perfil de risco** exige ainda um `suitability_assessment`
   **do mesmo usuário, respondido depois da proposta** (trigger
   `context.assert_risk_change_confirmed`). Apontar questionário antigo não vale.

O teste T24 exercita as quatro burlas possíveis + o caminho legítimo.

## Dependências e premissas a conferir

Estes arquivos referenciam objetos das migrations 00–16. **Só 4 dos 16
arquivos originais estavam no zip auditado** (01, 02, 06, 12) — antes de rodar,
confirme que o conjunto completo existe e que os nomes abaixo conferem:

- `core.new_id()`, `core.set_updated_at()`, `core.forbid_update_delete()`,
  `core.canonical_hash(jsonb)` (imutável — usada em coluna gerada);
- domains `core.slug`, `core.hash_hex`, `core.confidence`, `core.config_code`;
- `identity.users`, `identity.scopes`, `identity.suitability_assessments`
  (com `user_id`, `taken_at`, `superseded_at`);
- `billing.plan_code` — **premissa: labels `free`, `essential`, `advanced`**
  (confirmado `advanced` em 06; `free` era suposição — **resolvido:** os labels reais são
  `free/essential/advanced/wealth`, confirmados em `03_billing`);
- `engine.policy_versions` (code/version/payload/compliance_status/
  effective_from/effective_to) e o enum `engine.compliance_status`;
- Convenção RLS por GUCs `app.scope_id` / `app.role` (`'service'` = bypass **só para membro do papel `plexo_service`** — `core.is_service()`, `28_roles_grants`).

## Alembic (ATUALIZADO — a camada real existe)

Correção do que este README dizia originalmente: os arquivos **têm** `BEGIN;`/`COMMIT;` em coluna
zero (validado em PG real); a camada Alembic implementada (`alembic/sqlfile.py`) remove **apenas**
o par externo antes de executar, dentro da transação da revision. As revisions reais são
`alembic/versions/0017_agents.py … 0021_context.py` (encadeadas de `0000_core` a `0029_tool_gates`),
com `downgrade()` levantando `NotImplementedError` (base append-only). Detalhes: `README.md` §7.

Para rodar sem Alembic: `python tools/db_runner.py apply` (não há psql na máquina de dev).

## Filosofia dos seeds (leia antes de reclamar que travou)

- Os 4 `prompt_versions` nascem **draft** com template `[PENDENTE]`. O gate de
  19 **bloqueia qualquer conversa** até compliance aprovar — intencional,
  mesma decisão do C6 do conjunto original: o caminho sem aprovação não existe.
- `AGENT_QUOTAS`, `LLM_BUDGETS` e `CONTEXT_EXTRACTION` nascem draft com números
  placeholder — cota e orçamento mudam sem deploy, via nova versão da policy.
- O **catálogo de tools não tem seed**: é sincronizado do registro por
  decorator no deploy. O código é a fonte da verdade; o banco é o espelho
  auditável (git_sha + sha256 do fonte).

## Testes

```bash
python tools/db_runner.py tests                 # todas as suítes (T1–T57)
python tools/db_runner.py tests plexo_service   # as mesmas sob papel real (sem BYPASSRLS)
```

Termina em `ROLLBACK` — não deixa resíduo. Cobertura: gate de prompt (T15),
cota (T16), mensagens append-only (T17), família de tool por agente (T18),
execução imutável (T19), evidência sem provenance (T20), relatório imutável
(T21), conversa aberta não processável (T22), sinal sem evidência/forjado
(T23), e a regra-estrela em cinco atos (T24a–e).

**Validado (2026-08-22):** o aviso original desta seção — "não puderam ser executados, sem
PostgreSQL" — está superado: tudo roda contra PostgreSQL real (18.6, Aiven), 129 asserções verdes
no conjunto (T1–T57, com a 30), inclusive sob `plexo_service`. Ver `README.md` §1.2 e `../ESTADO_DO_PROJETO.md`.

**Consumidor real (2026-08-23, F3):** o agente de Contexto (`app/context/extractor.py`) e os jobs
(`app/jobs/tasks.py`) escrevem exatamente contra estes gates — T22 (conversa aberta), T23 (evidência da
mesma conversa) e T24 (só o próprio usuário confirma; risco exige suitability novo) são exercitados também
do lado Python em `tests/test_f3_contexto.py`, com as exceções traduzidas em `app/db/errors.py`
(`ConversationNotEnded`, `EvidenceInvalid`, `SelfConfirmationOnly`, `SuitabilityRequired`).

## Deliberadamente fora desta onda

Ficam para a próxima onda, quando o Analista sair das tools de 1 passo para
consultas históricas profundas (Fases 1–3 do Blueprint):

- `docs` — camada documental + RAG (tsvector + pgvector + RRF), compartilhada
  entre a evidência documental do Analista e o Educador;
- asset master point-in-time (`asset`, `symbol_history`, corporate actions,
  os três tempos §11.2);
- `dataset_catalog` / vintages de dados macro;
- `feedback` / `evaluation_case` estendidos (teach workflow §17.3 — hoje
  parcialmente coberto por `engine.golden_masters`).
