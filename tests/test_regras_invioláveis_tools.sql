-- =============================================================================
-- SYNAPTA · testes das regras invioláveis — gates de tools (T51–T53, 29_tool_gates)
-- Cada teste prova que o BANCO recusa a violação — não a aplicação.
-- Rodar com: psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_regras_invioláveis_tools.sql
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
VALUES ('51515151-0000-0000-0000-000000000001', 't51@synapta.com.br', 'Teste Gates', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('51515151-0000-0000-0000-000000000002', 'personal', 'Escopo Gates',
        '51515151-0000-0000-0000-000000000001');

-- prompts aprovados só dentro desta transação (gate de 19 exige)
UPDATE llm.prompt_versions
   SET compliance_status = 'approved', approved_at = now()
 WHERE code IN ('agent.assessor.system') AND compliance_status <> 'approved' AND effective_to IS NULL;

-- duas conversas do Assessor: uma no plano free, outra no essential (point-in-time)
INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start) VALUES
  ('51515151-0000-0000-0000-00000000000f', '51515151-0000-0000-0000-000000000002',
   '51515151-0000-0000-0000-000000000001', 'assessor', 'free'),
  ('51515151-0000-0000-0000-00000000000e', '51515151-0000-0000-0000-000000000002',
   '51515151-0000-0000-0000-000000000001', 'assessor', 'essential');

-- tool de família permitida ao Assessor, com plano mínimo essential
INSERT INTO tools.tools (code, family, display_name, description, param_schema, min_plan)
VALUES ('planejamento.teste_gate', 'planejamento', 'Tool de teste', 'só para o T51',
        '{"type":"object"}'::jsonb, 'essential');
INSERT INTO tools.tool_versions (id, tool_code, semver, git_sha, source_sha256)
VALUES ('51515151-0000-0000-0000-0000000000aa', 'planejamento.teste_gate', '1.0.0',
        repeat('a', 40), repeat('b', 64));

-- políticas: uma draft e uma aprovada, AMBAS criadas nesta transação (F8: o teste apontava para LLM_BUDGETS
-- "draft por seed", mas no dev ela está aprovada desde a F7 — teste não pode depender do estado do banco)
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, approved_at)
VALUES ('POLICY_T52_APROVADA', 1, '{"x": 1}'::jsonb, 'approved', now()),
       ('POLICY_T52_DRAFT',    1, '{"x": 1}'::jsonb, 'draft',    NULL);

-- ================================================================ TESTE 51
-- 29(b): tool com min_plan essential não roda em conversa aberta no plano free.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO tools.tool_executions (tool_version_id, scope_id, conversation_id, requested_params, input_hash)
  VALUES ('51515151-0000-0000-0000-0000000000aa', '51515151-0000-0000-0000-000000000002',
          '51515151-0000-0000-0000-00000000000f', '{}'::jsonb, repeat('1', 64));
$sql$, 'T51  tool essential em conversa free (paywall no banco)');

-- caminho feliz: no plano essential a mesma tool roda
INSERT INTO tools.tool_executions (id, tool_version_id, scope_id, conversation_id, requested_params, input_hash)
VALUES ('51515151-0000-0000-0000-0000000000b1', '51515151-0000-0000-0000-0000000000aa',
        '51515151-0000-0000-0000-000000000002', '51515151-0000-0000-0000-00000000000e',
        '{}'::jsonb, repeat('2', 64));
DO $$ BEGIN RAISE NOTICE 'ok   · T51b a mesma tool roda em conversa essential'; END $$;

-- ================================================================ TESTE 52
-- 29(a): execução ligada a conversa referenciando política NÃO aprovada é rejeitada.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO tools.tool_executions (tool_version_id, scope_id, conversation_id, requested_params, input_hash, policy_version_ids)
  SELECT '51515151-0000-0000-0000-0000000000aa', '51515151-0000-0000-0000-000000000002',
         '51515151-0000-0000-0000-00000000000e', '{}'::jsonb, repeat('3', 64), array[p.id]
  FROM engine.policy_versions p WHERE p.code = 'POLICY_T52_DRAFT' AND p.effective_to IS NULL;
$sql$, 'T52  execução client-facing com política draft');

-- caminho feliz: com política aprovada, passa
INSERT INTO tools.tool_executions (tool_version_id, scope_id, conversation_id, requested_params, input_hash, policy_version_ids)
SELECT '51515151-0000-0000-0000-0000000000aa', '51515151-0000-0000-0000-000000000002',
       '51515151-0000-0000-0000-00000000000e', '{}'::jsonb, repeat('4', 64), array[p.id]
FROM engine.policy_versions p WHERE p.code = 'POLICY_T52_APROVADA' AND p.effective_to IS NULL;
DO $$ BEGIN RAISE NOTICE 'ok   · T52b execução com política aprovada foi aceita'; END $$;

-- lista vazia é permitida (tool sem premissa de política)
INSERT INTO tools.tool_executions (tool_version_id, scope_id, conversation_id, requested_params, input_hash)
VALUES ('51515151-0000-0000-0000-0000000000aa', '51515151-0000-0000-0000-000000000002',
        '51515151-0000-0000-0000-00000000000e', '{}'::jsonb, repeat('5', 64));
DO $$ BEGIN RAISE NOTICE 'ok   · T52c execução sem políticas referenciadas foi aceita'; END $$;

-- ================================================================ TESTE 53
-- Execução GLOBAL (warmup/backfill, conversation_id NULL) escapa dos dois gates —
-- mesmo desenho do engine: o gate protege o que chega ao cliente.
INSERT INTO tools.tool_executions (tool_version_id, requested_params, input_hash, policy_version_ids)
SELECT '51515151-0000-0000-0000-0000000000aa', '{}'::jsonb, repeat('6', 64), array[p.id]
FROM engine.policy_versions p WHERE p.code = 'LLM_BUDGETS' AND p.effective_to IS NULL;
DO $$ BEGIN RAISE NOTICE 'ok   · T53  execução global escapa dos gates (min_plan e política) por desenho'; END $$;

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Gates de tools (29) concluídos: plano mínimo e política aprovada'
\echo ' valem no BANCO para tudo que chega ao cliente.'
\echo '================================================================'
