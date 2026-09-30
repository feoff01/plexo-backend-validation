-- =============================================================================
-- PLEXO · testes das regras invioláveis — proposta ao vivo (T89–T94, 39_live_extraction.sql)
--   T89  run 'turno' lê conversa ABERTA; 'pos_conversa' continua exigindo conversa encerrada
--   T90  run 'turno' NÃO marca a conversa como processada; 'pos_conversa' marca
--   T91  vários runs 'turno' por conversa; o sucesso único continua valendo para 'pos_conversa'
--   T92  proposta herda a origem do run que a gerou — ninguém declara `origin` à mão
--   T93  teto SEMANAL de cards ao vivo, que não atinge as propostas pós-conversa
--   T94  natureza pontual/incerta não se aplica a fato recorrente
--   T135 canário do card (58_canario_do_card.sql): card ao vivo só nasce para escopo na
--        allowlist da policy — e sem a chave, para ninguém (fail-closed)
--   T136 rótulo do extrator (nature_do_extrator) nasce copiado de nature e é imutável;
--        a reclassificação do cliente muda nature e preserva o rótulo
--   T137 context.v_precisao_extrator mede a precisão por classe a partir das respostas
--
-- Por que este arquivo existe: até a 38, `context.extraction_requires_ended` proibia o
-- Contexto de ler conversa aberta — e com razão, porque a extração em lote é registro
-- sobre um diálogo terminado. O card que aparece DURANTE a conversa é outro ato: ele
-- não conclui nada, faz uma pergunta sobre uma frase que acabou de ser dita.
--
-- O que NÃO se afrouxou: a cadeia sinal → evidência → proposta continua inteira. O run
-- ao vivo aponta as mensagens exatas do turno, e proposta sem sinal continua impossível.
-- O que se ganhou de governança: teto semanal de cards. Um produto cuja promessa é
-- respeitar o tempo do cliente não pode ter um laço que cutuca a cada turno.
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_perfil_vivo.sql [plexo_service]
-- Termina em ROLLBACK — não deixa resíduo.
-- =============================================================================
\set QUIET on
SET client_min_messages = notice;

CREATE OR REPLACE FUNCTION pg_temp.expect_fail(p_sql text, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  BEGIN
    EXECUTE p_sql;
    RAISE EXCEPTION 'FALHOU: "%" deveria ter sido rejeitado pelo banco', p_label;
  EXCEPTION
    WHEN raise_exception THEN
      IF sqlerrm LIKE 'FALHOU:%' THEN RAISE; END IF;
      RAISE NOTICE 'ok   · % (rejeitado: %)', p_label, left(sqlerrm, 70);
    WHEN others THEN
      RAISE NOTICE 'ok   · % (rejeitado: %)', p_label, left(sqlerrm, 70);
  END;
END $$;

CREATE OR REPLACE FUNCTION pg_temp.expect_count(p_sql text, p_expected bigint, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v bigint;
BEGIN
  EXECUTE 'SELECT count(*) FROM (' || p_sql || ') q' INTO v;
  IF v <> p_expected THEN
    RAISE EXCEPTION 'FALHOU: "%" — esperado % linha(s), obtido %', p_label, p_expected, v;
  END IF;
  RAISE NOTICE 'ok   · % (% linha(s), como esperado)', p_label, v;
END $$;

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixture (prefixo 8989 = T89)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('89890000-0000-4000-8000-000000000001', 't89-titular@teste.local', 'Titular T89', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('89890000-0000-4000-8000-000000000002', 'personal', 'Pessoal T89',
        '89890000-0000-4000-8000-000000000001');

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at)
VALUES ('89890000-0000-4000-8000-000000000002',
        '89890000-0000-4000-8000-000000000001', 'owner', now());

-- conversa ABERTA — é sobre ela que o card ao vivo trabalha
INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start, status)
VALUES ('89890000-0000-4000-8000-000000000010', '89890000-0000-4000-8000-000000000002',
        '89890000-0000-4000-8000-000000000001', 'assessor', 'essential', 'aberta');

INSERT INTO agents.messages (id, conversation_id, scope_id, seq, role, content)
VALUES ('89890000-0000-4000-8000-000000000011', '89890000-0000-4000-8000-000000000010',
        '89890000-0000-4000-8000-000000000002', 1, 'user', 'passei a ganhar 10 mil por mês');

-- conversa ENCERRADA — o caminho em lote, que não muda
INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start,
                                  status, started_at, ended_at)
VALUES ('89890000-0000-4000-8000-000000000012', '89890000-0000-4000-8000-000000000002',
        '89890000-0000-4000-8000-000000000001', 'assessor', 'essential',
        'encerrada', now() - interval '2 hours', now() - interval '10 minutes');

INSERT INTO agents.messages (id, conversation_id, scope_id, seq, role, content)
VALUES ('89890000-0000-4000-8000-000000000013', '89890000-0000-4000-8000-000000000012',
        '89890000-0000-4000-8000-000000000002', 1, 'user', 'minha despesa subiu bastante');

-- catálogo isolado (o real sai de cena; ver T88c do arquivo irmão)
UPDATE context.fact_definitions SET is_active = false;
-- `pergunta` é obrigatória para fato askable (CHECK `askable_has_question`, migration 43):
-- se o motor pode pedir o fato ao cliente, tem que existir a frase com que ele pede.
INSERT INTO context.fact_definitions
  (fact_key, subject_kind, attribute, family, display_name, pergunta, value_type, unit,
   source_precedence, half_life_days, materiality_abs, materiality_rel,
   min_value, max_value, is_recurring_by_nature, requires_nature_check)
VALUES
  ('t89.renda_mensal', 'renda', 't89_renda_mensal', 'fluxo', 'Renda mensal (T89)',
   'Quanto você recebe por mês, já líquido?',
   'money_brl', 'BRL',
   ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
   180, 500, 0.05, 0, 10000000, true, true),
  -- fato que NÃO é recorrente por natureza: uma herança é pontual e está tudo bem
  ('t89.entrada_pontual', 'patrimonio', 't89_entrada_pontual', 'estoque', 'Entrada pontual (T89)',
   'Entrou algum valor fora do comum nos últimos meses?',
   'money_brl', 'BRL',
   ARRAY['formulario','conversa','onboarding','upload','operador']::context.assertion_source[],
   365, 1000, 0.10, 0, 100000000, false, true);

-- Canário do card (F20, migration 58): o card ao vivo só nasce para escopo na allowlist da
-- policy. A fixture dá a allowlist aos escopos deste arquivo — sem isto, T89–T94 quebrariam
-- no dia em que o gate nascesse (a lição da F17: CHECK novo obriga a suíte inteira).
-- clock_timestamp(): now() é congelado na transação e violaria effective_to > effective_from
UPDATE engine.policy_versions SET effective_to = clock_timestamp()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'CONTEXT_FACT_CATALOG', coalesce(max(version), 0) + 1,
       coalesce((SELECT payload FROM engine.policy_versions
                  WHERE code = 'CONTEXT_FACT_CATALOG'
                  ORDER BY version DESC LIMIT 1), '{}'::jsonb)
       || jsonb_build_object('escopos_canario_card_ao_vivo', jsonb_build_array(
            '89890000-0000-4000-8000-000000000002',
            '13500000-0000-4000-8000-000000000002')),
       'draft', clock_timestamp()
  FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG';

-- ================================================================ TESTE 89
-- O gate deixou de ser "conversa encerrada" e passou a ser "conversa encerrada
-- PARA EXTRAÇÃO EM LOTE". O card ao vivo é outro ato e tem outra porta.
INSERT INTO context.extraction_runs (id, conversation_id, scope_id, kind, status)
VALUES ('89890000-0000-4000-8000-000000000020', '89890000-0000-4000-8000-000000000010',
        '89890000-0000-4000-8000-000000000002', 'turno', 'running');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.extraction_runs
   WHERE id = '89890000-0000-4000-8000-000000000020' AND kind = 'turno'
$sql$, 1, 'T89  run de turno é aceito sobre conversa ABERTA');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.extraction_runs (conversation_id, scope_id, kind, status)
  VALUES ('89890000-0000-4000-8000-000000000010',
          '89890000-0000-4000-8000-000000000002', 'pos_conversa', 'running');
$sql$, 'T89b extração em lote continua recusando conversa aberta');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.extraction_runs
   WHERE id = '89890000-0000-4000-8000-000000000020' AND kind::text = 'turno'
$sql$, 1, 'T89c o default do kind não vazou para o run de turno');

-- ================================================================ TESTE 90
-- Conversa aberta não vira "processada" porque um card apareceu no meio dela.
UPDATE context.extraction_runs SET status = 'succeeded', finished_at = now()
 WHERE id = '89890000-0000-4000-8000-000000000020';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM agents.conversations
   WHERE id = '89890000-0000-4000-8000-000000000010' AND status = 'aberta'
$sql$, 1, 'T90  run de turno bem-sucedido NÃO encerra nem processa a conversa');

INSERT INTO context.extraction_runs (id, conversation_id, scope_id, kind, status)
VALUES ('89890000-0000-4000-8000-000000000021', '89890000-0000-4000-8000-000000000012',
        '89890000-0000-4000-8000-000000000002', 'pos_conversa', 'running');
UPDATE context.extraction_runs SET status = 'succeeded', finished_at = now()
 WHERE id = '89890000-0000-4000-8000-000000000021';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM agents.conversations
   WHERE id = '89890000-0000-4000-8000-000000000012' AND status = 'processada'
$sql$, 1, 'T90b run em lote bem-sucedido continua marcando a conversa como processada');

-- ================================================================ TESTE 91
-- Um card por turno significa vários runs de turno por conversa. O sucesso único
-- continua valendo onde ele quer dizer alguma coisa: na extração em lote.
INSERT INTO context.extraction_runs (id, conversation_id, scope_id, kind, status, finished_at)
VALUES ('89890000-0000-4000-8000-000000000022', '89890000-0000-4000-8000-000000000010',
        '89890000-0000-4000-8000-000000000002', 'turno', 'succeeded', now());
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.extraction_runs
   WHERE conversation_id = '89890000-0000-4000-8000-000000000010'
     AND kind = 'turno' AND status = 'succeeded'
$sql$, 2, 'T91  dois runs de turno bem-sucedidos convivem na mesma conversa');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.extraction_runs (conversation_id, scope_id, kind, status, finished_at)
  VALUES ('89890000-0000-4000-8000-000000000012',
          '89890000-0000-4000-8000-000000000002', 'pos_conversa', 'succeeded', now());
$sql$, 'T91b segunda extração em lote bem-sucedida na mesma conversa é recusada');

-- ================================================================ TESTE 92
-- `origin` não é declarado pelo chamador: ele é DERIVADO do run que gerou o sinal.
-- Sem isso, bastaria a aplicação mentir a origem para escapar do teto semanal.
INSERT INTO context.signals (id, extraction_run_id, scope_id, user_id, kind, summary,
                             confidence, evidence_message_ids)
VALUES ('89890000-0000-4000-8000-000000000030', '89890000-0000-4000-8000-000000000020',
        '89890000-0000-4000-8000-000000000002', '89890000-0000-4000-8000-000000000001',
        'mudanca_renda', 'renda mencionada como 10.000', 0.9,
        ARRAY['89890000-0000-4000-8000-000000000011']::uuid[]);

INSERT INTO context.signals (id, extraction_run_id, scope_id, user_id, kind, summary,
                             confidence, evidence_message_ids)
VALUES ('89890000-0000-4000-8000-000000000031', '89890000-0000-4000-8000-000000000021',
        '89890000-0000-4000-8000-000000000002', '89890000-0000-4000-8000-000000000001',
        'mudanca_despesa', 'despesa mencionada como maior', 0.8,
        ARRAY['89890000-0000-4000-8000-000000000013']::uuid[]);

INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref,
   current_value, proposed_value, rationale, nature)
VALUES ('89890000-0000-4000-8000-000000000040',
        '89890000-0000-4000-8000-000000000030','89890000-0000-4000-8000-000000000002',
        '89890000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
        '{"table":"context.assertions"}'::jsonb,
        '{"amount":8000}'::jsonb,'{"amount":10000}'::jsonb,
        'você mencionou que passou a ganhar 10 mil', 'recorrente');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '89890000-0000-4000-8000-000000000040' AND origin = 'turno'
$sql$, 1, 'T92  proposta de sinal de turno nasce com origin = turno');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value,
     rationale, nature, origin)
  VALUES ('89890000-0000-4000-8000-000000000030','89890000-0000-4000-8000-000000000002',
          '89890000-0000-4000-8000-000000000001','profile_field','t89.entrada_pontual',
          '{"table":"context.assertions"}'::jsonb,'{"amount":50000}'::jsonb,
          'mentindo a origem para escapar do teto', 'pontual', 'pos_conversa');
$sql$, 'T92b declarar origem diferente da do sinal é recusado');

-- ================================================================ TESTE 93
-- Teto SEMANAL de cards ao vivo (policy CONTEXT_FACT_CATALOG). É a governança de
-- atenção que impede o laço de virar cutucão — e ela só vale para o que interrompe.
INSERT INTO context.change_proposals
  (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
SELECT '89890000-0000-4000-8000-000000000030','89890000-0000-4000-8000-000000000002',
       '89890000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
       '{"table":"context.assertions"}'::jsonb,
       jsonb_build_object('amount', 11000 + i * 1000), 'card ao vivo', 'recorrente'
  FROM generate_series(1, 2) AS i;

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE scope_id = '89890000-0000-4000-8000-000000000002' AND origin = 'turno'
$sql$, 3, 'T93  três cards ao vivo na semana é o teto da policy');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
  VALUES ('89890000-0000-4000-8000-000000000030','89890000-0000-4000-8000-000000000002',
          '89890000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,'{"amount":20000}'::jsonb,
          'o quarto card da semana', 'recorrente');
$sql$, 'T93b o quarto card ao vivo da semana é recusado');

-- a mesma mudança pelo caminho em lote passa: o teto é do que INTERROMPE
INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
VALUES ('89890000-0000-4000-8000-000000000041',
        '89890000-0000-4000-8000-000000000031','89890000-0000-4000-8000-000000000002',
        '89890000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
        '{"table":"context.assertions"}'::jsonb,'{"amount":20000}'::jsonb,
        'mesma mudança, pela extração em lote', 'recorrente');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '89890000-0000-4000-8000-000000000041' AND origin = 'pos_conversa'
$sql$, 1, 'T93c proposta pós-conversa não é atingida pelo teto semanal de cards');

-- ================================================================ TESTE 94
-- "Ganhei 10k esse mês" não pode virar "passei a ganhar 10k". É a classificação
-- mais importante do laço: sem ela, um bônus vira aumento salarial no plano.
UPDATE context.change_proposals
   SET status = 'confirmada', confirmed_at = now(),
       confirmed_by = '89890000-0000-4000-8000-000000000001'
 WHERE id = '89890000-0000-4000-8000-000000000040';

SELECT pg_temp.expect_fail($sql$
  UPDATE context.change_proposals
     SET nature = 'pontual', status = 'aplicada', applied_at = now()
   WHERE id = '89890000-0000-4000-8000-000000000040';
$sql$, 'T94  natureza pontual não se aplica a fato recorrente');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.change_proposals
     SET nature = 'incerto', status = 'aplicada', applied_at = now()
   WHERE id = '89890000-0000-4000-8000-000000000040';
$sql$, 'T94b natureza incerta nunca se aplica — "ainda não sei" não é resposta');

UPDATE context.change_proposals
   SET status = 'aplicada', applied_at = now()
 WHERE id = '89890000-0000-4000-8000-000000000040';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '89890000-0000-4000-8000-000000000040' AND status = 'aplicada'
$sql$, 1, 'T94c natureza recorrente aplica no fato recorrente');

-- e o pontual continua legítimo onde o catálogo diz que o fato é pontual
INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
VALUES ('89890000-0000-4000-8000-000000000042',
        '89890000-0000-4000-8000-000000000031','89890000-0000-4000-8000-000000000002',
        '89890000-0000-4000-8000-000000000001','estate_asset','t89.entrada_pontual',
        '{"table":"context.assertions"}'::jsonb,'{"amount":50000}'::jsonb,
        'uma herança é pontual, e está tudo bem', 'pontual');
UPDATE context.change_proposals
   SET status = 'confirmada', confirmed_at = now(),
       confirmed_by = '89890000-0000-4000-8000-000000000001'
 WHERE id = '89890000-0000-4000-8000-000000000042';
UPDATE context.change_proposals
   SET status = 'aplicada', applied_at = now()
 WHERE id = '89890000-0000-4000-8000-000000000042';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '89890000-0000-4000-8000-000000000042' AND status = 'aplicada'
$sql$, 1, 'T94d fato pontual por natureza aceita proposta pontual');

-- ================================================================ TESTE 135 (F20 — canário)
-- O card ao vivo interrompe a conversa do cliente. Antes de medir a precisão do extrator
-- (decisão da F16: shadow mode virou canário, porque card silencioso não gera rótulo),
-- ele só pode nascer para escopo na allowlist da policy — e sem a chave, para NINGUÉM:
-- o custo de um card falso para a marca é maior que o custo de nenhum card.

-- fixture própria (prefixo 1350): escopo cuja presença na allowlist cada sub-teste controla
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('13500000-0000-4000-8000-000000000001', 't135-titular@teste.local', 'Titular T135', 'active');
INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('13500000-0000-4000-8000-000000000002', 'personal', 'Pessoal T135',
        '13500000-0000-4000-8000-000000000001');
INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at)
VALUES ('13500000-0000-4000-8000-000000000002',
        '13500000-0000-4000-8000-000000000001', 'owner', now());
INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start, status)
VALUES ('13500000-0000-4000-8000-000000000010', '13500000-0000-4000-8000-000000000002',
        '13500000-0000-4000-8000-000000000001', 'assessor', 'essential', 'aberta');
INSERT INTO agents.messages (id, conversation_id, scope_id, seq, role, content)
VALUES ('13500000-0000-4000-8000-000000000011', '13500000-0000-4000-8000-000000000010',
        '13500000-0000-4000-8000-000000000002', 1, 'user', 'passei a ganhar 12 mil por mês');
INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start,
                                  status, started_at, ended_at)
VALUES ('13500000-0000-4000-8000-000000000012', '13500000-0000-4000-8000-000000000002',
        '13500000-0000-4000-8000-000000000001', 'assessor', 'essential',
        'encerrada', now() - interval '2 hours', now() - interval '10 minutes');
INSERT INTO agents.messages (id, conversation_id, scope_id, seq, role, content)
VALUES ('13500000-0000-4000-8000-000000000013', '13500000-0000-4000-8000-000000000012',
        '13500000-0000-4000-8000-000000000002', 1, 'user', 'entrou uma herança este mês');
INSERT INTO context.extraction_runs (id, conversation_id, scope_id, kind, status)
VALUES ('13500000-0000-4000-8000-000000000020', '13500000-0000-4000-8000-000000000010',
        '13500000-0000-4000-8000-000000000002', 'turno', 'running');
INSERT INTO context.extraction_runs (id, conversation_id, scope_id, kind, status)
VALUES ('13500000-0000-4000-8000-000000000021', '13500000-0000-4000-8000-000000000012',
        '13500000-0000-4000-8000-000000000002', 'pos_conversa', 'running');
INSERT INTO context.signals (id, extraction_run_id, scope_id, user_id, kind, summary,
                             confidence, evidence_message_ids)
VALUES ('13500000-0000-4000-8000-000000000030', '13500000-0000-4000-8000-000000000020',
        '13500000-0000-4000-8000-000000000002', '13500000-0000-4000-8000-000000000001',
        'mudanca_renda', 'renda mencionada como 12.000', 0.9,
        ARRAY['13500000-0000-4000-8000-000000000011']::uuid[]);
INSERT INTO context.signals (id, extraction_run_id, scope_id, user_id, kind, summary,
                             confidence, evidence_message_ids)
VALUES ('13500000-0000-4000-8000-000000000031', '13500000-0000-4000-8000-000000000021',
        '13500000-0000-4000-8000-000000000002', '13500000-0000-4000-8000-000000000001',
        'mudanca_renda', 'herança mencionada', 0.8,
        ARRAY['13500000-0000-4000-8000-000000000013']::uuid[]);

-- T135: SEM a chave na policy vigente, card ao vivo não nasce (fail-closed)
-- clock_timestamp(): now() é congelado na transação e violaria effective_to > effective_from
UPDATE engine.policy_versions SET effective_to = clock_timestamp()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'CONTEXT_FACT_CATALOG', max(version) + 1,
       (SELECT payload FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG'
         ORDER BY version DESC LIMIT 1) - 'escopos_canario_card_ao_vivo',
       'draft', clock_timestamp()
  FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG';

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
  VALUES ('13500000-0000-4000-8000-000000000030','13500000-0000-4000-8000-000000000002',
          '13500000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,'{"amount":12000}'::jsonb,
          'sem allowlist na policy, nenhum escopo é canário', 'recorrente');
$sql$, 'T135  sem a chave escopos_canario_card_ao_vivo, o card ao vivo não nasce (fail-closed)');

-- T135b: com allowlist que NÃO contém o escopo, o card não nasce
-- clock_timestamp(): now() é congelado na transação e violaria effective_to > effective_from
UPDATE engine.policy_versions SET effective_to = clock_timestamp()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'CONTEXT_FACT_CATALOG', max(version) + 1,
       (SELECT payload FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG'
         ORDER BY version DESC LIMIT 1)
       || jsonb_build_object('escopos_canario_card_ao_vivo',
            jsonb_build_array('89890000-0000-4000-8000-000000000002')),
       'draft', clock_timestamp()
  FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG';

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
  VALUES ('13500000-0000-4000-8000-000000000030','13500000-0000-4000-8000-000000000002',
          '13500000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
          '{"amount_fora":1}'::jsonb,'{"amount":12500}'::jsonb,
          'escopo fora da allowlist não é canário', 'recorrente');
$sql$, 'T135b escopo fora da allowlist não recebe card ao vivo');

-- T135c: dentro da allowlist, o card nasce (o canário existe para responder)
-- clock_timestamp(): now() é congelado na transação e violaria effective_to > effective_from
UPDATE engine.policy_versions SET effective_to = clock_timestamp()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'CONTEXT_FACT_CATALOG', max(version) + 1,
       (SELECT payload FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG'
         ORDER BY version DESC LIMIT 1)
       || jsonb_build_object('escopos_canario_card_ao_vivo', jsonb_build_array(
            '89890000-0000-4000-8000-000000000002',
            '13500000-0000-4000-8000-000000000002')),
       'draft', clock_timestamp()
  FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG';

INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
VALUES ('13500000-0000-4000-8000-000000000040',
        '13500000-0000-4000-8000-000000000030','13500000-0000-4000-8000-000000000002',
        '13500000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
        '{"table":"context.assertions"}'::jsonb,'{"amount":12000}'::jsonb,
        'renda mencionada em conversa; card A do canário', 'recorrente');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '13500000-0000-4000-8000-000000000040' AND origin = 'turno'
$sql$, 1, 'T135c escopo na allowlist recebe o card ao vivo');

-- T135d: o caminho em lote NÃO é gateado — o canário governa o que INTERROMPE
-- clock_timestamp(): now() é congelado na transação e violaria effective_to > effective_from
UPDATE engine.policy_versions SET effective_to = clock_timestamp()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'CONTEXT_FACT_CATALOG', max(version) + 1,
       (SELECT payload FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG'
         ORDER BY version DESC LIMIT 1)
       || jsonb_build_object('escopos_canario_card_ao_vivo', jsonb_build_array(
            '89890000-0000-4000-8000-000000000002')),
       'draft', clock_timestamp()
  FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG';
INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
VALUES ('13500000-0000-4000-8000-000000000041',
        '13500000-0000-4000-8000-000000000031','13500000-0000-4000-8000-000000000002',
        '13500000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
        '{"table":"context.assertions"}'::jsonb,'{"amount":12700}'::jsonb,
        'extração pós-conversa não interrompe ninguém', 'recorrente');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '13500000-0000-4000-8000-000000000041' AND origin = 'pos_conversa'
$sql$, 1, 'T135d proposta pós-conversa nasce mesmo fora da allowlist (gate é só do turno)');
-- restaura a allowlist com o escopo 1350 para o resto do arquivo
-- clock_timestamp(): now() é congelado na transação e violaria effective_to > effective_from
UPDATE engine.policy_versions SET effective_to = clock_timestamp()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'CONTEXT_FACT_CATALOG', max(version) + 1,
       (SELECT payload FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG'
         ORDER BY version DESC LIMIT 1)
       || jsonb_build_object('escopos_canario_card_ao_vivo', jsonb_build_array(
            '89890000-0000-4000-8000-000000000002',
            '13500000-0000-4000-8000-000000000002')),
       'draft', clock_timestamp()
  FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG';

-- ================================================================ TESTE 136
-- A resposta do cliente é o rótulo — e rótulo sobrescrito é medição perdida. O que o
-- extrator propôs fica gravado em nature_do_extrator, copiado no nascimento e imutável.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM information_schema.columns
   WHERE table_schema = 'context' AND table_name = 'change_proposals'
     AND column_name = 'nature_do_extrator'
$sql$, 1, 'T136  a coluna nature_do_extrator existe em change_proposals');

-- card B: extrator propõe PONTUAL num fato que admite as duas naturezas
INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
VALUES ('13500000-0000-4000-8000-000000000042',
        '13500000-0000-4000-8000-000000000030','13500000-0000-4000-8000-000000000002',
        '13500000-0000-4000-8000-000000000001','estate_asset','t89.entrada_pontual',
        '{"table":"context.assertions"}'::jsonb,'{"amount":50000}'::jsonb,
        'herança mencionada; card B do canário', 'pontual');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '13500000-0000-4000-8000-000000000042'
     AND nature_do_extrator = 'pontual'
$sql$, 1, 'T136b o rótulo do extrator é copiado de nature no nascimento');

-- o cliente reclassifica: "não, isso virou recorrente" — nature muda, o rótulo fica
UPDATE context.change_proposals
   SET nature = 'recorrente'
 WHERE id = '13500000-0000-4000-8000-000000000042';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '13500000-0000-4000-8000-000000000042'
     AND nature = 'recorrente' AND nature_do_extrator = 'pontual'
$sql$, 1, 'T136c reclassificar muda nature e PRESERVA nature_do_extrator');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.change_proposals
     SET nature_do_extrator = 'recorrente'
   WHERE id = '13500000-0000-4000-8000-000000000042';
$sql$, 'T136d o rótulo do extrator é imutável — reescrevê-lo apagaria a medição');

-- ================================================================ TESTE 137
-- A view que transforma resposta em número: por classe proposta pelo extrator,
-- quantas respondidas, quantas confirmadas na MESMA classe, quantas reclassificadas,
-- quantas rejeitadas — e a precisão que decide (na policy) quando o card sai do canário.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM pg_views
   WHERE schemaname = 'context' AND viewname = 'v_precisao_extrator'
$sql$, 1, 'T137  a view context.v_precisao_extrator existe');

-- desfechos: card A confirmado na mesma classe; card B confirmado reclassificado;
-- card C (recorrente) rejeitado — rejeição é erro do extrator e conta contra a precisão
UPDATE context.change_proposals
   SET status = 'confirmada', confirmed_at = now(),
       confirmed_by = '13500000-0000-4000-8000-000000000001'
 WHERE id IN ('13500000-0000-4000-8000-000000000040',
              '13500000-0000-4000-8000-000000000042');
INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
VALUES ('13500000-0000-4000-8000-000000000043',
        '13500000-0000-4000-8000-000000000030','13500000-0000-4000-8000-000000000002',
        '13500000-0000-4000-8000-000000000001','profile_field','t89.renda_mensal',
        '{"table":"context.assertions"}'::jsonb,'{"amount":15000}'::jsonb,
        'número mal ouvido; card C do canário', 'recorrente');
UPDATE context.change_proposals
   SET status = 'rejeitada', rejected_at = now()
 WHERE id = '13500000-0000-4000-8000-000000000043';

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_precisao_extrator
   WHERE scope_id = '13500000-0000-4000-8000-000000000002' AND classe = 'recorrente'
     AND n_respondidas = 2 AND n_mesma_classe = 1 AND n_reclassificadas = 0
     AND n_rejeitadas = 1 AND precisao = 0.5
$sql$, 1, 'T137b classe recorrente: 2 respondidas, 1 na mesma classe, 1 rejeitada, precisão 0,5');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_precisao_extrator
   WHERE scope_id = '13500000-0000-4000-8000-000000000002' AND classe = 'pontual'
     AND n_respondidas = 1 AND n_mesma_classe = 0 AND n_reclassificadas = 1
     AND precisao = 0
$sql$, 1, 'T137c classe pontual: 1 respondida, reclassificada — precisão 0');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Proposta ao vivo: o Contexto passou a poder perguntar durante a'
\echo ' conversa sem concluí-la, sem perder a evidência e sem poder'
\echo ' cutucar mais que o teto da semana.'
\echo '================================================================'
