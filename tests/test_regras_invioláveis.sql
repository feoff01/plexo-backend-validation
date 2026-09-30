-- =============================================================================
-- SYNAPTA · testes das regras invioláveis (§16.1)
-- Cada teste prova que o BANCO recusa a violação — não a aplicação.
-- Rodar com: psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_regras_invioláveis.sql
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

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixtures
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('11111111-1111-1111-1111-111111111111', 'teste@synapta.com.br', 'Teste', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('22222222-2222-2222-2222-222222222222', 'personal', 'Pessoal',
        '11111111-1111-1111-1111-111111111111');

INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('33333333-3333-3333-3333-333333333333', '1.0.0', repeat('a',40), repeat('b',64));

UPDATE engine.policy_versions
   SET compliance_status = 'approved', approved_at = now()
 WHERE code = 'ACTION_GOVERNANCE';

INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date,
                         policy_version_ids, is_client_facing)
VALUES ('44444444-4444-4444-4444-444444444444','22222222-2222-2222-2222-222222222222',
        'raiox','33333333-3333-3333-3333-333333333333', repeat('c',64), current_date,
        '{}', true);

-- `quantification` preenchida desde a migration 54: tipo quantificável sem o número é
-- recusado pelo banco (T122). A fixture ganhou o campo — nenhuma asserção deste arquivo
-- mudou; o que mudou é que ela passou a ser um finding legal, com o "quanto" que a ação
-- adiante precisa exibir no bloco de quantificação.
INSERT INTO diagnostics.findings
  (id, scope_id, finding_type_code, finding_key, severity, confidence,
   impact_brl_year, execution_friction, quantification, first_run_id, last_run_id)
VALUES ('55555555-5555-5555-5555-555555555555','22222222-2222-2222-2222-222222222222',
        'custo.taxa_fundo_alta','custo.taxa_fundo_alta:instrument:abc','alta',0.9,
        4200, 2,'{"taxa_aa": 0.023, "referencia_aa": 0.012, "custo_ano_brl": 4200}'::jsonb,
        '44444444-4444-4444-4444-444444444444','44444444-4444-4444-4444-444444444444');

-- ================================================================ TESTE 1
-- §16.1.10 / gate de compliance: run client-facing com política em draft
SELECT pg_temp.expect_fail($sql$
  INSERT INTO engine.runs (scope_id, kind, engine_version_id, input_hash, as_of_date,
                           policy_version_ids, is_client_facing)
  SELECT '22222222-2222-2222-2222-222222222222','builder',
         '33333333-3333-3333-3333-333333333333', repeat('d',64), current_date,
         array[id], true
  FROM engine.policy_versions WHERE code = 'DRIFT_BANDS';
$sql$, 'T1  run client-facing com política não aprovada por compliance');

-- ================================================================ TESTE 1b
-- [3ª onda] freeze endurecido: run finalizado não pode ser "reaberto" nem editado;
-- a única transição válida é succeeded → superseded, sem tocar em mais nada.
INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date,
                         policy_version_ids, is_client_facing)
VALUES ('bbbbbbbb-0000-0000-0000-000000000001','22222222-2222-2222-2222-222222222222',
        'score','33333333-3333-3333-3333-333333333333', repeat('e',64), current_date,
        '{}', false);
UPDATE engine.runs SET status = 'succeeded', finished_at = now(), duration_ms = 10
 WHERE id = 'bbbbbbbb-0000-0000-0000-000000000001';

SELECT pg_temp.expect_fail($sql$
  UPDATE engine.runs SET status = 'queued'
   WHERE id = 'bbbbbbbb-0000-0000-0000-000000000001';
$sql$, 'T1b run finalizado sendo "reaberto" (succeeded → queued)');

SELECT pg_temp.expect_fail($sql$
  UPDATE engine.runs SET duration_ms = 99999
   WHERE id = 'bbbbbbbb-0000-0000-0000-000000000001';
$sql$, 'T1b run finalizado sendo editado sem mudar status');

SELECT pg_temp.expect_fail($sql$
  UPDATE engine.runs SET status = 'superseded', duration_ms = 99999
   WHERE id = 'bbbbbbbb-0000-0000-0000-000000000001';
$sql$, 'T1b supersedência tentando alterar outro campo junto');

UPDATE engine.runs SET status = 'superseded'
 WHERE id = 'bbbbbbbb-0000-0000-0000-000000000001';
DO $$ BEGIN RAISE NOTICE 'ok   · T1b succeeded → superseded (só o status) foi aceito'; END $$;

-- ================================================================ TESTE 2
-- §16.5: ação sem os 5 blocos obrigatórios
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.actions (scope_id, finding_id, blocks, run_id)
  VALUES ('22222222-2222-2222-2222-222222222222',
          '55555555-5555-5555-5555-555555555555',
          '{"gatilho":"x","evidencia":"y","passo":"z"}'::jsonb,
          '44444444-4444-4444-4444-444444444444');
$sql$, 'T2  ação sem quantificação e sem "por que agora"');

-- ação válida, para os testes seguintes
INSERT INTO diagnostics.actions (id, scope_id, finding_id, blocks, run_id, is_featured)
VALUES ('66666666-6666-6666-6666-666666666666','22222222-2222-2222-2222-222222222222',
        '55555555-5555-5555-5555-555555555555',
        '{"gatilho":"3 fundos DI com taxa média de 0,9% a.a.",
          "evidencia":{"posicoes":["a","b","c"]},
          "quantificacao":{"impacto_brl_ano":4200,"metodologia":"..."},
          "passo":"Migrar para Tesouro Selic 2029",
          "porque_agora":"não é urgente"}'::jsonb,
        '44444444-4444-4444-4444-444444444444', true);
DO $$ BEGIN RAISE NOTICE 'ok   · T3  ação com os 5 blocos foi aceita'; END $$;

-- ================================================================ TESTE 4
-- §16.5 / §4.1: máximo 1 ação ativa exibida por escopo
INSERT INTO diagnostics.findings
  (id, scope_id, finding_type_code, finding_key, severity, confidence,
   impact_brl_year, execution_friction, quantification, first_run_id, last_run_id)
VALUES ('77777777-7777-7777-7777-777777777777','22222222-2222-2222-2222-222222222222',
        'risco.concentracao_emissor','risco.concentracao_emissor:issuer:xyz','alta',0.95,
        9000, 3,'{"exposicao_brl": 180000, "share_pct": 41.2, "limiar_pct": 20}'::jsonb,
        '44444444-4444-4444-4444-444444444444','44444444-4444-4444-4444-444444444444');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.actions (scope_id, finding_id, blocks, run_id, is_featured)
  VALUES ('22222222-2222-2222-2222-222222222222',
          '77777777-7777-7777-7777-777777777777',
          '{"gatilho":"a","evidencia":"b","quantificacao":"c","passo":"d","porque_agora":"e"}'::jsonb,
          '44444444-4444-4444-4444-444444444444', true);
$sql$, 'T4  segunda ação em destaque no mesmo escopo');

-- ================================================================ TESTE 5
-- §16.5: cooldown de 90d e supressão permanente após 2 recusas
UPDATE diagnostics.actions SET state='dispensada', dismissal_reason='nao_agora'
 WHERE id='66666666-6666-6666-6666-666666666666';
UPDATE diagnostics.actions SET state='dispensada', dismissal_reason='nao_entendi'
 WHERE id='66666666-6666-6666-6666-666666666666';

DO $$
DECLARE r record; t boolean;
BEGIN
  SELECT state, dismissal_count, cooldown_until, permanently_suppressed
    INTO r FROM diagnostics.actions WHERE id='66666666-6666-6666-6666-666666666666';
  IF r.state <> 'suprimida' OR NOT r.permanently_suppressed OR r.dismissal_count <> 2 THEN
    RAISE EXCEPTION 'FALHOU T5: esperado suprimida/2 recusas, obtido %/%', r.state, r.dismissal_count;
  END IF;
  IF r.cooldown_until <> current_date + 90 THEN
    RAISE EXCEPTION 'FALHOU T5: cooldown esperado %, obtido %', current_date + 90, r.cooldown_until;
  END IF;
  SELECT copy_review_needed INTO t FROM diagnostics.finding_types WHERE code='custo.taxa_fundo_alta';
  IF NOT t THEN RAISE EXCEPTION 'FALHOU T5: "não entendi" não marcou o tipo para revisão de copy'; END IF;
  RAISE NOTICE 'ok   · T5  2 recusas => suprimida, cooldown 90d, copy marcada para revisão';
END $$;

-- ================================================================ TESTE 6
-- §16.1.8: score não pode existir junto com is_disabled
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.portfolio_scores (scope_id, as_of_date, run_id, score, is_disabled, disabled_reason)
  VALUES ('22222222-2222-2222-2222-222222222222', current_date,
          '44444444-4444-4444-4444-444444444444', 72.5, true, 'fundacao_critica');
$sql$, 'T6  score preenchido com Fundação crítica');

-- ================================================================ TESTE 7
-- D27: duas carteiras-alvo ativas no mesmo escopo
INSERT INTO planning.target_portfolios (id, scope_id, origin, status, activated_at)
VALUES ('88888888-8888-8888-8888-888888888888','22222222-2222-2222-2222-222222222222',
        'builder','active', now());

-- [validação PG real] Desde 27_decisions (C27e), carteira-alvo ATIVA exige
-- decisions.records com o porquê — checagem DIFERIDA. Sem este fixture, o
-- `SET CONSTRAINTS ALL IMMEDIATE` do T14 disparava C27e antes da regra de pesos
-- e o T14 passava pelo motivo errado. O fixture cumpre C27a (motivo material),
-- C27b (suitability do próprio usuário, vigente em presented_at) e C27e.
INSERT INTO identity.suitability_assessments
  (id, user_id, scope_id, questionnaire_version, answers, result, taken_at, valid_until)
VALUES ('99999999-9999-9999-9999-999999999999',
        '11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222',
        'v1', '{"q1":"b"}'::jsonb, 'moderado', now() - interval '1 day', current_date + 700);

INSERT INTO decisions.records
  (id, scope_id, user_id, kind, headline, target_portfolio_id, suitability_assessment_id)
VALUES ('dec00000-0000-0000-0000-000000000001','22222222-2222-2222-2222-222222222222',
        '11111111-1111-1111-1111-111111111111','carteira_alvo',
        'Carteira-alvo de teste (fixture T7/T14)',
        '88888888-8888-8888-8888-888888888888','99999999-9999-9999-9999-999999999999');

INSERT INTO decisions.rationale_items (record_id, seq, driver, claim)
VALUES ('dec00000-0000-0000-0000-000000000001', 1, 'suitability', 'fixture de teste');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.target_portfolios (scope_id, origin, status, activated_at)
  VALUES ('22222222-2222-2222-2222-222222222222','carteira_modelo','active', now());
$sql$, 'T7  segunda carteira-alvo ativa no mesmo escopo');

-- ================================================================ TESTE 8
-- §4.6: o nome proibido
SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.model_portfolios (code, display_name, strategy, disclaimer_version)
  VALUES ('teste','Carteiras Recomendadas','Renda','v1');
$sql$, 'T8  carteira chamada "Recomendadas"');

-- ================================================================ TESTE 9
-- §16.1.6: retorno de mercado não é gravável no Ledger
SELECT pg_temp.expect_fail($sql$
  INSERT INTO ledger.value_entries (scope_id, category, amount_brl, occurred_on, run_id, methodology)
  VALUES ('22222222-2222-2222-2222-222222222222','retorno_mercado', 8000, current_date,
          '44444444-4444-4444-4444-444444444444','{"formula":"x"}'::jsonb);
$sql$, 'T9  categoria "retorno_mercado" no Ledger de Valor Realizado');

INSERT INTO ledger.value_entries (id, scope_id, category, amount_brl, occurred_on, run_id, methodology)
VALUES ('99999999-9999-9999-9999-999999999999','22222222-2222-2222-2222-222222222222',
        'custo_evitado', 4200, current_date,'44444444-4444-4444-4444-444444444444',
        '{"formula":"(taxa_atual - taxa_alvo) * pl","insumos":{"pl":350000}}'::jsonb);

SELECT pg_temp.expect_fail($sql$
  UPDATE ledger.value_entries SET amount_brl = 9999
   WHERE id = '99999999-9999-9999-9999-999999999999';
$sql$, 'T10 UPDATE em lançamento do Ledger (append-only)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO ledger.value_entries (scope_id, category, amount_brl, occurred_on, run_id, methodology)
  VALUES ('22222222-2222-2222-2222-222222222222','custo_evitado', 100, current_date,
          '44444444-4444-4444-4444-444444444444','{"nota":"sem formula"}'::jsonb);
$sql$, 'T11 lançamento no Ledger sem metodologia gravada');

-- ================================================================ TESTE 12
-- §4.1: teto de 2 push por semana
INSERT INTO content.notifications (scope_id, user_id, channel, subject_kind, title)
SELECT '22222222-2222-2222-2222-222222222222','11111111-1111-1111-1111-111111111111',
       'push','signal', 'Sinal ' || g
FROM generate_series(1,3) g;

DO $$
DECLARE v_sent int; v_supp int;
BEGIN
  SELECT count(*) FILTER (WHERE suppressed_at IS NULL),
         count(*) FILTER (WHERE suppressed_at IS NOT NULL)
    INTO v_sent, v_supp
  FROM content.notifications WHERE channel='push';
  IF v_sent <> 2 OR v_supp <> 1 THEN
    RAISE EXCEPTION 'FALHOU T12: esperado 2 enviadas / 1 suprimida, obtido %/%', v_sent, v_supp;
  END IF;
  RAISE NOTICE 'ok   · T12 3º push da semana gravado como suprimido, não enviado';
END $$;

-- ================================================================ TESTE 13
-- P08: holdings é append-only
INSERT INTO market.data_sources (code, display_name, cadence) VALUES ('teste_src','Teste','diaria')
ON CONFLICT DO NOTHING;
INSERT INTO market.instruments (id, kind, name, asset_class_code, currency)
VALUES ('aaaaaaaa-0000-0000-0000-000000000001','fundo','Fundo DI Teste','selic','BRL');
INSERT INTO wealth.accounts (id, scope_id, kind, label)
VALUES ('aaaaaaaa-0000-0000-0000-000000000002','22222222-2222-2222-2222-222222222222','corretora','Corretora');
INSERT INTO wealth.holdings_snapshots
  (scope_id, account_id, instrument_id, as_of_date, quantity, gross_value, value_brl, origin)
VALUES ('22222222-2222-2222-2222-222222222222','aaaaaaaa-0000-0000-0000-000000000002',
        'aaaaaaaa-0000-0000-0000-000000000001', current_date, 100, 35000, 35000, 'manual');

SELECT pg_temp.expect_fail($sql$
  UPDATE wealth.holdings_snapshots SET quantity = 200 WHERE quantity = 100;
$sql$, 'T13 UPDATE em holdings_snapshots (correção deve virar nova as_of_date)');

-- ================================================================ TESTE 14
-- pesos da carteira-alvo precisam somar 1
DO $$
BEGIN
  INSERT INTO planning.target_allocations (target_portfolio_id, asset_class_code, weight)
  VALUES ('88888888-8888-8888-8888-888888888888','selic', 0.4),
         ('88888888-8888-8888-8888-888888888888','ipca',  0.4);
  SET CONSTRAINTS ALL IMMEDIATE;      -- força a verificação diferida
  RAISE EXCEPTION 'FALHOU T14: pesos somando 0,80 foram aceitos';
EXCEPTION WHEN others THEN
  IF sqlerrm LIKE 'FALHOU%' THEN RAISE; END IF;
  RAISE NOTICE 'ok   · T14 carteira-alvo com pesos somando 0,80 (rejeitado: %)', left(sqlerrm,60);
END $$;

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Todos os testes concluídos. Cada "ok" acima é uma regra de'
\echo ' negócio que o banco recusa violar — independente da aplicação.'
\echo '================================================================'
