# Plexo · Banco de dados completo (MVP + Agentes IA)

> Estado atual do projeto inteiro (banco, tooling, frontend, pendências, changelog):
> **`../ESTADO_DO_PROJETO.md`**. Este README detalha o banco.

PostgreSQL 16+ (validado em 18.6). **60 migrations** (00–15 núcleo do produto,
17–21 camada de agentes, 22–27 contexto pessoal — ver `README_CONTEXTO.md` —,
28 papéis e privilégios, 29 gates de tools, 30 gate de conteúdo educativo, 31 séries de mercado imutáveis,
32 gates do DAG do Analista, 33 sessões, 34 camada documental, 35–37 expectativas Focus/BCB,
**38 catálogo de fatos, 39 extração ao vivo, 40 indicadores e scores do cliente, 41 premissas,
42 supersessão na confirmação, 43 janela operável do motor, 44 fidelidade do perfil, 45 gate na leitura do perfil, 46 insumos da lacuna, 47 renda comprometível** — [F14–F16],
**48–50 premissas de mercado e probabilidade da meta** — [F17] —, **51–52 orçamento da síntese e extração incremental** — [F18] —,
**53 reconciliação da carteira, 54 Raio-X da carteira, 55 `security_invoker` das views, 56 RLS das partições e das filhas por FK, 57 isenções de RLS declaradas** — [F19] —, **58 canário do card ao vivo e rótulo do extrator** — [F20] —, **59 fundações do onboarding obrigatório** — [F21a] —, **60 intake do onboarding com IA** — [F21b]), **20 arquivos de teste** (T1–T14,
T15–T24, T25–T40, T41–T50 RLS sob papéis reais, T51–T53 gates de tools, T54–T57 conteúdo educativo,
T58–T62 dados de mercado, T63–T67 pipeline do Analista, T68–T72 sessões, T73–T79 documental/Focus,
T80–T88 catálogo de fatos, T89–T94 proposta ao vivo, T95–T102 scores do cliente, T103–T110 derivação da estrutura,
T111–T116 premissas de mercado, **T117–T120 reconciliação da carteira**, **T121–T126 Raio-X**,
**T127–T129 `security_invoker` das views**, **T130–T134 RLS das partições e das filhas por FK** e
**T135–T137 canário do card ao vivo e rótulo do extrator**, **T138–T141 onboarding obrigatório** e **T142–T145 intake do onboarding**),
diagrama em `synapta_banco.drawio`.

**Números reais do conjunto 00–21:** 112 tabelas (93 núcleo + 19 agentes), 46 enums,
10 domains, 115 índices, 57 triggers, 24 funções, 6 views + 1 materialized view.
**Conjunto completo 00–54, medido no banco (2026-08-30 por `db_runner.py inventory`):** 138 tabelas
(179 partições), 76 enums, 10 domains, 331 índices, 130 triggers, 83 funções, 21 views + 1 materialized view,
83 políticas de RLS.

---

## 1. Aviso de procedência — leia primeiro

Este pacote foi montado em duas ondas:

1. **Arquivos originais (revisados na 3ª onda — ver §1.1):** `01_identity`,
   `02_engine`, `06_diagnostics`, `12_analytics` e o teste
   `test_regras_invioláveis.sql`. Eram os únicos que existiam — o README
   anterior (preservado em `README_original.md`) descrevia um conjunto de 16
   arquivos, mas 12 deles nunca foram gerados.
2. **Arquivos gerados por engenharia reversa dos 4 originais + testes:**
   `00, 03, 04, 05, 07, 08, 09, 10, 11, 13, 14, 15` e a camada de agentes
   `17–21`. O arquivo de testes original fixa nomes exatos de tabelas, colunas e
   comportamentos (T7–T14 referenciam tabelas que não existiam) — os novos
   arquivos foram escritos para honrar esse contrato.

### 1.0-F22b Changelog da onda F22 (2ª parte) — a projeção, e o incidente em produção (2026-09-09)

**Leia isto primeiro: esta onda derrubou a escrita em produção.** A carga de 2,9 milhões de linhas de
preço levou o banco de 45 MB a 622 MB, e a Aiven pôs o serviço em `default_transaction_read_only = on`.
O plano free tem **~1 GB de disco**, não os ~5 GB que o plano da onda supôs — o indício estava em
`max_wal_size = 49 MB`, no próprio servidor, e ninguém olhou antes. E o gate de disco escrito para
justamente evitar isso media `pg_database_size`, que **não conta o WAL** — e foi o WAL que encheu.
Recuperado com `TRUNCATE` em 90 partições que continham só o acervo (454 MB, banco a 168 MB), com
registro em `audit.activity_log`. Nada se perdeu: as linhas se reproduzem dos Parquet.

| Arquivo | Mudança | Por quê |
|---|---|---|
| `tools/projetar_acervo.py` (novo) | Subcomandos `instrumentos`, `precos`, `status`; lote idempotente por `file_hash` reusando a disciplina da 31; filtros vetorizados conferidos contra a regra escalar numa amostra de cada arquivo; teto de disco por `--teto-mb` | Roda no Python do SISTEMA, que tem pandas e pyarrow. O backend não os tem e não deve ter: `requirements.txt` é lista de deploy, e isto é backfill de uma vez. A rotina DIÁRIA continua sendo `plexo mercado ingerir`, que lê o TXT da B3 sem pandas |
| `app/market/acervo.py` (novo, stdlib puro) | FATCOT, filtro de mercado à vista, formato de ticker, kind e classe de ativo | São as decisões que produzem número errado em SILÊNCIO. Ficam num módulo sem dependência para que o pytest (na `.venv`) e o projetor (no Python do sistema) usem a MESMA fonte — duas cópias da mesma regra é o defeito que a 53 corrigiu na carteira |
| `app/tools/context_pack.py` | `cobertura_mercado` deixou de listar papel a papel: virou resumo com contagem por tipo, faixa de datas e ponteiro para `dados.resolver_instrumento` | Era uma linha por instrumento no prompt do sistema, a CADA chamada ao modelo, duas por turno — ~7.500 tokens com o acervo, para sempre — e ainda fazia `count(*)` agrupado sobre `market.prices` inteira num nó de 1 GB. Agora ~120 tokens, e o `min/max` usa o índice da PK |
| `app/tools/analista/{historico_comparado,serie_indice}.py` → **1.1.0** | Amostragem por `ANALISE_PARAMS.max_pontos` + campo `amostrado`; `_comum.amostrar_mensal` ganhou tipo genérico | O output da tool volta INTEIRO ao modelo como `role=tool`. `periodo='tudo'` são dez anos: ~2.520 pontos por série, duas séries. O mecanismo já existia e só `dados.serie_precos` o usava. **Amostrar não muda número**: base 100, resumo e acumulado seguem da série inteira, e a série cheia continua indo para o bloco |
| `tests/test_f22_acervo.py` · `tests/test_f5_analista_tools.py` | +10 pytest do módulo puro e da cobertura; +2 da amostragem | Quatro leituras do COTAHIST que só o arquivo real revelou — e os casos saíram do arquivo, não da cabeça de quem escreveu (ver abaixo) |

**As quatro leituras que o arquivo derrubou.** Escrevi o regex de ticker com `PETR4` e `BOVA11`, passou,
e o COTAHIST recusou `B3SA3` — a própria B3, que está no IBrX-100: código é 4 caracteres **alfanuméricos**,
não 4 letras. **BDR não está no CODBDI 02**, vive em 34/35/36 (~89 mil linhas por ano, e com elas toda a
exposição internacional do cliente). **CODBDI 07 e 08 trazem 20 a 30 ações por ano sem linha no 02**
(`AMER3`, `AMBP3`): papéis em situação especial, cuja exclusão apagaria esses tickers da base. E o
**CODBDI 14 não separa ETF de FIAGRO/FIP/FIDC** — todos com `specification = 'CI'` —, então o kind honesto
é `fundo` até o cadastro CVM chegar. A série começa em **1998**: antes disso o COTAHIST usa o código antigo
da Bovespa (`ACE 3`) e 100% das linhas são recusadas.

**Estado ao fim da onda:** 4.152 instrumentos catalogados (ISIN em 4.016, 128 aliases de renomeação),
556 mil preços de 2025-01-02 a 2026-09-08, banco em 168 MB, `is_in_universe` ainda nos 5 do dev.
Carga de preço histórico **parada** até a decisão de infraestrutura.

### 1.0-F22 Changelog da onda F22 — o acervo de mercado ganha estrutura (2026-09-09)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `61_acervo_de_mercado.sql` | Cinco tabelas em `market`, todas append-only por trigger **e** por privilégio (REVOKE derivado do catálogo, padrão da 28/31) e todas globais, sem `scope_id`: `trading_calendar` (feriados ANBIMA), `sector_classification` (**`reference_date` na chave**), `index_weights` (carteira teórica com peso), `yield_curve` (`day_count` enum NOT NULL, coluna `rate_pct`), `fundamentals` (`availability_date` NOT NULL e `>= reference_date`, `UNIQUE` por vintage) | A F5 declarou por escrito que o Analista "depende de fonte de preços (não existe)". Três desvios dela caem aqui: **(g)** o calendário era derivado dos próprios preços; **(c)** o benchmark era BOVA11 por falta do IBOV em pontos; **(b)** sem proventos, toda data-ex virava queda artificial |
| idem — views `market.v_fatores_ajuste` e `market.v_precos_ajustados` | Preço ajustado **calculado na leitura**, nunca gravado; fator piecewise-constante por (instrumento, data-ex), ~25 mil linhas cobrindo milhões de pregões; ambas `security_invoker` | O `cum_factor` de ontem MUDA quando um provento é anunciado hoje. Materializá-lo em `market.prices` seria reescrever série — o que o T58 proíbe. O coletor mediu o tamanho do erro que o ajuste evita: PETR4 em 2024 rende −4,21% no bruto e **+13,35%** no ajustado |
| idem — `core.ensure_year_partitions` + 28 partições novas | Anuais para 1995–2015 (`prices_AAAA`) e 7 mensais de 2016 para emendar com o que a 31 criou. `market.prices` foi de 133 para **161** partições | Mensal até 1995 custaria 259 partições novas; anual custa 21. O nó da Aiven tem 1 GB de RAM e dado velho não muda. A série só começa em 1995 porque antes disso são quatro trocas de moeda e o coletor não deflaciona |
| idem — `pg_trgm`, `unaccent`, `market.texto_busca()`, 2 GIN em `instruments` | Primeiras extensões desde `pgcrypto` na 00; invólucro IMMUTABLE declarado (trocar o dicionário exige REINDEX) | `dados.resolver_instrumento` faz `ilike '%termo%'`, e o glossário e `contexto.documento_oficial` filtram em Python com o comentário "o banco não tem unaccent". **Não é embedding**: ~6,5 mil tickers e ~60 mil fundos são cardinalidade de catálogo, e número com proveniência não se busca por aproximação — `pgvector` está no servidor (0.8.6) e ficou fora de propósito |
| `app/market/ingest.py` | `_PARTICAO` passou a aceitar `prices_AAAA` além de `prices_AAAAMM`; `_faixa_da_particao` extraída e testada à parte | Canário morto encontrado pela própria onda: as partições anuais seriam ignoradas **em silêncio** e `mercado status` diria que a base começa em 2016 com trinta anos de pregão carregados |
| `tools/gera_diagrama.py` | `assert n_listed==145` (era 138) | Segunda morte do mesmo canário: o real já era 140 desde a migration 60 e ninguém reviu. O comentário no arquivo agora registra as duas |
| `tests/test_regras_invioláveis_market.sql` · `tests/test_f22_acervo.py` | **T146–T150** (19 asserções novas; o arquivo foi de 26 para 45, verdes nos dois papéis) + 4 pytest | Vermelho antes, registrado: `[INEXISTENTE] DML referencia market.trading_calendar` no validador e `SQLSTATE 42P01: relation "market.trading_calendar" does not exist` na linha 234, com T58–T79 ainda verdes |

**Esta onda não carrega dado.** A projeção do acervo (`mercado_brasil_dados.zip`: 4,1 mi de linhas de
mercado à vista 1986→2026, medidas) é a Fase 2. Duas coisas medidas na investigação que ela precisa
respeitar: os Parquet **não** trazem `layout_version`, logo os preços precisam ser divididos por
`quote_factor` (FATCOT) — sem isso séries antigas ficam **1.000× erradas em silêncio** —, e `market_type`
no Parquet é o código cru (`'010'`), com ETF em **CODBDI 14**, não 02.

### 1.0-F21b Changelog da onda F21b — intake do onboarding com IA (2026-08-31)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `60_intake_do_onboarding.sql` | `context.intake_submissions` (texto/arquivo/áudio congelados como evidência: texto exige corpo e proíbe mídia; binário exige mídia+mime+sha256; **C60c** teto de bytes e quota diária lidos da policy `ONBOARDING_EXTRACAO`, padrão FAMILY_LIMITS; **C60d** mídia/hash/origem imutáveis, `body_text` só NULL→valor, status só para frente com `falhou→extraido` como retry) e `context.intake_items` (**C60a** item nasce 'proposto' com carimbos zerados; **C60b** payload/identidade imutáveis, transições únicas `proposto→confirmado\|rejeitado`, terminais imutáveis; `self_confirmation_only`; `fato_tem_chave` com FK ao catálogo); RLS `scope_isolation` nas duas; `ALTER TYPE llm.call_purpose ADD 'transcricao'` (uso na F21d); seed `ONBOARDING_EXTRACAO` v1 draft | O bullet "Objetivo: carro de 80 mil em 2 anos" é ENTIDADE composta — não cabe numa change_proposal de UM fato, e um texto rico estouraria o teto C38g (5 pendentes). Tabelas próprias reproduzem o padrão epistêmico de C21/C22a sem tocar a cadeia de extração de conversas (21/39/58), que segue intacta |
| `app/intake/{provedores,itens,extrator,aplicar}.py` | Protocols `Transcritor`/`ExtratorDeArquivo` + fakes + fábricas que devolvem **None** até a F21d (submissão binária fica HONESTAMENTE em `aguardando_provedor`); extrator espelha o de conversas (json_object + 1 reparo, `model_calls`, `cost_ledger ref_kind='job'`, descartes auditados em UMA linha, SAVEPOINT por item); itens validados por Pydantic com vocabulário fechado (`tipo` desconhecido vira 'outro', fato fora do catálogo/faixa é descartado com motivo, teto `max_itens_por_submissao`); `aplicar.confirmar_item` roda sob app_session (RLS decide o que existe) e escreve fato `source='onboarding'` (confiança 0,85) ou estrutura | "Dado insuficiente não é exceção" e "o LLM estrutura, o código decide" — os mesmos contratos das tools; a confirmação é o ato epistêmico e passa pelos gates reais do banco |
| `app/onboarding/estrutura.py` (novo) + `jornada.py`/`escrita.py` | escritores de objetivo/dívida/bem extraídos de jornada.py e compartilhados wizard↔intake; `confirmar_fato` ganhou `source`/`confianca` (defaults preservam a F21a) e o helper `validar_fato` | Duas rotas para a mesma linha é o padrão de bug que a migration 53 corrigiu na carteira — o intake escreve pelo MESMO caminho do wizard |
| `app/api/routes/onboarding.py` · `requirements.txt` | `POST /onboarding/intake` (JSON de texto processado INLINE — precedente do turno — devolvendo os itens; multipart `passo`+`tipo`+`midia` → 202; **primeira rota multipart do app**, `python-multipart` novo), `GET /onboarding/intake/{id}`, `POST …/itens/{id}/confirmar\|rejeitar`; C60c traduzido em 422, nunca 500 | — |
| `app/jobs/{tasks,worker}.py` · `app/cli.py` | task `processar_intake` (sem cron) + CLI `onboarding processar [--id]` (varre pendentes sem Redis) | F21d religa com os provedores reais |
| `prompts/context.onboarding_extractor.j2` | extrator de texto AVULSO (não conversa): devolve só `{"itens": [...]}` nos 4 kinds, não inventa valor ausente, nunca aconselha; v1 aprovado em dev (hash `249c0062158f`) | vocabulário CVM barra na aprovação; `preparar_ambiente.py` aprova por glob no local/CI |
| `tests/test_regras_invioláveis_intake.sql` · `tests/test_f21b_intake.py` | **T142–T145** (23 asserções, 2 papéis) + **12 pytest** (extração com FakeLLM, descartes, confirmação→estrutura/fato, 409/404, multipart honesto, transcritor plugado por DI) | Vermelho antes, registrado: `relation "context.intake_submissions" does not exist` (precedente F14 de onda com tabela nova) e `404 == 401` |

### 1.0-F21a Changelog da onda F21a — fundações do onboarding obrigatório (2026-08-31)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `59_onboarding_fundacoes.sql` | CHECKs `completed_needs_started`/`completed_needs_track` em `identity.user_profiles`; gate **C59a** `identity.assert_onboarding_conclusao()` (conclusão exige suitability VIGENTE + fatos-núcleo CONFIRMADOS lidos de `context.v_fact_current` num escopo do usuário; lista da policy `ONBOARDING_NUCLEO`, fallback renda+despesa, padrão `FAMILY_LIMITS`; carimbo de conclusão imutável, não se des-conclui); **C59b** `suitability_needs_scope` (suitability sem `scope_id` não se grava — é o que a RLS `scope_isolation` compara) e `suitability_immutable` (única mudança legal é `superseded_at` NULL→valor com o resto idêntico; linha superada é imutável — refazer é linha nova, RCVM 30); seeds `ONBOARDING_NUCLEO` v1 e `SUITABILITY_QUESTIONARIO` v1 (draft, config-first: perguntas, pontos, limiares e validade como dado) | `identity.user_profiles`, `analytics.onboarding_steps` e `identity.suitability_assessments` existiam desde as migrations 01/12 **sem produtor nenhum** — o padrão "gate sem produtor" pela quarta vez (`foundation_status`, `plano` do arquétipo, `findings`). A F21a entrega o produtor e transforma em constraint o que era só intenção: onboarding completo não se forja por INSERT |
| `app/onboarding/{jornada,suitability,escrita,erros}.py` · `app/api/routes/onboarding.py` · `app/main.py` | produtor da jornada: `GET /onboarding`, `POST /onboarding/iniciar`, `PUT /onboarding/passos/{vida,renda_despesa,dividas,patrimonio,objetivos,suitability}`, `POST …/pular` (só passos opcionais), `POST /onboarding/concluir` (pré-cheque 409 `{faltando}` + gate do banco como palavra final + pipeline `derivar→projetar→calcular` em best-effort auditado). Fato de formulário nasce `declarado` e é confirmado no segundo ato (C22a), com `subject_kind`/`attribute`/`unit` lidos do CATÁLOGO (nunca hardcode — `fluxo.aporte_mensal` tem `subject_kind='despesa'`); dívida entra em % a.a. e vive como fração (`core.rate_annual`); suitability supersede a vigente e materializa `vida.tolerancia_risco_declarada`; funil em `analytics.onboarding_steps`; `answers` guarda o payload cru | O banco executa as regras; a API só as percorre na ordem que os gates exigem (`scope_members` → titular do núcleo; `budget.debts` → `estate.assets` onerado). `source='formulario'` vence a precedência DECLARADA — `'onboarding'` fica para a extração de IA pré-confirmação (F21b) |
| `app/api/routes/auth.py` | `POST /auth/cadastro` cria também `identity.user_profiles(user_id)`; `GET /auth/me` expõe `{"onboarding": {obrigatorio, concluido}}` (conta sem linha = legado, não obrigada) | O gating de obrigatoriedade é do cliente (redirect via `useSessao`); `proxy.ts` só enxerga cookie opaco, por decisão da F7 |
| `tests/test_regras_invioláveis_onboarding.sql` · `tests/test_f21_onboarding.py` | **T138–T141** (22 asserções, nos dois papéis) + **19 testes pytest** (contrato da API, pontuação golden do questionário, fração da taxa, ônus→dívida, supersessão, funil, isolamento) | Vermelho antes, registrado: SQL abortava em `T138a … deveria ter sido rejeitado pelo banco` (o gate não existia) e pytest `assert 404 == 401` (rotas inexistentes) |
| `tests/test_regras_invioláveis_{agentes,contexto}.sql` | fixtures de suitability ganharam `scope_id` (e o usuário "Vencido" ganhou escopo próprio) | **C59b as invalidou — achado da suíte INTEIRA no fechamento, não da verificação direcionada** (o caso F17 de novo). Apareceu em 33 s no fechamento local-first; no Aiven a mesma bateria passava de 1 h estourando timeout |
| `tools/validador.py` | `59_…` em `ORDER`, `test_…_onboarding.sql` em `TESTS` | — |

### 1.0-F20 Changelog da onda F20 — canário do card ao vivo + rótulo do extrator (2026-08-31)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `58_canario_do_card.sql` | gate `context.assert_proposal_is_worth_asking` (proposta `origin='turno'`) passa a exigir `scope_id` na allowlist `escopos_canario_card_ao_vivo` de `CONTEXT_FACT_CATALOG` — chave ausente ou payload que não é array = fail-closed, nenhum escopo é canário; coluna `nature_do_extrator` (espelho imutável de `nature` capturado no nascimento pela trigger, backfill só em `status='proposta'` — nas respondidas o palpite original é irrecuperável); view `context.v_precisao_extrator` (`security_invoker`) com a precisão por classe | O card ao vivo (F14b, migration 39) nascia para QUALQUER escopo assim que o sinal certo disparava, sem nenhuma medição de quão bem o extrator acerta a natureza proposta. Até essa precisão estar medida por classe, só escopos canário (dev, personas, contas de demonstração) recebem o card que INTERROMPE a conversa; o resto do produto segue capturado pela extração de fim de conversa |
| `app/context/aplicador.py` | `classificar_natureza` grava `audit.activity_log` (`action = 'context.proposal.nature_classified'`, natureza anterior e nova em `details`) | A resposta do cliente ao card é o próprio rótulo que `v_precisao_extrator` compara com `nature_do_extrator` — reclassificar sem trilha seria adulterar a medição que a allowlist existe para produzir, mesmo padrão já usado em `registrar_recusa` |
| `app/cli.py` | comando `context canario` | Visão do operador: allowlist vigente, `precisao_minima_publicacao` e as linhas de `v_precisao_extrator`, sem exigir acesso direto ao banco |
| `tests/test_regras_invioláveis_perfil_vivo.sql`, `tests/test_f20_canario.py` | T135–T137 (11 asserções) + 3 testes de app | Vermelho antes: sem o gate, escopo fora da allowlist recebia o card; sem a coluna, `UndefinedColumn: nature_do_extrator`; sem a auditoria, `audit count 0`. **T137b** prova a fórmula da precisão (2 respondidas, 1 na mesma classe ⇒ 0,5) |

### 1.0-F19 Changelog da onda F19 — a carteira aberta e o Raio-X (2026-08-30)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `53_reconciliacao_da_carteira.sql` | trigger em `wealth.portfolio_snapshots`: havendo posição no dia, `total_brl` É a soma delas | A conta de demonstração tinha R$ 780.000 no rollup e ZERO posições. O `context_pack` injetava o número no prompt e a tool respondia "não há posição registrada no escopo" — **no mesmo turno**. Duas fontes para o mesmo fato, e nada obrigando as duas a concordarem |
| `54_raio_x_da_carteira.sql` | `implemented_at` vira CONDIÇÃO DE EXISTÊNCIA; quantificável exige `quantification`; tipo do FGC; `RAIOX_LIMIARES` | `diagnostics.findings` tinha **zero linhas** desde a migration 15 — 21 tipos semeados, `v_issuer_concentration` pronta, `engine.run_kind` com `'raiox'` desde a 02, e nenhum produtor. Terceiro caso do padrão (`foundation_status`, `plano`). Agora o catálogo não consegue mentir sobre si mesmo |
| `app/engine/raiox.py` | metade pura `detectar()` + metade que grava e FECHA o que sumiu | Fechar importa tanto quanto abrir: alerta resolvido que fica na tela ensina o cliente a ignorar a lista inteira. **Concentração se mede sobre a carteira INTEIRA** — a view divide pela parte com emissor cadastrado, o que é certo para ela e faria 30% virar 60% aqui |
| `app/seeds/personas.py` | `Emissor`, `Posicao`, `carteira` no `Arquetipo`; rollup DERIVADO da tabela | Somar a lista em memória fazia o rollup afirmar um total que a tabela não sustenta assim que a carteira declarada mudava — append-only não apaga o que já foi gravado no dia. O rollup é, por definição, a soma do que está lá |
| `app/tools/assessor/posicoes.py` | tool que cruza posição × preço × custo, com DUAS datas separadas | Nada no sistema expunha posição por ativo: a composição agrega `group by classe`, e a resposta a "devo vender minhas ações?" seria "ações: R$ 319.046". **1.0.1**: a cobertura do FGC é do INSTRUMENTO, não do emissor — ITUB4 voltou como coberta no primeiro smoke |
| `app/tools/assessor/atencao.py` | frase do cliente por DICIONÁRIO, nunca redigida pelo modelo | "vender", "venda" e "melhor" isolados **não estão** no vocabulário proibido; quem barra o imperativo é uma regra de prompt sem detector. Alerta é justo o texto que puxa o modelo para "então faça Y" |
| `app/agents/blocos.py` | tipos `carteira` e `atencao`; `_composicao_patrimonio` passou a traduzir o aviso | O slug cru atravessava até `Bloco.tsx`, que o descarta: `ha_passivo_no_consolidado` **nunca chegou a nenhum cliente**, com a frase já escrita esperando |
| `seeds/persona.sql` | `estate.valuations` sem `id` explícito | O seed se dizia idempotente e era — só dentro do mesmo dia. Em outro dia a PK estourava, porque a série append-only muda de data |

### 1.0-F17 Changelog da onda F17 — probabilidade de sucesso das metas (2026-08-29)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `tests/test_regras_invioláveis_{perfil,perfil_vivo,scores}.sql` | `pergunta` nas fixtures askable; T102 reescrito; **T102d/T102e novos** | O CI vermelho: a 43 acrescentou `askable_has_question` e eu re-rodei só o teste novo. A suíte inteira revelou que **o T102 provava uma regra que a 44 e a 47 já haviam mudado** — a fixture tinha UMA família crítica, então nem o mínimo de duas nem a margem eram exercitados |
| `48_market_assumptions.sql` | `market.assumption_sets` + `class_assumptions` + `class_correlations`; percentis, arrependimento e proveniência em `goal_projections` | O retorno esperado é a opinião mais forte da plataforma e a única sem versão, autor ou origem escrita. **Unidade virou constraint** (0,07 passa, 7,0 é recusado — a lição do CDI da F16) e **matriz aberta não é aprovada** (par ausente = correlação zero = risco subestimado) |
| `49_elegibilidade_calibrada.sql` | `piora_maxima_do_p5` de 0,00 para 0,10 | Tolerância zero vetava risco em TODA meta, inclusive nas longas em que a probabilidade sobe 35 pontos. Uma regra que dá sempre a mesma resposta não é regra. Achado RODANDO |
| `50_probabilidade_no_destino.sql` | indicador `destino.probabilidade_meta` + fato `objetivo.probabilidade_sucesso` | O indicador que a F14 adiou "por falta de motor" — e que nasce **com quem o alimenta**, que é a lição mais cara da F16 |
| `app/engine/{simulacao,elegibilidade,projecao}.py` | Monte Carlo puro, regra de risco, e a camada de banco | `jsonb` não preserva ordem de chave: a primeira versão tomava a carteira mais ARROJADA como base da comparação e ficou verde invertendo a regra. A ordem passou a ser derivada da volatilidade |
| `app/tools/assessor/simulacao_objetivo.py` | tool de LEITURA da projeção gravada | O executor tem cache endereçado por conteúdo: uma tool que simulasse devolveria, na 2ª chamada, números que ninguém calculou — e sem run para auditar |
| `tests/test_f17_guardrails.py` | o §8 do documento como asserção | O cenário ruim vem antes da mediana **no schema de saída**, não num prompt: prompt se reescreve, contrato não |

### 1.0-F16 Changelog da onda F16 — a rede de fidelidade (2026-08-29)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `46_insumos_da_lacuna.sql` | `protecao.cobertura_vida` e `divida.saldo_total` requeridos; `renda.tipo_vinculo` fora dos opcionais | A correção da 44 estava pela METADE: o catálogo virou requerido e a fórmula continuou lendo ausência como zero. Achado pelos testes de propriedade, na 1ª execução |
| `47_renda_comprometivel.sql` | fato `renda.comprometivel`; rigidez passa a dividir pelo PISO; margem mínima para o elo mais fraco | A rigidez julgava sustentabilidade pela renda MÉDIA, contra regra explícita da 24. E o elo era apontado com diferença de 0,01 |
| `app/engine/fundacao.py` | **produtor de `diagnostics.foundation_status`** | A tabela existia desde a 06, a regra D11 era testada por sabotagem em três arquivos, e **nada nunca a escreveu**: o gate nunca disparou. Sem leitura de reserva é VERMELHO, não verde |
| `tests/test_f16_propriedades.py` | 63 asserções parametrizadas pelo catálogo do banco | Propriedade pega o que exemplo não pega: exemplo confere o número que o autor esperava contra o que o autor escreveu |
| `tests/test_f16_personas.py` + `app/seeds/personas.py` | seis arquétipos e o golden do diagnóstico | Cinco das dez correções vieram de LER o que o motor disse sobre uma persona |

### 1.0-F15 Changelog da onda F15 — o contexto recebe carga (2026-08-29)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `43_fact_derivation.sql` | `context.v_fact_operavel` (confirmado + derivado, confirmado sempre na frente), `fact_definitions.pergunta` + CHECK, cobertura sobre a janela operável | A persona tinha R$ 1,52 mi em dados estruturados e **0% de cobertura**. Um fato que o motor deduziu não vale o mesmo que um que o cliente confirmou — e a diferença virou duas janelas, não uma flag que alguém esquece de filtrar |
| `44_fidelidade_do_perfil.sql` | lacuna de seguro exige a cobertura como insumo REQUERIDO; "elo mais fraco" exige duas famílias críticas | Achados ao RODAR: o indicador publicava R$ 1,8 mi de lacuna para quem o sistema não sabia se tinha seguro, e apontava elo mais fraco num conjunto de um |
| `45_perfil_client_facing.sql` | `v_client_profile` expõe `is_client_facing` e `politica_aprovada` | O gate C40d valia na ESCRITA e vazava na LEITURA: calibrar sobre rascunho levava o número à tela. Gate que só vale na escrita é convenção |
| `tests/test_regras_invioláveis_derivacao.sql` | T103–T110, 20 asserções | Vermelho antes: `column "pergunta" does not exist` |

### 1.0-F14 Changelog da onda F14 — contexto que se atualiza + perfil do cliente (2026-08-29)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `38_fact_catalog.sql` | `context.fact_definitions` (36 fatos, 6 famílias), `assertions.fact_key`, views `v_fact_current`/`v_fact_coverage`, gates C38a–C38h | `attribute` era slug LIVRE: sem vocabulário fechado não há unidade canônica, meia-vida, materialidade nem cobertura. Regras-estrela: o que o Open Finance (ou o suitability) governa a conversa não sobrescreve; mudança imaterial não vira pergunta |
| `39_live_extraction.sql` | `extraction_runs.kind` (`pos_conversa`\|`turno`), `change_proposals.origin` derivada, teto semanal de cards, gate de natureza na aplicação | A 21 proibia ler conversa aberta — certo para o LOTE, errado como proibição geral: perguntar no meio da conversa é outro ato. A cadeia run→sinal→evidência→proposta continua inteira |
| `40_client_profile.sql` | `indicator_definitions`, `client_indicators`, `score_definitions`, `client_scores`, `v_client_profile`; `run_kind` ganha `client_profile` | D11 estendida ao cliente: Fundação crítica DESATIVA o score. Três números por score (valor·cobertura·confiança) e **nenhuma tabela de score composto** — a ausência é a decisão |
| `41_score_premises.sql` | `CLIENT_SCORES` v2 com as premissas dos indicadores | Três fórmulas precisavam de premissa numérica; escrevê-la em Python violaria config-first, e editar a 40 (aplicada) violaria o append-only |
| `42_supersede_on_user_confirm.sql` | supersessão consciente de `allows_conversation_update` | **Bug achado por teste:** a precedência da 38 impedia a confirmação do cliente de aposentar a renda do onboarding — o cliente confirmava e o contexto não mudava. Um laço de confirmação que não muda nada é pior que não perguntar |
| `tests/test_regras_invioláveis_perfil{,_vivo}.sql`, `_scores.sql` | T80–T102, 70 asserções | Vermelho antes em todas: `relation does not exist` na fixture, `column kind does not exist`, `invalid input value for enum` |

### 1.0 Changelog da 6ª onda — F6 Analista research / DAG (2026-08-25)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `32_analysis_dag_gates.sql` + `0032` | `tools.tool_executions.analysis_id` + índice; `tools.execution_context()`; trigger `tools.assert_execution_analysis` (família/política/plano/escopo pela conversa da análise); `analysis.tasks.params/error_detail`, CHECKs, triggers `assert_task_insert` (dependência só de nó já existente no mesmo plano; plano da própria análise) e `assert_task_update` (definição congelada; execução da própria análise); `plans`/`reports`: `no_self_supersede`, versão derivada (`*_new_version`), supersessão em AFTER INSERT (`*_supersede`), replan contado; `assert_report_grounded`; CHECK `research_has_conversation`; `analyses_status_guard`; índice `model_calls(analysis_id)`; RLS nas 4 filhas | O DAG roda num job, fora da requisição: o que a conversa impunha passa a valer pela análise; replan, imutabilidade e fundamentação do relatório são do banco |
| `tests/test_regras_invioláveis_analysis.sql` | T63–T67 (32 asserções) | Sabotagem de cada regra; T64–T67 primeiro (vermelho na asserção), T63 por último (coluna nova); roda sob `plexo_service` |
| `tests/test_regras_invioláveis_agentes.sql` | T21 com `evidence_hash`; T18 com tool sintética `quant.t18` | Gate (d) da 32; `quant.correlacao` existe no dev desde a F5 |
| `tools/validador.py` | `ORDER` += 32, `TESTS` += analysis | — |
| `seeds/dev.sql` | policy operacional `ANALISE_RESEARCH` | Limites do DAG são config, não código |

### 1.0a Changelog da 5ª onda — F5 Analista standard (2026-08-25)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `31_market_immutability.sql` + `0031` | `core.forbid_update_delete` em `market.prices` (pai particionado → clonado nas partições), `index_values`, `fx_rates`, `corporate_actions` + REVOKE derivado do catálogo (padrão da 28, restrito a `market`); CHECK `price_close_positive` (yield pode ser negativo) e CHECKs de `corporate_actions`; trigger `market.assert_not_future` (`price_date`/`value_date` <= `current_date`); FK `prices.ingestion_batch_id`; lotes: CHECKs `batch_finished_has_timestamp`/`batch_succeeded_has_rows`, trigger `market.freeze_finished_batch`, índice único parcial `ingestion_batches_file_uk (source_code, dataset, file_hash) WHERE succeeded`; `core.ensure_month_partitions('market.prices', −10 anos, 120)`; `base_url`/`license_note` de `b3` e `bacen_sgs` | O Analista (F5) fundamenta análise em preço que não muda por baixo dele: correção é linha nova, nunca UPDATE; a idempotência da ingestão é do banco; partições retroativas nascem antes do backfill (o serviço não cria tabelas) |
| `tests/test_regras_invioláveis_market.sql` | T58–T62 (22 asserções) | Sabotagem de cada regra acima; roda como admin e sob `plexo_service` (aí o REVOKE fala primeiro) |
| `tools/validador.py` | `ORDER` += 31, `TESTS` += market | — |
| `tools/db_runner.py` | `tests [papel] [arquivo.sql …]` filtra a suíte | Verificação direcionada durante uma fase (pedido do usuário) |
| `seeds/dev.sql` | policies `MERCADO_INGESTAO` (operacional) e `ANALISE_PARAMS` (client-facing, draft → `policy approve`); universo de dev PETR4/VALE3/ITUB4/WEGE3/BOVA11 | Sem instrumento no universo a ingestão ignora o ticker; sem policy aprovada o gate 29a barra a tool |

### 1.0b Changelog da 4ª onda — F4 Educador (2026-08-24)

| Arquivo | Mudança | Por quê |
|---|---|---|
| `30_content_education_gate.sql` + `0030` | view `content.v_education_approved` (`security_invoker`; approved **e** publicado), índices GIN(tags)/parcial, trigger `content.assert_education_review()` | O Educador só ensina com conteúdo aprovado: a única janela das tools `educacao.*` é a view; aprovar exige `reviewed_by/at` + linha em `compliance_reviews` na mesma transação; sair de `approved` exige trilha; título/corpo aprovados são imutáveis (reabrir antes) |
| `tests/test_regras_invioláveis_content.sql` | T54–T57 (12 asserções) | Caminho feliz e sabotagem de cada regra acima; passa também sob `plexo_service` |
| `tests/test_regras_invioláveis_agentes.sql` | T15 rebaixa `agent.educador.system` para draft dentro da própria transação | F4 aprovou o prompt do Educador em dev; o teste não pode depender do estado do banco |
| `tools/validador.py` | `ORDER` += 30, `TESTS` += content | — |

### 1.1 Mudanças da 3ª onda nos arquivos originais (changelog)

Ao aplicar as regras novas de volta sobre os 4 originais, encontrei um bug
real e três lacunas de padrão. Toda mudança está marcada com `[3ª onda]` no
próprio SQL:

| Arquivo | Mudança | Por quê |
|---|---|---|
| `02_engine` | **`freeze_finished_run` endurecido** — a versão antiga só bloqueava UPDATE quando o status NÃO mudava; dava para "reabrir" um run finalizado com `SET status='queued'`. Agora: run finalizado é imutável; única transição é `succeeded → superseded`, e só o status pode mudar (diff via `to_jsonb`, padrão de `20_analysis`). | Bug real. A auditabilidade da RCVM 19 depende do run ser inalterável. |
| `02_engine` | `REVOKE UPDATE, DELETE` em `engine.artifacts` | Padrão T10 (trigger + privilégio) aplicado às append-only regulatórias. |
| `06_diagnostics` | `REVOKE` em `finding_observations` e `action_events` | Idem. |
| `12_analytics` | `analytics.events` vira **append-only explícito** (trigger + REVOKE) | Evento analítico é fato histórico; a costura anônimo→usuário é em leitura. Retenção continua sendo DROP de partição. |
| `01_identity` | Comentário corrigido: o trigger de limite de membros é criado em `02_engine`, não "05_engine" | O arquivo 05 é wealth; a referência apontava para um arquivo que nunca existiu. |
| teste original | **+ T1b** (3 rejeições + 1 aceite): reabertura bloqueada, edição bloqueada, supersedência que tenta alterar outro campo bloqueada, `succeeded→superseded` puro aceito | Prova que o buraco fechou sem quebrar o recálculo diário. |

**O que foi validado:** um validador estático (`tools/validador.py`, incluído)
conferiu, na ordem de execução: (a) toda FK, trigger, tipo de coluna e DML
aponta para objeto criado antes do uso; (b) referências dentro de corpos
plpgsql existem em algum ponto do conjunto; (c) toda coluna usada nos INSERTs
e UPDATEs dos DOIS arquivos de teste existe na tabela; (d) cobertura de RLS
de toda tabela com `scope_id` (única exceção documentada: `analytics.events`).
Resultado: zero pendências em 217 objetos.

**Execução em PostgreSQL real:** feita em 2026-08-22 — ver §1.2. Para repetir:

```bash
createdb synapta
for f in sql/*.sql; do psql -d synapta -v ON_ERROR_STOP=1 -f "$f"; done
psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_regras_invioláveis.sql
psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_regras_invioláveis_agentes.sql
psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_regras_invioláveis_contexto.sql
psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_rls_papeis.sql
psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_regras_invioláveis_tools.sql
```

(Sem psql na máquina de dev: `python tools/db_runner.py apply|tests` faz o mesmo.)

Os arquivos rodam em ordem alfabética (00 → 29; não existe 16, de propósito —
o número ficou reservado para não renumerar a camada de agentes já entregue).

### 1.2 Validação em PostgreSQL real (2026-08-22 — registro HISTÓRICO da etapa; números vivos no topo e em `../ESTADO_DO_PROJETO.md`)

Os 27 arquivos (00–27) foram aplicados do zero, em ordem alfabética, num
PostgreSQL 18.6 gerenciado (Aiven), e os 3 arquivos de teste rodaram até o fim:
**89 asserções, nenhum `FALHOU`** (18 + 20 + 51). Toda correção foi feita no
próprio arquivo (nenhuma migration nova — nada havia sido aplicado antes) e está
marcada com `[validação PG real]` no SQL:

| Arquivo | Correção | Por quê |
|---|---|---|
| `15_taxonomia` | `v_action_queue` passa a juntar `diagnostics.finding_types` e usar `ft.family` | `family` é coluna do **tipo** de finding, não do finding; a view referenciava `f.family` (erro só em execução real — o validador estático não resolve colunas em views) |
| `19_llm` | nova função `llm.prompt_hash(text)` IMMUTABLE usada na coluna gerada `prompt_versions.content_hash` | `jsonb_build_object` é STABLE no catálogo e não pode aparecer em `GENERATED ... STORED`; o wrapper preserva a semântica do hash |
| `24_income` | `monthly_gross_brl` usa frações exatas (`1.0/3`, `1.0/6`, `1.0/12`) em vez de `0.333333`/`0.166667`/`0.083333` | R$ 120 mil/ano virava R$ 9.999,96/mês — número que o cliente lê. Provado por **T30e** (novo), que falhava antes da correção |
| `00_core` + 14, 17–27 | nova `core.is_service()`; as 49 comparações `current_setting('app.role') = 'service'` das políticas passam a chamá-la | O bypass era uma string que QUALQUER conexão podia setar — a API escalava por GUC (provado: `plexo_app` com `app.role='service'` via 2 escopos). Agora exige membro de `plexo_service` E o GUC |
| `14_rls_partitions` | política `user_isolation` em 7 tabelas de PII por `user_id` + `users_self` em `identity.users` | Sem RLS, o papel da API lia o perfil de todos os usuários (provado: 2 perfis visíveis; com o fix, 1). O validador agora exige RLS também para `user_id` |
| 15 views (15, 22–27) | `WITH (security_invoker = true)` | View roda com o RLS do DONO — administrador com BYPASSRLS — e vazava todos os escopos (provado em `ledger.v_scope_totals`: 2 → 1) |
| `28_roles_grants` (nova) | papéis `plexo_app` / `plexo_service` (NOLOGIN, NOBYPASSRLS), USAGE + DML nos 23 schemas, REVOKE UPDATE/DELETE derivado do catálogo onde o trigger `forbid_update_delete` é incondicional | Não existia papel de aplicação; `avnadmin` tem BYPASSRLS, logo nenhuma política tinha sido exercitada até aqui |
| teste original | fixture `decisions.records` + `rationale_items` + suitability vigente para a carteira-alvo do T7 | Desde C27e (`27_decisions`), carteira ativa exige o porquê; sem o fixture, o `SET CONSTRAINTS ALL IMMEDIATE` do T14 disparava C27e antes da regra de pesos e **T14 passava pelo motivo errado**. Agora é rejeitado por "Pesos da carteira-alvo…" |

Inventário no banco NAQUELA DATA (sem partições filhas; a migration 29 depois somou +2 triggers e
+2 funções, e a 30 mais +1 trigger, +1 função, +1 view e +2 índices → hoje 96/50, 16 views + 1 matview, 290 índices): 124 tabelas (4 particionadas, 60 partições), 70 enums, 10 domains,
93 triggers (88 + 5 `CONSTRAINT TRIGGER`), 47 funções, 15 views + 1 matview, 288 índices, 76 tabelas com RLS / 76 políticas,
21 tabelas sem UPDATE para os papéis de aplicação. O recorte
00–21 confere com os números do topo (112 / 46 / 10 / 57 / 24 / 6+1 / 115).
`core.new_id()` resolveu para `uuidv7()` nativo (PG 18); `tools/validador.py`
agora resolve caminhos relativos ao script. **RLS sob papéis reais** (Etapa 3):
`tests/test_rls_papeis.sql` (T41–T50, 22 asserções) roda com `SET ROLE plexo_app`
/ `plexo_service`; além disso os 3 testes anteriores passam inteiros sob
`plexo_service` sem bypass (89 ok). Total à época: **111 asserções** (hoje **129** — T51–T53 chegaram com a migration 29, T54–T57 com a 30). **Alembic** (Etapa 4):
`upgrade head` do zero reproduz o mesmo banco — ver §7. Não validado ainda: comportamento de triggers que leem tabelas de OUTRO escopo sob `plexo_app`
(os testes de regra rodam como serviço); filhas sem `scope_id` (`decisions.rationale_items/inputs`,
`planning.target_allocations`, `engine.artifacts/run_inputs`, `analysis.*`,
`billing.payments`, `wealth.sync_runs`, `audit.pii_access`) seguem acessíveis direto
por `plexo_app` — ver §1.3.

### 1.3a Backend de agentes (`app/`) — F0–F6 concluídas (2026-08-25)
O Assessor conversa de ponta a ponta com o DeepSeek V4 Pro: turno com duas transações e proveniência
completa (mensagem ↔ tool_execution ↔ model_call ↔ cost_ledger), 6 tools determinísticas (orçamento,
planejamento, produto) atrás dos gates do banco (família/plano/política — migration 29), guardrails de
vocabulário RCVM e de orçamento de LLM, roteador do Copiloto, 2ª opinião em `decisions.*`, API FastAPI
com SSE e CLI `chat`. Mapa dos módulos: `app/README.md`. Plano/fase: `../PLANO_AGENTES_IA.md` §0;
estado: `../ESTADO_DO_PROJETO.md` §3.3.

**F3 (2026-08-23) — agente de Contexto:** conversa encerrada → `context.extraction_runs` → `signals` →
`assertions` → `change_proposals`, com o LLM referenciando mensagens por seq e o banco conferindo evidência,
nascimento `declarado/inferido`, likelihood e a regra-estrela (só o próprio usuário confirma; risco exige
novo suitability). Jobs (`app/jobs/`, Arq ou `plexo context run`), API `/proposals`, prompt
`context.extractor` aprovado. **Sem migration nova** — os gates de 21/22 já bastavam.

**F4 (2026-08-24) — Educador:** prompt real `agent.educador.system` aprovado; tools `educacao.glossario`,
`educacao.simulador_juros_compostos`, `educacao.exemplo_didatico` (`app/tools/educador/`) lendo SÓ
`content.v_education_approved` (migration 30); policies `EDUCACAO_PARAMS`/`EDUCACAO_EXEMPLOS`; 8 verbetes de
dev em `seeds/dev.sql` com trilha em `compliance_reviews`; turno com cadeia curta de tools
(`AGENT_CONVERSATIONS.max_tools_por_turno`), `cited_refs` de conteúdo e guardrail contra marcação de tool
vazada.

**F5 (2026-08-25) — Analista standard:** preços oficiais ingeridos de forma idempotente (`app/market/`: COTAHIST da B3 em
streaming, SGS do Bacen; tasks Arq + CLI `mercado`), migration 31 (séries append-only, lote imutável, partições), 6 tools
`dados.*`/`quant.*` (`app/tools/analista/`) com contrato `Evidencia` (point-in-time, lacunas, `suficiente`), toda pergunta
registrada em `analysis.analyses` + `evidence_findings` (`agents/analysis.py`), prompt real `agent.analista.system` aprovado.

**F6 (2026-08-25) — Analista research (DAG):** `app/analysis/` (dsl → compiler → executor com checkpoints → report), planner e
síntese por LLM com prompts aprovados, pipeline idempotente por job (Arq) ou CLI `analise run`, migration 32 (gates pela
análise, DAG, replan contado, relatório fundamentado, RLS nas filhas), API `/analyses*`. Próxima fase: F7 (tela do Copiloto).

### 1.3 Papéis e contrato de sessão (28_roles_grants)

| Papel | Para quê | O que enxerga |
|---|---|---|
| `plexo_app` | API/web | só `app.scope_id` / `app.user_id` da sessão; `app.role='service'` não muda nada |
| `plexo_service` | jobs, motor, backfills, cadastro/login por e-mail | tudo — **somente** com `SET app.role='service'` na sessão (`core.is_service()`) |

Ambos NOLOGIN, NOBYPASSRLS. Logins com senha ficam fora do repositório: ops cria
o login e faz `GRANT plexo_app TO <login_api>` / `GRANT plexo_service TO <login_jobs>`.
Contrato por requisição da API: `SET LOCAL app.user_id`, `SET LOCAL app.scope_id`,
`SET LOCAL app.role = 'user'`. Consequências de desenho: cadastro de usuário e
busca por e-mail são operações de serviço (`identity.users` tem `users_self`);
eventos anônimos de `analytics.onboarding_steps`/`wtp_surveys` (`user_id` NULL)
podem ser gravados por qualquer sessão, mas só o serviço os lê de volta;
`REFRESH MATERIALIZED VIEW` exige o dono (administrador).

---

## 2. As sete críticas que moldaram o núcleo (herdadas e mantidas)

| # | Decisão | Consequência de schema |
|---|---|---|
| C1 | `scope_id` é a raiz de tudo que é financeiro, nunca `user_id` | Family Office (Advanced) é leitura via `scopes.parent_scope_id`, não migração |
| C2 | `engine.runs` ≠ audit log | `runs` + `run_inputs` + `artifacts` respondem "como reproduzo o número"; `audit.activity_log` responde "quem fez o quê" |
| C3 | Findings estáveis entre recálculos | `finding_key` determinístico; cooldown/supressão vivem no FINDING |
| C4 | Regra inviolável é constraint | carteira-alvo única, 5 blocos da ação, retorno de mercado ausente do enum |
| C5 | O fake-door é uma tabela | `analytics.paywall_impressions` grava preço exibido + impacto revelado na mesma linha |
| C6 | Premissa aprovada é estado versionado | `engine.policy_versions` + gate que recusa run client-facing com política draft |
| C7 | Snapshot é imutável | `wealth.holdings_snapshots` append-only, particionado, correção = novo `as_of_date` |

## 3. Mapa de schemas (contagens reais)

| Schema | Tabelas | Arquivo | Responde a |
|---|---:|---|---|
| `core` | — | 00 | domains, `new_id()`, `canonical_hash()`, `ensure_month_partitions()` |
| `identity` | 8 | 01 | usuários, **escopos**, suitability point-in-time, LGPD |
| `engine` | 6 | 02 | política versionada, runs auditáveis, golden masters |
| `billing` | 9 | 03 | planos, **entitlements como dado**, assinaturas, `plan_prices` VAZIA (preço é [PENDENTE]) |
| `market` | 21 | 04 (+31, 35, 48, 61) | instrumentos, emissores (conglomerado), preços D-1 particionados, índices, FX, expectativas Focus, premissas versionadas, calendário/setor/curva/fundamentos |
| `wealth` | 8 | 05 | contas, Open Finance, **snapshots append-only**, transações |
| `diagnostics` | 9 | 06 | taxonomia, findings estáveis, ações (5 blocos), Fundação, score desativável |
| `planning` | 12 | 07 | objetivos, Builder, **carteira-alvo única**, Carteiras Modelo, drift 5/25 |
| `budget` | 6 | 08 | fluxos, taxa de poupança, dívidas, reserva (pode ficar na gaveta — decisão nº 4) |
| `content` | 7 | 09 | Sinais em 5 COLUNAS, Cartas, **teto de 2 push/semana como trigger** |
| `copilot` | 5 | 10 | conversas contextuais, `cited_refs`, guardrails de vocabulário |
| `ledger` | 2 | 11 | Valor Realizado: enum sem `retorno_mercado`, metodologia obrigatória, append-only |
| `analytics` | 7 | 12 | eventos particionados, **paywall/fake-door**, van Westendorp |
| `audit` | 2 | 13 | log imutável particionado + acesso a PII (LGPD art. 37) |
| — | — | 14 | RLS habilitada e FORÇADA (lista curada) + partições mensais iniciais |
| — | — | 15 | seed das 13 políticas (todas DRAFT), 20 finding_types, 6 views + 1 MV |
| `agents` | 5 | 17 | os 4 agentes, conversas, mensagens append-only, cota via policy |
| `tools` | 3 | 18 | catálogo de códigos prontos, versões com git_sha+hash, execuções imutáveis |
| `llm` | 3 | 19 | prompts com aprovação de compliance, model_calls, cost_ledger |
| `analysis` | 5 | 20 | pipeline profundo do Analista: plano, DAG/checkpoints, evidência, relatório |
| `context` | 3 | 21 | extração de sinais e **propostas que só o usuário aplica** |

## 4. Regras que o banco recusa violar (todas com teste)

**Núcleo (tests/test_regras_invioláveis.sql):** T1 política aprovada p/ output
ao cliente · T1b run finalizado imutável (única transição: succeeded→superseded) · T2 ação sem 5 blocos não existe · T4 máx. 1 ação em destaque ·
T5 cooldown 90d + supressão após 2 recusas + "não entendi" marca copy ·
T6 Fundação crítica ⇒ score DESATIVADO · T7 uma carteira-alvo ativa ·
T8 nunca "Recomendadas" · T9 retorno de mercado fora do Ledger · T10 Ledger
append-only · T11 valor sem metodologia não entra · T12 3º push da semana
gravado como suprimido · T13 holdings append-only · T14 pesos somam 1,000.

**Agentes (tests/test_regras_invioláveis_agentes.sql):** T15 sem prompt
aprovado, sem conversa · T16 cota por plano rejeita excedente · T17 mensagens
append-only · T18 agente só invoca tool de família permitida · T19 execução
finalizada imutável · T20 evidência material exige provenance · T21 relatório
publicado imutável · T22 Contexto não lê conversa aberta · T23 sinal sem
evidência real não existe · **T24 (a regra-estrela, em 5 atos): perfil de
risco só muda com confirmação DO PRÓPRIO usuário + NOVO suitability posterior
à proposta.**

## 5. Decisões que tomei ao gerar os faltantes (revise)

1. **Numeração 13/14/15:** o README antigo dizia "13, 14 = RLS, partições" sem
   lugar para `audit`. Ficou: `13_audit`, `14_rls_partitions`, `15_taxonomia`
   (seeds de políticas + taxonomia + views).
2. **Labels de `billing.plan_code`:** `free/essential/advanced/wealth`
   (o original só confirmava `advanced`). Wealth nasce invendável
   (`requires_cvm_authorization`).
3. **Todas as 13 políticas nascem DRAFT** com payloads-placeholder — o primeiro
   run client-facing trava até compliance aprovar (C6, intencional). Idem os 4
   prompts dos agentes.
4. **`analytics.events` sem RLS** (eventos anônimos pré-cadastro); escrita
   sempre via papel `service`. Única tabela com `scope_id` fora da política.
5. **Cartas gerais** (`content.letters` com scope NULL) têm política própria:
   públicas quando publicadas.
6. **Sem FK para tabelas particionadas** (prices, holdings, events,
   activity_log) — proveniência via `engine.run_inputs`, integridade na escrita.
7. **Copilot (10) e Agentes (17+) coexistem**: o Copiloto é a interface
   embutida nas telas; os Agentes são o produto conversacional novo com tools.
   Unificação futura é decisão de produto, não de schema.
8. **Partições:** mês anterior → +12 meses + DEFAULT, via
   `core.ensure_month_partitions()`. Decisão pg_partman × cron segue aberta.

## 6. Decisões que continuam bloqueando (herdadas)

Provider de Postgres (muda particionamento e uuidv7) · auth próprio vs.
provider (`password_hash`) · quando coletar CPF · Orçamento no 1º MVP ·
cortes de banda do van Westendorp (conflito C05) · **preços** (a tabela
`plan_prices` segue vazia de propósito).

## 7. Alembic

Camada pronta em `alembic.ini` + `alembic/` (validada em 2026-08-22, Etapa 4):

- **Uma revision por arquivo SQL**, `alembic/versions/0000_core.py … 0055_security_invoker_das_views.py` (antes: `… 0031_market_immutability.py`, `… 0030_content_education_gate.py`
  (sem 0016, como nos arquivos). Cada `upgrade()` só chama
  `run_sql_file("NN_nome.sql")` — o SQL em `sql/` continua sendo a fonte da
  verdade (RCVM 19: inspecionável em forma não compilada); não há metadata nem
  autogenerate.
- `alembic/sqlfile.py` remove **apenas** o `BEGIN;`/`COMMIT;` externo (coluna
  zero) e executa o texto pela conexão do driver, sem parâmetros: chega ao
  servidor byte a byte (nem `text()` interpretando `:b` em JSON, nem psycopg
  interpretando o `%I` dos `format()`), dentro da transação que o Alembic abre
  por revision (`transaction_per_migration = true` — mesma semântica do loop psql).
- `alembic/env.py` lê `DATABASE_URL` de `plexo-backend/.env` (nunca do ini, nunca
  impressa), normaliza para `postgresql+psycopg://` e força `sslmode=require`.
- **`downgrade()` levanta `NotImplementedError`** em todas as revisions: a base é
  append-only por desenho e o README_CONTEXTO já alertava que os downgrades
  parciais "não são confiáveis sem teste". Voltar atrás = derrubar os 23 schemas
  do projeto (+ `public.alembic_version`) e reaplicar.
- `alembic_exemplo_0017_agents.py` ficou superado por `alembic/versions/0017_agents.py`.

```bash
pip install -r requirements-db.txt
cd plexo-backend
python -m alembic upgrade head      # do zero: 32 revisions, head = 0032_analysis_dag_gates
python -m alembic current           # 0032_analysis_dag_gates (head)
python -m alembic history
```

Provado: `upgrade head` num banco vazio produz inventário idêntico ao da
aplicação via psql (hoje, com a 30: 124 tabelas, 70 enums, 10 domains, 96 triggers, 50 funções,
16 views + 1 mv, 290 índices, 76 políticas, 60 partições); as 6 suítes de teste passam
em cima dele; um segundo `upgrade head` é no-op.

## 8. O que deliberadamente não está aqui

Preços · screening como tabela (é query sobre `instruments.metadata` +
`fund_facts`) · aba Mercado (V2) · execução de ordens (bloqueado) · séries
brutas de Monte Carlo (S3 via `engine.artifacts.storage_key`) · camada
documental/RAG e asset master point-in-time dos agentes (próxima onda —
ver README_AGENTES.md §"Deliberadamente fora").

## 9. Diagrama

`synapta_banco.drawio` — abrir em https://app.diagrams.net (File → Open From →
Device). **Completo:** os 23 schemas com TODAS as 124 tabelas listadas (extraídas
programaticamente dos SQLs por `tools/gera_diagrama.py` — regenerável a
qualquer momento), ★ marcando as que carregam regra inviolável testada,
views em itálico, e ~24 setas nomeadas nas dependências estruturais.
