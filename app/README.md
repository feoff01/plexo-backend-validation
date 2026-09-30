# `app/` — backend de agentes da Plexo (F0–F21b prontas; F20 canário do card · F21a fundações do onboarding · F21b intake com IA)

> Estado do projeto: `../../ESTADO_DO_PROJETO.md` §3.3 · Plano e fase atual: `../../PLANO_AGENTES_IA.md` §0.
> Princípios: o banco executa as regras (RLS, gates 23514/42501); **o LLM nunca calcula** — escolhe a
> tool e sintetiza; config-first (números em `engine.policy_versions`); segredos jamais em log.

## Mapa dos módulos

| Pasta | O quê |
|---|---|
| `config/` | `settings.py` (.env, segredos mascarados; **bloco auth F7**: `AUTH_HEADERS_DEV`, `SESSAO_TTL_H`, `COOKIE_NOME/SECURE/DOMAIN`, `CORS_ORIGINS`, `LOGIN_MAX_FALHAS_*`, `CADASTRO_ABERTO`) · `policies.py` (PolicyStore TTL) · `vocabulario_proibido.yaml` · `chips.yaml` |
| `auth/` | F7 — `senha.py` (scrypt stdlib, formato PHC `$scrypt$ln=15,r=8,p=3$sal$hash`; `gerar`/`verificar`/`precisa_rehash`) · `sessoes.py` (token opaco `token_urlsafe(32)`, sha256 no banco, cookie `plx_sessao` HttpOnly/Lax, expiração deslizante; tudo sob `service_session`) |
| `db/` | `database.py` (sessões por papel: `SET LOCAL ROLE plexo_app/plexo_service` + GUCs; testes = savepoint; **F10:** pool com `check_connection` + `max_idle` — o Aiven fecha conexões ociosas) · `errors.py` (23514/42501 → exceções de domínio) · `repos/` (SQL fino: prompts, policies, audit (com `ip_address`/`user_agent`), identity (cadastro/login), **`sessoes`** (criar/autenticar/tocar/revogar/trocar_escopo/login_attempts)) |
| `llm/` | `client.py` (interface neutra; `reasoning_content` p/ provedores em modo thinking; **F9:** `Trecho` + `streamar()`) · `deepseek.py` (OpenAI-compatible; id `deepseek-v4-pro`; devolve o `reasoning_content` junto das tool_calls; **`chat_stream`** com usage no último chunk) · `fake.py` (testes; `trechos=` reparte o texto em stream) · `recorder.py` (`llm.model_calls` + custo via `LLM_PRICING`) · `prompts.py` (Jinja2 estrito; hash = `llm.prompt_hash`) · `budget.py` (`TurnBudget` ← `LLM_BUDGETS`) |
| `tools/` | `registry.py` (`@tool`: `preparar` assíncrona + `calcular` PURA/golden; `emite_numero=False` = sem rodapé de simulação) · `executor.py` (validação, cache content-addressed, `_policies`/`_inputs`; `ToolConteudoIndisponivel`) · `sync.py` (espelho `tools.tools/tool_versions` com git_sha+sha256) · `context_pack.py` (leituras RLS + pacote minimizado p/ prompt; `nivel_conhecimento`; **F8:** `cobertura_mercado` — universo/período com preço/índices, variável `{{ cobertura_mercado }}` do prompt do Analista) · **`analista/expectativas.py`** (F13b: `dados.expectativas_mercado` — mediana por horizonte da pesquisa Focus, com janela e nº de respondentes declarados; devolve `Evidencia`, então gera finding) · **`contexto/oficial.py`** (F13a: `contexto.documento_oficial` — trecho literal de documento aprovado, com data e link; lê SÓ `docs.v_documentos_citaveis`; `evidencia_documental` vira finding `documentary` e `cited_refs kind=document`) · `assessor/{orcamento,planejamento,produto}.py` · **`assessor/posicoes.py`** (F19: `planejamento.posicoes_carteira` — a carteira POSIÇÃO A POSIÇÃO, primeira tool a cruzar `wealth.holdings_snapshots` com `market.prices` e `market.fund_facts`; duas datas separadas, cobertura do FGC pelo TIPO do instrumento e não pelo emissor; o peso é sempre sobre a carteira inteira, mesmo sob filtro) · **`assessor/atencao.py`** (F19: `planejamento.pontos_de_atencao` — lê `diagnostics.findings` com o gate de plano e a revelação estrutural; a frase de cada alerta vem de DICIONÁRIO, nunca do modelo) · **`assessor/patrimonio.py`** (F12: `planejamento.composicao_patrimonio` — carteira por classe de ativo com rótulo/grupo de `market.asset_classes`; `emite_numero=False` porque é descrição do registrado, não simulação) · `educador/{glossario,juros_compostos,exemplo_didatico}.py` (F4: leem SÓ `content.v_education_approved`) · **`analista/{_comum,resolver_instrumento,serie_precos,serie_indice,retorno_volatilidade,correlacao,event_study}.py`** (F5: contrato `Evidencia`; `price_date <= cutoff`; dado insuficiente = `suficiente=false`, nunca exceção) |
| `agents/` | `turn.py` (o TURNO: Tx A pergunta+cota → **laço único de tool-use (F8)**: o modelo devolve 0..N tool_calls por resposta, todas executadas e respondidas; erro de tool (`parametros_invalidos`/`insumo_faltante`/`conteudo_indisponivel`) volta ao modelo como resultado da chamada até `AGENT_CONVERSATIONS.max_erros_de_tool_por_turno`, depois texto fixo registrado (`outro·bloqueado teto_de_erros_de_tool`); cadeia até `max_tools_por_turno`; `encaminhar` usa o texto do modelo; `ProviderUnavailable` → evento `erro provedor_indisponivel` → Tx B resposta+proveniência (`cited_refs` inclui `education_content`)+cost_ledger) · `router.py` (chip/forçado/auto/clarify; **F8:** `Intencao.resposta_curta` — saudação/meta/fora de finanças vira `Clarify` com o texto do modelo, sem conversa nem cota) · `conversations.py` (`historico(..., max_chars_resultado)` anexa `[dados medidos: …]` às mensagens do agente que vieram de tool) · `guardrails.py` (vocabulário, ILUSTRATIVO, orçamento, **marcação de tool vazada** — F7: corta do 1º resto de tag DSML em diante, o turno tenta um reparo sem tools (`INSTRUCAO_SEM_TOOL`) e só então usa `texto_seguro_tool(executadas)`; parâmetro inválido no meio da cadeia volta ao modelo como resultado da tool, uma correção por turno) · `conversations.py` · `second_opinion.py` (C27) · **`analysis.py`** (F5/F6: `criar(mode, max_replans)`, `carregar`, `avancar_status` CAS, `listar_findings`, `evidence_hash_de`; `analysis.analyses` na Tx A do Analista; `evidence_findings` quantitative/methodology/warning/missing + `cited_refs` `price_asof`/`index_asof`/`analysis_finding` na Tx B; status final/final_with_warnings/cancelled/blocked) · `eventos.py` (contrato SSE) |
| `agents/blocos.py` | **F11** — `blocos_de(code, payload, execution_id, max_blocos, max_pontos)`: output determinístico da tool → blocos `serie`/`barras`/`indicadores`/`progresso`/`tabela`/`citacao`/`faixa`/**`carteira`**/**`atencao`** com proveniência e nota; `blocos_de_execucoes(conn, [(code, id)])` reconstrói do `output_payload` (research). Goldens `tests/golden/blocos_*.json`; tetos em `AGENT_CONVERSATIONS` |
| `context/` | agente de Contexto (interno, F3): `schemas.py` (Pydantic estrito da saída do extrator; item inválido = descartado com motivo) · `extractor.py` (`processar_conversa`: conversa ENCERRADA → `extraction_run` running → LLM `extracao_contexto` json_object + 1 reparo → sinais/asserções/propostas em UMA transação de serviço, cada item em SAVEPOINT → run `succeeded`; nunca aplica) |
| `analysis/` | F6 — `config.py` (policy `ANALISE_RESEARCH`) · `dsl.py` (`AnalysisPlan`/`NodeSpec` estritos; `validar_plano` descarta nó inválido com motivo e propaga) · `compiler.py` (registry + `tools.tools` + família + `min_plan` + `params_model`; Kahn; grava `plans`+`tasks` em ordem topológica — o banco recusa dependência inexistente; plano inválido também vira versão) · `executor.py` (claim CAS, `timeout_task_s`, retentativas, `skipped` em cascata, `warning` p/ important/optional, findings por task na mesma Tx, retomada) · `budget.py` (custo real de `model_calls` × `analyses.budget`) · `planner.py` (prompt `analista.planner`; catálogo = `param_schema` filtrado; `json_object` + 1 reparo) · `report.py` (`evidence_hash`; guardrails ANTES do INSERT; mensagem na conversa com `cited_refs`; `cost_ledger 'analysis'`) · `pipeline.py` (máquina de status idempotente com advisory lock; replan até o teto do banco; `blocked`/`failed`) |
| `docs/` | **F13a** — camada documental: `copom.py` (parser PURO da API de dados abertos do BCB: índice → detalhe → HTML sem marcação → sha256; `DATASET='copom@N'` versiona o contrato de leitura) · `ingest.py` (grava como **pendente**, reusa `market.ingestion_batches` como lote imutável, e roda o matcher de vocabulário vetado sobre o texto de TERCEIRO antes de qualquer aprovação) |
| `market/` | **F13b:** `focus.py` (parser puro do OData de Expectativas do BCB; `baseCalculo` é CHAVE, não detalhe — 0 = 30 dias, 1 = 5 dias úteis, respondentes diferentes; `DATASET='focus@N'`) · F5 — `cotahist.py` (layout posicional B3, CODBDI {02,12,14 = ETFs}, `iter_registros` gerador, ZIP/TXT em streaming, `hash_arquivo`; `DATASET='cotahist@N'` versiona o contrato de leitura) · `sgs.py` (`url_serie`, `parse_sgs`, `janelas`; rede só em `buscar*`) · `ingest.py` (`abrir_lote` = no-op se o hash já é `succeeded`, `gravar_precos`/`gravar_indice` com `ON CONFLICT DO NOTHING`, `fechar_lote` + audit, `mapa_universo`, `cobertura_particoes`) |
| `jobs/` | `tasks.py` (tasks puras, `ctx={db,llm,policies,enfileirar}`: `extrair_conversa`, `varrer_encerradas`, `encerrar_inativas`, `expirar`, `varrer_execucoes_travadas`, `ingerir_cotahist`, `ingerir_sgs`, **`analisar`** (research, `_job_id=analise:{id}`), **`varrer_analises_pendentes`**, **`varrer_analises_travadas`**) · `worker.py` (Arq: `WorkerSettings`, cron — inclui SGS 06:30 e COTAHIST D-1 07:00 em dias úteis —, `REDIS_URL`; sem Redis o ciclo roda por `plexo context run` / `plexo mercado ingerir`) |
| `api/` | FastAPI: `POST /copilot/turns` (SSE ou `?stream=false`; 402 = paywall) · `GET/POST /conversations/*` (RLS → 404 p/ escopo alheio) · `GET /proposals` + `POST /proposals/{id}/confirm|reject` (403 terceiro do mesmo escopo, 409 estado; risco só orienta "refaça o suitability") · **`GET /analyses`, `/analyses/{id}`, `/analyses/{id}/report`** (RLS: 404 p/ escopo alheio; relatório `null` enquanto roda) · `POST /copilot/turns` aceita `mode: research` · `GET /health` · **F7:** `POST /auth/cadastro|login|logout`, `GET /auth/me`, `POST /auth/escopo`; `GET /agents`, `GET /chips[?agente=]`, `GET /conversations?limit=&status=`; mensagens com `id/content_json/cited_refs` + cabeçalho `conversa`. Identidade (`deps.py`): cookie `plx_sessao` → `identity.autenticar_sessao` sob serviço → membership; mutação com cookie exige `Origin` ∈ `CORS_ORIGINS` (CSRF); headers `X-Plexo-*` **só** com `AUTH_HEADERS_DEV=true` (o conftest liga). `CORSMiddleware` com credenciais. |
| `main.py` | `criar_app(db, llm, policies, settings)` — injeção p/ testes; sem args monta produção no lifespan; `app.state.settings` |
| `servir.py` | `python -m app.servir [--port] [--reload]` — sobe a API com loop **Selector** (no Windows `uvicorn app.main:app` cria ProactorEventLoop e o psycopg recusa: toda rota 500) |
| `engine/` | **F14–F19** — **`raiox.py`** (F19: o PRIMEIRO produtor da taxonomia de findings da migration 15 — 21 tipos semeados desde 2026 e zero linhas até aqui; metade pura `detectar()` travada por golden + metade que grava `findings`/`finding_observations`/`coverage_reports` e FECHA o que deixou de ser verdade; concentração medida sobre a carteira INTEIRA, não sobre a parte com emissor cadastrado; NÃO escreve `actions`, cujo bloco `passo` é instrução sobre o dinheiro) · `indicadores.py` (fórmulas puras) · `scores.py` (interpolação, peso ausente redistribuído) · `fundacao.py` (o produtor do gate D11) · `perfil.py` (run auditável) · **`simulacao.py`** (F17: Monte Carlo puro, σ_p = √(wᵀΣw), semente portátil) · **`elegibilidade.py`** (F17: risco só é elegível se aumenta materialmente a probabilidade E não piora o p5 além da tolerância; o veredito cita o número que decidiu) · **`projecao.py`** (F17: lê premissa versionada, um run por alocação, deriva `objetivo.probabilidade_sucesso`) |
| `cli.py` | `plexo prompts push|approve|check` · `policy set|approve` · `tools sync [--check]` · `seed dev` · **`auth definir-senha <uuid|e-mail> [--senha]`** (revoga sessões) · **`auth revogar-sessoes`** · `db check-roles` · `chat` · `context run [--conversa ID] | status` · `mercado ingerir …` · `mercado status` · **`chat --research`** · **`analise run [--id]` · `analise status [--id]`** · **`objetivo projetar [--semente] | status`** · **`raiox run | status`** · `seed conta-teste` · `worker` |

## Rodar (de `plexo-backend/`, interpretador `.venv\Scripts\python.exe`)

```bash
python -m app.cli chat "Quanto posso aportar por mês?" --agent assessor   # conversa real (DeepSeek)
python -m app.cli chat "o que é come-cotas?" --agent educador               # Educador: cita o slug do verbete aprovado
python -m app.cli chat "como foi o retorno da PETR4 em 2025?" --agent analista   # Analista: métrica com as_of/fonte/método (exige preços ingeridos)
python -m app.cli mercado ingerir --fonte sgs --indice cdi --de 2026-08-01  # SGS real → market.index_values (lote idempotente)
python -m app.cli mercado ingerir --fonte cotahist --ano 2025               # COTAHIST anual da B3 → market.prices (só o universo)
python -m app.cli mercado status                                          # cobertura: último preço por ativo, índices, lotes, partições
python -m app.cli chat "análise aprofundada da PETR4 em 2026" --agent analista --research   # cria a análise (mensagem 'em andamento')
python -m app.cli analise run                                             # planner → DAG → relatório (DeepSeek), sem Redis; idempotente
python -m app.cli analise status --id <analysis_id>                       # status, tasks, relatório
python -m app.cli context run                                             # encerra inativas → extrai a fila (DeepSeek) → expira → varre travadas
python -m app.cli context status                                          # fila e produção do Contexto
python -m app.cli worker                                                  # Arq de verdade (REDIS_URL no .env)
python -m app.servir --port 8000                                          # API (SSE em /copilot/turns; /auth/*) — Windows: NÃO usar `uvicorn app.main:app` direto
python -m app.cli auth definir-senha dev@teste.local --senha "…"          # senha do usuário de seeds para entrar pela tela
python -m pytest -q tests/test_f6_research.py                             # 227 testes no total (~65 min) — rode POR ARQUIVO (convenção 18)
python -m app.cli mercado ingerir --fonte focus --indicador Selic   # expectativas (Focus/BCB)
python -m app.cli docs ingerir --fonte copom --ultimos 6   # comunicados do Copom (pendentes)
python -m app.cli docs status --pendentes                   # fila de curadoria
python -m app.cli docs aprovar <uuid> --by <e-mail>         # aprova COM trilha
python -m app.cli seed persona     # cliente de demonstração (patrimônio completo, plano essential)
python -m app.cli tools sync --check && python -m app.cli prompts check   # drift zero
PLEXO_LIVE=1 python -m pytest -q tests/evals -k "rota_"                   # evals com DeepSeek REAL, por bloco (rota_/edu_/ass_/ana_) — relatório JSON em tests/evals/relatorios/
python tests/evals/consolidar.py tests/evals/relatorios/<saida>.json tests/evals/relatorios/<data>_*.json   # junta os blocos; imprime acerto por caso
```

## Deploy (EC2 + Docker, porta 80; frontend na Vercel) — 2026-08-26

Só a porta **80** da EC2 (`3.236.177.183`, Ubuntu 24.04, 2 GB + swap 2 GB) responde de fora. A API fica em HTTP na raiz
(`http://3.236.177.183/health`); o **frontend na Vercel** chega a ela por **rewrite server-side** do Next
(`/api/:path*` → `http://3.236.177.183/:path*`, `next.config.ts`; `NEXT_PUBLIC_API_URL=/api` resolve na origem da
página em `lib/api/cliente.ts`) — o navegador só fala HTTPS com a Vercel, mesma origem, cookie `Secure`+`Lax`. Variáveis
na Vercel: `NEXT_PUBLIC_API_URL=/api`, `API_PROXY_TARGET=http://3.236.177.183`. No servidor, `CORS_ORIGINS` precisa do
domínio da Vercel (o CSRF por `Origin` exige) — `deploy/env.prod.overrides`. Arquivos: `Dockerfile` (api/worker),
`docker-compose.yml` (**api** + **worker** Arq + **redis** + **caddy**, limites de memória), `deploy/Caddyfile` (80 →
api; 81 HTTPS pronto para quando o Security Group abrir), `deploy/env.prod.overrides` (ENV=prod, AUTH_HEADERS_DEV=false,
cookie, `DB_POOL_MIN=0`/`DB_POOL_MAX=2` — o Aiven tem `max_connections=20` (3 reservados) e api + worker abrem 2 pools cada; com 4 por pool os slots esgotavam (`PoolTimeout`, "remaining connection slots are reserved") —, CORS com a origem da Vercel) e `deploy/deploy.sh` (tar/ssh do backend, `.env` local + sobrescritas como `.env` do servidor —
nunca na imagem —, build → `alembic upgrade head` → `docker compose up -d`; mudança só no Caddyfile exige
`docker compose restart caddy`). O banco continua o Aiven; o worker roda crons e research.
Atualizar: `bash deploy/deploy.sh` (`--sem-env` mantém o `.env` do servidor; `--sem-migrar` pula o Alembic).

O passo do Alembic roda num container efêmero da imagem nova, **antes** de o código novo subir:
`docker compose run --rm --no-deps --user root -v "$PWD/.env:/srv/plexo/.env:ro" api python -m alembic upgrade head`.
O `.env` vai por bind mount porque `alembic/env.py` lê `DATABASE_URL` do **arquivo** `.env` (que não entra na imagem, por
`.dockerignore`), e `--user root` porque esse arquivo é 0600 do usuário do host enquanto o container roda como `plexo`
(uid 10001). Migrations são append-only: se o banco já está em `head`, o passo não faz nada.

### CI/CD (GitHub Actions) — 2026-08-26

`.github/workflows/deploy.yml` no repo do backend: todo push na `main` roda a verificação mínima deste README
(`validador.py` com erros **e** avisos zerados, `db_runner.py tests` nos dois papéis, `pytest -q`, `prompts check`,
`tools sync --check`) e, **só se tudo passar**, chama `deploy/deploy.sh` — o mesmo script do deploy manual, fonte única —
e exige `http://<host>/health` respondendo `"ok":true` (24 tentativas a cada 5 s). Também dá para disparar na mão
(`workflow_dispatch`). Segredos do repositório: `PLEXO_ENV` (conteúdo do `.env`; vira arquivo no runner porque
`db_runner.py`, `alembic/env.py` e o `Settings` leem por dotenv), `EC2_SSH_KEY` (o `.pem` inteiro) e, opcionais,
`EC2_HOST`/`EC2_USER` (padrão `3.236.177.183`/`ubuntu`).

O CI **nunca** roda `db_runner.py reset` (apagaria os 23 schemas do banco real, que é o mesmo de dev e de produção) nem
`PLEXO_LIVE=1` (evals com DeepSeek de verdade custam dinheiro — ficam sob demanda). Os testes são seguros contra o banco
vivo porque cada arquivo SQL termina em `ROLLBACK` e cada teste pytest roda numa transação revertida no fim. O
`concurrency` do workflow serializa os deploys sem cancelar o que está no meio.

## Regras que o código respeita (e onde estão provadas)
- Sem prompt aprovado por compliance, sem conversa (gate 19; `tests/test_f0_fundacao.py`, T15).
- Cota por plano/agente recusada na ESCRITA → paywall 402 (`test_f2_turno.py`, T16).
- Tool: família por agente (T18), plano mínimo e política aprovada (29, T51–T53) — gates do banco.
- Toda mensagem do agente aponta `tool_execution_id` + `model_call_id` + `cited_refs`; custo em `cost_ledger`.
- Vocabulário RCVM: reescrita → bloqueio; rodapé ILUSTRATIVO; comparação nunca vira "melhor".
- 2ª opinião: asserção `recomendacao_externa` (nasce `declarado`) + `decisions.records` com motivo material.
- Contexto: só conversa ENCERRADA (T22); evidência da mesma conversa (T23); asserção nasce
  declarado/inferido (C22a); likelihood bicondicional; proposta nasce `proposta` e só o próprio usuário
  confirma (T24b); risco aplicado exige suitability NOVO (T24c–e) — `tests/test_f3_contexto.py`.
  `extraction_runs` nasce `running` e vira `succeeded` por UPDATE (é o AFTER UPDATE que marca a conversa
  `processada`); descartes/falhas ficam em `audit.activity_log` (`context.extraction.*`).
- Educador (F4): só conteúdo aprovado E publicado (view da 30; T54–T57); sem verbete a tool devolve
  `encontrado=false` / `ToolConteudoIndisponivel` e o turno diz que não há material — nunca improvisa;
  nível de linguagem = parâmetro → asserção confirmada `nivel_conhecimento` → `EDUCACAO_PARAMS.nivel_padrao`;
  glossário não recebe rodapé ILUSTRATIVO (`emite_numero=False`), simulador/exemplo recebem; pergunta sobre
  ativo vira `encaminhar`; nunca produz `decisions.*` — `tests/test_f4_educador.py`.
- Analista (F5): séries de mercado append-only, sem data futura, lote idempotente por hash (31; T58–T62); tools leem
  só `price_date <= cutoff` (point-in-time) e o cutoff entra no `input_hash`; dado insuficiente ⇒ `suficiente=false`
  → evidência `missing` e resposta "sem base"; toda pergunta cria `analysis.analyses` (RLS por escopo) e findings
  com `tool_execution_id`; família (T18) e policy aprovada (29a) valem; nunca produz `decisions.*`; prompt diz
  "retorno passado não indica futuro" e "correlação não é causalidade" — `tests/test_f5_analista*.py`.
- Analista research (F6): execução de job é julgada pela conversa da análise (T63); research exige conversa e terminal não
  reabre (T64); tarefa só depende de nó já existente, pertence ao plano da própria análise, definição congelada, fecha com
  execução da própria análise (T65); versão de plano/relatório derivada, replan contado e limitado pelo banco (T66);
  relatório final exige `evidence_hash` + evidência material e é imutável (T67); RLS nas filhas; nó inválido nunca derruba
  o plano (descartado com motivo); orçamento estourado ⇒ `blocked` com texto seguro; nunca produz `decisions.*` —
  `tests/test_f6_research*.py`.
- Turno conversacional (F8, 2026-08-25): erro de tool volta ao modelo (até `max_erros_de_tool_por_turno`; depois texto
  fixo registrado); várias tool_calls por resposta são todas executadas e respondidas (uma `role=tool` por id);
  `encaminhar` usa o texto do modelo; histórico leva `[dados medidos: …]`; roteador devolve `resposta_curta` (passa pelo
  vocabulário) para saudação/meta/fora de finanças — sem conversa, sem cota; provedor fora → `erro provedor_indisponivel`
  (a pergunta fica na Tx A, nenhuma resposta inventada) — `tests/test_f8_turno_conversacional.py` (9). Prompts v2:
  Educador explica fora da base aprovada só com o rótulo "Explicação geral, não revisada por compliance:" e sem número;
  Assessor faz leitura qualitativa sem número quando não há tool; Analista recebe a cobertura de mercado; exceções de
  vocabulário (`custo de oportunidade`) em `vocabulario_proibido.yaml` — `tests/test_f8_prompts_v2.py` (13). Evals
  opt-in com o provedor real: `tests/evals/` (40 casos; `PLEXO_LIVE=1`).


## Convenções para continuar o desenvolvimento (lições das F0–F2 — leia antes de codar)

1. **Fluxo**: skill `plexo-implementacao` sempre — teste VERMELHO registrado antes da implementação;
   ao fechar, atualizar `ESTADO_DO_PROJETO.md` + `PLANO_AGENTES_IA.md §0` + este README.
2. **Testes nunca dependem do estado do banco de dev** (rodam nele, com rollback): prompt →
   `prompts_repo.reabrir_rascunho()+approve()` na transação; policy → `set_policy()` (nova versão
   draft) ou `approve_current()`; tool no sync → spec com código sintético (`dataclasses.replace`).
3. **Exceções do banco são traduzidas NA SAÍDA da sessão** — `pytest.raises(...)` envolve o
   `async with db.app_session(...)` inteiro, nunca só o `conn.execute`.
4. **Append-only por privilégio**: para `plexo_service`, UPDATE/DELETE em messages/model_calls/
   tool_executions dá `PermissionDenied` (o trigger `AppendOnlyViolation` é a 2ª barreira). Não
   tente "limpar" nada em teste — o rollback do conftest resolve.
5. **SQL fino nos repos**: enums com cast (`%s::agents.agent_code`), jsonb com
   `psycopg.types.json.Jsonb`, e `clock_timestamp()` (não `now()`) quando duas versões nascem na
   mesma transação (CHECK `effective_to > effective_from`).
6. **LLM**: sempre via `LLMClient`; toda chamada passa por `TurnBudget.reservar_chamada()` e
   `ModelCallRecorder.gravar()`; em teste, `FakeLLM([...])` roteirizado — nunca o provedor real
   (o `live` pula sem chave). JSON do LLM: `response_format json_object` + parse tolerante +
   1 reparo, e o LLM referencia mensagens por **seq**, nunca UUID.
7. **Ambiente Windows**: `asyncio.WindowsSelectorEventLoopPolicy` (conftest/cli/main já fazem);
   console cp1252 → `reconfigure(encoding='utf-8')`; o hook `rtk` quebra heredocs bash — scripts
   vão para arquivo e rodam com `python arquivo.py`; interpretador é `.venv\Scripts\python.exe`.
8. **Segredos**: jamais em expressão de `assert` (o pytest imprime o valor na falha), log ou echo.
9. **Suíte completa ~12 min** (transações reais na Aiven): durante o desenvolvimento rode o arquivo
   de teste alvo; a suíte inteira roda no fechamento da fase (pode ser em background).
10. **Config-first**: número de negócio novo = policy (`policy set` + `approve` se client-facing);
    a varredura AST dos módulos de tools recusa literais fora de {0, 1, 2, 12, 100}.
11. **Gate do banco dentro de um lote** (lição da F3): item a item em `async with conn.transaction():`
    (SAVEPOINT) e `except psycopg.Error` → o 23514 descarta só aquele item, a transação segue. A
    tradução de erro (`app/db/errors.py`) casa por mensagem do trigger ou `diag.constraint_name`.
12. **Jobs**: tasks puras em `app/jobs/tasks.py` com `ctx` injetado — nunca importe Redis nelas.
    Job global (ex.: `encerrar_inativas`) afeta tudo que estiver no banco de dev: teste prova sobre as
    SUAS linhas (`>= 1` + estado das linhas criadas), não sobre a contagem global.
13. **Tool sincronizada não se reescreve** (lição da F4): depois de `tools sync` no dev, qualquer mudança no
    fonte exige bump de semver (`SyncConflito`) — mesmo em desenvolvimento. Módulo por tool, para o
    `source_sha256` não arrastar bumps de vizinhas. **O sha é do fonte normalizado em LF** (lição de
    2026-08-26): hasheando os bytes crus, o mesmo commit dava sha diferente no dev Windows (CRLF, `core.autocrlf`)
    e no runner Linux — o `tools sync --check` do CI acusava drift eterno e pedia um bump falso. Sha do banco
    que casa com a forma CRLF do fonte atual = mesmo código: o `sync` corrige a impressão digital no lugar
    (relatório `sha corrigido (CRLF→LF, mesmo fonte)`), sem versão nova e sem tocar no `git_sha`.
14. **Dados de referência comitados em dev** (verbetes do Educador): testes usam slugs/tags próprios
    (`f4-*`) e uma policy com `conteudo_slug` apontando para eles — nunca para o que o seed publicou.
15. **Reset do banco apaga aprovações de dev**: depois de `db_runner.py reset && alembic upgrade head`, refaça
    `seed dev`, `prompts push/approve` (assessor, educador, router, extractor), `policy approve` das
    premissas client-facing e `tools sync --allow-dirty` — o ESTADO lista o que deve estar aprovado.
16. **Provedor em modo thinking**: o `reasoning_content` da mensagem com tool_calls volta ao provedor na
    síntese (senão 400); só a call executada é reenviada; se o modelo tentar chamar tool na síntese sem
    tools, a marcação vaza como texto — o guardrail `limpar_marcacao_de_tool` bloqueia.
17. **Pytest sozinho no banco** (lição de 2026-08-24): não rode `db_runner.py tests` nem `chat` real em paralelo
    com `pytest`. A rodada concorrente derrubou conexões (`psycopg.OperationalError`) e deixou um backend órfão
    `idle in transaction` segurando a fixture (`tools.tools`, `prompt_versions`, `policy_versions`) — a rodada
    seguinte travou 13 min esperando lock. Diagnóstico: `pg_stat_activity` + `pg_blocking_pids(pid)`; se o backend
    não tem processo python local correspondente, `pg_terminate_backend(pid)` (só desfaz a transação de teste).
18. **Verificação direcionada** (pedido do usuário, F5): durante a fase rode só o arquivo de teste alvo
    (`pytest tests/test_f5_analista_tools.py`), o SQL tocado (`db_runner.py tests <arquivo.sql> [papel]`) e
    `test_f2_turno.py` só depois de editar `turn.py`/`executor.py`. A suíte inteira fica para o fechamento da fase,
    **um arquivo por vez em foreground** (tarefas em background longas são mortas pelo ambiente).
19. **Fixture ingerida tem hash único por rodada** (F5): a idempotência por `file_hash` é do banco e o dev pode já
    ter ingerido a fixture original — `tests/test_f5_analista.fixture_cotahist_unica(tmp_path)` copia o arquivo
    com cabeçalho único. Séries antigas exigem `de`/`ate` explícitos: a janela padrão conta a partir do cutoff.
20. **Função de migration aplicada não se redefine** (F6): o validador recusa `CREATE OR REPLACE` de função criada em
    arquivo anterior; regra nova = trigger/função NOVOS (ex.: `tools.assert_execution_analysis` ao lado dos gates da 18/29).
    E `SELECT * FROM funcao(...)` dentro de corpo é lido como tabela pelo validador — use `SELECT (funcao(...)).* INTO`.
21. **Tudo que o LLM devolve vira versão** (F6): plano inválido também é gravado em `analysis.plans` com o
    `validation_report` — trilha e contagem de replan pelo banco. Testes que simulam "queda" do executor devolvem a task
    `running` a `pending` antes de retomar (é o que `varrer_analises_travadas` faz; o claim é por CAS).
22. **Reasoning conta como saída** (F6): em prompt longo o DeepSeek pode gastar todo o `max_output_tokens` pensando e
    devolver texto vazio. Chamada que produz texto client-facing longo precisa de teto próprio por policy
    (`LLM_BUDGETS.max_output_tokens_por_relatorio`) e de guarda contra saída vazia — nunca publicar vazio como `final`.
23. **Erro de tool é resultado, não fim de turno** (F8): `ToolParamsInvalid`/`ToolInsumoFaltante`/`ToolConteudoIndisponivel`
    voltam ao modelo como `{"erro": ..., "detalhe": ...}` na mensagem `role=tool` e ele redige a pergunta/negativa. Texto
    fixo só quando `max_erros_de_tool_por_turno` estoura — e sempre registrado em `guardrail_events`. Teste com FakeLLM
    roteiriza a 2ª resposta (a que redige) — um teste com uma única resposta passou a ser contrato antigo.
24. **Policy nova = seed + `policy set` no dev** (F8): chave nova de `AGENT_CONVERSATIONS`/`LLM_BUDGETS` entra em
    `seeds/dev.sql` (só vale em banco zerado) E via `policy set --file` + `approve` no dev vivo. O código lê com default
    igual ao comportamento anterior, para o banco antigo não quebrar.
25. **Medir antes de mexer no prompt** (F8): `tests/evals/` com `PLEXO_LIVE=1` dá a linha de base do provedor real
    (por bloco `-k rota_|edu_|ass_|ana_`, ~5 min cada; `consolidar.py` junta). Na varredura de 2026-08-25 a linha de
    base revelou que o Assessor estava quebrado no dev por policies sem aprovação (`FOUNDATION_THRESHOLDS`,
    `INCOME_HAIRCUT`, `PREMISSAS_FALLBACK` em draft após o reset) — não era limitação do agente.
27. **Gráfico nasce da tool, nunca do texto** (F11): representação = função pura do `output_payload`, golden-testada; o
    evento `bloco` sai logo após `tool_done` e o `content_json.blocos` guarda o mesmo objeto que a tela viu. Tool nova com
    número ⇒ mapeador em `blocos.py` + golden `blocos_<tool>.json`.
28. **Hash reproduzido tem UMA ordem canônica — e não é `created_at`** (lição do CI, 2026-08-26): o
    `evidence_hash` do relatório sai de `an.listar_findings`, que ordena por `(kind, id)`; `id` é uuidv7,
    total e estável. O teste ponta a ponta reconstruía o bundle por `(kind, created_at)` e o default da
    coluna é `now()` — **timestamp da transação**, igual para tudo que foi gravado na mesma Tx (aqui, 2
    evidências por `kind`). Com empate, quem desempata é o plano do Postgres: o hash batia no Windows e
    falhava no runner Linux, sem uma linha de código diferente. Teste que reconstrói hash precisa usar a
    MESMA ordem documentada de quem calculou; ordenar por tempo só serve onde há um registro por transação.

31. **ERRO em lote no pytest longo é conexão, não regressão** (F12): rodar dois arquivos pesados em
    sequência (~20 min) fez o Aiven derrubar a conexão e 24 testes viraram ERROR de fixture
    (`server closed the connection unexpectedly` / `consuming input failed`). Rodando o mesmo arquivo
    sozinho: 31/31. Antes de investigar código, REPITA o arquivo isolado — ERROR em lote (setup/teardown)
    é sintoma de conexão; FAILED em asserção é que é regressão. Vale para `chat`/evals longos também.

40. **A suíte era 99% rede, não CPU** (lição de 2026-08-27): 383 testes contra o Aiven levavam
    ~66 min porque cada comando custava **190 ms de ida e volta**; as suítes SQL levavam 26 s porque o
    `db_runner` manda o arquivo inteiro numa ida. Com um Postgres no próprio runner (`services:
    postgres`), a mesma suíte leva **33 s** — e as SQL, menos de 1 s. Para rodar assim na sua máquina:
    `docker run -d -e POSTGRES_PASSWORD=plexo -e POSTGRES_DB=plexo -p 5433:5432 postgres:18`, aponte a
    `DATABASE_URL` do `.env` para ele (com `?sslmode=disable`) e rode `alembic upgrade head` +
    `tools/preparar_ambiente.py`. **Faça backup do `.env` antes** — as três ferramentas (alembic,
    db_runner, Settings) leem a URL do ARQUIVO, não do ambiente.

41. **`pytest-xdist` não acelera esta suíte** (medido, não suposto): `test_f4_educador` levou 8m59s
    serial e **9m09s** com `-n 4`. A causa é o `conftest.abrir_conversa`, que faz `reabrir_rascunho` +
    `approve` na MESMA linha de `llm.prompt_versions` e a segura até o rollback — os workers se
    serializam no lock. É a convenção 17 vista de outro ângulo. Paralelizar exige antes tirar a
    escrita compartilhada das fixtures; sem isso, qualquer paralelismo (xdist ou matriz de jobs)
    esbarra no mesmo lock.

42. **"Aprovar todo rascunho" desliga gate em silêncio** (lição do preparo de CI): a primeira versão
    do `preparar_ambiente.py` aprovava toda policy `draft` e a suíte SQL ficou vermelha no **T1** —
    que prova justamente que run client-facing com política não aprovada é recusado, e depende de
    `DRIFT_BANDS` seguir em rascunho. A lista de aprovação é EXPLÍCITA (`POLICIES_CLIENT_FACING`), do
    ESTADO §5. Num sistema onde aprovar é ato de compliance, "aprova tudo" nunca é atalho inocente.

39. **Verificar só o arquivo tocado não alcança caminho compartilhado** (lição do CI, 2026-08-27): uma
    linha inserida com indentação errada em `turn.py` (fora do laço, não dentro) passou por toda a verificação
    da fase — os testes da F13b eram verdes — e quebrou turno SEM tool, que nenhum teste da fase exercitava.
    Pior: com duas tools, só a última era lida e a citação da primeira sumia sem erro. `turn.py`, `blocos.py`,
    `analysis.py` e `guardrails.py` são lidos por toda a suíte de turno: mexeu neles, rode `test_f2_turno`,
    `test_f4_educador` e `test_f8_turno_conversacional` ANTES de declarar pronto — não só o arquivo da fase.

35. **Chave natural incompleta é número errado em silêncio** (lição da F13b): o Focus publica, para a
    MESMA data e o MESMO horizonte, duas estatísticas — `baseCalculo` 0 (30 dias, 145 respondentes) e 1
    (5 dias úteis, 72). A chave natural da 35 não tinha essa coluna: as duas colapsavam e a ingestão
    guardava a que chegasse primeiro. Achado ao conferir "200 lidas, 100 gravadas" — o número que não
    fecha é o sintoma. Corrigido pela 37, com a coluna ANULÁVEL (as linhas anteriores têm base
    desconhecida e não são citáveis) e `coalesce(base_calculo, -1)` no índice.

36. **Mudou o que se LÊ, bumpe o layout** (F13b): depois da 37 o parser passou a extrair `baseCalculo`,
    mas a resposta do provedor era byte a byte a mesma — mesmo `file_hash`, lote `succeeded`, reingestão
    no-op. `LAYOUT_VERSAO` 1→2 (`DATASET='focus@2'`) é o que destrava. Vale para `cotahist` e `copom` igual.

37. **Saída de tool não passava por guardrail nenhum** (F13b): `vocabulario()` só via texto do LLM; output
    de tool, `blocos` e `cited_refs` chegavam ao cliente sem checagem. `guardrails.vocabulario_em_tool`
    varre as strings do payload e REGISTRA (`action_taken='registrado'`) sem derrubar a resposta — quem
    barra é a aprovação do documento no banco (34). Bloquear aqui apagaria resposta correta por causa de
    texto que um humano já aprovou.

38. **Bloco novo tem três travas, não uma** (F13b): a união é fechada dos DOIS lados (`blocos.py:TIPOS` e
    `tipos.ts`), o despacho em `Bloco.tsx` é cadeia de `&&` **sem exhaustiveness check** (tipo desconhecido
    desenha moldura vazia e o typecheck cala), e `temTabela` manda todo tipo não previsto para o
    "ver tabela", que chama `tabelaDe` e não sabe converter. Tipo novo entra nos três.

32. **Schema novo depois da 28 não herda nada** (lição da F13a): `docs` é o primeiro schema criado
    após `28_roles_grants.sql`, e a lista de schemas daquela migration é LITERAL — o `DO $$` que
    concede `USAGE`/DML/`ALTER DEFAULT PRIVILEGES` já rodou e não volta. O mesmo vale para o REVOKE
    derivado do catálogo (`28:71-88`), que fecha append-only: tabela nova em schema novo precisa dos
    dois à mão, no próprio arquivo. E três listas hardcoded fora do SQL têm de ser atualizadas junto,
    ou falham em silêncio: `tools/db_runner.py` `PROJECT_SCHEMAS` (senão `reset` não derruba o schema),
    `tools/validador.py` `SCHEMAS` (**sem isso o validador IGNORA todo `docs.*` e segue verde**) e
    `tools/gera_diagrama.py` (`META` + o `assert` de contagem).

33. **`ALTER TYPE ... ADD VALUE` cabe na migration, o USO não** (F13a): a família de tool `contexto`
    nasce na 34 e o enum aceita o valor novo dentro da transação — desde que nada o CASTE ali. Deu
    certo porque `agents.agent_definitions.allowed_tool_families` é `text[]`, e quem grava
    `tools.tools.family` é o `tools sync`, depois do commit. Se a migration precisasse inserir uma
    linha com o valor novo, seriam duas migrations.

34. **Texto de terceiro só é citável se aprovado** (F13a): `docs.documents` nasce `pendente`; aprovar
    exige revisor, trilha na mesma transação e ZERO termo vetado (CHECK `aprovado_sem_vocabulario_vetado`,
    T73–T77). A tool lê só a view de aprovados, como o glossário. É o único ponto do sistema em que
    texto externo é inspecionado ANTES de chegar ao cliente — o guardrail de saída (`turn.py:393`) só
    vê texto do LLM, nunca output de tool.

29. **Contagem global em teste SQL é bomba-relógio** (lição da F12): o banco de dev é compartilhado e
    ACUMULA dado commitado. `expect_count($sql$SELECT 1 FROM wealth.accounts$sql$, 2)` passava porque a
    tabela estava vazia; o seed da persona commitou duas contas e o T43 caiu. Sob `plexo_app` a RLS já
    filtra pelo GUC e a contagem global é inofensiva — o perigo é sob **papel de serviço com
    `app.role='service'`** (ou administrador), onde `core.is_service()` é verdadeira e nada filtra.
    Asserção assim tem de escopar pelos ids da própria fixture. O `validador.py` passou a acusar o caso
    (aviso ⇒ falha no CI), e ele só olha a conjunção papel+intenção que a `core.is_service()` exige:
    `plexo_service` com `app.role='user'` continua preso ao GUC e não é acusado.

30. **Seed de demonstração mora em escopo próprio** (F12): `seeds/persona.sql` usa `0fe0a000-…`, nunca o
    `0de0a000-…` do dev — assim nenhum teste, golden ou eval existente muda de valor. Depois de
    `db_runner.py reset`, refazer também o `seed persona`, senão `tests/test_f12_persona.py` falha e os
    casos `pers_*` dos evals se pulam.

26. **Stream reconcilia, nunca confia** (F9): o que o cliente viu em `Delta` é comparado ao texto final depois dos
    guardrails — prefixo igual ⇒ `Delta` do resto (rodapé); diferente ⇒ `Replace`. Texto que acompanhou tool_call ⇒
    `Replace("")`. Teste de turno que junta só os `Delta` está errado desde a F9: simule a tela (`_visto` em
    `test_f9_streaming.py`). `FakeLLM(trechos=n)` exercita o caminho de stream; `LLMSemStream` o antigo.

43. **Preço ajustado é leitura, não dado** (F22): o `cum_factor` de uma data MUDA quando um provento é
    anunciado depois dela. Gravá-lo em `market.prices` seria reescrever série — o que o T58 proíbe. Ficam
    as views `market.v_fatores_ajuste` (fator por evento, piecewise-constante) e `market.v_precos_ajustados`.
    **Todo cálculo de retorno lê a segunda, nunca `market.prices` cru**: o coletor mediu a diferença na
    PETR4 de 2024 e ela inverte a conclusão — −4,21% no bruto contra +13,35% no ajustado.

44. **Migration que muda a FORMA de um nome quebra quem lê o nome** (F22): a 61 criou partições ANUAIS
    (`prices_AAAA`) ao lado das mensais, e `app/market/ingest.py::cobertura_particoes` casava só
    `prices_AAAAMM`. As anuais seriam ignoradas **em silêncio** e `mercado status` diria que a base começa
    em 2016 com trinta anos de pregão carregados — nenhum teste falharia. Antes de criar objeto com nome
    fora do padrão vigente, procure o padrão antigo em `app/` (e no `tools/`).

45. **Gate de disco que mede `pg_database_size` não protege nada** (F22): ele não conta o WAL. Um
    backfill de 2,9 milhões de linhas passou pelo gate a cada ano carregado e mesmo assim encheu o
    disco do plano free da Aiven (~1 GB), que pôs o serviço em `default_transaction_read_only` e
    **derrubou a escrita em produção**. Antes de qualquer escrita em massa: confira o TAMANHO DO
    PLANO (`max_wal_size` é o indício no servidor — 49 MB significa disco pequeno), e trate o teto
    seguro como centenas de MB, não gigabytes.

46. **Para desfazer carga em série append-only, `TRUNCATE` de partição — nunca `DELETE`** (F22): o
    trigger da 31 recusa DELETE, e desabilitá-lo num banco compartilhado com produção não se faz.
    `TRUNCATE` é DDL, não dispara trigger de linha, libera espaço na hora e PRESERVA a partição, de
    modo que a cobertura declarada pela migration continua verdadeira (o T61 conta partições). Só
    vale para partição que contenha EXCLUSIVAMENTE o dado a remover — conferir antes, linha a linha.

47. **Teste cujos casos você inventou não prova leitura de arquivo** (F22): o regex de ticker passou
    com `PETR4` e `BOVA11`, os dois que eu escolhi, e recusava `B3SA3` no arquivo real. O mesmo vale
    para os CODBDI: BDR não está no 02, e o 14 não separa ETF de FIAGRO. Ao ler formato de terceiro,
    **os casos de teste saem de uma amostra do arquivo**, e o que for recusado é contado e reportado.

48. **Campo novo numa tool com golden exige editar as DUAS seções do golden** (F22): `resolvido` e
    `esperado`. `test_golden_master` faz `Resolvido.model_validate(dados["resolvido"])`, então um
    campo novo no Resolvido quebra com `ValidationError` — e o de blocos NÃO valida modelo nenhum
    (recebe o dict cru), então passa alegremente com o golden malformado. Foi o que aconteceu:
    coloquei `amostrado` no topo do arquivo em vez de dentro de `esperado`, `test_f11_blocos` deu 47
    verdes e só a suíte longa acusou, dezesseis minutos depois. Ao mexer em tool com golden, rode
    `pytest tests/test_f5_analista_tools.py -k golden` — são 0,3 segundo.

## F14 — contexto que se atualiza e perfil do cliente (2026-08-29)

`app/context/{catalogo,propostas,aplicador}.py` e `app/engine/{indicadores,scores,perfil}.py`.

**Três convenções que valem para quem continuar:**

1. **Tool que o modelo chama no turno é READ-ONLY.** O executor devolve output de cache sem executar
   a função quando o `input_hash` repete; uma tool que escrevesse seria silenciosamente pulada na
   segunda chamada idêntica. A escrita fica no orquestrador (Tx B do `turn.py`), idempotente por
   `proposal_hash`. Vale para qualquer efeito colateral novo, não só para propostas.
2. **Array de domínio (`core.slug[]`) SEMPRE com `::text[]` na leitura.** Sem o cast o psycopg não
   conhece o OID e devolve `'{a,b}'` como texto — `list()` quebra em caracteres e a conta dá zero
   *em silêncio*. Custou dois bugs na F14 (`v_fact_coverage.faltando` e
   `indicator_definitions.required_fact_keys`).
3. **Indisponível não é zero.** Indicador sem insumo grava `is_unavailable` com motivo, e o peso dele
   é redistribuído entre os presentes (a cobertura cai). Imputar zero diria ao cliente que ele vai
   mal onde ninguém mediu — é a diferença entre não saber e saber que está ruim.

**Para acrescentar um fato:** migration nova com a linha em `context.fact_definitions` (o gate C38a
recusa asserção incoerente com o catálogo). **Para acrescentar um indicador:** linha em
`diagnostics.indicator_definitions` + função com o mesmo nome do `formula_ref` em
`app/engine/indicadores.py` + curva em `CLIENT_SCORES`. Sem a fórmula, o motor grava
`motor_ausente` em vez de silêncio.

## F15 — derivação, janela operável e perguntas (2026-08-29)

`app/context/derivacao.py`, `app/agents/perguntas.py`, `app/engine/perfil.py` (passou a ler
`context.v_fact_operavel`).

**Duas janelas, e é importante não confundi-las:**

| view | quem lê | o que mostra |
|---|---|---|
| `context.v_fact_current` | o AGENTE (prompt, tools, `context_pack`) | só `confirmado` pelo cliente |
| `context.v_fact_operavel` | o MOTOR (`engine/perfil.py`) | `confirmado` + `inferido`, confirmado na frente |

Ao escrever código novo, a pergunta é "isto vai ser MOSTRADO como verdade do cliente ou CALCULADO?".
Mostrar → `v_fact_current`. Calcular → `v_fact_operavel`.

**Três convenções da onda:**

1. **Derivar não é confessar.** Tudo que a derivação grava nasce `inferido` / `inferencia_motor`,
   com a confiança descontada por `CONTEXT_FACT_CATALOG.fator_confianca_derivado`. Nunca
   `confirmado` — o gate C22a vale para o motor como vale para o LLM.
2. **`None` ≠ `[]`.** Em `Bruto`, `None` é "nunca consultado" e `[]` é "consultado e não há". Com
   `[]` como default, um objeto não populado afirmaria "saldo devedor zero" — a mesma falha que a
   migration 44 corrigiu na lacuna de seguro. Teste: `test_insumo_ausente_nao_vira_zero`.
3. **Capacidade não é comportamento.** Superávit do orçamento não vira `fluxo.aporte_mensal`: é por
   ele que `destino.esforco_requerido` divide, e trocar um pelo outro faria todo plano parecer
   factível. O que não dá para derivar honestamente vira pergunta.

**Para acrescentar uma derivação:** leitor em `coletar` (reusando `context_pack` quando houver),
mapeamento na função pura `derivar` e o `fact_key` correspondente já cadastrado no catálogo. Se o
número exigir premissa, ela vai para política — nunca para o Python.

## F16 — a rede de fidelidade, e o gate que não tinha produtor (2026-08-29)

`tests/test_f16_propriedades.py`, `tests/test_f16_personas.py`, `app/seeds/personas.py`,
`app/engine/fundacao.py`.

**A lição transferível, e ela não é sobre este motor.** A regra D11 tinha QUATRO camadas de
proteção — CHECK em `portfolio_scores`, trigger em `client_scores`, teste de sabotagem SQL em
três arquivos e teste de unidade em Python — e todas testavam o **gate**. Nenhuma perguntava
quem escrevia `diagnostics.foundation_status`. A tabela existia desde a migration 06, vazia, e
a regra mais importante do produto nunca disparou.

> **Para toda tabela que existe para ser LIDA por uma decisão, pergunte quem a escreve.**
> Gate sem produtor não falha: ele passa, sempre, e todos os testes ficam verdes.

**Três hábitos que esta onda deixou:**

1. **Propriedade antes de exemplo.** `taxa_poupanca == 0,32` confere o número que o autor
   esperava contra o número que o autor escreveu. `piorar nunca melhora o score` e `insumo
   opcional que muda o resultado não é opcional` valem para os 14 indicadores de hoje e para
   os que vierem — a parametrização lê o catálogo do banco, não uma lista à mão.
2. **Unidade é a classe de erro mais silenciosa.** `market.index_values` guarda percentual,
   `core.rate_annual` guarda fração, e comparar os dois fez um rotativo a 400% ao ano parecer
   mais barato que o CDI. Toda travessia de fronteira de unidade merece função nomeada e
   propriedade própria — `taxa_anual_em_fracao` é o modelo.
3. **Ler o diagnóstico é etapa, não conferência.** Das sete correções da F16, três vieram de
   propriedade e quatro de LER o que o motor disse sobre uma persona. Nenhum teste substitui
   essa leitura, e o golden existe justamente para que ela só precise acontecer uma vez por
   mudança.

**Para acrescentar persona:** um `Arquetipo` em `app/seeds/personas.py` (quinze linhas), depois
`plexo seed personas` e `pytest tests/test_f16_personas.py` — o golden nasce e é conferido à mão
antes de versionar.

---

## F17 — probabilidade de sucesso das metas (2026-08-29)

**Migrations 48–50 · `app/engine/{simulacao,elegibilidade,projecao}.py` · tool
`planejamento.simulacao_objetivo` · CLI `plexo objetivo projetar|status`**

### A separação que organiza os três arquivos

| arquivo | conhece | não conhece |
|---|---|---|
| `simulacao.py` | matemática: σ_p = √(wᵀΣw), lognormal, percentis | banco, política, RCVM |
| `elegibilidade.py` | a regra do §4 e como escrevê-la em português | banco, Monte Carlo |
| `projecao.py` | de onde vem cada insumo, o que gravar, o que fazer com ausência | matemática |

`simulacao.py` e `elegibilidade.py` são puros e travados por propriedade + âncora fechada
(`tests/test_f17_simulacao.py`); `projecao.py` é testado contra o banco real
(`tests/test_f17_projecao.py`).

### Ordem do pipeline — e ela passou a importar

```
perfil derivar      → renda.mensal_liquida, despesa.total_mensal, objetivo.prazo_meses, …
objetivo projetar   → LÊ os dois primeiros · grava goal_projections
                      · ESCREVE `objetivo.probabilidade_sucesso`
perfil calcular     → indicadores e scores (lê `destino.probabilidade_meta`)
```

A dependência é de **mão dupla** e só esta ordem satisfaz as duas pontas. A primeira versão
punha a projeção na frente, lembrando que ela escreve e esquecendo que ela lê — e passou,
porque o banco de dev já tinha `renda`/`despesa` persistidos de execuções anteriores. Num banco
limpo a projeção saía `aporte_desconhecido` para toda persona, e o CI caiu inteiro. **A
migration 50 tem essa frase invertida no cabeçalho; ela está aplicada e não se edita — vale o
que está aqui.**

Quem calcular o perfil sem projetar antes encontra o indicador **indisponível, dizendo qual
fato falta** — que é o comportamento certo, não uma falha. O golden das personas roda nessa
ordem justamente para que ela continue sendo a ordem real.

### Quatro defeitos que esta onda produziu, e o que cada um ensina

1. **`jsonb` não preserva ordem de chave.** `list(payload["alocacoes"])` devolvia
   `arrojada, balanceada, conservadora` — o Postgres ordena por tamanho e depois por bytes.
   A caminhada da elegibilidade tomava a carteira MAIS ARROJADA como base e ficou verde
   fazendo o contrário do escrito. **Nunca dependa da ordem de chaves de um `jsonb`.** A
   correção não foi declarar a ordem numa lista (que poderia discordar dos pesos sem ninguém
   perceber) e sim DERIVÁ-LA da volatilidade — a ordem passou a ser impossível de divergir
   da carteira que ela ordena.
2. **Uma tolerância zero não é a escolha conservadora: é um veto universal.**
   `piora_maxima_do_p5 = 0` vetava risco em toda meta, porque mais risco quase sempre baixa
   o p5 — é o que "mais risco" significa. Uma regra que dá sempre a mesma resposta não é
   regra. Achado RODANDO, não lendo (migration 49).
3. **Fixture de teste envelhece com regra nova — e isso aconteceu TRÊS vezes nesta onda.**
   (a) três arquivos SQL quebrados pelo CHECK da migration 43, que foi o CI vermelho;
   (b) o T102 provando uma regra que as migrations 44 e 47 já haviam mudado — passava sem
   exercitar nem o mínimo de duas famílias críticas nem a margem;
   (c) `test_f14_perfil.py::test_formulas_dos_indicadores`, que ainda esperava a rigidez
   dividida pela renda MÉDIA, um insumo que a 47 trocou pelo piso.
   **Regra nova obriga a rodar a suíte inteira — SQL e pytest —, não só o arquivo novo.** As
   três só apareceram no fechamento; nenhuma teria aparecido na verificação direcionada.
4. **Teste que depende do que sobrou de outra execução só ainda não falhou.** Duas formas
   disso apareceram no mesmo fechamento:
   (a) `test_projecao_grava_o_que_calculou` contava as linhas de `goal_projections` por
   `goal_id` e passou até o dia em que um smoke de CLI deixou projeções persistidas no banco
   de dev — aí eram 9, não 3. **Filtre pelos identificadores que a PRÓPRIA execução criou.**
   (b) o golden das personas congelava a **confiança**, que é o produto da confiança gravada
   pelo decaimento por FRESCOR — e frescor é distância até `now()`. Enquanto `aplicar` criava
   as asserções dentro da transação do teste elas nasciam com zero dia e o número era estável;
   a partir do momento em que `plexo seed personas` as persistiu no dev, ele passou a
   escorregar sozinho (0,700 → 0,694 em três horas). **Golden não congela número que é função
   do relógio** — a confiança saiu do snapshot, e o decaimento continua testado exatamente,
   sem relógio, em `test_f14_perfil.py`.
5. **O veredito precisa saber quando a pergunta é outra.** Com alvo inalcançável, discutir
   qual carteira "se sustenta" esconde a única alavanca real. O motor passou a dizer: "o que
   move este plano é o aporte ou o prazo, não o risco".

### O que continua em aberto, e é decisão de gente

- **`PLEXO_BASE v1` e `SIMULACAO_METAS v3` são rascunho.** O gate C48c impede que rascunho
  vire número na tela. Aprovar é decisão de compliance com nome e data.
- **`score.destino` continua indisponível para as seis personas.** A probabilidade sozinha dá
  cobertura 0,45, abaixo do mínimo de 0,50 da família — faltam `fluxo.aporte_mensal` e
  `destino.idade_aposentadoria`. O primeiro é DERIVÁVEL do que a projeção já calcula (renda −
  despesa), e derivá-lo é a próxima correção certa; mexer no `min_coverage` seria afrouxar o
  limiar para caber o resultado.
- **A normal subestima a cauda.** Declarado na `metodologia`, na `limitacao` da tool e no
  rodapé do CLI. t-Student ou bootstrap histórico é melhoria real e não entrou aqui.

### Conta de demonstração (`plexo seed conta-teste`)

`app/seeds/conta_teste.py` — **Helena Ferraz Antunes**, `helena_completa@teste.local`, plano
**`advanced`**. É a única conta do repositório em que as cinco famílias saem com nota, e existe
para exercitar o produto pela tela.

| por quê | |
|---|---|
| fora de `ARQUETIPOS` | é uma conta para MEXER à mão; se fosse golden, o primeiro teste manual quebraria a suíte e a resposta seria "regrave o golden" — que é como um golden morre |
| plano `advanced`, não `wealth` | `wealth` é `is_purchasable = false` e `requires_cvm_authorization = true` (migration 03): conta de teste nele simularia um produto que a Plexo não pode vender |
| dois objetivos ativos | é o que exercita a regra da F17 "a MENOR probabilidade entre os objetivos ativos" — nenhuma persona tinha mais de um |
| fatos declarados | `destino.idade_aposentadoria`, `fluxo.aporte_mensal` e os dois de comportamento: sem eles Destino e Comportamento ficam mudos em TODAS as personas |

Criar: `plexo seed conta-teste` (roda derivar → projetar → calcular no fim).
Senha: `plexo auth definir-senha helena_completa@teste.local` (prompt oculto, com confirmação).

**Quatro defeitos que esta conta expôs — e dois deles corrompiam dados com o tempo:**

0. **`objetivo.prazo_meses` virava conflito permanente.** Ele é uma contagem regressiva, era
   derivado em `dias / 30,4375` e mudava TODO DIA (23,10 → 23,06 → 23,03). A derivação
   comparava com um `0.005` cravado no código, gravava asserção nova a cada execução, e o
   gate C38c marcava a nova e a anterior como `conflitante` — as duas fora da janela
   operável. **Duas execuções bastavam para o fato sumir para sempre**, levando junto o
   `destino.esforco_requerido`, sem erro em lugar nenhum. Duas correções: o prazo passa a ser
   derivado em MESES INTEIROS, e o limiar de regravação passa a vir do **catálogo**
   (`materiality_abs`/`materiality_rel`, o maior dos dois), que já dizia "3 meses" e ninguém
   lia. Número mágico contra config-first não é estilo: aqui ele apagava um indicador.
   Regressão em `test_f15_derivacao.py::test_o_limiar_de_regravacao_vem_do_catalogo`.

0b. **O diagnóstico dependia de haver CDI ingerido.** Sem CDI, `fundacao.py` mede dívida cara
   contra o piso do spread — e QUALQUER dívida realista fica cara, Fundação crítica, todas as
   famílias sem nota. É o motor se recusando a concluir "não há dívida cara" por ignorância,
   e está certo; o problema era o golden congelar um lado dessa moeda. `test_f16_personas.py`
   passou a **fixar o CDI dentro da transação** e a recusar rodar sem ele. `seed conta-teste`
   avisa quando falta.

**E dois no construtor de personas:**

1. **`plano` era campo sem produtor.** Existia no `Arquetipo` desde a F16, quatro personas se
   declaravam `essential`, e **nada escrevia `billing.subscriptions`** — então
   `plano_do_escopo` devolvia `free` para todas e as tools com `min_plan='essential'`, incluindo
   `planejamento.simulacao_objetivo`, nunca chegavam ao modelo. Mesma armadilha do
   `foundation_status`: ninguém tinha perguntado quem escreve.
2. **`stability='fixo'` com parte variável.** A regra era `variavel > 0.5 → 'variavel'`, o que
   quebrava no primeiro caso realista de CLT com bônus (20% variável): o banco recusa `fixo`
   com `variable_share > 0` (CONSTRAINT `fixed_has_no_variable_part`, migration 24). Agora
   `fixo` é só quando a parte variável é ZERO. Nenhum arquétipo existente muda.

**Para acrescentar uma classe de ativo às premissas:** uma linha em `market.class_assumptions`
e **mais N−1 correlações** — o C48b confere a conta na aprovação e recusa a matriz aberta. A
fricção é intencional: correlação faltando seria lida como zero, e zero subestima o risco da
carteira inteira.

---

## F18 — o que um teste real de ponta a ponta mostrou (2026-08-30)

**Migrations 51–52 · `AVISOS_CLIENTE` em `blocos.py` · bloco `faixa` · conversa que reabre**

Um teste manual do produto inteiro produziu um relatório melhor que qualquer suíte deste
repositório. Sete defeitos, todos com arquivo e linha, e três deles faziam a plataforma dizer
coisa falsa ao cliente.

### As três mentiras

| o cliente lia | a verdade | causa |
|---|---|---|
| chance de **0,4%** | **37,4%** | fração enviada com formato de pontos percentuais |
| faculdade com mediana de **R$ 1,96 mi** para alvo de 600 mil | o mesmo dinheiro em dois objetivos | a projeção dava a sobra INTEIRA a cada meta |
| capacidade de aporte **R$ 26.000** | sobra ~R$ 9.200 | renda comprometível apresentada como dinheiro livre |

### A lição que se repete: o número certo com o nome errado

`committable_brl` sempre significou "renda com que dá para contar". Chamá-lo de *capacidade de
aporte* não mudou o número — mudou a pergunta que ele parecia responder, e a resposta virou
falsa. **Quando um número é reaproveitado, o que precisa ser conferido é o nome.**

### Onde a tradução para o cliente acontece

`AVISOS_CLIENTE` em `app/agents/blocos.py` é a fronteira: as tools emitem SLUG (estável,
comparável, testável) e o bloco traduz. **Slug sem frase não é renderizado** — nem aqui nem no
front, que tem uma segunda barreira (`ehSlug` em `Bloco.tsx`). O `replace("_", " ")` que
existia produzia "aporte necessario acima da capacidade": meia tradução, em vermelho, com cara
de defeito.

Orientação dirigida ao MODELO vive em campo separado (`orientacao_ao_modelo`) que `blocos.py`
não copia. Antes morava em `avisos`, e o cliente lia *"diga isso ao cliente"* na tela.

### O turno que media e não redigia

A causa não era o modelo: era orçamento. `sintese_vazia` está gravado três vezes em
`agents.guardrail_events`, sempre nos turnos com mais medições. Com um provedor que raciocina,
o `reasoning_content` conta como saída, e quatro chamadas de tool consumiam os 6.000 tokens do
turno antes da chamada que escreve.

**Quem pagava era sempre a redação, porque ela é a última** — então quanto melhor a pergunta,
maior a chance de não haver resposta. É o pior formato possível para um defeito de produto.
`reserva_para_sintese_tokens` (migration 51) é um piso intocável; `tokens_para(purpose)` no
`TurnBudget` é quem o respeita.

### Conversa que continua

Escrever numa conversa encerrada reabre. Isso exigiu tornar a extração de contexto
**incremental** (migration 52: o run registra até que `seq` leu) — sem isso, tudo o que fosse
dito depois da reabertura ficaria invisível para o contexto, em silêncio.

### O bloco `faixa`

A distribuição contra o alvo. A comparação entre "valor mais provável" e "alvo" virou POSIÇÃO:
ou o traço está antes da linha, ou depois. O guardrail do §8 passou a ser estrutural — a faixa
não consegue desenhar a mediana sem desenhar o piso, porque são extremos do mesmo traço.

Duas armadilhas de desenho resolvidas: **piso de largura** para a banda não sumir quando o alvo
está muito longe (o caso interessante), e **rótulo que se alinha pela borda** perto das pontas,
que era o que cortava "R$ 600.000,00" pela metade.

## F19 — a carteira aberta, e o produtor que faltava (2026-08-30)

### O defeito que abriu a fase

"Devo vender alguma das minhas ações?" na conta de demonstração devolveu **"não há posição
registrada no escopo"**. Não era o agente errando: `wealth.holdings_snapshots` estava vazia
para aquele escopo. O que era grave é o que acontecia ao lado disso — o `context_pack`
injetava no prompt "Patrimônio — investível: R$ 780.000,00", vindo de `estate.v_net_worth` ←
`wealth.portfolio_snapshots`. **Duas fontes para o mesmo fato, uma populada, e nada no banco
obrigando as duas a concordarem.** O modelo teve de administrar a contradição sozinho, e não
havia resposta certa a dar.

A migration 53 fecha isso com a regra mais simples possível: **havendo detalhe, o agregado é o
detalhe**. A recíproca não vale — agregado sem detalhe continua válido, que é como vivem as
seis personas da F16.

### `diagnostics.findings` tinha zero linhas

Terceiro caso do mesmo padrão nesta base, depois de `foundation_status` (F16) e do campo
`plano` do arquétipo. A taxonomia de 21 tipos está semeada desde a migration 15 — e são
literalmente os cartões de "pontos de atenção" de qualquer produto do gênero. `findings` tem
`priority_score` gerado, `actions` tem o CHECK dos cinco blocos, `v_action_queue` ordena a
fila, `gate_reveals` guarda a revelação do paywall, `engine.run_kind` tem `'raiox'` desde a
02, e `v_issuer_concentration` consolida conglomerado por `parent_issuer_id`. Nada nunca
escreveu uma linha.

A migration 54 faz a lição virar estrutura: **`implemented_at` deixou de ser documentação e
virou condição de existência**. Um tipo só produz finding depois que alguém escreveu o
produtor e declarou isso numa migration. O catálogo passou a dizer a verdade sobre si mesmo, e
14 dos 21 tipos hoje se declaram sem produtor — de forma explícita, imposta pelo banco.

### Os cinco defeitos que só apareceram RODANDO

1. **ITUB4 voltou como coberta pelo FGC.** A cobertura é do INSTRUMENTO (CDB, LCI/LCA,
   poupança), não do emissor. Lendo só `issuers.fgc_covered`, uma ação de banco entrava no
   teto de R$ 250 mil e inflava a exposição coberta — o alerta dispararia sobre um número que
   não existe. O `tools sync` então recusou reescrever a versão publicada e exigiu o bump,
   que é o registro auditável do art. 17 funcionando na prática.
2. **O achado CRÍTICO aparecia por último.** `priority_score` = (impacto × confiança) /
   atrito, e concentração não tem impacto em reais por ano: com o campo nulo o score cai a
   zero, e 45% da carteira num emissor só ficava atrás de um fundo de R$ 240/ano. Inventar um
   impacto teria sido pior. A APRESENTAÇÃO passou a ordenar por gravidade, com o score como
   desempate — que é onde ele funciona bem.
3. **Caixa parado não disparava** porque a regra comparava o caixa contra o SALDO da reserva
   em vez da REQUERIDA. Invertido: reserva já cheia é justamente a condição que transforma o
   resto do caixa em dinheiro parado.
4. **O custo de fundo nunca disparava**: o motor lia `taxa_adm_referencia_por_classe`, chave
   que eu inventei, em vez de `referencia_taxa_adm_aa`, que é a que `produto.custo_fundo` já
   usa. `.get` devolveu vazio e não houve erro nenhum.
5. **O gate de vocabulário recusou o prompt v8** por "garantido", em "limite garantido pelo
   FGC". Trocado por "coberto" no prompt e na copy — e o plural "garantidos" escapava do
   detector por casamento de palavra inteira, que é exatamente por que não devia ficar.

### A unidade do impacto

`impact_brl_year` recebe custo por ano (fundo caro), valor exposto (FGC) e valor parado
(caixa). São grandezas diferentes na mesma coluna, e é a coluna que gera `priority_score`. Em
vez de forçar tudo a virar custo — o que exigiria uma premissa de retorno que este motor não
tem —, cada achado declara `unidade_do_impacto` na evidência, e a tela escreve "por ano", "sem
garantia" ou "parados". Sem isso ela diria "R$ 20.000 por ano" sobre uma quantia que não é
anual nem é custo.

### Onde a frase do cliente é escrita

Em `atencao.py`, num dicionário, e não pelo modelo. A razão é concreta: a lista de vocabulário
proibido tem doze termos, e **"vender", "venda" e "melhor" isolados não estão nela** — o que
está é `venda já`, `melhor fundo`, `melhor investimento`, `melhor opção`. Quem barra "esta
posição você deveria reduzir" é a regra 4/5 do prompt, que é qualitativa e não tem detector
automático. Um alerta é justamente o texto que puxa o modelo para o imperativo: "concentração
alta em X" pede, gramaticalmente, um "então faça Y". O modelo lê o achado e o interpreta; não
o redige.

## F21a — fundações do onboarding obrigatório (2026-08-31)

Migration 59 + `app/onboarding/` + `app/api/routes/onboarding.py`. O achado que abriu a fase: o
schema previa o onboarding desde a migration 01 (`identity.user_profiles` com trilha A/B, passo e
carimbos; `analytics.onboarding_steps` com o funil nomeado; `identity.suitability_assessments`) e
**nada nunca escreveu nelas** — o quarto caso do padrão "gate sem produtor". A F21a entrega o
produtor e sobe os invariantes para o banco: conclusão exige suitability vigente + fatos-núcleo
confirmados (policy `ONBOARDING_NUCLEO`, fallback no trigger como `FAMILY_LIMITS`); suitability
exige `scope_id` (C59b — sem ele a RLS `scope_isolation` rejeita o INSERT sob `plexo_app` em
silêncio) e é imutável fora da supersessão; o carimbo de conclusão não regride.

O que vale reter para as próximas fases:
- **Fato de formulário**: nasce `declarado` + UPDATE `confirmado` na MESMA transação
  (`app/onboarding/escrita.py::confirmar_fato`), com `subject_kind`/`attribute`/`unit`/faixa lidos
  de `context.fact_definitions` — o catálogo é a fonte; `fluxo.aporte_mensal` tem
  `subject_kind='despesa'` e `attribute` nunca é o sufixo do `fact_key`.
- **`source='formulario'`** (vence a precedência DECLARADA); `'onboarding'` fica reservada para a
  extração de IA pré-confirmação (F21b).
- **Questionário config-first**: perguntas, pontos, limiares e validade em `SUITABILITY_QUESTIONARIO`
  (draft — entra na lista de aprovação client-facing antes de cliente real); `pontuar()` é pura com
  golden no pytest.
- **`e.errors()` do Pydantic v2 não é JSON-serializável** quando um `model_validator` levanta
  `ValueError` e a rota valida o corpo manualmente (schema depende do `{passo}` da URL): use
  `e.errors(include_url=False, include_context=False)` ou o `detail` vira 500 dentro do render.
- **`prazo_meses → target_date` é `hoje + prazo_meses*30 dias`** — constante de calendário (como
  `MESES_POR_ANO`), não aritmética de mês real (em 25 anos a diferença passa de 4 meses).
- **A fixture `escopos` do conftest não cria `scope_members`** — quem for tocar `household` garante
  a membership do owner antes (`_garantir_membro`, idempotente), senão o `members_titular_gate`
  morde com 23514 vindo de outro schema.
- **Fechamento local-first** (regra desde 2026-08-31, no CLAUDE.md da raiz): a bateria inteira roda
  no Postgres local em minutos (F21a: from-zero 00→59 + SQL 2 papéis + pytest `576 passed` em
  3m35s); no Aiven só o incremento. Foi a suíte inteira — não a direcionada — que pegou o C59b
  invalidando fixtures de suitability em `_agentes.sql`/`_contexto.sql`.

## F21b — intake do onboarding com IA (2026-08-31)

Migration 60 + `app/intake/` + rotas de intake em `app/api/routes/onboarding.py`. Desenho
refinado ANTES de codar (registrado no changelog do ESTADO): em vez de relaxar a cadeia
`extraction_runs → signals → proposals` (o bullet "Objetivo: carro de 80 mil em 2 anos" é
entidade composta, e o teto C38g de 5 pendentes morderia), o intake tem tabelas próprias
(`intake_submissions`/`intake_items`) com o padrão epistêmico em gates C60a–d, e a cadeia de
conversas ficou intacta.

O que vale reter:
- **Escritores compartilhados**: objetivo/dívida/bem se criam SÓ por `app/onboarding/estrutura.py`
  — wizard (F21a) e confirmação do intake usam o mesmo caminho (a lição da migration 53).
- **`escrita.confirmar_fato(source=, confianca=)`**: 'formulario'/0,95 no wizard;
  'onboarding'/0,85 no intake confirmado. `validar_fato()` valida contra o catálogo sem gravar
  (descarte de item com motivo na extração).
- **Provedores plugáveis** (`app/intake/provedores.py`): fábricas devolvem None até a F21d —
  submissão binária vai para `aguardando_provedor`, nunca 500; `plexo onboarding processar`
  reprocessa quando o provedor entrar.
- **Primeira rota multipart do app** (`python-multipart` no requirements): form `passo` + `tipo`
  (arquivo|audio) + `midia`; texto continua JSON e é processado inline (uma chamada de LLM por
  requisição — precedente do turno).
- **Teste com prompt**: `test_f21b_intake.py` depende do `context.onboarding_extractor` APROVADO
  no ambiente (dev: aprovado à mão; local/CI: `preparar_ambiente.py` aprova todo `prompts/*.j2`
  por glob) — desvio consciente da regra "teste não depende do estado do dev", registrado no §5
  do ESTADO.
- **429 no meio da fase**: a cota de sessão do Sonnet estourou e derrubou o implementador; o
  orquestrador assumiu com o briefing congelado como plano. O fallback do harness funcionou.
- **CORS: `PUT` entrou no `allow_methods` (F21c, `app/main.py`)** — a rota de passos do wizard é
  PUT e o preflight do navegador devolvia 400 com a lista da F7 (`GET/POST/OPTIONS`). O pytest
  não pega: ASGITransport não faz preflight. **Rota nova com MÉTODO novo exige smoke de
  navegador**, não só pytest — foi a captura de tela que acusou.
