-- =============================================================================
-- PLEXO · testes das regras invioláveis — catálogo de fatos (T80–T88, 38_fact_catalog.sql)
--   T80  asserção com fact_key incoerente com o catálogo é recusada
--   T81  fato governado por outra fonte não é confirmado a partir de conversa
--   T82  supersessão respeita precedência: fonte inferior não aposenta a superior
--   T83  proposta com delta abaixo do limiar de materialidade é recusada
--   T84  proposta pendente idêntica não se repete (idempotência)
--   T85  proposta NASCE 'proposta' — nunca confirmada ou aplicada
--   T86  teto de propostas pendentes por escopo, com o limite vindo da policy
--   T87  expires_at vem da policy; proposta vencida não se confirma
--   T88  v_fact_current devolve UMA linha por fato; v_fact_coverage conta o que falta
--
-- Por que este arquivo existe: até a 37, `context.assertions.attribute` era um slug LIVRE.
-- Nada impedia `renda_mensal`, `salario` e `renda` coexistirem no mesmo escopo — e sem
-- vocabulário fechado não há unidade canônica, meia-vida, materialidade nem cobertura.
-- O catálogo é o que transforma "o sistema guardou uma frase" em "o sistema sabe um fato".
--
-- As duas regras que mais importam aqui:
--   (a) o que o Open Finance governa, a conversa não sobrescreve — só marca divergência (T81/T82);
--   (b) mudança que não é material não vira pergunta (T83). Sem isso o card vira spam, e um
--       produto que promete respeitar o tempo do cliente passa a cutucá-lo por R$ 50.
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_perfil.sql [plexo_service]
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

-- ---------------------------------------------------------------- fixture (prefixo 8080 = T80)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('80800000-0000-4000-8000-000000000001', 't80-titular@teste.local', 'Titular T80', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('80800000-0000-4000-8000-000000000002', 'personal', 'Pessoal T80',
        '80800000-0000-4000-8000-000000000001');

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at)
VALUES ('80800000-0000-4000-8000-000000000002',
        '80800000-0000-4000-8000-000000000001', 'owner', now());

-- conversa ENCERRADA + mensagens: sinal exige evidência real (gate da 21)
INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start,
                                  status, started_at, ended_at)
VALUES ('80800000-0000-4000-8000-000000000010', '80800000-0000-4000-8000-000000000002',
        '80800000-0000-4000-8000-000000000001', 'assessor', 'essential',
        'encerrada', now() - interval '1 hour', now() - interval '5 minutes');

INSERT INTO agents.messages (id, conversation_id, scope_id, seq, role, content)
VALUES ('80800000-0000-4000-8000-000000000011', '80800000-0000-4000-8000-000000000010',
        '80800000-0000-4000-8000-000000000002', 1, 'user',
        'passei a ganhar 10 mil por mês');

INSERT INTO context.extraction_runs (id, conversation_id, scope_id, status)
VALUES ('80800000-0000-4000-8000-000000000020', '80800000-0000-4000-8000-000000000010',
        '80800000-0000-4000-8000-000000000002', 'running');

INSERT INTO context.signals (id, extraction_run_id, scope_id, user_id, kind, summary,
                             confidence, evidence_message_ids)
VALUES ('80800000-0000-4000-8000-000000000030', '80800000-0000-4000-8000-000000000020',
        '80800000-0000-4000-8000-000000000002', '80800000-0000-4000-8000-000000000001',
        'mudanca_renda', 'renda mencionada como 10.000', 0.9,
        ARRAY['80800000-0000-4000-8000-000000000011']::uuid[]);

-- ---------------------------------------------------------------- catálogo de teste
-- O catálogo real (36 fatos, seed da 38) sai de cena DENTRO desta transação: a cobertura
-- do T88 precisa ser contável, e um teste que muda de resultado quando alguém acrescenta
-- um fato ao catálogo não prova nada. Mesmo remédio do T43/T47b depois do seed da persona.
UPDATE context.fact_definitions SET is_active = false;

-- Renda: a pessoa sabe do próprio salário melhor que o extrato adivinha, então a declaração
-- explícita vem ANTES do open_finance na precedência — e a conversa pode atualizar.
-- `pergunta` é obrigatória para fato askable desde o CHECK `askable_has_question` (migration 43).
-- Estas fixtures nasceram na F14, ANTES da 43, e só o CI as re-executou — foi assim que o
-- vermelho apareceu. Fato governado por outra fonte segue sem pergunta, que é o outro lado do CHECK.
INSERT INTO context.fact_definitions
  (fact_key, subject_kind, attribute, family, display_name, pergunta, value_type, unit,
   source_precedence, half_life_days, materiality_abs, materiality_rel,
   min_value, max_value, is_recurring_by_nature, requires_nature_check, allows_conversation_update)
VALUES
  ('t80.renda_mensal', 'renda', 't80_renda_mensal', 'fluxo', 'Renda mensal líquida (T80)',
   'Quanto você recebe por mês, já líquido?',
   'money_brl', 'BRL',
   ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
   180, 500, 0.05, 0, 10000000, true, true, true),
  -- Patrimônio investido: quem manda é o Open Finance. A conversa NÃO sobrescreve.
  ('t80.patrimonio_investido', 'patrimonio', 't80_patrimonio_investido', 'estoque',
   'Patrimônio investido (T80)', NULL,        -- governado pelo Open Finance: ninguém pergunta
   'money_brl', 'BRL',
   ARRAY['open_finance','upload','formulario','onboarding','conversa','inferencia_motor','operador']::context.assertion_source[],
   NULL, 1000, 0.02, 0, 1000000000, true, false, false);

-- ================================================================ TESTE 80
-- O catálogo é vocabulário fechado: fact_key preenchido tem que casar com a definição.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source)
  VALUES ('80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
          't80.renda_mensal','patrimonio','t80_renda_mensal','{"amount":10000}'::jsonb,'BRL',
          'fato','formulario');
$sql$, 'T80  fact_key com subject_kind divergente do catálogo');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source)
  VALUES ('80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
          't80.renda_mensal','renda','salario','{"amount":10000}'::jsonb,'BRL',
          'fato','formulario');
$sql$, 'T80b attribute divergente do catálogo (o "salario" solto morre aqui)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source)
  VALUES ('80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
          't80.renda_mensal','renda','t80_renda_mensal','{"amount":10000}'::jsonb,'USD',
          'fato','formulario');
$sql$, 'T80c unidade divergente do catálogo (BRL vira USD sem tocar no valor)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source)
  VALUES ('80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
          't80.renda_mensal','renda','t80_renda_mensal','{"amount":-5}'::jsonb,'BRL',
          'fato','formulario');
$sql$, 'T80d valor fora da faixa de sanidade do catálogo');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.assertions
    (scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source)
  VALUES ('80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
          't80.renda_mensal','renda','t80_renda_mensal','{"texto":"uns dez mil"}'::jsonb,'BRL',
          'fato','formulario');
$sql$, 'T80e valor sem número onde o catálogo exige money_brl');

-- caminho feliz: coerente com o catálogo, entra.
-- `valid_from` 30 dias atrás para o T88d poder vencê-la sem esbarrar no CHECK
-- validity_range (valid_until >= valid_from) — a meia-vida do catálogo (180 d)
-- devolve valid_until = hoje + 150, então ela nasce vigente.
INSERT INTO context.assertions
  (id, scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source, valid_from)
VALUES ('80800000-0000-4000-8000-000000000040',
        '80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
        't80.renda_mensal','renda','t80_renda_mensal','{"amount":8000}'::jsonb,'BRL',
        'fato','formulario', current_date - 30);
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.assertions
   WHERE id = '80800000-0000-4000-8000-000000000040'
     AND valid_until = current_date - 30 + 180
$sql$, 1, 'T80g meia-vida do catálogo (180 d) vira valid_until concreto');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.assertions WHERE id = '80800000-0000-4000-8000-000000000040'
$sql$, 1, 'T80f asserção coerente com o catálogo é aceita');

-- ================================================================ TESTE 81
-- O que o Open Finance governa, a conversa não sobrescreve. Ela só marca divergência.
INSERT INTO context.assertions
  (id, scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality,
   source, evidence_message_ids)
VALUES ('80800000-0000-4000-8000-000000000041',
        '80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
        't80.patrimonio_investido','patrimonio','t80_patrimonio_investido',
        '{"amount":500000}'::jsonb,'BRL','fato','conversa',
        ARRAY['80800000-0000-4000-8000-000000000011']::uuid[]);

SELECT pg_temp.expect_fail($sql$
  UPDATE context.assertions
     SET status = 'confirmado', confirmed_at = now(),
         confirmed_by = '80800000-0000-4000-8000-000000000001'
   WHERE id = '80800000-0000-4000-8000-000000000041';
$sql$, 'T81  fato governado pelo Open Finance não se confirma por conversa');

-- a mesma informação, pela fonte que o catálogo diz mandar: passa
INSERT INTO context.assertions
  (id, scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source)
VALUES ('80800000-0000-4000-8000-000000000042',
        '80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
        't80.patrimonio_investido','patrimonio','t80_patrimonio_investido',
        '{"amount":520000}'::jsonb,'BRL','fato','open_finance');
UPDATE context.assertions
   SET status = 'confirmado', confirmed_at = now(),
       confirmed_by = '80800000-0000-4000-8000-000000000001'
 WHERE id = '80800000-0000-4000-8000-000000000042';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.assertions
   WHERE id = '80800000-0000-4000-8000-000000000042' AND status = 'confirmado'
$sql$, 1, 'T81b a mesma confirmação pela fonte autoritativa passa');

-- ================================================================ TESTE 82
-- Supersessão é precedência-consciente: extrato enviado à mão (upload) não aposenta
-- o dado do Open Finance. Divergência aparece; não vira sobrescrita silenciosa.
INSERT INTO context.assertions
  (id, scope_id, user_id, fact_key, subject_kind, attribute, value, unit, modality, source)
VALUES ('80800000-0000-4000-8000-000000000043',
        '80800000-0000-4000-8000-000000000002','80800000-0000-4000-8000-000000000001',
        't80.patrimonio_investido','patrimonio','t80_patrimonio_investido',
        '{"amount":610000}'::jsonb,'BRL','fato','upload');
UPDATE context.assertions
   SET status = 'confirmado', confirmed_at = now(),
       confirmed_by = '80800000-0000-4000-8000-000000000001'
 WHERE id = '80800000-0000-4000-8000-000000000043';

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.assertions
   WHERE id = '80800000-0000-4000-8000-000000000042'
     AND status = 'confirmado' AND superseded_at IS NULL
$sql$, 1, 'T82  fonte inferior (upload) não aposenta a superior (open_finance)');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_current
   WHERE scope_id = '80800000-0000-4000-8000-000000000002'
     AND fact_key = 't80.patrimonio_investido'
$sql$, 1, 'T82b v_fact_current devolve UMA linha mesmo com duas fontes vigentes');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_current
   WHERE scope_id = '80800000-0000-4000-8000-000000000002'
     AND fact_key = 't80.patrimonio_investido'
     AND source = 'open_finance'
$sql$, 1, 'T82c e a linha que sobrevive é a da fonte que o catálogo diz mandar');

-- ================================================================ TESTE 83
-- Materialidade: mudança pequena não vira pergunta. É isto que separa
-- "produto que respeita seu tempo" de "produto que fica te cutucando".
-- `nature` vai preenchida DE PROPÓSITO: sem ela o gate de natureza recusaria antes,
-- e o teste passaria sem nunca exercitar a materialidade. Limiar efetivo aqui é
-- greatest(500 ; 5% × 8.000 = 400) = 500, e o delta é 50.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref,
     current_value, proposed_value, rationale, nature)
  VALUES ('80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
          '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,
          '{"amount":8000}'::jsonb,'{"amount":8050}'::jsonb,
          'você mencionou 8.050', 'recorrente');
$sql$, 'T83  delta de R$ 50 (0,6%) está abaixo do limiar do catálogo');

-- E o contrário do limiar "o que for maior": 450 passa dos 5% (400) mas não dos R$ 500.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref,
     current_value, proposed_value, rationale, nature)
  VALUES ('80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
          '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,
          '{"amount":8000}'::jsonb,'{"amount":8450}'::jsonb,
          'delta de 450: passa do relativo, não do absoluto', 'recorrente');
$sql$, 'T83a limiar é o MAIOR dos dois (5% = 400 não basta; o piso é R$ 500)');

-- delta material: passa
INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref,
   current_value, proposed_value, rationale, nature)
VALUES ('80800000-0000-4000-8000-000000000050',
        '80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
        '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
        '{"table":"context.assertions"}'::jsonb,
        '{"amount":8000}'::jsonb,'{"amount":10000}'::jsonb,
        'você mencionou que passou a ganhar 10 mil', 'recorrente');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals WHERE id = '80800000-0000-4000-8000-000000000050'
$sql$, 1, 'T83b delta de R$ 2.000 (25%) é material e vira proposta');

-- fato NOVO (sem valor atual) é sempre material — não há delta para comparar
INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, fact_key, target_ref,
   proposed_value, rationale, nature)
VALUES ('80800000-0000-4000-8000-000000000051',
        '80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
        '80800000-0000-4000-8000-000000000001','estate_asset','t80.patrimonio_investido',
        '{"table":"context.assertions"}'::jsonb,
        '{"amount":700000}'::jsonb, 'primeira vez que este fato aparece', 'recorrente');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals WHERE id = '80800000-0000-4000-8000-000000000051'
$sql$, 1, 'T83c fato novo (sem current_value) não passa pelo teste de materialidade');

-- fora da faixa do catálogo não vira proposta nem sendo material
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref,
     current_value, proposed_value, rationale, nature)
  VALUES ('80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
          '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,
          '{"amount":8000}'::jsonb,'{"amount":-1}'::jsonb, 'renda negativa', 'recorrente');
$sql$, 'T83d valor proposto fora da faixa de sanidade');

-- catálogo que exige natureza: proposta sem ela é recusada ("ganhei 10k" ≠ "passei a ganhar 10k")
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref,
     current_value, proposed_value, rationale)
  VALUES ('80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
          '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,
          '{"amount":8000}'::jsonb,'{"amount":12000}'::jsonb, 'sem classificar a natureza');
$sql$, 'T83e fato que exige natureza não vira proposta sem pontual/recorrente');

-- ================================================================ TESTE 84
-- Idempotência: a mesma proposta não volta. Sem isto, cada turno repete o card.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref,
     current_value, proposed_value, rationale, nature)
  VALUES ('80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
          '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,
          '{"amount":8000}'::jsonb,'{"amount":10000}'::jsonb,
          'o mesmo card, de novo', 'recorrente');
$sql$, 'T84  proposta pendente idêntica é recusada (idempotência)');

-- ================================================================ TESTE 85
-- Proposta NASCE 'proposta'. Era regra só da aplicação até aqui (pendência da F3).
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value,
     rationale, nature, status, confirmed_at, confirmed_by)
  VALUES ('80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
          '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,'{"amount":15000}'::jsonb,
          'nascendo confirmada', 'recorrente', 'confirmada', now(),
          '80800000-0000-4000-8000-000000000001');
$sql$, 'T85  proposta não nasce confirmada');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value,
     rationale, nature, status, rejected_at)
  VALUES ('80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
          '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,'{"amount":16000}'::jsonb,
          'nascendo rejeitada', 'recorrente', 'rejeitada', now());
$sql$, 'T85b proposta não nasce rejeitada (com rejected_at, para o CHECK antigo não mascarar o gate novo)');

-- ================================================================ TESTE 86
-- Teto de propostas pendentes por escopo — o número vem da policy CONTEXT_EXTRACTION,
-- não do código. Config-first vale também para governança de atenção.
INSERT INTO context.change_proposals
  (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
SELECT '80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
       '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
       '{"table":"context.assertions"}'::jsonb,
       jsonb_build_object('amount', 20000 + i), 'enchendo a fila', 'recorrente'
  FROM generate_series(1, 3) AS i;

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE scope_id = '80800000-0000-4000-8000-000000000002' AND status = 'proposta'
$sql$, 5, 'T86  cinco propostas pendentes é o teto da policy');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.change_proposals
    (signal_id, scope_id, user_id, kind, fact_key, target_ref, proposed_value, rationale, nature)
  VALUES ('80800000-0000-4000-8000-000000000030','80800000-0000-4000-8000-000000000002',
          '80800000-0000-4000-8000-000000000001','profile_field','t80.renda_mensal',
          '{"table":"context.assertions"}'::jsonb,'{"amount":30000}'::jsonb,
          'a sexta', 'recorrente');
$sql$, 'T86b a sexta proposta pendente é recusada pelo teto do escopo');

-- ================================================================ TESTE 87
-- Validade: expires_at vem da policy quando não é informado, e proposta vencida
-- não se confirma — hoje `expires_at` era só decoração para o job `expirar`.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.change_proposals
   WHERE id = '80800000-0000-4000-8000-000000000050'
     AND expires_at = current_date + 30
$sql$, 1, 'T87  expires_at preenchido pela policy (30 dias) quando ausente');

UPDATE context.change_proposals SET expires_at = current_date - 1
 WHERE id = '80800000-0000-4000-8000-000000000051';
SELECT pg_temp.expect_fail($sql$
  UPDATE context.change_proposals
     SET status = 'confirmada', confirmed_at = now(),
         confirmed_by = '80800000-0000-4000-8000-000000000001'
   WHERE id = '80800000-0000-4000-8000-000000000051';
$sql$, 'T87b proposta vencida não pode ser confirmada');

SELECT pg_temp.expect_count($sql$
  SELECT 1 WHERE context.expire_stale_proposals() >= 1
$sql$, 1, 'T87c expire_stale_proposals() aposenta a vencida');

-- ================================================================ TESTE 88
-- As duas views que a tela e o motor leem: o fato vigente e o que ainda falta.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_current
   WHERE scope_id = '80800000-0000-4000-8000-000000000002'
$sql$, 1, 'T88  v_fact_current: só o patrimônio está confirmado (a renda não)');

UPDATE context.assertions
   SET status = 'confirmado', confirmed_at = now(),
       confirmed_by = '80800000-0000-4000-8000-000000000001'
 WHERE id = '80800000-0000-4000-8000-000000000040';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_current
   WHERE scope_id = '80800000-0000-4000-8000-000000000002'
$sql$, 2, 'T88b confirmada a renda, são dois fatos vigentes');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_coverage
   WHERE scope_id = '80800000-0000-4000-8000-000000000002'
     AND fatos_presentes = 2 AND cobertura = 1.0
$sql$, 1, 'T88c v_fact_coverage: 2 de 2 fatos do catálogo de teste presentes');

-- fato vencido sai do vigente e derruba a cobertura — não invalida em silêncio
UPDATE context.assertions SET valid_until = current_date - 1
 WHERE id = '80800000-0000-4000-8000-000000000040';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.v_fact_coverage
   WHERE scope_id = '80800000-0000-4000-8000-000000000002' AND fatos_presentes = 1
$sql$, 1, 'T88d fato vencido sai da cobertura e vira pergunta');

-- o catálogo é config, não dado do cliente: sem escopo, sem RLS
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM context.fact_definitions WHERE fact_key LIKE 't80.%'
$sql$, 2, 'T88e catálogo de teste com as duas definições');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Catálogo de fatos: atributo é vocabulário fechado, o Open'
\echo ' Finance não é sobrescrito por conversa, e mudança pequena'
\echo ' não vira pergunta. Fato sem catálogo não é fato — é frase.'
\echo '================================================================'
