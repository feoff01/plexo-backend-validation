-- =============================================================================
-- SYNAPTA · testes das regras invioláveis — onda de CONTEXTO (22–27)
-- Continua a numeração dos arquivos anteriores (T1–T14, T15–T24).
-- Cada teste prova que o BANCO recusa a violação — não a aplicação.
-- Rodar com:
--   psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_regras_invioláveis_contexto.sql
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
END;
$$;

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixtures
INSERT INTO identity.users (id, email, full_name, status) VALUES
  ('cccc1111-1111-1111-1111-111111111111', 'contexto@synapta.com.br', 'Titular',  'active'),
  ('cccc9999-9999-9999-9999-999999999999', 'vencido@synapta.com.br',  'Vencido',  'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('dddd2222-2222-2222-2222-222222222222', 'personal', 'Pessoal',
        'cccc1111-1111-1111-1111-111111111111');

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at)
VALUES ('dddd2222-2222-2222-2222-222222222222',
        'cccc1111-1111-1111-1111-111111111111', 'owner', now());

INSERT INTO identity.suitability_assessments
  (id, user_id, scope_id, questionnaire_version, answers, result, taken_at, valid_until)
VALUES ('eeee3333-3333-3333-3333-333333333333',
        'cccc1111-1111-1111-1111-111111111111','dddd2222-2222-2222-2222-222222222222',
        'v1', '{"q1":"b"}'::jsonb, 'moderado', now() - interval '10 days',
        (current_date + 700));

-- suitability VENCIDO, de outro usuário (para o T34). [F21a] o gate C59b (migration 59)
-- passou a exigir scope_id em toda suitability — o Vencido ganha o próprio escopo pessoal.
INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('dddd9999-9999-9999-9999-999999999999', 'personal', 'Pessoal do Vencido',
        'cccc9999-9999-9999-9999-999999999999');
INSERT INTO identity.suitability_assessments
  (id, user_id, scope_id, questionnaire_version, answers, result, taken_at, valid_until)
VALUES ('eeee4444-4444-4444-4444-444444444444',
        'cccc9999-9999-9999-9999-999999999999', 'dddd9999-9999-9999-9999-999999999999',
        'v1', '{"q1":"a"}'::jsonb, 'conservador', now() - interval '900 days',
        (current_date - 30));

INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('eeee5555-5555-5555-5555-555555555555', '1.0.0', repeat('a',40), repeat('b',64));

INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date,
                         policy_version_ids, is_client_facing)
VALUES ('eeee6666-6666-6666-6666-666666666666','dddd2222-2222-2222-2222-222222222222',
        'builder','eeee5555-5555-5555-5555-555555555555', repeat('c',64), current_date,
        '{}', false);

INSERT INTO budget.debts (id, scope_id, kind, description, outstanding_brl, annual_rate)
VALUES ('eeee7777-7777-7777-7777-777777777777','dddd2222-2222-2222-2222-222222222222',
        'financiamento_imovel','Financiamento apto', 900000, 0.095);

-- =============================================================== TESTE 25
-- C22a — asserção não NASCE confirmada; e "talvez" exige probabilidade.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, subject_kind, attribute, value, modality, status,
     confirmed_at, confirmed_by, source)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'renda','renda_mensal','{"amount":18000}'::jsonb,'fato','confirmado',
          now(),'cccc1111-1111-1111-1111-111111111111','formulario');
$sql$, 'T25  asserção inserida já como confirmada');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, subject_kind, attribute, value, modality, source)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'objetivo','compra_imovel','{"amount":800000}'::jsonb,'hipotese','conversa');
$sql$, 'T25b "talvez eu compre uma casa" sem likelihood');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, subject_kind, attribute, value, modality, likelihood, source)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'renda','renda_mensal','{"amount":18000}'::jsonb,'fato', 0.9,'formulario');
$sql$, 'T25c fato com likelihood (só intenção/hipótese têm probabilidade)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, subject_kind, attribute, value, modality, source)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'patrimonio','tem_imovel','{"bool":true}'::jsonb,'fato','conversa');
$sql$, 'T25d asserção vinda de conversa sem as mensagens de evidência');

-- =============================================================== TESTE 26
-- Opinião nunca vira fato; e ninguém confirma o contexto do outro.
INSERT INTO context.assertions
  (id, scope_id, user_id, subject_kind, attribute, value, modality, source)
VALUES ('aaaa0001-0000-0000-0000-000000000001',
        'dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'mercado','bolsa_vai_cair','{"text":"acho que cai"}'::jsonb,'opiniao','formulario');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.assertions
     SET status='confirmado', confirmed_at=now(),
         confirmed_by='cccc1111-1111-1111-1111-111111111111'
   WHERE id='aaaa0001-0000-0000-0000-000000000001';
$sql$, 'T26  opinião promovida a fato confirmado');

INSERT INTO context.assertions
  (id, scope_id, user_id, subject_kind, attribute, value, modality, source)
VALUES ('aaaa0002-0000-0000-0000-000000000002',
        'dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'renda','renda_mensal','{"amount":18000}'::jsonb,'fato','onboarding');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.assertions
     SET status='confirmado', confirmed_at=now(),
         confirmed_by='cccc9999-9999-9999-9999-999999999999'
   WHERE id='aaaa0002-0000-0000-0000-000000000002';
$sql$, 'T26b confirmação feita por outro usuário');

-- =============================================================== TESTE 27
-- C22b — conteúdo é imutável: mudança é linha nova + supersessão.
SELECT pg_temp.expect_fail($sql$
  UPDATE context.assertions SET value = '{"amount":25000}'::jsonb
   WHERE id='aaaa0002-0000-0000-0000-000000000002';
$sql$, 'T27  UPDATE no valor de uma asserção');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM context.assertions WHERE id='aaaa0002-0000-0000-0000-000000000002';
$sql$, 'T27b DELETE de asserção');

-- =============================================================== TESTE 28
-- C22c — contradição vira 'conflitante', e confirmar resolve.
INSERT INTO context.assertions
  (id, scope_id, user_id, subject_kind, attribute, value, modality, source)
VALUES ('aaaa0003-0000-0000-0000-000000000003',
        'dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'renda','renda_mensal','{"amount":25000}'::jsonb,'fato','open_finance');

DO $$
DECLARE v_conf int;
BEGIN
  SELECT count(*) INTO v_conf FROM context.assertions
   WHERE attribute='renda_mensal' AND status='conflitante';
  IF v_conf <> 2 THEN
    RAISE EXCEPTION 'FALHOU T28: esperava 2 asserções conflitantes, achei %', v_conf;
  END IF;
  RAISE NOTICE 'ok   · T28  duas rendas divergentes viraram conflito (não escolha silenciosa)';
END $$;

UPDATE context.assertions
   SET status='confirmado', confirmed_at=now(),
       confirmed_by='cccc1111-1111-1111-1111-111111111111'
 WHERE id='aaaa0003-0000-0000-0000-000000000003';

DO $$
DECLARE v_st context.assertion_status; v_by uuid;
BEGIN
  SELECT status, superseded_by INTO v_st, v_by FROM context.assertions
   WHERE id='aaaa0002-0000-0000-0000-000000000002';
  IF v_st <> 'obsoleto' OR v_by <> 'aaaa0003-0000-0000-0000-000000000003' THEN
    RAISE EXCEPTION 'FALHOU T28b: confirmação não superou a concorrente (status=%)', v_st;
  END IF;
  RAISE NOTICE 'ok   · T28b confirmar resolveu o conflito e deixou ponteiro';
END $$;

-- =============================================================== TESTE 29
-- C22 — o gate: estrutura só recebe FATO CONFIRMADO.
INSERT INTO context.assertions
  (id, scope_id, user_id, subject_kind, attribute, value, modality, likelihood, source)
VALUES ('aaaa0004-0000-0000-0000-000000000004',
        'dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'membro','tem_filho','{"text":"talvez outro filho"}'::jsonb,'hipotese',0.4,'formulario');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO household.members (scope_id, relation, display_name, assertion_id)
  VALUES ('dddd2222-2222-2222-2222-222222222222','filho','Futuro filho',
          'aaaa0004-0000-0000-0000-000000000004');
$sql$, 'T29  membro do núcleo criado a partir de uma HIPÓTESE');

INSERT INTO context.assertions
  (id, scope_id, user_id, subject_kind, attribute, value, modality, source)
VALUES ('aaaa0005-0000-0000-0000-000000000005',
        'dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'membro','filho_existente','{"nome":"Ana","nascimento":"2014-03-02"}'::jsonb,
        'fato','formulario');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO household.members (scope_id, relation, display_name, assertion_id)
  VALUES ('dddd2222-2222-2222-2222-222222222222','filho','Ana',
          'aaaa0005-0000-0000-0000-000000000005');
$sql$, 'T29b membro criado a partir de fato ainda NÃO confirmado');

UPDATE context.assertions
   SET status='confirmado', confirmed_at=now(),
       confirmed_by='cccc1111-1111-1111-1111-111111111111'
 WHERE id='aaaa0005-0000-0000-0000-000000000005';

INSERT INTO household.members
  (id, scope_id, user_id, relation, display_name, dependency, dependency_until, assertion_id)
VALUES ('bbbb0001-0000-0000-0000-000000000001','dddd2222-2222-2222-2222-222222222222',
        NULL,'filho','Ana','total', date '2036-12-31',
        'aaaa0005-0000-0000-0000-000000000005');

INSERT INTO household.members (id, scope_id, user_id, relation, display_name)
VALUES ('bbbb0002-0000-0000-0000-000000000002','dddd2222-2222-2222-2222-222222222222',
        'cccc1111-1111-1111-1111-111111111111','titular','Titular');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO household.members (scope_id, user_id, relation, display_name)
  VALUES ('dddd2222-2222-2222-2222-222222222222',
          'cccc1111-1111-1111-1111-111111111111','titular','Segundo titular');
$sql$, 'T29c segundo titular no mesmo escopo');


SELECT pg_temp.expect_fail($sql$
  INSERT INTO household.life_events (scope_id, kind, certainty, scheduled_on, occurred_on)
  VALUES ('dddd2222-2222-2222-2222-222222222222','compra_imovel','programado',
          date '2029-01-01', date '2029-01-01');
$sql$, 'T29d evento de vida ocorrido E programado ao mesmo tempo');

-- =============================================================== TESTE 30
-- Renda: fixo não tem parte variável; e não se compromete mês bom.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO budget.income_sources
    (scope_id, member_id, kind, stability, gross_amount_brl, variable_share)
  VALUES ('dddd2222-2222-2222-2222-222222222222','bbbb0002-0000-0000-0000-000000000002',
          'salario_clt','fixo', 20000, 0.3);
$sql$, 'T30  renda "fixa" com 30% variável');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO budget.income_sources
    (scope_id, kind, stability, gross_amount_brl, variable_share)
  VALUES ('dddd2222-2222-2222-2222-222222222222','comissao','variavel', 15000, 0);
$sql$, 'T30b renda "variável" com 0% variável');

INSERT INTO budget.income_sources
  (id, scope_id, member_id, kind, stability, frequency, gross_amount_brl, variable_share)
VALUES ('bbbb0003-0000-0000-0000-000000000003','dddd2222-2222-2222-2222-222222222222',
        'bbbb0002-0000-0000-0000-000000000002','salario_clt','fixo','mensal', 12000, 0),
       ('bbbb0004-0000-0000-0000-000000000004','dddd2222-2222-2222-2222-222222222222',
        'bbbb0002-0000-0000-0000-000000000002','comissao','variavel','mensal', 8000, 1.0);

SELECT pg_temp.expect_fail($sql$
  INSERT INTO budget.income_summaries
    (scope_id, month, fixed_brl, variable_brl, variable_p10_brl, committable_brl)
  VALUES ('dddd2222-2222-2222-2222-222222222222', date_trunc('month', current_date)::date,
          12000, 8000, 2000, 20000);
$sql$, 'T30c comprometer R$ 20 mil quando o piso é R$ 14 mil');

INSERT INTO budget.income_summaries
  (scope_id, month, fixed_brl, variable_brl, variable_p10_brl, committable_brl,
   variable_share, months_observed)
VALUES ('dddd2222-2222-2222-2222-222222222222', date_trunc('month', current_date)::date,
        12000, 8000, 2000, 14000, 0.4, 12);

DO $$
DECLARE v numeric;
BEGIN
  SELECT monthly_gross_brl INTO v FROM budget.income_sources
   WHERE id='bbbb0004-0000-0000-0000-000000000004';
  IF v <> 8000 THEN RAISE EXCEPTION 'FALHOU T30d: monthly_gross_brl = %', v; END IF;
  RAISE NOTICE 'ok   · T30d equivalente mensal calculado pelo banco (coluna gerada)';
END $$;

-- [validação PG real] T30e — o equivalente mensal não pode perder centavos por
-- constante truncada: R$ 120 mil/ano são R$ 10.000,00/mês (não 9.999,96) e
-- R$ 120 mil/trimestre são R$ 40.000,00/mês (não 39.999,96). É número que o
-- cliente lê.
INSERT INTO budget.income_sources
  (id, scope_id, member_id, kind, stability, frequency, gross_amount_brl, variable_share)
VALUES ('bbbb00e0-0000-0000-0000-0000000000e0','dddd2222-2222-2222-2222-222222222222',
        'bbbb0002-0000-0000-0000-000000000002','bonus_ppr','fixo','anual', 120000, 0),
       ('bbbb00e1-0000-0000-0000-0000000000e1','dddd2222-2222-2222-2222-222222222222',
        'bbbb0002-0000-0000-0000-000000000002','pro_labore','fixo','trimestral', 120000, 0);

DO $$
DECLARE v_anual numeric; v_trim numeric;
BEGIN
  SELECT monthly_gross_brl INTO v_anual FROM budget.income_sources
   WHERE id='bbbb00e0-0000-0000-0000-0000000000e0';
  SELECT monthly_gross_brl INTO v_trim  FROM budget.income_sources
   WHERE id='bbbb00e1-0000-0000-0000-0000000000e1';
  IF v_anual <> 10000 OR v_trim <> 40000 THEN
    RAISE EXCEPTION 'FALHOU T30e: anual 120000 → %/mês, trimestral 120000 → %/mês', v_anual, v_trim;
  END IF;
  RAISE NOTICE 'ok   · T30e equivalente mensal sem perda de centavos (anual 120k → 10.000,00; trimestral 120k → 40.000,00)';
END $$;

-- =============================================================== TESTE 31
-- Patrimônio: bruto sem passivo é mentira; e nada conta duas vezes.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO estate.assets (scope_id, kind, label, liquidity, is_encumbered)
  VALUES ('dddd2222-2222-2222-2222-222222222222','imovel_residencial',
          'Apto Pinheiros','acima_12m', true);
$sql$, 'T31  imóvel financiado sem a dívida vinculada');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO estate.assets (scope_id, kind, label, liquidity, also_in_wealth)
  VALUES ('dddd2222-2222-2222-2222-222222222222','previdencia_fechada',
          'PGBL','acima_12m', true);
$sql$, 'T31b ativo marcado como já contabilizado em wealth, sem apontar a conta');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO estate.assets (scope_id, kind, label, liquidity, generates_income)
  VALUES ('dddd2222-2222-2222-2222-222222222222','imovel_comercial',
          'Sala alugada','acima_12m', true);
$sql$, 'T31c imóvel que gera aluguel sem a fonte de renda correspondente');

INSERT INTO estate.assets
  (id, scope_id, kind, label, liquidity, is_encumbered, linked_debt_id, is_primary_residence)
VALUES ('bbbb0005-0000-0000-0000-000000000005','dddd2222-2222-2222-2222-222222222222',
        'imovel_residencial','Apto Pinheiros','acima_12m', true,
        'eeee7777-7777-7777-7777-777777777777', true);

SELECT pg_temp.expect_fail($sql$
  INSERT INTO estate.assets
    (scope_id, kind, label, liquidity, is_primary_residence)
  VALUES ('dddd2222-2222-2222-2222-222222222222','imovel_residencial',
          'Casa de praia','acima_12m', true);
$sql$, 'T31d segunda residência principal no mesmo escopo');

INSERT INTO estate.valuations (asset_id, scope_id, as_of_date, value_brl, method, confidence)
VALUES ('bbbb0005-0000-0000-0000-000000000005','dddd2222-2222-2222-2222-222222222222',
        current_date, 1800000, 'declarado', 0.5);

SELECT pg_temp.expect_fail($sql$
  UPDATE estate.valuations SET value_brl = 2200000
   WHERE asset_id='bbbb0005-0000-0000-0000-000000000005';
$sql$, 'T31e UPDATE em avaliação (reavaliar é linha nova em data nova — C7)');

DO $$
DECLARE v_pl numeric; v_inv numeric;
BEGIN
  SELECT patrimonio_liquido_brl, investivel_brl INTO v_pl, v_inv
  FROM estate.v_net_worth WHERE scope_id='dddd2222-2222-2222-2222-222222222222';
  IF v_pl <> 900000 THEN
    RAISE EXCEPTION 'FALHOU T31f: patrimônio líquido = % (esperado 900.000)', v_pl;
  END IF;
  IF v_inv <> 0 THEN
    RAISE EXCEPTION 'FALHOU T31f: imóvel entrou como investível (%)', v_inv;
  END IF;
  RAISE NOTICE 'ok   · T31f imóvel de 1,8 mi − financiamento de 900 mil = 900 mil, e nada disso é investível';
END $$;

-- =============================================================== TESTE 32
-- C26a — o veto do cliente é inviolável nos três caminhos.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO preferences.constraints (scope_id, user_id, kind, enforcement, asset_class_code)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'veto_classe','bloqueante','cripto');
$sql$, 'T32  veto bloqueante criado sem confirmação do cliente');

INSERT INTO preferences.constraints
  (id, scope_id, user_id, kind, enforcement, asset_class_code, reason,
   confirmed_at, confirmed_by)
VALUES ('bbbb0006-0000-0000-0000-000000000006','dddd2222-2222-2222-2222-222222222222',
        'cccc1111-1111-1111-1111-111111111111','veto_classe','bloqueante','cripto',
        'não quero investir em cripto', now(), 'cccc1111-1111-1111-1111-111111111111');

INSERT INTO preferences.constraints
  (id, scope_id, user_id, kind, enforcement, asset_class_code, threshold,
   confirmed_at, confirmed_by)
VALUES ('bbbb0007-0000-0000-0000-000000000007','dddd2222-2222-2222-2222-222222222222',
        'cccc1111-1111-1111-1111-111111111111','limite_max_classe','bloqueante',
        'acoes_br', 0.20, now(), 'cccc1111-1111-1111-1111-111111111111');

INSERT INTO planning.target_portfolios (id, scope_id, origin, status)
VALUES ('bbbb0008-0000-0000-0000-000000000008','dddd2222-2222-2222-2222-222222222222',
        'builder','draft');

SET CONSTRAINTS planning.target_allocations_respect_constraints IMMEDIATE;

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.target_allocations (target_portfolio_id, asset_class_code, weight)
  VALUES ('bbbb0008-0000-0000-0000-000000000008','cripto', 0.05);
$sql$, 'T32b carteira-alvo com a classe vetada pelo cliente');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.target_allocations (target_portfolio_id, asset_class_code, weight)
  VALUES ('bbbb0008-0000-0000-0000-000000000008','acoes_br', 0.35);
$sql$, 'T32c carteira-alvo acima do teto de 20% definido pelo cliente');

SET CONSTRAINTS planning.target_allocations_respect_constraints DEFERRED;

-- Carteira Modelo contendo a classe vetada
INSERT INTO planning.model_portfolios (code, display_name, strategy, disclaimer_version)
VALUES ('agressiva_teste','Carteira Modelo Agressiva','Crescimento','v1');

INSERT INTO planning.model_portfolio_versions (id, model_code, version, published_at)
VALUES ('bbbb0009-0000-0000-0000-000000000009','agressiva_teste', 1, now());

INSERT INTO planning.model_portfolio_holdings (model_version_id, asset_class_code, weight)
VALUES ('bbbb0009-0000-0000-0000-000000000009','selic', 0.90),
       ('bbbb0009-0000-0000-0000-000000000009','cripto', 0.10);

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.model_adoptions
    (scope_id, model_version_id, disclaimer_version)
  VALUES ('dddd2222-2222-2222-2222-222222222222',
          'bbbb0009-0000-0000-0000-000000000009','v1');
$sql$, 'T32d adoção de Carteira Modelo que contém a classe vetada');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.contribution_routings
    (scope_id, target_portfolio_id, run_id, amount_brl, suggestion)
  VALUES ('dddd2222-2222-2222-2222-222222222222','bbbb0008-0000-0000-0000-000000000008',
          'eeee6666-6666-6666-6666-666666666666', 1000,
          '{"selic": 800, "cripto": 200}'::jsonb);
$sql$, 'T32e roteamento de aporte sugerindo a classe vetada');

-- =============================================================== TESTE 33
-- C26b — restrição não afrouxa em silêncio.
SELECT pg_temp.expect_fail($sql$
  UPDATE preferences.constraints SET enforcement='alerta'
   WHERE id='bbbb0006-0000-0000-0000-000000000006';
$sql$, 'T33  veto bloqueante rebaixado para alerta via UPDATE');

SELECT pg_temp.expect_fail($sql$
  UPDATE preferences.constraints SET threshold = 0.60
   WHERE id='bbbb0007-0000-0000-0000-000000000007';
$sql$, 'T33b teto de 20% elevado para 60% via UPDATE');

SELECT pg_temp.expect_fail($sql$
  UPDATE preferences.constraints
     SET revoked_at = now(), revoked_by = 'cccc9999-9999-9999-9999-999999999999'
   WHERE id='bbbb0006-0000-0000-0000-000000000006';
$sql$, 'T33c veto revogado por outra pessoa que não o cliente');

SELECT pg_temp.expect_fail($sql$
  UPDATE preferences.constraints SET asset_class_code='fii'
   WHERE id='bbbb0006-0000-0000-0000-000000000006';
$sql$, 'T33d alvo do veto reescrito');

-- =============================================================== TESTE 34
-- C27 — não existe entrega sem porquê, sem perfil vigente e sem fato por trás.
SET CONSTRAINTS decisions.records_need_rationale IMMEDIATE;

SELECT pg_temp.expect_fail($sql$
  INSERT INTO decisions.records
    (scope_id, user_id, kind, headline, suitability_assessment_id)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'carteira_alvo','Sua carteira sugerida',
          'eeee3333-3333-3333-3333-333333333333');
$sql$, 'T34  entrega registrada sem nenhum motivo material (C27a)');

SET CONSTRAINTS decisions.records_need_rationale DEFERRED;

SELECT pg_temp.expect_fail($sql$
  INSERT INTO decisions.records
    (scope_id, user_id, kind, headline, suitability_assessment_id)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'carteira_alvo','Carteira recomendada para você',
          'eeee3333-3333-3333-3333-333333333333');
$sql$, 'T34b headline usando a palavra proibida "recomendada" (§4.6 / T8)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO decisions.records (scope_id, user_id, kind, headline)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'carteira_alvo','Sua carteira sugerida');
$sql$, 'T34c carteira-alvo entregue sem suitability referenciado');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO decisions.records
    (scope_id, user_id, kind, headline, suitability_assessment_id)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc9999-9999-9999-9999-999999999999',
          'carteira_alvo','Sua carteira sugerida',
          'eeee4444-4444-4444-4444-444444444444');
$sql$, 'T34d carteira-alvo apoiada em suitability VENCIDO');

-- caminho legítimo: registro + motivo + insumos
INSERT INTO decisions.records
  (id, scope_id, user_id, kind, headline, target_portfolio_id,
   suitability_assessment_id, engine_run_id, plan_code)
VALUES ('bbbb000a-0000-0000-0000-00000000000a','dddd2222-2222-2222-2222-222222222222',
        'cccc1111-1111-1111-1111-111111111111','carteira_alvo',
        'Carteira-alvo sugerida: 60% pós-fixado, 20% IPCA+, 20% ações',
        'bbbb0008-0000-0000-0000-000000000008','eeee3333-3333-3333-3333-333333333333',
        'eeee6666-6666-6666-6666-666666666666','essential');

INSERT INTO decisions.rationale_items (record_id, seq, driver, claim) VALUES
  ('bbbb000a-0000-0000-0000-00000000000a', 1, 'suitability',
   'Perfil moderado vigente desde a última revisão'),
  ('bbbb000a-0000-0000-0000-00000000000a', 2, 'restricao_cliente',
   'Cripto excluído por veto explícito do cliente'),
  ('bbbb000a-0000-0000-0000-00000000000a', 3, 'contexto_familiar',
   'Dependente até 2036 mantém a despesa da casa estável até lá');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO decisions.inputs (record_id, input_kind, assertion_id, is_material)
  VALUES ('bbbb000a-0000-0000-0000-00000000000a','assertion',
          'aaaa0004-0000-0000-0000-000000000004', true);
$sql$, 'T34e insumo MATERIAL apoiado numa hipótese ("talvez eu compre uma casa") — C27c');

INSERT INTO decisions.inputs (record_id, input_kind, assertion_id, is_material)
VALUES ('bbbb000a-0000-0000-0000-00000000000a','assertion',
        'aaaa0003-0000-0000-0000-000000000003', true);

INSERT INTO decisions.inputs (record_id, input_kind, assertion_id, is_material)
VALUES ('bbbb000a-0000-0000-0000-00000000000a','assertion',
        'aaaa0004-0000-0000-0000-000000000004', false);

SELECT pg_temp.expect_fail($sql$
  UPDATE decisions.records SET headline='Outra coisa'
   WHERE id='bbbb000a-0000-0000-0000-00000000000a';
$sql$, 'T34f reescrever o que foi dito ao cliente (C27d)');

UPDATE decisions.records SET outcome='adotada', outcome_at=now()
 WHERE id='bbbb000a-0000-0000-0000-00000000000a';

-- =============================================================== TESTE 35
-- C27e — carteira-alvo ativa sem registro do porquê não vai para o ar.
SET CONSTRAINTS planning.target_active_needs_record IMMEDIATE;

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.target_portfolios (scope_id, origin, status, activated_at)
  VALUES ('dddd2222-2222-2222-2222-222222222222','builder','active', now());
$sql$, 'T35  carteira-alvo ativada sem decisions.records');

UPDATE planning.target_portfolios
   SET status='active', activated_at=now()
 WHERE id='bbbb0008-0000-0000-0000-000000000008';

DO $$
BEGIN
  RAISE NOTICE 'ok   · T35b carteira-alvo COM registro do porquê ativou normalmente';
END $$;

-- =============================================================== TESTE 36
-- REGRESSÃO da auditoria: confirmar um valor NOVO por cima de um fato JÁ
-- CONFIRMADO — o fluxo mais comum do produto ("minha renda mudou").
-- Na versão anterior, os CHECKs bidirecionais faziam isso explodir.
INSERT INTO context.assertions
  (id, scope_id, user_id, subject_kind, attribute, value, modality, source)
VALUES ('aaaa0006-0000-0000-0000-000000000006',
        'dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'renda','renda_mensal','{"amount":30000}'::jsonb,'fato','formulario');

DO $$
DECLARE v_st context.assertion_status;
BEGIN
  SELECT status INTO v_st FROM context.assertions
   WHERE id='aaaa0003-0000-0000-0000-000000000003';
  IF v_st <> 'conflitante' THEN
    RAISE EXCEPTION 'FALHOU T36: fato confirmado contradito deveria virar conflitante (está %)', v_st;
  END IF;
  RAISE NOTICE 'ok   · T36  declaração nova SUSPENDE o fato confirmado (vira conflito, sai de v_current_facts)';
END $$;

UPDATE context.assertions
   SET status='confirmado', confirmed_at=now(),
       confirmed_by='cccc1111-1111-1111-1111-111111111111'
 WHERE id='aaaa0006-0000-0000-0000-000000000006';

DO $$
DECLARE v_st context.assertion_status; v_by uuid; v_facts int;
BEGIN
  SELECT status, superseded_by INTO v_st, v_by FROM context.assertions
   WHERE id='aaaa0003-0000-0000-0000-000000000003';
  IF v_st <> 'obsoleto' OR v_by <> 'aaaa0006-0000-0000-0000-000000000006' THEN
    RAISE EXCEPTION 'FALHOU T36b: confirmado antigo não foi superado (status=%)', v_st;
  END IF;
  SELECT count(*) INTO v_facts FROM context.v_current_facts
   WHERE attribute='renda_mensal';
  IF v_facts <> 1 THEN
    RAISE EXCEPTION 'FALHOU T36b: v_current_facts deveria ter exatamente 1 renda (tem %)', v_facts;
  END IF;
  RAISE NOTICE 'ok   · T36b confirmar renda nova por cima da antiga funciona; sobra 1 fato vigente';
END $$;

-- =============================================================== TESTE 37
-- REGRESSÃO: expirar um fato CONFIRMADO (renda venceu a validade).
INSERT INTO context.assertions
  (id, scope_id, user_id, subject_kind, attribute, value, modality, source,
   valid_from, valid_until)
VALUES ('aaaa0007-0000-0000-0000-000000000007',
        'dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'renda','renda_conjuge','{"amount":9000}'::jsonb,'fato','formulario',
        current_date - 200, current_date - 10);

UPDATE context.assertions
   SET status='confirmado', confirmed_at=now(),
       confirmed_by='cccc1111-1111-1111-1111-111111111111'
 WHERE id='aaaa0007-0000-0000-0000-000000000007';

DO $$
DECLARE v_n int; v_st context.assertion_status;
BEGIN
  SELECT context.expire_stale_assertions() INTO v_n;
  SELECT status INTO v_st FROM context.assertions
   WHERE id='aaaa0007-0000-0000-0000-000000000007';
  IF v_st <> 'obsoleto' THEN
    RAISE EXCEPTION 'FALHOU T37: fato confirmado vencido deveria expirar (está %)', v_st;
  END IF;
  RAISE NOTICE 'ok   · T37  renda confirmada vencida expirou (% linha(s)) e volta a ser pergunta', v_n;
END $$;

-- =============================================================== TESTE 38
-- A direção que o gate C26a NÃO cobre: veto criado DEPOIS da carteira ativa.
-- O veto nunca é obstruído (espírito do C26b) — mas a violação fica VISÍVEL.
INSERT INTO planning.target_allocations (target_portfolio_id, asset_class_code, weight)
VALUES ('bbbb0008-0000-0000-0000-000000000008','ipca', 1.000);

INSERT INTO preferences.constraints
  (scope_id, user_id, kind, enforcement, asset_class_code, reason,
   confirmed_at, confirmed_by)
VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'veto_classe','bloqueante','ipca','mudei de ideia sobre indexados',
        now(), 'cccc1111-1111-1111-1111-111111111111');

DO $$
DECLARE v_n int;
BEGIN
  SELECT count(*) INTO v_n FROM preferences.v_violations
   WHERE scope_id='dddd2222-2222-2222-2222-222222222222';
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'FALHOU T38: veto pós-carteira deveria aparecer em v_violations (achei %)', v_n;
  END IF;
  RAISE NOTICE 'ok   · T38  veto aceito depois da carteira ativa vira violação VISÍVEL, não silêncio';
END $$;

-- =============================================================== TESTE 39
-- REGRESSÃO da auditoria 2: teto por CLASSE não pode ser burlado fatiando a
-- classe em vários instrumentos (3 × 15% = 45% > teto de 20% do cliente).
INSERT INTO market.issuers (id, name, kind)
VALUES ('eeee8888-8888-8888-8888-888888888888','Gestora Teste','gestora');

INSERT INTO market.instruments (id, kind, name, ticker, issuer_id, asset_class_code)
VALUES ('eeee9991-9999-9999-9999-999999999991','acao','Ação A','TSTA3',
        'eeee8888-8888-8888-8888-888888888888','acoes_br'),
       ('eeee9992-9999-9999-9999-999999999992','acao','Ação B','TSTB3',
        'eeee8888-8888-8888-8888-888888888888','acoes_br'),
       ('eeee9993-9999-9999-9999-999999999993','acao','Ação C','TSTC3',
        'eeee8888-8888-8888-8888-888888888888','acoes_br');

INSERT INTO planning.model_portfolios (code, display_name, strategy, disclaimer_version)
VALUES ('fatiada_teste','Carteira Modelo Fatiada','Teste de burla','v1');
INSERT INTO planning.model_portfolio_versions (id, model_code, version, published_at)
VALUES ('bbbb000b-0000-0000-0000-00000000000b','fatiada_teste', 1, now());
INSERT INTO planning.model_portfolio_holdings
  (model_version_id, asset_class_code, instrument_id, weight)
VALUES ('bbbb000b-0000-0000-0000-00000000000b','acoes_br',
        'eeee9991-9999-9999-9999-999999999991', 0.15),
       ('bbbb000b-0000-0000-0000-00000000000b','acoes_br',
        'eeee9992-9999-9999-9999-999999999992', 0.15),
       ('bbbb000b-0000-0000-0000-00000000000b','acoes_br',
        'eeee9993-9999-9999-9999-999999999993', 0.15),
       ('bbbb000b-0000-0000-0000-00000000000b','selic', NULL, 0.55);

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.model_adoptions (scope_id, model_version_id, disclaimer_version)
  VALUES ('dddd2222-2222-2222-2222-222222222222',
          'bbbb000b-0000-0000-0000-00000000000b','v1');
$sql$, 'T39  classe fatiada em 3 instrumentos de 15% NÃO burla o teto de 20%');

-- veto de instrumento pontual (classe dentro do teto, instrumento vetado)
INSERT INTO preferences.constraints
  (scope_id, user_id, kind, enforcement, instrument_id, reason, confirmed_at, confirmed_by)
VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
        'veto_instrumento','bloqueante','eeee9991-9999-9999-9999-999999999991',
        'não quero esse papel', now(),'cccc1111-1111-1111-1111-111111111111');

-- modelo PRÓPRIO para o T39b: model_versions_one_current permite só UMA versão
-- publicada não-aposentada por model_code — v2 de 'fatiada_teste' colidiria.
INSERT INTO planning.model_portfolios (code, display_name, strategy, disclaimer_version)
VALUES ('fatiada2_teste','Carteira Modelo Fatiada II','Teste de veto pontual','v1');
INSERT INTO planning.model_portfolio_versions (id, model_code, version, published_at)
VALUES ('bbbb000c-0000-0000-0000-00000000000c','fatiada2_teste', 1, now());
INSERT INTO planning.model_portfolio_holdings
  (model_version_id, asset_class_code, instrument_id, weight)
VALUES ('bbbb000c-0000-0000-0000-00000000000c','acoes_br',
        'eeee9991-9999-9999-9999-999999999991', 0.15),
       ('bbbb000c-0000-0000-0000-00000000000c','selic', NULL, 0.85);

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.model_adoptions (scope_id, model_version_id, disclaimer_version)
  VALUES ('dddd2222-2222-2222-2222-222222222222',
          'bbbb000c-0000-0000-0000-00000000000c','v1');
$sql$, 'T39b instrumento vetado pontualmente barra a adoção mesmo com classe no teto');

-- =============================================================== TESTE 40
-- Endurecimentos do 22: asserção só nasce pendente; conteúdo TODO imutável.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, subject_kind, attribute, value, modality, status, source)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'renda','renda_teste','{"amount":1}'::jsonb,'fato','obsoleto','formulario');
$sql$, 'T40  asserção nascendo direto como obsoleta');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.assertions SET unit = 'USD'
   WHERE id='aaaa0006-0000-0000-0000-000000000006';
$sql$, 'T40b trocar a unidade de uma asserção existente');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, subject_kind, attribute, value, modality, source,
     evidence_message_ids)
  VALUES ('dddd2222-2222-2222-2222-222222222222','cccc1111-1111-1111-1111-111111111111',
          'renda','renda_teste','{"amount":1}'::jsonb,'fato','conversa',
          ARRAY['99999999-9999-9999-9999-999999999999']::uuid[]);
$sql$, 'T40c evidência apontando para mensagem que não existe');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Onda 22–27 concluída. Cada "ok" acima é uma regra que o banco'
\echo ' recusa violar: dúvida não vira fato, veto não afrouxa em'
\echo ' silêncio, e nenhuma carteira sai sem o porquê registrado.'
\echo '================================================================'
