-- =============================================================================
-- PLEXO · testes das regras invioláveis — indicadores e scores do cliente
--   (T95–T102, 40_client_profile.sql)
--   T95  indicador que exige fato fora do catálogo é recusado
--   T96  score sem indicador válido, ou de família que não é score, é recusado
--   T97  indisponível XOR valor — em indicador e em score
--   T98  Fundação crítica DESATIVA o score; não o rebaixa
--   T99  cobertura abaixo do mínimo não vira score imputado
--   T100 score client-facing exige política APROVADA por compliance
--   T101 score vive em [0,1]; cobertura e confiança também
--   T102 v_client_profile aponta o elo mais fraco entre as famílias críticas
--   T102d empate dentro da margem da política não aponta elo (47)
--   T102e uma única família crítica pontuada não produz elo (44)
--
-- Por que este arquivo existe: `diagnostics.portfolio_scores` já provava, desde a 06,
-- que um score pode faltar em vez de mentir (D11: Fundação crítica DESATIVA o score,
-- não o abaixa). Essa disciplina valia para a carteira. Estes testes a estendem para
-- o cliente — que é onde ela importa mais, porque o cliente não tem como conferir.
--
-- As três regras que sustentam o resto:
--   (T98) uma falha crítica não é diluída por força em outra família;
--   (T99) score sem base não sai — sai "indisponível, falta X". Isso é rede de
--         compliance e, ao mesmo tempo, a mecânica de onboarding: o dado que
--         falta vira a próxima pergunta, não um campo em branco;
--   (T100) número client-facing só sai de premissa que compliance aprovou (RCVM 19).
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_scores.sql [plexo_service]
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

-- ---------------------------------------------------------------- fixture (prefixo 9595 = T95)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('95950000-0000-4000-8000-000000000001', 't95-titular@teste.local', 'Titular T95', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('95950000-0000-4000-8000-000000000002', 'personal', 'Pessoal T95',
        '95950000-0000-4000-8000-000000000001');

INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('95950000-0000-4000-8000-000000000003', '1.0.0', repeat('9', 40), repeat('5', 64));

-- política DRAFT e política APROVADA — o par que o T100 usa
INSERT INTO engine.policy_versions (id, code, version, payload, compliance_status)
VALUES ('95950000-0000-4000-8000-000000000004', 'T95_RASCUNHO', 1, '{"pontos": []}'::jsonb, 'draft');

INSERT INTO engine.policy_versions (id, code, version, payload, compliance_status,
                                    approved_by, approved_at)
VALUES ('95950000-0000-4000-8000-000000000005', 'T95_APROVADA', 1, '{"pontos": []}'::jsonb,
        'approved', '95950000-0000-4000-8000-000000000001', now());

-- run client-facing e run interno
INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date, is_client_facing)
VALUES ('95950000-0000-4000-8000-000000000006', '95950000-0000-4000-8000-000000000002',
        'client_profile', '95950000-0000-4000-8000-000000000003', repeat('a', 64),
        current_date, true),
       ('95950000-0000-4000-8000-000000000007', '95950000-0000-4000-8000-000000000002',
        'client_profile', '95950000-0000-4000-8000-000000000003', repeat('b', 64),
        current_date, false);

-- catálogo isolado, como nos arquivos irmãos
UPDATE context.fact_definitions SET is_active = false;
-- `pergunta` é obrigatória para fato askable (CHECK `askable_has_question`, migration 43):
-- se o motor pode pedir o fato ao cliente, tem que existir a frase com que ele pede.
INSERT INTO context.fact_definitions
  (fact_key, subject_kind, attribute, family, display_name, pergunta, value_type, unit,
   source_precedence, half_life_days, materiality_abs, materiality_rel)
VALUES
  ('t95.reserva', 'patrimonio', 't95_reserva', 'protecao', 'Reserva (T95)',
   'Quanto você tem guardado para imprevisto?', 'money_brl', 'BRL',
   ARRAY['formulario','conversa','operador']::context.assertion_source[], 90, 1000, 0.05),
  ('t95.despesa', 'despesa', 't95_despesa', 'fluxo', 'Despesa (T95)',
   'Quanto sai por mês com o essencial?', 'money_brl', 'BRL',
   ARRAY['formulario','conversa','operador']::context.assertion_source[], 180, 300, 0.10);

-- ================================================================ TESTE 95
-- Indicador é contrato: ele declara de QUE fatos depende, e é dessa lista que a
-- cobertura sai. Fato fora do catálogo tornaria a cobertura incalculável.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.indicator_definitions
    (code, family, display_name, value_type, higher_is_better, required_fact_keys, formula_ref)
  VALUES ('t95.indicador_fantasma', 'protecao', 'Indicador fantasma', 'meses', true,
          ARRAY['t95.reserva','fato.que.nao.existe']::core.slug[], 'calcular_fantasma');
$sql$, 'T95  indicador que exige fato fora do catálogo');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.indicator_definitions
    (code, family, display_name, value_type, higher_is_better, required_fact_keys, formula_ref)
  VALUES ('t95.sem_insumo', 'protecao', 'Indicador sem insumo', 'meses', true,
          ARRAY[]::core.slug[], 'calcular_nada');
$sql$, 'T95b indicador sem nenhum fato requerido');

-- caminho feliz
INSERT INTO diagnostics.indicator_definitions
  (code, family, display_name, unit, value_type, higher_is_better, required_fact_keys, formula_ref)
VALUES ('t95.cobertura_reserva', 'protecao', 'Cobertura da reserva (T95)', 'meses', 'meses', true,
        ARRAY['t95.reserva','t95.despesa']::core.slug[], 'cobertura_reserva_meses');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.indicator_definitions WHERE code = 't95.cobertura_reserva'
$sql$, 1, 'T95c indicador com insumos catalogados é aceito');

-- ================================================================ TESTE 96
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.score_definitions
    (code, family, display_name, indicator_codes, is_critical_family)
  VALUES ('t95.score_fantasma', 'protecao', 'Score fantasma',
          ARRAY['indicador.inexistente']::core.slug[], true);
$sql$, 'T96  score que aponta indicador inexistente');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.score_definitions
    (code, family, display_name, indicator_codes, is_critical_family)
  VALUES ('t95.score_vida', 'vida', 'Score de contexto de vida',
          ARRAY['t95.cobertura_reserva']::core.slug[], false);
$sql$, 'T96b "vida" é contexto que MODULA o score, não família de score');

INSERT INTO diagnostics.score_definitions
  (code, family, display_name, indicator_codes, is_critical_family, min_coverage)
-- [47] As TRÊS são críticas de propósito: desde a migration 44 o elo mais fraco exige DUAS
-- famílias críticas pontuadas, e desde a 47 exige margem entre a menor e a segunda. Com uma
-- família crítica só, o T102 provava uma regra que o banco não tem mais.
VALUES ('t95.protecao', 'protecao', 'Proteção (T95)',
        ARRAY['t95.cobertura_reserva']::core.slug[], true, 0.6),
       ('t95.estoque', 'estoque', 'Estoque (T95)',
        ARRAY['t95.cobertura_reserva']::core.slug[], true, 0.6),
       ('t95.fluxo', 'fluxo', 'Fluxo (T95)',
        ARRAY['t95.cobertura_reserva']::core.slug[], true, 0.6);
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.score_definitions WHERE code LIKE 't95.%'
$sql$, 3, 'T96c os três scores de teste cadastrados');

-- ================================================================ TESTE 97
-- Indisponível não é zero, e zero não é indisponível. As duas coisas nunca coexistem.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_indicators
    (scope_id, as_of_date, indicator_code, run_id, value, coverage, confidence,
     is_unavailable, unavailable_reason)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.cobertura_reserva',
          '95950000-0000-4000-8000-000000000007', 4.2, 1.0, 0.9, true, 'dados_insuficientes');
$sql$, 'T97  indicador indisponível COM valor');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_indicators
    (scope_id, as_of_date, indicator_code, run_id, coverage, confidence, is_unavailable)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.cobertura_reserva',
          '95950000-0000-4000-8000-000000000007', 0.5, 0.5, true);
$sql$, 'T97b indicador indisponível SEM motivo declarado');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_indicators
    (scope_id, as_of_date, indicator_code, run_id, coverage, confidence)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.cobertura_reserva',
          '95950000-0000-4000-8000-000000000007', 1.0, 0.9);
$sql$, 'T97c indicador disponível SEM valor');

INSERT INTO diagnostics.client_indicators
  (scope_id, as_of_date, indicator_code, run_id, value, unit, coverage, confidence, inputs)
VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.cobertura_reserva',
        '95950000-0000-4000-8000-000000000007', 4.2, 'meses', 1.0, 0.9,
        '{"t95.reserva": {"amount": 21000}, "t95.despesa": {"amount": 5000}}'::jsonb);
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.client_indicators
   WHERE scope_id = '95950000-0000-4000-8000-000000000002' AND value = 4.2
$sql$, 1, 'T97d indicador com valor, cobertura, confiança e insumos gravados');

-- ================================================================ TESTE 98
-- D11 estendida ao cliente: Fundação crítica DESATIVA o score. Não é score baixo —
-- é ausência de score. Média ponderada esconderia rotativo aberto atrás de carteira boa.
INSERT INTO diagnostics.foundation_status
  (scope_id, as_of_date, run_id, monthly_cost_brl, reserve_amount_brl, reserve_months,
   reserve_target_months, reserve_light, debt_light, overall_light, is_critical)
VALUES ('95950000-0000-4000-8000-000000000002', current_date,
        '95950000-0000-4000-8000-000000000007', 5000, 2000, 0.4, 6,
        'vermelho', 'vermelho', 'vermelho', true);

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_scores
    (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.protecao',
          '95950000-0000-4000-8000-000000000007', 0.72, 1.0, 0.9,
          '95950000-0000-4000-8000-000000000005');
$sql$, 'T98  score com valor enquanto a Fundação está crítica');

INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, coverage, confidence,
   is_disabled, disabled_reason, policy_version_id)
VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.protecao',
        '95950000-0000-4000-8000-000000000007', 1.0, 0.9,
        true, 'fundacao_critica', '95950000-0000-4000-8000-000000000005');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.client_scores
   WHERE score_code = 't95.protecao' AND is_disabled AND disabled_reason = 'fundacao_critica'
$sql$, 1, 'T98b com a Fundação crítica, o score sai DESATIVADO');

-- e o motivo tem que ser o certo: desativar por outro motivo mascararia a Fundação
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_scores
    (scope_id, as_of_date, score_code, run_id, coverage, confidence,
     is_disabled, disabled_reason, policy_version_id)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.estoque',
          '95950000-0000-4000-8000-000000000007', 1.0, 0.9,
          true, 'dados_insuficientes', '95950000-0000-4000-8000-000000000005');
$sql$, 'T98c Fundação crítica desativa POR ELA, não por outro motivo');

-- ================================================================ TESTE 99
-- Cobertura insuficiente não vira imputação silenciosa.
UPDATE diagnostics.foundation_status SET is_critical = false, overall_light = 'amarelo'
 WHERE scope_id = '95950000-0000-4000-8000-000000000002';

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_scores
    (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.estoque',
          '95950000-0000-4000-8000-000000000007', 0.5, 0.3, 0.9,
          '95950000-0000-4000-8000-000000000005');
$sql$, 'T99  score com cobertura 0,30 abaixo do mínimo 0,60 do cadastro');

INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, coverage, confidence,
   is_disabled, disabled_reason, policy_version_id)
VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.estoque',
        '95950000-0000-4000-8000-000000000007', 0.3, 0.5,
        true, 'cobertura_insuficiente', '95950000-0000-4000-8000-000000000005');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.client_scores
   WHERE score_code = 't95.estoque' AND disabled_reason = 'cobertura_insuficiente'
$sql$, 1, 'T99b sem base, o score sai indisponível — e diz por quê');

-- ================================================================ TESTE 100
-- RCVM 19: número que o cliente lê sai de premissa que compliance aprovou.
DELETE FROM diagnostics.client_scores WHERE score_code = 't95.protecao';
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_scores
    (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.protecao',
          '95950000-0000-4000-8000-000000000006', 0.72, 1.0, 0.9,
          '95950000-0000-4000-8000-000000000004');
$sql$, 'T100 score client-facing sobre política em rascunho');

INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.protecao',
        '95950000-0000-4000-8000-000000000006', 0.31, 1.0, 0.9,
        '95950000-0000-4000-8000-000000000005');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.client_scores
   WHERE score_code = 't95.protecao' AND value = 0.31
$sql$, 1, 'T100b com política aprovada, o score client-facing entra');

-- run interno pode usar rascunho: é assim que se calibra antes de publicar
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
VALUES ('95950000-0000-4000-8000-000000000002', current_date - 1, 't95.protecao',
        '95950000-0000-4000-8000-000000000007', 0.44, 1.0, 0.9,
        '95950000-0000-4000-8000-000000000004');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.client_scores
   WHERE score_code = 't95.protecao' AND as_of_date = current_date - 1
$sql$, 1, 'T100c run interno pode calibrar sobre rascunho');

-- ================================================================ TESTE 101
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_scores
    (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date - 2, 't95.protecao',
          '95950000-0000-4000-8000-000000000007', 1.4, 1.0, 0.9,
          '95950000-0000-4000-8000-000000000005');
$sql$, 'T101 score fora de [0,1]');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.client_scores
    (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
  VALUES ('95950000-0000-4000-8000-000000000002', current_date - 2, 't95.protecao',
          '95950000-0000-4000-8000-000000000007', 0.5, 1.7, 0.9,
          '95950000-0000-4000-8000-000000000005');
$sql$, 'T101b cobertura fora de [0,1]');

-- ================================================================ TESTE 102
-- Sem score único: o que a tela lê é o perfil por família com o elo mais fraco
-- marcado entre as CRÍTICAS. É dele que sai a próxima ação.
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
VALUES ('95950000-0000-4000-8000-000000000002', current_date - 3, 't95.protecao',
        '95950000-0000-4000-8000-000000000006', 0.31, 1.0, 0.9,
        '95950000-0000-4000-8000-000000000005'),
       ('95950000-0000-4000-8000-000000000002', current_date - 3, 't95.estoque',
        '95950000-0000-4000-8000-000000000006', 0.72, 1.0, 0.9,
        '95950000-0000-4000-8000-000000000005');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '95950000-0000-4000-8000-000000000002'
     AND as_of_date = current_date - 3 AND elo_mais_fraco
$sql$, 1, 'T102 exatamente um elo mais fraco por escopo e data');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '95950000-0000-4000-8000-000000000002'
     AND as_of_date = current_date - 3 AND elo_mais_fraco
     AND score_code = 't95.protecao'
$sql$, 1, 'T102b o elo mais fraco é a família crítica com o menor score');

-- score desativado não concorre a elo mais fraco: ausência não é fraqueza.
-- Em `current_date` o estoque está indisponível (T99b) e a proteção vale 0,31; o fluxo entra
-- aqui como o segundo crítico ATIVO, sem o qual não há contra quem medir margem.
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
VALUES ('95950000-0000-4000-8000-000000000002', current_date, 't95.fluxo',
        '95950000-0000-4000-8000-000000000006', 0.80, 1.0, 0.9,
        '95950000-0000-4000-8000-000000000005');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '95950000-0000-4000-8000-000000000002'
     AND as_of_date = current_date AND elo_mais_fraco
$sql$, 1, 'T102c o score desativado não concorre — o elo sai dos ativos');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '95950000-0000-4000-8000-000000000002'
     AND as_of_date = current_date AND elo_mais_fraco AND score_code = 't95.protecao'
$sql$, 1, 'T102c2 e é a menor entre as ATIVAS, não a indisponível');

-- ================================================================ TESTE 102d  [47]
-- Empate técnico não vira próxima ação. A diferença abaixo da margem da política é ruído, e
-- ruído apresentado como sinal manda o cliente agir sobre uma distinção que o motor não
-- consegue justificar. O valor do desempate sai da POLÍTICA, não deste arquivo: teste com
-- número mágico próprio deixa de acompanhar a premissa quando ela muda.
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
SELECT '95950000-0000-4000-8000-000000000002', current_date - 4, c.code,
       '95950000-0000-4000-8000-000000000006', c.v, 1.0, 0.9,
       '95950000-0000-4000-8000-000000000005'
  FROM (SELECT (payload ->> 'margem_minima_do_elo')::numeric AS m
          FROM engine.policy_versions
         WHERE code = 'CLIENT_SCORES' AND effective_to IS NULL) p,
       LATERAL (VALUES ('t95.protecao', 0.50::numeric),
                       ('t95.estoque',  0.50 + p.m / 2)) AS c(code, v);

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '95950000-0000-4000-8000-000000000002'
     AND as_of_date = current_date - 4 AND elo_mais_fraco
$sql$, 0, 'T102d diferença abaixo da margem não aponta elo nenhum');

-- ================================================================ TESTE 102e  [44]
-- Uma família crítica sozinha é a mais fraca por falta de concorrente, não por diagnóstico.
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
VALUES ('95950000-0000-4000-8000-000000000002', current_date - 5, 't95.protecao',
        '95950000-0000-4000-8000-000000000006', 0.20, 1.0, 0.9,
        '95950000-0000-4000-8000-000000000005');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.v_client_profile
   WHERE scope_id = '95950000-0000-4000-8000-000000000002'
     AND as_of_date = current_date - 5 AND elo_mais_fraco
$sql$, 0, 'T102e com uma única família crítica pontuada, não há elo');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Scores do cliente: Fundação crítica DESATIVA, cobertura baixa'
\echo ' não imputa, número client-facing exige política aprovada — e'
\echo ' não existe score único onde uma falha crítica possa se esconder.'
\echo '================================================================'
