# Plexo · Banco de dados do MVP

> **Documento HISTÓRICO** — README anterior à 3ª onda, preservado como registro de procedência.
> Nada aqui descreve o estado atual; ver `../ESTADO_DO_PROJETO.md` e `README.md`.


Estrutura PostgreSQL completa, executável e testada, derivada de `CONTEXTO_COMPLETO_PROJETO.md`.

**Estado:** 16 migrations rodam limpas do zero em PostgreSQL 16. 94 tabelas, 426 índices, 703 constraints, 66 triggers, 6 views + 1 materialized view. 14 testes de regra de negócio passando.

---

## 1. As sete críticas que mudaram o desenho

O documento de contexto propõe, em §11.6, uma lista de tabelas centrais. Ela está incompleta em pontos que custam caro depois. Três críticas contrariam o que está escrito lá.

### C1 — `users` como raiz é o erro mais caro do MVP `[contraria §11.6]`

§11.6 começa com `users · accounts · holdings`. Mas §4.12 diz, com todas as letras, que Family Office é **decisão de arquitetura de dados, não feature de tela** — e que o produto **deixa de ser mono-usuário**.

Se as tabelas financeiras nascerem com `user_id`, o Advanced exige migração de `holdings`, `findings`, `goals`, `actions` e `value_ledger` **com dados reais de cliente em produção e histórico point-in-time**. E o Advanced é justamente o plano que a concentração cruzada familiar vende sozinho — o achado que o próprio documento chama de melhor retorno da segunda onda inteira.

**Adotado:** `scope_id` é a raiz de tudo que é financeiro. Escopo pessoal é um escopo com um membro. Escopo familiar agrega escopos pessoais por `parent_scope_id`. Custo hoje: uma coluna. Custo depois: uma migração que ninguém quer fazer.

### C2 — `audit_log` e `engine.runs` são coisas diferentes `[lacuna em §11.6]`

§16.1.10 exige `{input_hash, engine_version, params, output_hash}` em todo output de motor. Isso **não é log de auditoria**. Log de auditoria responde *quem fez o quê*. Isso responde *como reproduzo, byte a byte, o número que o cliente viu em março*.

Sem `engine.runs` referenciado por todo artefato derivado, a exigência da RCVM 19 art. 17 fica pela metade: o código-fonte é inspecionável, mas o número específico não é reconstruível.

**Adotado:** `engine.runs` + `engine.run_inputs` (grafo de proveniência) + `engine.artifacts` (imutável) + `audit.activity_log` (separado, particionado, append-only).

### C3 — O job das 22h destrói o estado das ações `[o coração do desenho]`

Findings são recalculados todo dia. Ações têm estado que **precisa sobreviver ao recálculo**: cooldown de 90 dias, supressão permanente após 2 recusas, "não entendi" acumulado.

Se cada run criar findings novos, a regra §16.5 nunca dispara — o cooldown reseta toda madrugada e o usuário recebe eternamente a ação que já dispensou duas vezes. A governança anti-ruído vira letra morta sem nenhum erro aparecer em log nenhum.

**Adotado:**
```
finding_key             chave lógica determinística, estável entre runs
findings                1 linha por finding lógico  · governança de recusa vive AQUI
finding_observations    1 linha por run             · série temporal do mesmo finding
actions                 estado do usuário           · reemitida, mas ancorada no finding
```

Um teste (T5) provou que a primeira versão deste trigger estava errada: o contador de recusas na *ação* não incrementava, porque uma ação reemitida é uma linha nova. O contador foi movido para o *finding*. Esse bug teria chegado em produção silencioso.

### C4 — Três regras invioláveis devem ser constraint, não código de aplicação

Regra que vive só no serviço vaza no primeiro backfill, script de suporte ou endpoint novo. As três mais estruturais viraram schema:

| Regra | Mecanismo |
|---|---|
| Carteira-alvo ativa única (D27) | índice único parcial `WHERE status = 'active'` |
| 5 blocos obrigatórios da ação (§16.5) | `CHECK (blocks ?& array[...])` |
| Retorno de mercado fora do Ledger (§16.1.6) | o valor **não existe no enum** |

### C5 — Falta a tabela que valida a hipótese-mãe `[lacuna em §11.6]`

O schema proposto não mede WTP nem a métrica-mãe. Sobe-se a plataforma inteira e continua-se sem a única resposta que importa (P01: ARR varia **3,75×** só em função de conversão e ARPU).

**Adotado:** `analytics.paywall_impressions` grava, na mesma linha, o **preço exibido** e o **impacto revelado** — é o que permite responder se a conversão responde ao preço ou ao valor. Mais `analytics.wtp_surveys` (van Westendorp em 4 colunas) e `analytics.onboarding_steps` (mede P04, o vazamento de conversão).

**O fake-door é uma tabela, não uma landing page.**

### C6 — `validado_por_lucas` é sintoma, não bug de nome

§13.6 pede para renomear a flag. Renomear não resolve. Premissa aprovada por compliance é **estado versionado com aprovador, data e escopo de vigência**.

**Adotado:** `engine.policy_versions` com `compliance_status` e um trigger que **recusa gravar run client-facing referenciando política não aprovada**. Todas as políticas do seed nascem `draft` — o primeiro deploy vai travar, e isso é intencional enquanto a vaga de compliance estiver aberta (P02).

### C7 — Snapshot não capturado hoje não existe depois

P08 já reconhece o problema. A consequência de schema é específica e não negociável: `wealth.holdings_snapshots` **nunca sofre UPDATE**. Correção de posição é linha nova em `as_of_date` novo. Trigger bloqueia UPDATE e DELETE.

Mais `wealth.portfolio_snapshots` (rollup diário), porque a Barra de Rumo lê "Δ desde a última visita" a cada page load e não pode varrer partição.

---

## 2. Mapa de schemas

Os schemas espelham os serviços de §11.2 — o monolito modular fica modular também no banco.

| Schema | Tabelas | Responde a |
|---|---:|---|
| `core` | — | domains financeiros, funções, triggers transversais |
| `identity` | 8 | usuários, **escopos**, suitability point-in-time, LGPD |
| `billing` | 9 | planos, **entitlements (TIER_CONFIG como dado)**, assinaturas |
| `market` | 12 | instrumentos, preços D-1, índices, FX, proveniência |
| `wealth` | 9 | contas, Open Finance, **snapshots append-only**, transações |
| `engine` | 6 | **política versionada, runs auditáveis**, golden masters |
| `diagnostics` | 9 | taxonomia de findings, findings estáveis, ações, Fundação, score |
| `planning` | 12 | objetivos, Carteiras Modelo, **carteira-alvo única**, drift 5/25 |
| `budget` | 6 | fluxos, taxa de poupança, dívidas, reserva |
| `content` | 7 | Cartas, Sinais (5 partes), notificações, **aprovações de compliance** |
| `copilot` | 5 | conversas, `cited_refs`, guardrails de vocabulário |
| `ledger` | 2 | Valor Realizado append-only |
| `analytics` | 7 | eventos, **paywall/fake-door**, van Westendorp, experimentos |
| `audit` | 2 | log imutável particionado, acesso a PII |

### Convenções

- **Dinheiro é `numeric`, nunca float.** Domains: `core.money_brl`, `core.quantity`, `core.weight`, `core.rate_annual`, `core.confidence`.
- `timestamptz` sempre; `date` para data de negócio (D-1).
- UUID v7 quando disponível (PG 18), v4 como fallback — `core.new_id()`.
- Particionamento mensal nativo em `market.prices`, `wealth.holdings_snapshots`, `analytics.events`, `audit.activity_log`, com partição `DEFAULT` para que nenhuma escrita falhe.
- RLS habilitada e **forçada** em toda tabela com `scope_id`. Contexto por GUC: `app.user_id`, `app.scope_id`, `app.role`.
- Nada de `ON DELETE CASCADE` a partir de assinatura: §16.4 diz *dados preservados, nunca apagados*. Downgrade é filtro de leitura (`is_visible`, `entitlement_of`), não deleção.

---

## 3. Regras de negócio que o banco recusa violar

Cada linha tem teste correspondente em `tests/test_regras_invioláveis.sql`.

| # | Regra | Onde | Mecanismo |
|---|---|---|---|
| T1 | Output ao cliente exige política aprovada | §16.6 | trigger `runs_policy_gate` |
| T2 | Ação sem os 5 blocos não existe | §16.5 | `CHECK action_five_blocks` |
| T4 | Máximo 1 ação ativa exibida | §16.5 | índice único parcial |
| T5 | Cooldown 90d · supressão após 2 recusas · "não entendi" marca copy | §16.5 | trigger no finding |
| T6 | Fundação crítica ⇒ score **desativado**, não baixo | §16.1.8 | `CHECK score_disabled_xor_value` |
| T7 | Uma carteira-alvo ativa por escopo | D27 | índice único parcial |
| T8 | "Carteiras Modelo", nunca "Recomendadas" | §4.6 | `CHECK` no nome |
| T9 | Retorno de mercado não entra no Ledger | §16.1.6 | ausência no enum |
| T10 | Ledger é append-only (estorno, não UPDATE) | §4.11 | trigger + `REVOKE` |
| T11 | Valor sem metodologia gravada não entra | §13.6 | `CHECK` no jsonb |
| T12 | Máximo 2 push/semana — excedente **gravado como suprimido** | §4.1 | trigger |
| T13 | Holdings append-only | P08 | trigger |
| T14 | Pesos da carteira-alvo somam 1,000 | §16.2 | constraint trigger diferida |

Rodar:
```bash
createdb synapta
for f in sql/*.sql; do psql -d synapta -v ON_ERROR_STOP=1 -f "$f"; done
psql -d synapta -f tests/test_regras_invioláveis.sql
```

---

## 4. Onde cada feature vive

| Feature | Tabelas principais |
|---|---|
| Raio-X | `diagnostics.finding_types` → `findings` → `finding_observations` → `actions` |
| Fundação | `diagnostics.foundation_status`, `budget.debts`, `budget.reserve_settings` |
| Score | `diagnostics.portfolio_scores` (desativável) |
| Cobertura | `market.instruments.is_in_universe` → `diagnostics.coverage_reports` |
| Paywall | `diagnostics.gate_reveals` → `analytics.paywall_impressions` |
| Portfolio Builder | `planning.target_portfolios` + `target_allocations` + `engine.artifacts` |
| Objetivos | `planning.goals` → `goal_projections` |
| Carteiras Modelo | `planning.model_portfolios` → `_versions` → `_holdings` → `model_adoptions` |
| Drift 5/25 e aporte | `planning.drift_evaluations`, `contribution_routings` |
| Orçamento | `budget.cash_events` → `monthly_summaries.savings_rate` |
| Calendário patrimonial | `planning.calendar_events` |
| Copiloto | `copilot.conversations` → `messages.cited_refs` → `guardrail_events` |
| Sinais | `content.signals` (5 colunas) → `content.notifications` |
| Cartas | `content.letters`, `content.user_reports` (share_token) |
| Ledger | `ledger.value_entries` → `monthly_rollups` |
| Family Office | `identity.scopes.parent_scope_id` → `diagnostics.v_issuer_concentration` |

**Views notáveis:**
- `diagnostics.v_issuer_concentration` — concentração cruzada familiar consolidando conglomerado (`issuers.parent_issuer_id`). Marido 22% + esposa 19% no mesmo emissor, cada um dentro do limite individual.
- `analytics.mv_activation_d14` — a métrica-mãe: % de escopos com ≥1 ação concluída em D+14.
- `diagnostics.v_action_queue` — Fundação primeiro, cooldown e supressão respeitados, `queue_rank = 1` é a única exibida.
- `analytics.v_paywall_funnel` — conversão por preço exibido × impacto revelado.

---

## 5. Sequenciamento (mapeado às fases F0–F5)

| Fase | Migrations | Comentário |
|---|---|---|
| **F0** fundação técnica | `00`–`05`, `13`, `14` | identity, engine, market, wealth, RLS, partições |
| **F0/F1** Raio-X | `06` + `15` (taxonomia) | subir de 19 para 45 findings é **INSERT**, não migração |
| **F1** planejamento | `07` | Builder, objetivos, Carteiras Modelo |
| **F2** loop | `08`, `09` | Orçamento, Sinais, Cartas |
| **F3** monetização | `03`, `12` | billing + fake-door |
| **F4** escala | `wealth.connections` já existe | Open Finance é ativar, não modelar |
| **F5** Wealth | `plans.requires_cvm_authorization` | bloqueado por CVM, já previsto |

**`12_analytics.sql` deve subir junto com F0, não com F3.** A prioridade nº 1 do negócio é validar WTP; sem eventos e paywall instrumentados desde o primeiro usuário, a fase F3 chega sem dado histórico.

---

## 6. Decisões que preciso de você (bloqueiam ou mudam o schema)

1. **Provider de Postgres** — Neon, Supabase, RDS ou self-hosted? Muda a estratégia de particionamento (`pg_partman` vs. cron próprio) e se PG 18 (`uuidv7()` nativo) está disponível.
2. **Auth próprio ou provider?** `identity.users` traz `password_hash`; se for Clerk/Supabase Auth/Cognito, essa coluna some e `auth_identities` vira a raiz.
3. **CPF: coletar quando?** Modelei `cpf_sha256` + `cpf_encrypted` com chave fora do banco. LGPD pede minimização — se billing não exige nota fiscal no MVP, sugiro não coletar.
4. **Escopo do Orçamento no 1º MVP.** Modelei completo (`08_budget.sql`), mas §4.5 é decisão de ago/2026 e o onboarding já está inflado (P04). Se o Orçamento não entra no 1º MVP, `08` fica na gaveta sem afetar nada.
5. **Multi-moeda.** Gravei `value_brl` congelado no snapshot com `fx_rate` ao lado. Alternativa é converter na leitura — mais flexível, mas quebra reprodutibilidade point-in-time. Escolhi reprodutibilidade.
6. **Limite de 5 membros** — está como `[IDEIA]` no documento. Deixei em `policy_versions('FAMILY_LIMITS')`, alterável sem deploy.
7. **Conflito C05 do documento** (banda R$100k–3M vs. R$300k–3M) aparece em `analytics.wtp_surveys.portfolio_band`. Confirme os cortes que quer testar.

---

## 7. O que deliberadamente **não** está aqui

- **Preços dos planos.** São `[PENDENTE]` no documento. `billing.plan_prices` está pronto e vazio — chutar número no seed seria criar uma âncora falsa.
- **Screening de ativos.** §4.7 mudou de "travar a tese" para "fatos e filtros". Os fatos vivem em `market.instruments.metadata` e `fund_facts`; a camada de filtros é query, não tabela nova. Se virar produto com filtros salvos, é uma tabela — não antes.
- **Aba Mercado.** V2, sem spec.
- **Execução de ordens (Níveis 1–4).** Fora do MVP e regulatoriamente bloqueado.
- **Séries de Monte Carlo brutas.** `engine.artifacts.storage_key` aponta para S3. Milhões de caminhos não vão para o Postgres.

---

## 8. Uma observação sobre prioridade

Este schema suporta o produto inteiro descrito no documento. Mas o próprio documento é explícito: *"trate a Synapta como uma empresa com produto forte e negócio não validado. Todo conselho deve empurrar na direção de validar, não de construir mais."*

Construir as 94 tabelas antes de validar WTP seria exatamente o erro que o documento pede para evitar. A leitura honesta do sequenciamento é:

**`00`–`02` + `12` + a taxonomia de `06` respondem à pergunta que importa.** Identidade, motor auditável, findings e o instrumento de fake-door. O resto pode esperar o primeiro real de receita — e a estrutura já está desenhada para que esperar não custe migração.
