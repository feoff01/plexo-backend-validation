-- =============================================================================
-- seeds/dev.sql — dados de DESENVOLVIMENTO. Idempotente. Rodar como serviço:
--   python -m app.cli seed dev
-- NÃO é migration (não entra no Alembic) e NÃO é dado de negócio de cliente.
-- Sem BEGIN/COMMIT: a CLI executa dentro da sessão de serviço (uma transação).
-- =============================================================================

-- Usuário de operação (aprova prompts/policies em dev; actor de audit.activity_log)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('0be0a000-0000-4000-8000-000000000001', 'synaptainvest@gmail.com', 'Operação Plexo', 'active')
ON CONFLICT (email) WHERE deleted_at IS NULL DO NOTHING;

-- Usuário + escopo de teste manual (CLI chat, exploração)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('0de0a000-0000-4000-8000-000000000001', 'dev@teste.local', 'Usuário Dev', 'active')
ON CONFLICT (email) WHERE deleted_at IS NULL DO NOTHING;

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('0de0a000-0000-4000-8000-000000000002', 'personal', 'Pessoal Dev', '0de0a000-0000-4000-8000-000000000001')
ON CONFLICT (id) DO NOTHING;

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at)
SELECT '0de0a000-0000-4000-8000-000000000002', '0de0a000-0000-4000-8000-000000000001', 'owner', now()
WHERE NOT EXISTS (SELECT 1 FROM identity.scope_members
                  WHERE scope_id = '0de0a000-0000-4000-8000-000000000002'
                    AND user_id = '0de0a000-0000-4000-8000-000000000001');

-- Policies OPERACIONAIS dos agentes (draft; números são ponto de partida, não verdade).
-- Só insere se o código ainda não tem versão vigente — mudanças vão por `policy set`.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'LLM_PRICING', 1, $j${
  "deepseek": {
    "deepseek-v4-pro": {"usd_por_m_input": 0.435, "usd_por_m_cache_hit": 0.0036, "usd_por_m_output": 0.87},
    "_nota": "DeepSeek V4 Pro, ago/2026 (fontes públicas); há variação peak/off-peak — conferir fatura e atualizar por `policy set`."
  }
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'LLM_PRICING' AND effective_to IS NULL);

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'AGENT_ROUTING', 1, $j${
  "min_confidence": 0.6,
  "_nota": "abaixo disto o Copiloto devolve 'clarify' com opções, sem abrir conversa nem consumir cota."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'AGENT_ROUTING' AND effective_to IS NULL);

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'AGENT_CONVERSATIONS', 1, $j${
  "inatividade_minutos": 30,
  "max_historico_mensagens": 20,
  "max_tools_por_turno": 4,
  "max_erros_de_tool_por_turno": 2,
  "max_chars_resultado_no_historico": 1500,
  "max_blocos_por_mensagem": 6,
  "max_pontos_por_bloco": 400,
  "_nota": "conversa sem mensagem por inatividade_minutos é encerrada pelo job (F3) e entra na fila do agente de Contexto; max_historico_mensagens limita o histórico enviado ao LLM no turno; max_tools_por_turno limita a cadeia de tools num turno (F4: 2; F7: 4 — perguntas do Analista com três medições (+ uma leitura de série) estouravam o limite e o provedor vazava a 3ª chamada como texto); F8: max_erros_de_tool_por_turno = quantos erros de tool (parâmetro inválido, insumo faltante, conteúdo indisponível) voltam ao modelo antes do texto fixo; max_chars_resultado_no_historico = tamanho do output da tool anexado à mensagem do agente no histórico enviado ao LLM (follow-up vê os números)."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'AGENT_CONVERSATIONS' AND effective_to IS NULL);

-- Jobs de manutenção (F3): execução de tool em 'running' além deste tempo vira 'timeout'.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'JOBS_MANUTENCAO', 1, $j${
  "execucao_travada_minutos": 15,
  "_nota": "lido por app/jobs/tasks.py (varrer_execucoes_travadas). Operacional: não é client-facing."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'JOBS_MANUTENCAO' AND effective_to IS NULL);

-- Dados de ORÇAMENTO do escopo de dev — para testar o chat manualmente (idempotente).
INSERT INTO budget.income_summaries (scope_id, month, fixed_brl, variable_brl, variable_p10_brl,
                                     committable_brl, variable_share, months_observed)
SELECT '0de0a000-0000-4000-8000-000000000002', date_trunc('month', current_date)::date,
       12000, 8000, 2000, 14000, 0.4, 12
WHERE NOT EXISTS (SELECT 1 FROM budget.income_summaries
                  WHERE scope_id = '0de0a000-0000-4000-8000-000000000002'
                    AND month = date_trunc('month', current_date)::date);

INSERT INTO budget.monthly_summaries (scope_id, month, income_brl, expense_brl)
SELECT '0de0a000-0000-4000-8000-000000000002',
       (date_trunc('month', current_date) - (n || ' months')::interval)::date, 20000, 8000
FROM generate_series(1, 6) n
ON CONFLICT (scope_id, month) DO NOTHING;

INSERT INTO budget.reserve_settings (scope_id, target_months)
VALUES ('0de0a000-0000-4000-8000-000000000002', 6.0)
ON CONFLICT (scope_id) DO NOTHING;

INSERT INTO budget.debts (scope_id, kind, description, outstanding_brl, annual_rate,
                          monthly_payment_brl, is_expensive)
SELECT '0de0a000-0000-4000-8000-000000000002', 'cartao_rotativo', 'cartão de crédito (dev)',
       15000, 0.9, 1500, true
WHERE NOT EXISTS (SELECT 1 FROM budget.debts
                  WHERE scope_id = '0de0a000-0000-4000-8000-000000000002' AND settled_at IS NULL);

-- Premissas de planejamento do Assessor (F2). Draft: aprovar com `policy approve` antes do uso
-- client-facing (gate 29a). Números são PONTO DE PARTIDA — calibrar com comitê.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'PLANEJAMENTO_PREMISSAS', 1, $j${
  "taxa_retirada_anual": 0.04,
  "_nota": "placeholder — taxa de retirada segura para independência; calibrar e aprovar."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'PLANEJAMENTO_PREMISSAS' AND effective_to IS NULL);

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'PRODUTO_REFERENCIAS', 1, $j${
  "referencia_taxa_adm_aa": {"renda_fixa": 0.005, "multimercado": 0.02, "acoes": 0.015},
  "_nota": "placeholder — tetos de REFERÊNCIA de taxa de administração por classe, para comparação 'caro vs. barato'; calibrar e aprovar."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'PRODUTO_REFERENCIAS' AND effective_to IS NULL);

-- META_PROBABILIDADE_DE_SUCESSO.md §9: confiança padrão, materialidade, caminhos e semente — config, não código.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'SIMULACAO_METAS', 1, $j${
  "nivel_confianca_padrao": 0.90,
  "limiar_materialidade_prob": 0.10,
  "n_caminhos": 10000,
  "semente": 20260823,
  "_nota": "placeholder — calibrar e aprovar com compliance antes de exibir probabilidade ao cliente."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'SIMULACAO_METAS' AND effective_to IS NULL);

-- =============================================================================
-- F4 · Educador — policies e conteúdo educativo de DEV
-- =============================================================================
-- Parâmetros das tools educacao.* (config-first). Draft: aprovar com `policy approve` (gate 29a).
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'EDUCACAO_PARAMS', 1, $j${
  "nivel_padrao": "basico",
  "max_itens": 3,
  "trecho_chars": 900,
  "prazo_max_anos": 50,
  "taxa_max_aa_pct": 100,
  "_nota": "nivel_padrao quando não há asserção confirmada nivel_conhecimento; limites do simulador são sanidade didática, não premissa de mercado."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'EDUCACAO_PARAMS' AND effective_to IS NULL);

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'EDUCACAO_EXEMPLOS', 1, $j${
  "valor_base_brl": 10000,
  "conteudo_slug": {"come_cotas": "come-cotas", "taxa_administracao": "taxa-de-administracao", "ir_regressivo": "ir-regressivo-renda-fixa"},
  "come_cotas": {"aliquota_curto_pct": 20, "aliquota_longo_pct": 15, "rendimento_semestre_pct": 5},
  "taxa_administracao": {"taxa_aa_pct": 2.0, "rendimento_bruto_aa_pct": 10, "anos": 10},
  "ir_regressivo": {"rendimento_aa_pct": 10, "dias_por_mes": 30, "meses_por_ano": 12, "prazo_meses_padrao": 24,
                    "faixas": [{"ate_dias": 180, "aliquota_pct": 22.5}, {"ate_dias": 360, "aliquota_pct": 20},
                               {"ate_dias": 720, "aliquota_pct": 17.5}, {"ate_dias": null, "aliquota_pct": 15}]},
  "_nota": "alíquotas conforme legislação vigente em ago/2026 (conferir a cada mudança tributária); rendimentos são DIDÁTICOS, não referência de mercado."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'EDUCACAO_EXEMPLOS' AND effective_to IS NULL);

-- Verbetes de DEV (texto de partida para revisão editorial/compliance). Fluxo que o gate da 30 exige:
-- INSERT em draft → trilha em compliance_reviews → UPDATE para approved+published. Idempotente por slug.
DO $seed$
DECLARE
  v_revisor uuid := '0be0a000-0000-4000-8000-000000000001';
  v_id uuid;
  r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES
    ('come-cotas', 'Come-cotas', 'basico', ARRAY['fundos','imposto'],
$md$O **come-cotas** é a cobrança antecipada do imposto de renda em fundos de investimento abertos (renda fixa, multimercado, cambiais). Duas vezes por ano — no último dia útil de maio e de novembro — o administrador do fundo calcula o rendimento do período e recolhe o imposto vendendo uma parte das suas cotas. Por isso o nome: o imposto "come" cotas.

A alíquota do come-cotas é a menor da tabela do tipo do fundo: 15% em fundos de longo prazo e 20% em fundos de curto prazo. Se, no resgate, a alíquota devida pelo seu prazo for maior, a diferença é cobrada naquele momento; se for igual, nada mais é devido.

Na prática, o come-cotas reduz o número de cotas, não o valor de cada cota. O efeito ao longo dos anos é que uma parte do rendimento deixa de render junto com o restante — é a razão de fundos de ações (que não têm come-cotas) e alguns títulos serem tributados só no resgate.$md$),
    ('juros-compostos', 'Juros compostos', 'basico', ARRAY['conceito','rendimento'],
$md$**Juros compostos** são juros calculados sobre o valor inicial mais os juros já acumulados. Em cada período o rendimento passa a render também — daí a ideia de "juros sobre juros".

Um exemplo cotidiano: R$ 1.000 a 1% ao mês rendem R$ 10 no primeiro mês; no segundo, o 1% incide sobre R$ 1.010, e assim por diante. No começo a diferença para os juros simples é pequena; com prazos longos ela fica grande.

Duas consequências práticas: (1) tempo de aplicação costuma pesar mais do que pequenas diferenças de taxa; (2) o mesmo mecanismo age contra quem deve — dívidas com juros altos crescem no mesmo ritmo. Juros compostos são uma regra de cálculo, não uma promessa de resultado: a taxa efetiva de qualquer aplicação varia.$md$),
    ('cdi-e-selic', 'CDI e Selic', 'intermediario', ARRAY['juros','referencia','renda-fixa'],
$md$A **Selic** é a taxa básica de juros da economia brasileira, definida pelo Comitê de Política Monetária do Banco Central a cada 45 dias. O **CDI** (Certificado de Depósito Interbancário) é a taxa média dos empréstimos de um dia entre bancos; ela acompanha de perto a Selic e é a referência mais usada para remunerar aplicações de renda fixa.

Quando uma aplicação diz render "100% do CDI", ela paga a variação do CDI do período; "110% do CDI" paga um pouco mais, "90%" um pouco menos. A comparação entre aplicações atreladas ao CDI, portanto, é feita pelo percentual — e pelo imposto e prazo de cada uma.

Ambas as taxas são divulgadas ao ano, mas apuradas dia a dia (dias úteis). Elas mudam ao longo do tempo: uma aplicação "a 100% do CDI" não tem retorno fixo, tem retorno que segue a taxa.$md$),
    ('ir-regressivo-renda-fixa', 'Tabela regressiva do IR na renda fixa', 'intermediario', ARRAY['imposto','renda-fixa'],
$md$Na renda fixa (CDB, Tesouro Direto, LC, debêntures comuns) e na maioria dos fundos, o imposto de renda sobre o rendimento segue uma **tabela regressiva**: quanto mais tempo a aplicação fica, menor a alíquota.

As faixas são: 22,5% até 180 dias; 20% de 181 a 360 dias; 17,5% de 361 a 720 dias; 15% acima de 720 dias. A alíquota incide só sobre o rendimento, nunca sobre o valor aplicado, e é retida na fonte no resgate ou no vencimento.

Algumas aplicações são isentas de IR para pessoa física (LCI, LCA, CRI, CRA, debêntures incentivadas, poupança), o que muda a comparação entre elas: uma taxa menor isenta pode equivaler a uma taxa maior tributada. Regras tributárias mudam; a referência aqui é a vigente na data de revisão deste verbete.$md$),
    ('reserva-de-emergencia', 'Reserva de emergência', 'basico', ARRAY['orcamento','planejamento'],
$md$A **reserva de emergência** é um valor guardado para cobrir imprevistos — perda de renda, despesa médica, conserto inadiável — sem precisar se endividar ou desfazer investimentos de longo prazo em má hora.

A referência usual é ter alguns meses de custo de vida guardados; o número certo depende da estabilidade da renda (quem tem renda variável costuma precisar de mais) e das obrigações fixas da família. A reserva mede-se em *meses de custo*, não em um valor absoluto.

Duas características importam mais do que o rendimento: **liquidez** (poder sacar quando precisar, sem perda) e **baixa oscilação**. Por isso ela costuma ficar em aplicações de resgate imediato. O diagnóstico de quantos meses você tem hoje é feito com os seus números de orçamento, pelo Assessor.$md$),
    ('taxa-de-administracao', 'Taxa de administração', 'basico', ARRAY['fundos','custo'],
$md$A **taxa de administração** é o percentual anual cobrado por um fundo de investimento (ou plano de previdência) para remunerar a gestão e a administração. Ela é descontada diariamente do patrimônio do fundo, de forma proporcional, e por isso o valor da cota já aparece líquido dessa taxa.

Como é cobrada sobre o patrimônio — e não sobre o ganho — ela é devida mesmo em períodos de resultado negativo. Ao longo de anos, o efeito é composto: uma diferença de um ponto percentual ao ano vira uma diferença grande no montante final.

Alguns fundos cobram também **taxa de performance** (percentual sobre o que exceder um índice de referência) e, em casos raros, taxas de entrada ou saída. Todas constam na lâmina e no regulamento. Comparar custos entre produtos concretos, considerando o seu contexto, é trabalho do Assessor.$md$),
    ('diversificacao', 'Diversificação', 'basico', ARRAY['conceito','risco'],
$md$**Diversificar** é distribuir o dinheiro entre investimentos que não sobem e descem juntos, para que um resultado ruim em um deles pese menos no conjunto. É a forma mais básica de reduzir risco sem depender de acertar o momento certo.

Diversificação de verdade envolve *tipos* diferentes (renda fixa, ações, imóveis, moedas), *emissores* diferentes e, quando faz sentido, *países* diferentes. Ter dez fundos que compram as mesmas ações não é diversificar — é repetir a mesma aposta com custos diferentes.

Ela reduz o risco de um evento isolado, mas não elimina o risco do mercado como um todo: em crises amplas, muitos ativos caem ao mesmo tempo. Quanto diversificar, e em quê, depende do objetivo e do prazo de cada pessoa.$md$),
    ('inflacao-e-ipca', 'Inflação e IPCA', 'basico', ARRAY['conceito','indice'],
$md$**Inflação** é o aumento generalizado dos preços ao longo do tempo — o mesmo dinheiro passa a comprar menos. No Brasil, o índice oficial é o **IPCA**, calculado mensalmente pelo IBGE a partir de uma cesta de consumo das famílias.

Para investimentos, o que importa é o **rendimento real**: quanto a aplicação rendeu *acima* da inflação. Uma aplicação que rende 6% ao ano num período em que a inflação foi de 5% preservou o poder de compra e ganhou cerca de 1% real. Rendimento abaixo da inflação, mesmo positivo, significa perda de poder de compra.

Alguns títulos são indexados ao IPCA (pagam inflação mais uma taxa fixa); outros são prefixados ou seguem o CDI. Entender a diferença ajuda a ler qualquer proposta de aplicação — comparar produtos específicos, porém, é trabalho do Assessor.$md$)
  ) AS v(slug, title, level, tags, body_md)
  LOOP
    IF EXISTS (SELECT 1 FROM content.education_contents WHERE slug = r.slug) THEN CONTINUE; END IF;
    INSERT INTO content.education_contents (slug, title, body_md, level, tags)
    VALUES (r.slug, r.title, r.body_md, r.level, r.tags) RETURNING id INTO v_id;
    INSERT INTO content.compliance_reviews (subject_kind, subject_id, decision, reviewer_id, notes)
    VALUES ('education', v_id, 'approved', v_revisor, 'seed de dev — aprovação pelo usuário de operação');
    UPDATE content.education_contents
       SET review_status = 'approved', reviewed_by = v_revisor, reviewed_at = now(), published_at = now()
     WHERE id = v_id;
  END LOOP;
END
$seed$;

-- CONTEXT_ASSERTIONS ganha validade para `nivel_conhecimento` (F4): nova versão (draft) só se a vigente
-- não tiver a chave — a anterior é fechada como `policy set` faria.
DO $ctx$
DECLARE p record;
BEGIN
  SELECT * INTO p FROM engine.policy_versions
   WHERE code = 'CONTEXT_ASSERTIONS' AND effective_to IS NULL;
  IF FOUND AND NOT (p.payload->'validade_dias' ? 'nivel_conhecimento') THEN
    UPDATE engine.policy_versions
       SET effective_to = greatest(clock_timestamp(), effective_from + interval '1 microsecond')
     WHERE id = p.id;
    INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
    VALUES ('CONTEXT_ASSERTIONS', p.version + 1,
            jsonb_set(p.payload, '{validade_dias,nivel_conhecimento}', '365'::jsonb, true), 'draft',
            clock_timestamp());
  END IF;
END
$ctx$;

-- =============================================================================
-- [5ª onda — F5 Analista] Mercado: policy de ingestão (operacional) e universo mínimo de dev.
-- Preços NÃO entram por seed: `python -m app.cli mercado ingerir --fonte cotahist --arquivo <COTAHIST>`
-- (ou --ano/--data com rede) e `mercado ingerir --fonte sgs`. Regras do banco: 31_market_immutability.
-- =============================================================================
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'MERCADO_INGESTAO', 1, $j${
  "sgs_base_url": "https://api.bcb.gov.br",
  "sgs_janela_max_dias": 3650,
  "cotahist_url_anual": "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP",
  "cotahist_url_diario": "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{ddmmaaaa}.ZIP",
  "backfill_anos": 5,
  "somente_universo": true,
  "lote_insert_linhas": 5000,
  "timeout_s": 120,
  "_nota": "lido por app/jobs/tasks.py (ingerir_cotahist/ingerir_sgs). Operacional, não client-facing. backfill_anos <= cobertura de partições (31: 10 anos)."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'MERCADO_INGESTAO' AND effective_to IS NULL);

-- Universo de dev (is_in_universe): só estes entram na ingestão. Ampliar é INSERT.
-- Premissas das expectativas de mercado (F13b) — client-facing: exige `policy approve`.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'EXPECTATIVAS_PARAMS', 1, '{
  "base_calculo": 0,
  "max_horizontes": 5,
  "janela_descricao": "últimos 30 dias",
  "_nota": "Qual janela do Focus é citável (0 = 30 dias, 1 = 5 dias úteis) e quantos horizontes a resposta traz."
}'::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions
                  WHERE code = 'EXPECTATIVAS_PARAMS' AND effective_to IS NULL);

-- Premissas da citação documental (F13a) — client-facing: exige `policy approve`.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'CONTEXTO_DOCUMENTAL', 1, '{
  "max_documentos": 3,
  "trecho_chars": 700,
  "_nota": "Quantos documentos a resposta pode citar e o tamanho do trecho literal recortado."
}'::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions
                  WHERE code = 'CONTEXTO_DOCUMENTAL' AND effective_to IS NULL);

INSERT INTO market.instruments (kind, name, ticker, asset_class_code, is_in_universe, source_code)
VALUES ('acao', 'Petrobras PN',           'PETR4',  'acoes_br', true, 'b3'),
       ('acao', 'Vale ON',                'VALE3',  'acoes_br', true, 'b3'),
       ('acao', 'Itaú Unibanco PN',       'ITUB4',  'acoes_br', true, 'b3'),
       ('acao', 'WEG ON',                 'WEGE3',  'acoes_br', true, 'b3'),
       ('etf',  'iShares Ibovespa (ETF)', 'BOVA11', 'acoes_br', true, 'b3')
ON CONFLICT (ticker) WHERE ticker IS NOT NULL DO NOTHING;

-- Premissas metodológicas do Analista (client-facing: gate 29a exige `policy approve ANALISE_PARAMS`).
-- Números são PONTO DE PARTIDA — calibrar e aprovar com compliance antes de exibir ao cliente.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'ANALISE_PARAMS', 1, $j${
  "janela_padrao_dias": 365,
  "min_observacoes": 30,
  "max_dias_defasagem": 5,
  "dias_uteis_ano": 252,
  "metodo_retorno": "log",
  "max_pontos": 260,
  "benchmark_padrao": "BOVA11",
  "event_study": {"janela_estimacao_dias": 120, "pre_dias": 5, "pos_dias": 5, "metodo": "market_model"},
  "_nota": "lido pelas tools dados.*/quant.* (app/tools/analista). janela_padrao_dias em dias corridos; benchmark_padrao precisa estar no universo com preços."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'ANALISE_PARAMS' AND effective_to IS NULL);

-- Modo research do Analista (F6): limites operacionais do DAG. Operacional, não client-facing.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'ANALISE_RESEARCH', 1, $j${
  "max_tasks": 8,
  "max_paralelo": 1,
  "timeout_task_s": 60,
  "max_tentativas": 2,
  "dsl_version": "1",
  "analise_travada_minutos": 30,
  "_nota": "lido por app/analysis (compiler/executor/pipeline) e pelo job de varredura. max_paralelo é reservado (v1 executa em ordem topológica)."
}$j$::jsonb, 'draft'
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'ANALISE_RESEARCH' AND effective_to IS NULL);
