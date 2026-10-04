-- =============================================================================
-- PLEXO · testes das regras invioláveis — onboarding obrigatório (T138–T141, 59_onboarding_fundacoes)
--   T138 gate de conclusão: onboarding só se declara completo com suitability VIGENTE
--        + fatos-núcleo CONFIRMADOS (lista da policy ONBOARDING_NUCLEO; fallback =
--        renda.mensal_liquida + despesa.total_mensal) + started_at + trilha; carimbo
--        de conclusão é imutável e não se des-conclui
--   T139 suitability: linha nova exige scope_id; resultado/answers/score vigentes são
--        imutáveis (refazer = nova linha + superseded_at, nunca UPDATE); linha superada
--        é imutável por inteiro; só 1 vigente por usuário
--   T140 identity.user_profiles sob plexo_app: cada usuário só vê e escreve a própria jornada
--   T141 analytics.onboarding_steps: app grava o próprio funil (e o anônimo), nunca o alheio;
--        linha anônima só volta para o serviço
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_onboarding.sql [plexo_service]
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
END;
$$;

CREATE OR REPLACE FUNCTION pg_temp.expect_count(p_sql text, p_expected bigint, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v bigint;
BEGIN
  EXECUTE 'SELECT count(*) FROM (' || p_sql || ') q' INTO v;
  IF v <> p_expected THEN
    RAISE EXCEPTION 'FALHOU: "%" — esperado % linha(s), papel enxergou %', p_label, p_expected, v;
  END IF;
  RAISE NOTICE 'ok   · % (% linha(s), como esperado)', p_label, v;
END;
$$;

-- Fato do catálogo nascido 'declarado' (C22a) e, se pedido, confirmado no segundo ato —
-- o mesmo padrão de aplicador.py/personas.py. Atenção: attribute NÃO é o sufixo do
-- fact_key (renda.mensal_liquida → renda_mensal_liquida; fluxo.aporte_mensal → despesa/aporte_mensal).
CREATE OR REPLACE FUNCTION pg_temp.fato(p_scope uuid, p_user uuid, p_key text,
    p_kind context.subject_kind, p_attr text, p_valor numeric, p_confirmar boolean) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_id uuid;
BEGIN
  INSERT INTO context.assertions
    (scope_id, user_id, subject_kind, attribute, fact_key, value, unit,
     modality, status, source, confidence)
  VALUES
    (p_scope, p_user, p_kind, p_attr, p_key, jsonb_build_object('amount', p_valor), 'BRL',
     'fato', 'declarado', 'formulario', 0.9)
  RETURNING id INTO v_id;
  IF p_confirmar THEN
    UPDATE context.assertions
       SET status = 'confirmado', confirmed_at = now(), confirmed_by = p_user
     WHERE id = v_id;
  END IF;
END;
$$;

BEGIN;
SET LOCAL app.role = 'service';   -- fixtures como serviço/administrador

-- ---------------------------------------------------------------- fixtures
-- U1/S1 completo (fatos-núcleo confirmados + suitability vigente) — conclui sob plexo_app
-- U2/S2 sem nada — sem suitability
-- U3/S3 fatos ok + suitability VENCIDA
-- U4/S4 suitability ok + despesa apenas DECLARADA
-- U5/S5 e U6/S6 completos — sabotagens de started/trilha
-- U7/S7 núcleo ok, sem aporte — a policy ONBOARDING_NUCLEO passa a exigir o aporte
INSERT INTO identity.users (id, email, full_name, status)
SELECT ('13800000-0000-4000-8000-00000000000' || n)::uuid,
       't' || n || '-t138@plexo.local', 'Usuário T138-' || n, 'active'
FROM generate_series(1, 7) n;

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
SELECT ('13800000-0000-4000-8000-0000000000a' || n)::uuid, 'personal', 'S' || n,
       ('13800000-0000-4000-8000-00000000000' || n)::uuid
FROM generate_series(1, 7) n;

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at)
SELECT ('13800000-0000-4000-8000-0000000000a' || n)::uuid,
       ('13800000-0000-4000-8000-00000000000' || n)::uuid, 'owner', now()
FROM generate_series(1, 7) n;

-- fatos-núcleo (renda + despesa) confirmados para S1, S3, S5, S6, S7; no S4 a despesa fica declarada
SELECT pg_temp.fato(('13800000-0000-4000-8000-0000000000a' || n)::uuid,
                    ('13800000-0000-4000-8000-00000000000' || n)::uuid,
                    'renda.mensal_liquida', 'renda', 'renda_mensal_liquida', 12000, true)
FROM unnest(ARRAY[1, 3, 4, 5, 6, 7]) n;
SELECT pg_temp.fato(('13800000-0000-4000-8000-0000000000a' || n)::uuid,
                    ('13800000-0000-4000-8000-00000000000' || n)::uuid,
                    'despesa.total_mensal', 'despesa', 'despesa_total_mensal', 8000, true)
FROM unnest(ARRAY[1, 3, 5, 6, 7]) n;
SELECT pg_temp.fato('13800000-0000-4000-8000-0000000000a4', '13800000-0000-4000-8000-000000000004',
                    'despesa.total_mensal', 'despesa', 'despesa_total_mensal', 8000, false);

-- suitability: vigente para U1, U4, U5, U6, U7; vencida (mas não superada) para U3
INSERT INTO identity.suitability_assessments
  (id, user_id, scope_id, questionnaire_version, answers, result, score, valid_until)
SELECT ('13800000-0000-4000-8000-0000000000b' || n)::uuid,
       ('13800000-0000-4000-8000-00000000000' || n)::uuid,
       ('13800000-0000-4000-8000-0000000000a' || n)::uuid,
       'suit-plexo-v1', '{"reacao_queda": "manter"}'::jsonb, 'moderado', 6,
       current_date + 365
FROM unnest(ARRAY[1, 4, 5, 6, 7]) n;
INSERT INTO identity.suitability_assessments
  (id, user_id, scope_id, questionnaire_version, answers, result, score, valid_until)
VALUES ('13800000-0000-4000-8000-0000000000b3', '13800000-0000-4000-8000-000000000003',
        '13800000-0000-4000-8000-0000000000a3', 'suit-plexo-v1',
        '{"reacao_queda": "manter"}'::jsonb, 'moderado', 6, current_date - 1);

-- ================================================================ TESTE 138 (gate de conclusão)
SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.user_profiles (user_id, onboarding_track, onboarding_started_at, onboarding_completed_at)
  VALUES ('13800000-0000-4000-8000-000000000002', 'a_nao_investe', now() - interval '1 hour', now());
$sql$, 'T138a concluir sem suitability vigente é rejeitado');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.user_profiles (user_id, onboarding_track, onboarding_started_at, onboarding_completed_at)
  VALUES ('13800000-0000-4000-8000-000000000003', 'b_ja_investe', now() - interval '1 hour', now());
$sql$, 'T138b suitability vencida não sustenta conclusão');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.user_profiles (user_id, onboarding_track, onboarding_started_at, onboarding_completed_at)
  VALUES ('13800000-0000-4000-8000-000000000004', 'a_nao_investe', now() - interval '1 hour', now());
$sql$, 'T138c fato-núcleo apenas declarado (não confirmado) não sustenta conclusão');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.user_profiles (user_id, onboarding_track, onboarding_completed_at)
  VALUES ('13800000-0000-4000-8000-000000000005', 'a_nao_investe', now());
$sql$, 'T138d concluído sem onboarding_started_at é rejeitado');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.user_profiles (user_id, onboarding_started_at, onboarding_completed_at)
  VALUES ('13800000-0000-4000-8000-000000000006', now() - interval '1 hour', now());
$sql$, 'T138e concluído sem trilha é rejeitado');

-- caminho feliz sob o PAPEL REAL: o gate consulta suitability e v_fact_current
-- através da RLS de quem conclui — é assim que a API vai rodar.
SET LOCAL ROLE plexo_app;
SET LOCAL app.role = 'user';
SET LOCAL app.user_id = '13800000-0000-4000-8000-000000000001';
SET LOCAL app.scope_id = '13800000-0000-4000-8000-0000000000a1';

INSERT INTO identity.user_profiles (user_id, onboarding_track, onboarding_started_at, onboarding_step)
VALUES ('13800000-0000-4000-8000-000000000001', 'b_ja_investe', now() - interval '1 hour', 'suitability');

DO $$
DECLARE n int;
BEGIN
  UPDATE identity.user_profiles
     SET onboarding_completed_at = now(), onboarding_step = 'output'
   WHERE user_id = '13800000-0000-4000-8000-000000000001';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN
    RAISE EXCEPTION 'FALHOU T138f: conclusão legítima sob plexo_app deveria atingir 1 linha, atingiu %', n;
  END IF;
  RAISE NOTICE 'ok   · T138f com suitability vigente + fatos-núcleo confirmados, plexo_app conclui';
END $$;

SELECT pg_temp.expect_fail($sql$
  UPDATE identity.user_profiles SET onboarding_completed_at = NULL
   WHERE user_id = '13800000-0000-4000-8000-000000000001';
$sql$, 'T138g onboarding concluído não se des-conclui');

SELECT pg_temp.expect_fail($sql$
  UPDATE identity.user_profiles SET onboarding_completed_at = now() + interval '1 hour'
   WHERE user_id = '13800000-0000-4000-8000-000000000001';
$sql$, 'T138h o carimbo de conclusão é imutável');

RESET ROLE;
SET LOCAL app.role = 'service';

-- a lista de fatos-núcleo é CONFIG: publicada uma versão da policy exigindo também o
-- aporte, quem não o confirmou deixa de conseguir concluir (mesmo padrão FAMILY_LIMITS).
UPDATE engine.policy_versions SET effective_to = clock_timestamp()
 WHERE code = 'ONBOARDING_NUCLEO' AND effective_to IS NULL;
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'ONBOARDING_NUCLEO', coalesce(max(version), 0) + 1,
       '{"fatos_nucleo": ["renda.mensal_liquida", "despesa.total_mensal", "fluxo.aporte_mensal"]}'::jsonb,
       'draft', clock_timestamp()
  FROM engine.policy_versions WHERE code = 'ONBOARDING_NUCLEO';

SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.user_profiles (user_id, onboarding_track, onboarding_started_at, onboarding_completed_at)
  VALUES ('13800000-0000-4000-8000-000000000007', 'b_ja_investe', now() - interval '1 hour', now());
$sql$, 'T138i a policy manda: sem o fato extra exigido, não conclui');

SELECT pg_temp.fato('13800000-0000-4000-8000-0000000000a7', '13800000-0000-4000-8000-000000000007',
                    'fluxo.aporte_mensal', 'despesa', 'aporte_mensal', 2500, true);
DO $$
DECLARE n int;
BEGIN
  INSERT INTO identity.user_profiles (user_id, onboarding_track, onboarding_started_at, onboarding_completed_at)
  VALUES ('13800000-0000-4000-8000-000000000007', 'b_ja_investe', now() - interval '1 hour', now());
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FALHOU T138j: com o fato extra confirmado deveria concluir'; END IF;
  RAISE NOTICE 'ok   · T138j confirmado o fato extra da policy, a conclusão passa';
END $$;

-- ================================================================ TESTE 139 (suitability)
SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.suitability_assessments
    (user_id, scope_id, questionnaire_version, answers, result, score, valid_until)
  VALUES ('13800000-0000-4000-8000-000000000002', NULL, 'suit-plexo-v1',
          '{"reacao_queda": "vender_tudo"}'::jsonb, 'conservador', 1, current_date + 365);
$sql$, 'T139a suitability sem scope_id é rejeitada');

SELECT pg_temp.expect_fail($sql$
  UPDATE identity.suitability_assessments SET result = 'arrojado'
   WHERE id = '13800000-0000-4000-8000-0000000000b1';
$sql$, 'T139b resultado vigente é imutável — refazer é nova linha');

SELECT pg_temp.expect_fail($sql$
  UPDATE identity.suitability_assessments SET score = 99
   WHERE id = '13800000-0000-4000-8000-0000000000b1';
$sql$, 'T139c score vigente é imutável');

DO $$
DECLARE n int;
BEGIN
  UPDATE identity.suitability_assessments SET superseded_at = now()
   WHERE id = '13800000-0000-4000-8000-0000000000b3';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FALHOU T139d: supersessão legítima deveria atingir 1 linha'; END IF;
  INSERT INTO identity.suitability_assessments
    (user_id, scope_id, questionnaire_version, answers, result, score, valid_until)
  VALUES ('13800000-0000-4000-8000-000000000003', '13800000-0000-4000-8000-0000000000a3',
          'suit-plexo-v1', '{"reacao_queda": "aportar_mais"}'::jsonb, 'arrojado', 11, current_date + 365);
  RAISE NOTICE 'ok   · T139d refazer = superseded_at na antiga + linha nova vigente';
END $$;

SELECT pg_temp.expect_fail($sql$
  UPDATE identity.suitability_assessments SET answers = '{"editado": true}'::jsonb
   WHERE id = '13800000-0000-4000-8000-0000000000b3';
$sql$, 'T139e linha superada é imutável por inteiro (trilha point-in-time)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.suitability_assessments
    (user_id, scope_id, questionnaire_version, answers, result, score, valid_until)
  VALUES ('13800000-0000-4000-8000-000000000001', '13800000-0000-4000-8000-0000000000a1',
          'suit-plexo-v1', '{"x": 1}'::jsonb, 'moderado', 6, current_date + 365);
$sql$, 'T139f duas suitability vigentes para o mesmo usuário não existem');

-- ================================================================ TESTE 140 (user_profiles sob plexo_app)
SET LOCAL ROLE plexo_app;
SET LOCAL app.role = 'user';
SET LOCAL app.user_id = '13800000-0000-4000-8000-000000000001';
SET LOCAL app.scope_id = '13800000-0000-4000-8000-0000000000a1';

SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.user_profiles $sql$, 1,
  'T140a plexo_app vê apenas a própria jornada');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM identity.user_profiles WHERE user_id = '13800000-0000-4000-8000-000000000007'
$sql$, 0, 'T140b a jornada alheia não existe para plexo_app');
DO $$
DECLARE n int;
BEGIN
  UPDATE identity.user_profiles SET answers = answers || '{"nota": "editado pelo dono"}'::jsonb
   WHERE user_id = '13800000-0000-4000-8000-000000000001';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FALHOU T140c: dono deveria editar answers da própria jornada'; END IF;
  RAISE NOTICE 'ok   · T140c dono edita a própria jornada (answers)';
END $$;
SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.user_profiles (user_id) VALUES ('13800000-0000-4000-8000-000000000002');
$sql$, 'T140d plexo_app não cria jornada para outro usuário');

-- ================================================================ TESTE 141 (funil sob plexo_app)
DO $$
BEGIN
  INSERT INTO analytics.onboarding_steps (user_id, track, step_code, step_index)
  VALUES ('13800000-0000-4000-8000-000000000001', 'b_ja_investe', 'intro', 0);
  INSERT INTO analytics.onboarding_steps (user_id, anonymous_id, step_code, step_index)
  VALUES (NULL, 'anon-t141', 'intro', 0);
  RAISE NOTICE 'ok   · T141a app grava o próprio funil e o funil anônimo';
END $$;
SELECT pg_temp.expect_fail($sql$
  INSERT INTO analytics.onboarding_steps (user_id, step_code, step_index)
  VALUES ('13800000-0000-4000-8000-000000000002', 'intro', 0);
$sql$, 'T141b funil de outro usuário não se grava');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analytics.onboarding_steps WHERE anonymous_id = 'anon-t141'
$sql$, 0, 'T141c linha anônima não volta para o papel de app (só o serviço lê)');

RESET ROLE;
ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Onboarding: cada "ok" acima é um caminho de conclusão forjada,'
\echo ' suitability reescrita ou vazamento de jornada que o banco recusa.'
\echo '================================================================'
