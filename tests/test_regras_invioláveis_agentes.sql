-- =============================================================================
-- SYNAPTA · testes das regras invioláveis — camada de AGENTES (17–21)
-- Continua a numeração do arquivo original (T1–T14).
-- Cada teste prova que o BANCO recusa a violação — não a aplicação.
-- Rodar com: psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_regras_invioláveis_agentes.sql
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
VALUES ('aaaa1111-1111-1111-1111-111111111111', 'agentes@synapta.com.br', 'Teste Agentes', 'active'),
       ('aaaa9999-9999-9999-9999-999999999999', 'terceiro@synapta.com.br', 'Terceiro', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('bbbb2222-2222-2222-2222-222222222222', 'personal', 'Pessoal',
        'aaaa1111-1111-1111-1111-111111111111');

-- Cota apertada para o teste: analista free = 2 perguntas/mês
UPDATE engine.policy_versions
   SET payload = '{"free": {"analista": 2}}'::jsonb
 WHERE code = 'AGENT_QUOTAS' AND effective_to IS NULL;

-- ================================================================ TESTE 15
-- Estado PRÓPRIO do teste (F4 aprovou o prompt do Educador no banco de dev): dentro desta
-- transação o Educador volta a draft, para provar o gate sem depender do que dev tem aprovado.
UPDATE llm.prompt_versions
   SET compliance_status = 'draft', approved_at = NULL, approved_by = NULL
 WHERE code = 'agent.educador.system' AND effective_to IS NULL;

-- Gate de compliance: conversa com agente cujo prompt vigente está em draft
SELECT pg_temp.expect_fail($sql$
  INSERT INTO agents.conversations (scope_id, user_id, agent_code, plan_code_at_start)
  VALUES ('bbbb2222-2222-2222-2222-222222222222',
          'aaaa1111-1111-1111-1111-111111111111', 'educador', 'free');
$sql$, 'T15  conversa com agente client-facing sem prompt aprovado');

-- ninguém conversa com o agente de Contexto
SELECT pg_temp.expect_fail($sql$
  INSERT INTO agents.conversations (scope_id, user_id, agent_code, plan_code_at_start)
  VALUES ('bbbb2222-2222-2222-2222-222222222222',
          'aaaa1111-1111-1111-1111-111111111111', 'contexto', 'free');
$sql$, 'T15b o agente de Contexto não abre conversa');

-- compliance aprova os prompts; agora conversas podem existir
UPDATE llm.prompt_versions
   SET compliance_status = 'approved',
       approved_at = now(),
       approved_by = 'aaaa1111-1111-1111-1111-111111111111'
 WHERE code LIKE 'agent.%' OR code = 'context.extractor';

INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start)
VALUES ('cccc3333-3333-3333-3333-333333333333',
        'bbbb2222-2222-2222-2222-222222222222',
        'aaaa1111-1111-1111-1111-111111111111', 'analista', 'free');
DO $$ BEGIN RAISE NOTICE 'ok   · T15c conversa com prompt aprovado foi aceita'; END $$;

-- ================================================================ TESTE 16
-- Cota mensal: analista free = 2. A 3ª pergunta do mês é rejeitada.
INSERT INTO agents.messages (id, conversation_id, scope_id, seq, role, content)
VALUES ('dddd0001-0001-0001-0001-000000000001',
        'cccc3333-3333-3333-3333-333333333333',
        'bbbb2222-2222-2222-2222-222222222222', 1, 'user',
        'Se os juros sobem, a Petrobras sobe junto?');

INSERT INTO agents.messages (id, conversation_id, scope_id, seq, role, content)
VALUES ('dddd0002-0002-0002-0002-000000000002',
        'cccc3333-3333-3333-3333-333333333333',
        'bbbb2222-2222-2222-2222-222222222222', 2, 'agent',
        'Testei a correlação no período pedido; segue a evidência.');

INSERT INTO agents.messages (conversation_id, scope_id, seq, role, content)
VALUES ('cccc3333-3333-3333-3333-333333333333',
        'bbbb2222-2222-2222-2222-222222222222', 3, 'user',
        'E contra o IBOV no mesmo período?');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO agents.messages (conversation_id, scope_id, seq, role, content)
  VALUES ('cccc3333-3333-3333-3333-333333333333',
          'bbbb2222-2222-2222-2222-222222222222', 4, 'user',
          'terceira pergunta do mês no plano free');
$sql$, 'T16  pergunta além da cota do plano é rejeitada (paywall na aplicação)');

-- ================================================================ TESTE 17
-- Conversa é registro: mensagem não sofre UPDATE nem DELETE
SELECT pg_temp.expect_fail($sql$
  UPDATE agents.messages SET content = 'reescrevendo a história'
  WHERE id = 'dddd0001-0001-0001-0001-000000000001';
$sql$, 'T17  mensagens são append-only');

-- ================================================================ TESTE 18
-- Agente só invoca tool de família permitida (o código legacy quant.correlacao segue registrado para replay/auditoria)
INSERT INTO tools.tools (code, family, display_name, description, param_schema)
VALUES ('quant.t18', 'quant', 'Correlação',
        'Correlação entre duas séries com política de janela explícita.',
        '{"type":"object","properties":{"a":{"type":"string"},"b":{"type":"string"}},"additionalProperties":false}'::jsonb);

INSERT INTO tools.tool_versions (id, tool_code, semver, git_sha, source_sha256)
VALUES ('eeee4444-4444-4444-4444-444444444444', 'quant.t18', '1.0.0',
        repeat('a', 40), repeat('b', 64));

-- conversa com o Educador (só família 'educacao')
INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start)
VALUES ('cccc5555-5555-5555-5555-555555555555',
        'bbbb2222-2222-2222-2222-222222222222',
        'aaaa1111-1111-1111-1111-111111111111', 'educador', 'free');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO tools.tool_executions
    (tool_version_id, scope_id, conversation_id, requested_params, input_hash)
  VALUES ('eeee4444-4444-4444-4444-444444444444',
          'bbbb2222-2222-2222-2222-222222222222',
          'cccc5555-5555-5555-5555-555555555555',
          '{"a":"PETR4","b":"SELIC"}'::jsonb, repeat('c', 64));
$sql$, 'T18  Educador não roda tool quantitativa');

-- com o Analista, a mesma tool passa
INSERT INTO tools.tool_executions
  (id, tool_version_id, scope_id, conversation_id, requested_params, input_hash)
VALUES ('ffff6666-6666-6666-6666-666666666666',
        'eeee4444-4444-4444-4444-444444444444',
        'bbbb2222-2222-2222-2222-222222222222',
        'cccc3333-3333-3333-3333-333333333333',
        '{"a":"PETR4","b":"SELIC"}'::jsonb, repeat('c', 64));
DO $$ BEGIN RAISE NOTICE 'ok   · T18b Analista roda tool quantitativa'; END $$;

-- ================================================================ TESTE 19
-- Execução finalizada é imutável
UPDATE tools.tool_executions
   SET status = 'succeeded', output_hash = repeat('d', 64),
       output_payload = '{"correlacao": -0.31, "n": 252}'::jsonb,
       finished_at = now(), duration_ms = 840
 WHERE id = 'ffff6666-6666-6666-6666-666666666666';

SELECT pg_temp.expect_fail($sql$
  UPDATE tools.tool_executions SET output_payload = '{"correlacao": 0.99}'::jsonb
  WHERE id = 'ffff6666-6666-6666-6666-666666666666';
$sql$, 'T19  execução de tool finalizada é imutável');

-- ================================================================ TESTE 20
-- Afirmação material sem proveniência não entra no EvidenceBundle
INSERT INTO analysis.analyses (id, scope_id, user_id, question)
VALUES ('abab7777-7777-7777-7777-777777777777',
        'bbbb2222-2222-2222-2222-222222222222',
        'aaaa1111-1111-1111-1111-111111111111',
        'Se os juros sobem, a Petrobras sobe junto?');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO analysis.evidence_findings (analysis_id, kind, finding, provenance)
  VALUES ('abab7777-7777-7777-7777-777777777777', 'quantitative',
          '{"metric":"correlacao","value":-0.31}'::jsonb, '[]'::jsonb);
$sql$, 'T20  evidência quantitativa sem provenance é rejeitada');

INSERT INTO analysis.evidence_findings (analysis_id, kind, finding, provenance)
VALUES ('abab7777-7777-7777-7777-777777777777', 'quantitative',
        '{"metric":"correlacao","value":-0.31,"n":252}'::jsonb,
        '["ffff6666-6666-6666-6666-666666666666"]'::jsonb);
DO $$ BEGIN RAISE NOTICE 'ok   · T20b evidência com provenance foi aceita'; END $$;

-- ================================================================ TESTE 21
-- Relatório publicado é imutável (correção = nova versão + superseded_by)
-- [6ª onda] relatório final exige evidence_hash (gate da 32); a asserção abaixo é a mesma de sempre
INSERT INTO analysis.reports (id, analysis_id, content_md, evidence_hash)
VALUES ('baba8888-8888-8888-8888-888888888888',
        'abab7777-7777-7777-7777-777777777777',
        'No período analisado, a correlação foi negativa (-0,31, n=252)...', repeat('c', 64));

SELECT pg_temp.expect_fail($sql$
  UPDATE analysis.reports SET content_md = 'na verdade era positiva'
  WHERE id = 'baba8888-8888-8888-8888-888888888888';
$sql$, 'T21  relatório publicado é imutável');

-- ================================================================ TESTE 22 / 23
-- O Contexto não lê conversa aberta; sinal sem evidência não existe
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.extraction_runs (conversation_id, scope_id)
  VALUES ('cccc5555-5555-5555-5555-555555555555',
          'bbbb2222-2222-2222-2222-222222222222');
$sql$, 'T22  Contexto não processa conversa aberta');

UPDATE agents.conversations
   SET status = 'encerrada', ended_at = now()
 WHERE id = 'cccc3333-3333-3333-3333-333333333333';

INSERT INTO context.extraction_runs (id, conversation_id, scope_id)
VALUES ('cdcd9999-9999-9999-9999-999999999999',
        'cccc3333-3333-3333-3333-333333333333',
        'bbbb2222-2222-2222-2222-222222222222');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.signals
    (extraction_run_id, scope_id, user_id, kind, summary, confidence, evidence_message_ids)
  VALUES ('cdcd9999-9999-9999-9999-999999999999',
          'bbbb2222-2222-2222-2222-222222222222',
          'aaaa1111-1111-1111-1111-111111111111',
          'mencao_aposentadoria', 'sem evidência', 0.9, ARRAY[]::uuid[]);
$sql$, 'T23  sinal sem mensagens de evidência é rejeitado');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.signals
    (extraction_run_id, scope_id, user_id, kind, summary, confidence, evidence_message_ids)
  VALUES ('cdcd9999-9999-9999-9999-999999999999',
          'bbbb2222-2222-2222-2222-222222222222',
          'aaaa1111-1111-1111-1111-111111111111',
          'mencao_aposentadoria', 'evidência forjada', 0.9,
          ARRAY['00000000-0000-0000-0000-000000000000']::uuid[]);
$sql$, 'T23b sinal apontando mensagem inexistente é rejeitado');

INSERT INTO context.signals
  (id, extraction_run_id, scope_id, user_id, kind, summary, confidence, evidence_message_ids)
VALUES ('dede1010-1010-1010-1010-101010101010',
        'cdcd9999-9999-9999-9999-999999999999',
        'bbbb2222-2222-2222-2222-222222222222',
        'aaaa1111-1111-1111-1111-111111111111',
        'mudanca_tolerancia_risco',
        'Usuário disse que quer se aposentar cedo e correr menos risco',
        0.85,
        ARRAY['dddd0001-0001-0001-0001-000000000001']::uuid[]);
DO $$ BEGIN RAISE NOTICE 'ok   · T23c sinal com evidência real foi aceito'; END $$;

-- ================================================================ TESTE 24
-- A REGRA-ESTRELA: perfil de risco nunca muda por inferência de conversa
INSERT INTO context.change_proposals
  (id, signal_id, scope_id, user_id, kind, target_ref, proposed_value, rationale)
VALUES ('efef2020-2020-2020-2020-202020202020',
        'dede1010-1010-1010-1010-101010101010',
        'bbbb2222-2222-2222-2222-222222222222',
        'aaaa1111-1111-1111-1111-111111111111',
        'suitability_risk_profile',
        '{"table":"identity.suitability_assessments"}'::jsonb,
        '"moderado"'::jsonb,
        'Você mencionou aposentadoria antecipada e menor apetite a risco.');

-- (a) aplicar sem confirmação do usuário
SELECT pg_temp.expect_fail($sql$
  UPDATE context.change_proposals
     SET status = 'aplicada', applied_at = now()
   WHERE id = 'efef2020-2020-2020-2020-202020202020';
$sql$, 'T24a proposta de risco aplicada sem confirmação do usuário');

-- (b) confirmada por TERCEIRO
SELECT pg_temp.expect_fail($sql$
  UPDATE context.change_proposals
     SET status = 'confirmada', confirmed_at = now(),
         confirmed_by = 'aaaa9999-9999-9999-9999-999999999999'
   WHERE id = 'efef2020-2020-2020-2020-202020202020';
$sql$, 'T24b só o próprio usuário confirma mudança do próprio contexto');

-- confirmação legítima
UPDATE context.change_proposals
   SET status = 'confirmada', confirmed_at = now(),
       confirmed_by = 'aaaa1111-1111-1111-1111-111111111111'
 WHERE id = 'efef2020-2020-2020-2020-202020202020';

-- (c) aplicar confirmada, mas SEM novo suitability
SELECT pg_temp.expect_fail($sql$
  UPDATE context.change_proposals
     SET status = 'aplicada', applied_at = now()
   WHERE id = 'efef2020-2020-2020-2020-202020202020';
$sql$, 'T24c risco aplicado sem novo suitability é rejeitado');

-- (d) apontando um suitability ANTIGO (anterior à proposta) — burla clássica
INSERT INTO identity.suitability_assessments
  (id, user_id, scope_id, questionnaire_version, answers, result, taken_at, valid_until, superseded_at)
VALUES ('fafa3030-3030-3030-3030-303030303030',
        'aaaa1111-1111-1111-1111-111111111111', 'bbbb2222-2222-2222-2222-222222222222',
        'v1', '{}'::jsonb, 'arrojado',
        now() - interval '90 days', (current_date + 365), now());

SELECT pg_temp.expect_fail($sql$
  UPDATE context.change_proposals
     SET status = 'aplicada', applied_at = now(),
         applied_suitability_id = 'fafa3030-3030-3030-3030-303030303030'
   WHERE id = 'efef2020-2020-2020-2020-202020202020';
$sql$, 'T24d suitability anterior à proposta não vale — questionário tem que ser refeito');

-- (e) caminho legítimo: usuário refez o questionário DEPOIS da proposta
INSERT INTO identity.suitability_assessments
  (id, user_id, scope_id, questionnaire_version, answers, result, valid_until)
VALUES ('fbfb4040-4040-4040-4040-404040404040',
        'aaaa1111-1111-1111-1111-111111111111', 'bbbb2222-2222-2222-2222-222222222222',
        'v1', '{}'::jsonb, 'moderado',
        (current_date + 730));

UPDATE context.change_proposals
   SET status = 'aplicada', applied_at = now(),
       applied_suitability_id = 'fbfb4040-4040-4040-4040-404040404040'
 WHERE id = 'efef2020-2020-2020-2020-202020202020';
DO $$ BEGIN RAISE NOTICE 'ok   · T24e confirmação + novo suitability: aplicação aceita'; END $$;

-- ================================================================
DO $$ BEGIN RAISE NOTICE '---- todos os testes T15–T24 passaram ----'; END $$;

ROLLBACK;
