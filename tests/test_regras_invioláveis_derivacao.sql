-- =============================================================================
-- PLEXO · testes das regras invioláveis — derivação de fatos (T103–T107, 43_fact_derivation.sql)
--   T103  v_fact_operavel devolve UM fato por chave, e o CONFIRMADO vence o derivado
--   T104  derivado (inferencia_motor) não demove nem aposenta o que o cliente confirmou
--   T105  derivado vencido sai da janela operável, como qualquer fato
--   T106  v_fact_current NÃO mudou: continua sendo só o que o cliente confirmou
--   T107  fato que a conversa pode atualizar precisa ter pergunta cadastrada
--
-- Por que este arquivo existe: a F14 provou o laço e expôs que ele não tinha carga — a persona
-- tem R$ 1,52 mi em dados estruturados e 0% de cobertura, porque nada ligava
-- `budget.*`/`estate.*`/`household.*` ao catálogo. A derivação preenche isso, e a pergunta que
-- ela levanta é epistêmica: um fato que o MOTOR deduziu vale o mesmo que um que o cliente
-- CONFIRMOU?
--
-- A resposta deste arquivo é não, e ela tem forma de duas janelas:
--   v_fact_current   contrato do AGENTE — só 'confirmado'. Não mudou (T106).
--   v_fact_operavel  contrato do MOTOR  — 'confirmado' + 'inferido', com o confirmado
--                                          sempre na frente (T103) e nunca rebaixado (T104).
-- Assim o score passa a existir sem que nada seja apresentado ao cliente como se ele
-- tivesse confirmado.
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_derivacao.sql [plexo_service]
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

-- ---------------------------------------------------------------- fixture (prefixo 1030 = T103)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('10300000-0000-4000-8000-000000000001', 't103-titular@teste.local', 'Titular T103', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('10300000-0000-4000-8000-000000000002', 'personal', 'Pessoal T103',
        '10300000-0000-4000-8000-000000000001');

-- catálogo isolado (o real sai de cena; mesmo remédio dos arquivos irmãos da F14)
UPDATE context.fact_definitions SET is_active = false;
INSERT INTO context.fact_definitions
  (fact_key, subject_kind, attribute, family, display_name, pergunta, value_type, unit,
   source_precedence, allows_conversation_update, half_life_days,
   materiality_abs, materiality_rel, min_value, max_value)
VALUES
  ('t103.despesa', 'despesa', 't103_despesa', 'fluxo', 'Despesa essencial (T103)',
   'Quanto você gasta por mês com o essencial?', 'money_brl', 'BRL',
   ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
   true, 180, 300, 0.10, 0, 10000000),
  -- fato que SÓ a derivação alimenta: é o caso que a coluna allows_conversation_update existe
  -- para cobrir, e por isso ele não precisa de pergunta.
  ('t103.patrimonio', 'patrimonio', 't103_patrimonio', 'estoque', 'Patrimônio líquido (T103)',
   NULL, 'money_brl', 'BRL',
   ARRAY['open_finance','upload','inferencia_motor','formulario','onboarding','conversa','operador']::context.assertion_source[],
   false, NULL, 1000, 0.02, -1000000000, 1000000000);

-- ================================================================ TESTE 103
-- O motor deduziu a despesa a partir de budget.monthly_summaries; o cliente já tinha
-- confirmado o mesmo número no onboarding. Os dois coexistem, e a janela operável
-- devolve UM — o confirmado.
INSERT INTO context.assertions
  (id, scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source)
VALUES ('10300000-0000-4000-8000-000000000010',
        '10300000-0000-4000-8000-000000000002','10300000-0000-4000-8000-000000000001',
        't103.despesa','despesa','t103_despesa','{"amount":5000}'::jsonb,'BRL','fato','formulario');
UPDATE context.assertions
   SET status = 'confirmado', confirmed_at = now(),
       confirmed_by = '10300000-0000-4000-8000-000000000001'
 WHERE id = '10300000-0000-4000-8000-000000000010';

-- derivado com o MESMO valor: não há divergência, então ele nasce e permanece 'inferido'
INSERT INTO context.assertions
  (id, scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source, status)
VALUES ('10300000-0000-4000-8000-000000000011',
        '10300000-0000-4000-8000-000000000002','10300000-0000-4000-8000-000000000001',
        't103.despesa','despesa','t103_despesa','{"amount":5000}'::jsonb,'BRL','fato',
        'inferencia_motor','inferido');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_operavel
   WHERE scope_id = '10300000-0000-4000-8000-000000000002' AND fact_key = 't103.despesa'
$sql$, 1, 'T103  v_fact_operavel devolve UMA linha com confirmado e derivado vivos');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_operavel
   WHERE id = '10300000-0000-4000-8000-000000000010' AND confirmado
$sql$, 1, 'T103b e a linha que sobrevive é a que o CLIENTE confirmou');

-- o fato que só a derivação alimenta: aparece para o motor, com a marca de não confirmado
-- `valid_from` no passado para o T105 poder vencê-la sem esbarrar no CHECK validity_range
-- (o catálogo deste fato não tem meia-vida, então `valid_until` nasce NULL).
INSERT INTO context.assertions
  (id, scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source, status,
   valid_from)
VALUES ('10300000-0000-4000-8000-000000000012',
        '10300000-0000-4000-8000-000000000002','10300000-0000-4000-8000-000000000001',
        't103.patrimonio','patrimonio','t103_patrimonio','{"amount":1521500}'::jsonb,'BRL','fato',
        'inferencia_motor','inferido', current_date - 30);
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_operavel
   WHERE fact_key = 't103.patrimonio' AND NOT confirmado AND numero = 1521500
$sql$, 1, 'T103c fato só derivado ENTRA na janela do motor, marcado como não confirmado');

-- ================================================================ TESTE 104
-- Regressão das migrations 38 e 42: o motor não rebaixa o cliente. Um derivado que
-- DIVERGE do confirmado não o demove nem o aposenta — a divergência fica com o derivado.
INSERT INTO context.assertions
  (id, scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source, status)
VALUES ('10300000-0000-4000-8000-000000000013',
        '10300000-0000-4000-8000-000000000002','10300000-0000-4000-8000-000000000001',
        't103.despesa','despesa','t103_despesa','{"amount":7200}'::jsonb,'BRL','fato',
        'inferencia_motor','inferido');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.assertions
   WHERE id = '10300000-0000-4000-8000-000000000010'
     AND status = 'confirmado' AND superseded_at IS NULL
$sql$, 1, 'T104  o fato confirmado pelo cliente continua confirmado e vigente');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.assertions
   WHERE id = '10300000-0000-4000-8000-000000000013' AND status = 'conflitante'
$sql$, 1, 'T104b quem fica em conflito é o DERIVADO, não o cliente');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_operavel
   WHERE scope_id = '10300000-0000-4000-8000-000000000002' AND fact_key = 't103.despesa'
     AND numero = 5000
$sql$, 1, 'T104c e a janela operável continua devolvendo o número do cliente');

-- ================================================================ TESTE 105
-- Derivado apodrece como qualquer fato: a meia-vida do catálogo vale para ele também.
UPDATE context.assertions SET valid_until = current_date - 1
 WHERE id = '10300000-0000-4000-8000-000000000012';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_operavel WHERE fact_key = 't103.patrimonio'
$sql$, 0, 'T105  derivado vencido sai da janela operável');

-- ================================================================ TESTE 106
-- O contrato do AGENTE não mudou: ele continua vendo só o que o cliente confirmou.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_current
   WHERE scope_id = '10300000-0000-4000-8000-000000000002'
$sql$, 1, 'T106  v_fact_current mostra só o fato confirmado (o derivado não entra)');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_current
   WHERE scope_id = '10300000-0000-4000-8000-000000000002' AND fact_key = 't103.patrimonio'
$sql$, 0, 'T106b patrimônio derivado NÃO aparece como verdade do cliente');

-- a cobertura passa a contar o que o motor consegue usar
UPDATE context.assertions SET valid_until = NULL
 WHERE id = '10300000-0000-4000-8000-000000000012';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_coverage
   WHERE scope_id = '10300000-0000-4000-8000-000000000002' AND fatos_presentes = 2
$sql$, 1, 'T106c cobertura conta o derivado — é ela que diz o que dá para calcular');

-- ================================================================ TESTE 107
-- A onda das perguntas depende disto: fato que a conversa pode atualizar tem que saber
-- COMO ser perguntado. `display_name` é rótulo de tela, não pergunta.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.fact_definitions
    (fact_key, subject_kind, attribute, family, display_name, value_type, unit,
     source_precedence, allows_conversation_update, materiality_abs)
  VALUES ('t103.sem_pergunta', 'renda', 't103_sem_pergunta', 'fluxo', 'Sem pergunta',
          'money_brl', 'BRL',
          ARRAY['formulario','conversa','operador']::context.assertion_source[], true, 100);
$sql$, 'T107  fato atualizável por conversa sem pergunta cadastrada');

-- o inverso passa: fato governado por outra fonte não precisa de pergunta
INSERT INTO context.fact_definitions
  (fact_key, subject_kind, attribute, family, display_name, value_type, unit,
   source_precedence, allows_conversation_update, materiality_abs)
VALUES ('t103.governado', 'patrimonio', 't103_governado', 'estoque', 'Governado',
        'money_brl', 'BRL',
        ARRAY['open_finance','inferencia_motor','operador']::context.assertion_source[], false, 100);
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.fact_definitions WHERE fact_key = 't103.governado'
$sql$, 1, 'T107b fato que ninguém pergunta não precisa de pergunta');

-- e o catálogo real está inteiro: todo fato perguntável tem pergunta
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.fact_definitions
   WHERE allows_conversation_update AND pergunta IS NULL AND fact_key NOT LIKE 't103.%'
$sql$, 0, 'T107c nenhum fato do catálogo v1 ficou sem pergunta');

-- ================================================================ TESTE 108
-- Achado ao rodar a derivação na persona: `protecao.lacuna_seguro_vida` publicou uma lacuna
-- de R$ 1,8 milhão para alguém de quem NÃO SE SABE se tem seguro. A cobertura do seguro
-- estava como insumo OPCIONAL, então ausência de dado virava "cobertura zero" — que é uma
-- afirmação, não uma ausência. Passa a ser insumo REQUERIDO: sem ele o indicador sai
-- indisponível e "você tem seguro de vida?" vira a próxima pergunta.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.indicator_definitions
   WHERE code = 'protecao.lacuna_seguro_vida'
     AND 'protecao.cobertura_vida' = ANY(required_fact_keys)
$sql$, 1, 'T108  a lacuna de seguro EXIGE saber se há seguro');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.indicator_definitions
   WHERE code = 'protecao.lacuna_seguro_vida'
     AND 'protecao.cobertura_vida' = ANY(optional_fact_keys)
$sql$, 0, 'T108b e não o trata mais como opcional');

-- ================================================================ TESTE 109
-- Também achado ao rodar: com uma só família crítica pontuada, ela era marcada "elo mais
-- fraco" por ser o mínimo de um conjunto de um. "Fluxo 1,00 ← elo mais fraco" é ruído com
-- cara de diagnóstico. Elo mais fraco exige comparação: no mínimo DUAS famílias críticas.
INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('10300000-0000-4000-8000-000000000020', '1.0.0', repeat('1', 40), repeat('3', 64));

INSERT INTO engine.policy_versions (id, code, version, payload, compliance_status,
                                    approved_by, approved_at)
VALUES ('10300000-0000-4000-8000-000000000021', 'T103_POLICY', 1, '{}'::jsonb, 'approved',
        '10300000-0000-4000-8000-000000000001', now());

INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date, is_client_facing)
VALUES ('10300000-0000-4000-8000-000000000022', '10300000-0000-4000-8000-000000000002',
        'client_profile', '10300000-0000-4000-8000-000000000020', repeat('7', 64),
        current_date, false);

-- só UMA família crítica com valor (a outra desativada)
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
VALUES ('10300000-0000-4000-8000-000000000002', current_date, 'score.fluxo',
        '10300000-0000-4000-8000-000000000022', 1.0, 1.0, 0.7,
        '10300000-0000-4000-8000-000000000021');
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, coverage, confidence,
   is_disabled, disabled_reason, policy_version_id)
VALUES ('10300000-0000-4000-8000-000000000002', current_date, 'score.protecao',
        '10300000-0000-4000-8000-000000000022', 0.3, 0.7,
        true, 'cobertura_insuficiente', '10300000-0000-4000-8000-000000000021');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '10300000-0000-4000-8000-000000000002'
     AND as_of_date = current_date AND elo_mais_fraco
$sql$, 0, 'T109  uma família crítica sozinha não é "elo mais fraco" — falta com quem comparar');

-- com a segunda família crítica pontuada, o elo aparece
UPDATE diagnostics.client_scores
   SET is_disabled = false, disabled_reason = NULL, value = 0.31, coverage = 0.8
 WHERE scope_id = '10300000-0000-4000-8000-000000000002'
   AND as_of_date = current_date AND score_code = 'score.protecao';

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '10300000-0000-4000-8000-000000000002'
     AND as_of_date = current_date AND elo_mais_fraco AND score_code = 'score.protecao'
$sql$, 1, 'T109b com duas críticas pontuadas, o elo é a menor delas');

-- ================================================================ TESTE 110
-- O gate C40d valia na ESCRITA e vazava na LEITURA: bastava calibrar sobre política em
-- rascunho (run interno) para o número aparecer em v_client_profile — e daí na tela.
-- Um gate que só vale na escrita não é gate, é convenção.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '10300000-0000-4000-8000-000000000002'
     AND as_of_date = current_date
     AND is_client_facing AND politica_aprovada
$sql$, 0, 'T110  score de run interno não é publicável, mesmo com política aprovada');

-- run client-facing sobre a MESMA política aprovada: publicável
INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date, is_client_facing)
VALUES ('10300000-0000-4000-8000-000000000023', '10300000-0000-4000-8000-000000000002',
        'client_profile', '10300000-0000-4000-8000-000000000020', repeat('8', 64),
        current_date - 1, true);
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
VALUES ('10300000-0000-4000-8000-000000000002', current_date - 1, 'score.fluxo',
        '10300000-0000-4000-8000-000000000023', 0.6, 1.0, 0.9,
        '10300000-0000-4000-8000-000000000021');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE as_of_date = current_date - 1 AND is_client_facing AND politica_aprovada
$sql$, 1, 'T110b run client-facing sobre política aprovada é publicável');

-- e o score de calibração continua VISÍVEL para a operação — só não é publicável
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '10300000-0000-4000-8000-000000000002' AND as_of_date = current_date
$sql$, 2, 'T110c calibração não some da view: some da TELA');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Derivação: o motor passa a enxergar o que o banco já sabia, sem'
\echo ' que nada disso seja apresentado ao cliente como se ele tivesse'
\echo ' confirmado. Duas janelas, e o confirmado sempre na frente.'
\echo '================================================================'
