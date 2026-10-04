# Plexo · Camada de Contexto Pessoal — migrations 21–27, 38–44

> **F15 (2026-08-29) — o contexto recebe carga.** A F14 entregou o laço e a verificação mostrou que
> ele não tinha o que processar: a persona aparecia com 0% de cobertura porque nada ligava
> `budget.*`, `estate.*` e `household.*` ao catálogo. `app/context/derivacao.py` faz essa ligação,
> e a decisão que a sustenta é epistêmica — **duas janelas, não uma flag**:
>
> | view | quem lê | o que mostra |
> |---|---|---|
> | `context.v_fact_current` | o AGENTE | só `confirmado`. **Não mudou** |
> | `context.v_fact_operavel` | o MOTOR | `confirmado` + `inferido`, confirmado sempre na frente, confiança descontada |
>
> A derivação nunca toca no que o cliente confirmou e nunca regrava valor igual. E o catálogo ganhou
> `pergunta`: o que falta vira a próxima conversa (`app/agents/perguntas.py` ordena por quantos
> indicadores cada fato destrava), não um campo em branco.
>
> A migration **44** corrigiu dois erros de fidelidade que só apareceram ao rodar com números reais —
> ver o §17 do `PLANO_AGENTES_IA.md`.


> **F14 (2026-08-29) — o catálogo, o card ao vivo e o perfil.** Três coisas que faltavam:
>
> 1. **`context.fact_definitions` (38)** — `attribute` era slug LIVRE; `renda_mensal`, `salario` e
>    `renda` podiam coexistir e nenhuma junta fechava. O catálogo dá vocabulário fechado (36 fatos
>    em 6 famílias) e, com ele, unidade canônica, meia-vida, **precedência de fonte**, **limiar de
>    materialidade** e cobertura. `context.assertions` ganhou `fact_key`; views novas
>    `v_fact_current` (um fato por chave, por precedência e recência) e `v_fact_coverage`.
>    As duas regras-estrela: **o que o Open Finance governa a conversa não sobrescreve**
>    (`allows_conversation_update`, que vale também para tolerância a risco) e **mudança imaterial
>    não vira pergunta** (limiar = o MAIOR entre absoluto e relativo). T80–T88.
> 2. **`extraction_runs.kind` (39)** — a 21 proibia ler conversa aberta, e com razão para a extração
>    em LOTE. O card DURANTE a conversa é outro ato: `kind='turno'` o libera sem afrouxar a cadeia
>    run → sinal → evidência → proposta. `origin` é DERIVADA do run, e há teto SEMANAL de cards.
>    T89–T94.
> 3. **O aplicador (`app/context/aplicador.py`)** — até aqui `/proposals/{id}/confirm` parava em
>    `confirmada` e **nada acontecia**. Agora aplica: asserção nasce declarada → é confirmada pelo
>    próprio usuário → supersessão → proposta `aplicada` → auditoria → perfil invalidado.
>
> A migration **42** corrigiu um erro da 38 achado por teste: a precedência impedia a confirmação do
> cliente de aposentar a renda vinda do onboarding — o cliente confirmava e o contexto não mudava.
> Quem protege o dado medido é `allows_conversation_update`, não a precedência.


> Estado atual do projeto: `../ESTADO_DO_PROJETO.md`. Validação em PG real: `README.md` §1.2.
> **Implementação:** a extração (extraction_runs → signals → assertions → change_proposals) é a
> **F3 do backend**, concluída em 2026-08-23 (`../PLANO_AGENTES_IA.md` §0; F4 Educador concluída em 2026-08-24). A 2ª opinião do Assessor já grava
> asserções `recomendacao_externa` (F2).

> **v1.2 — segunda auditoria + municiamento dos agentes.** Revisão contra o
> fluxo completo dos 4 agentes (CONTEXTO_COMPLETO_PROJETO):
>
> 1. **[bug real, 26]** O gate de adoção de Carteira Modelo checava o teto de
>    classe **por linha**, não por classe: `acoes_br` fatiada em 3 instrumentos
>    de 15% (45% total) passava por um teto de 20%. Agora agrega por classe
>    antes de checar; vetos de instrumento/emissor viraram um loop próprio.
>    Regressão: **T39, T39b**.
> 2. **[22]** Asserção agora só NASCE `declarado` ou `inferido` — nascer
>    `obsoleto`/`refutado`/`conflitante` também era possível e sem sentido (T40).
> 3. **[22]** Imutabilidade agora cobre também `unit`, `valid_from`,
>    `source_ref`, `signal_id` e `evidence_message_ids` — dava para trocar a
>    unidade de "18000" de BRL para USD sem tocar no valor (T40b).
> 4. **[22]** `evidence_message_ids` validado contra `agents.messages` do MESMO
>    escopo (uuid[] não tem FK; mesmo padrão do gate de `context.signals`) (T40c).
> 5. **[municiamento]** `context.subject_kind` ganhou `'recomendacao_externa'`
>    e `decisions.deliverable_kind` ganhou `'segunda_opiniao'` — o fluxo
>    "meu assessor humano indicou o COE X, é bom pra mim?" agora tem onde viver:
>    a indicação entra como asserção, o veredito sai como registro de entrega.
> 6. **[27]** `outcome='substituida'` agora exige `superseded_by`.
>
> **v1.1 — correções da primeira auditoria.** 4 bugs reais + 2 fragilidades;
> regressões T36–T38:
>
> 1. **[grave, 22]** CHECKs bidirecionais (`status='confirmado' ⇔ confirmed_at`)
>    explodiam o fluxo principal: confirmar renda nova por cima da antiga,
>    expirar fato confirmado, demover para `conflitante`. Unidirecionais agora
>    (**T36, T37**).
> 2. **[grave, 26]** Gate C26a era **fail-open** quando o portfólio não era
>    visível. Agora fail-closed.
> 3. **[design, 24]** `CHECK (p10 <= variable_brl)` removido: p10 é piso
>    histórico; o mês ruim vem abaixo dele — e é o que mais precisa ser gravado.
> 4. **[bug, 27]** `v_client_timeline` inflava contagens (JOIN duplo) →
>    `count(DISTINCT)`.
> 5. **[22]** Supersessão não atropela `refutado`. **[26]** `%%%` no RAISE.
> 6. **Adições:** `preferences.v_violations` (veto pós-carteira vira violação
>    VISÍVEL, **T38**); `liquidity_requirements` não afrouxa em silêncio;
>    `life_events` valida escopo dos ponteiros; `decisions.records` congela
>    também `plan_code`/`agent_message_id`/`goal_id`.

---

## Municiamento dos 4 agentes — o que cada um lê deste banco

Checado contra o fluxo do projeto (usuário escolhe agente → LLM entende →
despacha para código pronto → roda → LLM sintetiza → conversa encerrada →
agente de Contexto extrai).

> **Estado (2026-08-23, F3):** o agente de Contexto existe (`app/context/extractor.py`) e grava
> `assertions` com `source='conversa'`, `signal_id`, `evidence_message_ids` e `valid_until` por
> `CONTEXT_ASSERTIONS.validade_dias`; nasce sempre `declarado/inferido` (C22a), dedup contra
> `v_current_facts`, contradição vira linha nova (C22c marca `conflitante` → `v_open_questions`).
> `change_proposals` nascem `proposta` com `expires_at` por `CONTEXT_EXTRACTION`; confirmação é a API
> `/proposals/{id}/confirm` (só o próprio usuário) e **nada é aplicado** nesta fase — o gate C22 das
> tabelas estruturadas continua sendo o único caminho. `expire_stale_assertions()` é chamada pelo job
> `expirar` (diário). Sem migration nova.

| Agente | O que precisa | De onde vem | Estado |
|---|---|---|---|
| **Analista** (testar tese: "juros sobe ⇒ Petrobras sobe?") | séries de preço, índices, câmbio, proventos; profundidade de análise | `market.prices/index_values/fx_rates/corporate_actions` + `analysis.*` + `tools.tool_executions` | ✅ coberto |
| **Assessor** (planejamento + 2ª opinião) | contexto completo da pessoa; custos do produto indicado; registro do veredito | `context.v_current_facts` · `household.v_summary` · `budget.v_income_breakdown` + `income_summaries` · `estate.v_net_worth` · `preferences.v_active_constraints` · `market.fund_facts` (taxas, come-cotas) · `decisions.records kind='segunda_opiniao'` | ✅ coberto (v1.2) |
| **Educador** | conteúdo; nível de conhecimento do aluno | `content.education_contents`; nível via asserção `attribute='nivel_conhecimento'` | ✅ suficiente p/ v1 |
| **Contexto Pessoal** | conversas ENCERRADAS → sinais → asserções → propostas; NUNCA aplica | `context.extraction_runs → signals → assertions → change_proposals`; risco segue exigindo NOVO suitability (regra-estrela) | ✅ coberto |

O pacote de contexto que o serviço injeta no prompt de Assessor/Analista é a
união das 6 views acima — todas por `scope_id`, todas RLS.

**Lacunas conhecidas, deliberadamente não construídas agora:**
- **Fundamentos de empresa** (P/L, ROE, payout) para teses do Analista que vão
  além de preço/índice — exigiria tabela de fundamentals point-in-time. Preço e
  índice cobrem a tese exemplo do projeto ("juros × Petrobras").
- **Comissão de distribuição/rebate** do produto avaliado na 2ª opinião — o
  dado não é público; `fund_facts` cobre taxas de adm/perf/come-cotas, que já
  sustentam o veredito "caro vs. barato".
- **Nível de conhecimento como progressão estruturada** (trilhas do Educador) —
  asserção resolve o v1; tabela própria só quando houver trilha de verdade.

Extensão do schema Synapta (00–21) para o que faltava responder à pergunta
que o cliente realmente faz: **"posso parar de trabalhar aos 55?"**

Seis arquivos, 12 tabelas, 9 views, 11 regras invioláveis novas (T25–T40c).

| Arquivo | Schema | O que entrega |
|---|---|---|
| `22_assertions.sql` | `context` (estende 21) | `assertions`: fato · intenção · hipótese · preferência · opinião, com status, validade e proveniência. **O gate C22** usado pelos quatro arquivos seguintes |
| `23_household.sql` | `household` | `members` + `life_events` — quem depende desta renda e até quando |
| `24_income.sql` | `budget` (estende 08) | `income_sources` + `income_summaries` — fixo vs. variável, e `committable_brl` |
| `25_estate.sql` | `estate` | `assets` + `valuations` — imóvel, empresa, veículo; patrimônio líquido de verdade |
| `26_preferences.sql` | `preferences` | `constraints` + `liquidity_requirements` — o mandato do cliente, **bloqueante no banco** |
| `27_decisions.sql` | `decisions` | `records` + `rationale_items` + `inputs` — o que foi entregue, por quê e com base em quê |
| `tests/test_regras_invioláveis_contexto.sql` | — | T25–T40c |

A ordem 22 → 27 é obrigatória: 23–26 dependem do gate criado em 22,
25 depende de 23 e 24, 27 depende de 22 e 26.

---

## A ideia central: dúvida não vira fato por descuido

O banco já sabia registrar o que foi **detectado** (`context.signals`) e o que
foi **proposto** (`context.change_proposals`). Faltava o meio: **o que o sistema
sabe, com que força, desde quando e com base em quê.**

`context.assertions` separa duas coisas que quase todo produto colapsa numa só:

- **`modality`** — que tipo de coisa é: `fato` · `intencao` · `hipotese` ·
  `preferencia` · `opiniao`
- **`status`** — quem responde por ela: `declarado` · `inferido` ·
  `confirmado` · `conflitante` · `obsoleto` · `refutado`

Confirmar "talvez eu compre uma casa" confirma **a dúvida**, não a compra.
Por isso `likelihood` é **obrigatória** para intenção e hipótese, e **proibida**
para fato: um "talvez" sem probabilidade é um "sim" disfarçado.

E daí sai a regra que amarra a onda inteira:

> **C22 — tabela estruturada só recebe FATO CONFIRMADO.**
> `household.members`, `budget.income_sources`, `estate.assets`,
> `estate.valuations`, `preferences.constraints` e
> `preferences.liquidity_requirements` carregam `assertion_id`, e o trigger
> `context.assert_assertion_confirmed()` recusa qualquer linha cuja asserção
> de origem não esteja em `modality ∈ {fato, preferencia}` **e**
> `status = 'confirmado'`.

Um único trigger, seis tabelas. Contradição não é bug: duas afirmações vigentes
com valores diferentes viram `conflitante` automaticamente e aparecem em
`context.v_open_questions` como **pergunta ao cliente** — não como escolha
silenciosa do sistema.

---

## As regras invioláveis novas

| Regra | Onde | O que impede |
|---|---|---|
| **C22a** | `22` | Asserção não nasce confirmada. Confirmação é sempre um segundo ato, com `confirmed_by = user_id` |
| **C22b** | `22` | Conteúdo de asserção é imutável. Mudou a renda? Linha nova + `superseded_by` |
| **C22c** | `22` | Opinião nunca vira fato confirmado |
| **C22** | `22–26` | O gate acima |
| **—** | `23` | Um titular por escopo; evento de vida é `ocorrido` ou `programado` — "talvez" não entra |
| **—** | `24` | `fixo ⇒ variable_share = 0`; `variavel ⇒ variable_share > 0` |
| **—** | `24` | `committable_brl ≤ fixed_brl + variable_p10_brl` — não se compromete o mês bom |
| **—** | `25` | Ativo onerado **exige** a dívida vinculada; residência principal é uma só; avaliação é append-only (C7 estendido) |
| **C26a** | `26` | Veto bloqueante recusado nos **três** caminhos: carteira-alvo, adoção de Carteira Modelo, roteamento de aporte |
| **C26b** | `26` | Restrição não afrouxa em silêncio: `bloqueante → alerta` por UPDATE é proibido; teto não sobe; revogar exige `revoked_by = user_id` |
| **C27a** | `27` | Não existe entrega sem ao menos um motivo material |
| **C27b** | `27` | Carteira-alvo exige o suitability **vigente na hora da apresentação** |
| **C27c** | `27` | Insumo **material** não pode ser hipótese nem opinião — o fecho da onda |
| **C27d** | `27` | Registro de entrega é imutável; só o desfecho muda |
| **C27e** | `27` | Carteira-alvo não fica `active` sem registro do porquê |

---

## ⚠️ Uma mudança que quebrava o teste original — RESOLVIDA (2026-08-22)

**C27e** (`decisions.assert_active_target_has_record`) é um constraint trigger
diferido sobre `planning.target_portfolios`. O arquivo
`tests/test_regras_invioláveis.sql` inseria a carteira-alvo ativa do T7 sem
`decisions.records`; o `SET CONSTRAINTS ALL IMMEDIATE` do T14 disparava a
checagem pendente de C27e e o T14 reportava `ok` **pelo motivo errado** —
confirmado na execução real (`rejeitado: C27e — carteira-alvo 8888…`).

Correção aplicada no teste original, logo após o INSERT da carteira do T7:
suitability vigente do usuário de teste + `decisions.records` (`carteira_alvo`)
+ `decisions.rationale_items`. O fixture cumpre C27a/C27b/C27e e o T14 passou a
ser rejeitado por `Pesos da carteira-alvo 8888…` — a regra que ele prova.
C27e ficou intacta.

---

## Premissas confirmadas nesta rodada

- `billing.plan_code` = `('free','essential','advanced','wealth')` — **confirmado**
  em `03_billing.sql:16`. A pendência anotada no `README_AGENTES.md` está resolvida:
  `free` e `essential` existem mesmo, e há um quarto plano (`wealth`) que talvez
  valha revisar nos seeds de `AGENT_QUOTAS`.
- Convenções verificadas contra o conjunto completo 00–21 (que agora está no zip):
  `core.new_id()`, `core.set_updated_at()`, `core.forbid_update_delete()`,
  domains, padrão RLS por GUC, `BEGIN/COMMIT` por arquivo, coluna gerada com
  domain (precedente: `budget.monthly_summaries.surplus_brl`).

## Validação em PostgreSQL real (2026-08-22)

Os 27 arquivos foram aplicados do zero num PostgreSQL 18.6 gerenciado (Aiven) e
`tests/test_regras_invioláveis_contexto.sql` rodou até o fim: **51 asserções
(T25–T40c), nenhum `FALHOU`**. Validador estático: 289 objetos, 0 erros, 0 avisos.
Os três pontos de atenção listados antes, um a um:

1. `SET CONSTRAINTS planning.target_allocations_respect_constraints IMMEDIATE`
   (T32), `decisions.records_need_rationale` (T34) e
   `planning.target_active_needs_record` (T35) — a qualificação de schema
   funciona; os três testes passaram.
2. `ALTER TYPE context.proposal_kind ADD VALUE` dentro da transação de
   `22_assertions` — aplicou sem erro (valores só usados após o COMMIT).
3. `budget.income_sources.monthly_gross_brl` — o arredondamento **estava errado**:
   as constantes truncadas (`0.333333`, `0.166667`, `0.083333`) davam
   R$ 9.999,96/mês para R$ 120 mil/ano e R$ 39.999,96 para R$ 120 mil/trimestre.
   Corrigido em `24_income.sql` com frações exatas (`1.0/3`, `1.0/6`, `1.0/12`;
   o arredondamento a centavos acontece uma vez, no domain `money_brl`) e
   provado por **T30e** (novo), que falhava antes da correção. `semanal` = 4,345
   (365 ÷ 7 ÷ 12) foi mantido como convenção.

Também corrigido nesta rodada, fora deste recorte: `15_taxonomia`
(`v_action_queue` referenciava `f.family`, que vive em `finding_types`) e
`19_llm` (`jsonb_build_object` é STABLE — não pode em coluna gerada; wrapper
`llm.prompt_hash` IMMUTABLE). Detalhes no `README.md` §1.2.

---

## Alembic

**Implementado em `alembic/versions/0022_assertions.py … 0027_decisions.py`** (README.md §7);
o esboço abaixo é histórico — os downgrades ali sugeridos NÃO foram implementados
(append-only; `downgrade()` levanta `NotImplementedError`).

Mesmo padrão: uma revision por arquivo, encadeadas a partir de `0021_context`.

```python
# versions/0022_assertions.py
revision = "0022_assertions"
down_revision = "0021_context"

def upgrade() -> None:
    sql = (Path(__file__).parent.parent / "sql" / "22_assertions.sql").read_text()
    op.execute(sql)

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS members_assertion_gate ON household.members;")
    op.execute("DROP TABLE context.assertions CASCADE;")
    op.execute("DROP TYPE context.assertion_modality, context.assertion_status, "
               "context.assertion_source, context.subject_kind;")
    op.execute("DELETE FROM engine.policy_versions WHERE code = 'CONTEXT_ASSERTIONS';")
    # labels de enum adicionados por ADD VALUE não têm downgrade — documentado.
```

Downgrades dos demais: `DROP SCHEMA household|estate|preferences|decisions CASCADE`
e, no caso de 24, `DROP TABLE budget.income_sources, budget.income_summaries CASCADE`
+ os enums + `DELETE FROM engine.policy_versions WHERE code = 'INCOME_HAIRCUT'`.
**Atenção:** o downgrade de 26 e 27 precisa remover explicitamente os triggers
plantados em `planning.*` (`target_allocations_respect_constraints`,
`model_adoptions_respect_constraints`, `contribution_routings_respect_constraints`,
`target_active_needs_record`) — `DROP SCHEMA CASCADE` os leva junto, mas só
porque as funções vivem nos schemas novos. Não confie nisso sem testar.

---

## Sobre o nome `decisions` (e não `recommendations`)

`planning.model_portfolios` já tem `CHECK (display_name !~* 'recomendad')` —
§4.6/T8, porque recomendação é ato regulado (RCVM 19). Chamar o schema de
`recommendations` seria criar, na própria estrutura do banco, a prova de que o
produto se entende como consultoria. `decisions.records` registra **o que foi
apresentado**, e o mesmo CHECK vale no `headline`.

---

## Deliberadamente fora desta onda

- **Vetos setoriais e de país com efeito real** — `veto_setor` e `veto_pais`
  existem no enum, mas o gate C26a só resolve classe, emissor e instrumento.
  Setor exige uma taxonomia em `market.instruments.metadata` que ainda não existe.
- **Reconciliação renda × `budget.cash_events`** — hoje `income_sources` e os
  eventos de caixa convivem sem cruzamento automático.
- **`estate` conectado a `diagnostics`** — concentração em imóvel deveria virar
  finding. O dado agora existe; o `finding_type` não.
- **Point-in-time do núcleo familiar** — `household.members` tem `ended_at`, mas
  não é bitemporal. Reproduzir "quantos dependentes ele tinha em 2027" exige as
  asserções, não a tabela.
- **RLS em `decisions.rationale_items` e `decisions.inputs`** — herdam por
  `record_id` (CASCADE) e acesso via JOIN. Se algum serviço ler direto, isso vira
  buraco: adicione `scope_id` denormalizado + policy antes disso acontecer.

---

## Uma observação fora do escopo técnico

Esta onda é boa arquitetura e não muda o risco número um do Synapta.
O produto continua sem deploy em produção e sem cliente pagante; o que
`preferences.constraints` e `decisions.records` valem depende inteiramente de
existir alguém do outro lado dizendo "não quero cripto". As seis migrations
custam pouco para manter paradas — mas cada semana gasta aqui é uma semana não
gasta descobrindo se alguém paga. Vale decidir conscientemente, não por inércia.
