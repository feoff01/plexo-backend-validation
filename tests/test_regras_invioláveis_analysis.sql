-- =============================================================================
-- SYNAPTA · testes das regras invioláveis — pipeline do Analista research (T63–T67, 32_analysis_dag_gates)
-- O DAG do Analista (plans → tasks → tool_executions → evidence_findings → reports) é executado
-- por um job, fora de uma requisição: o BANCO precisa impor o que antes só a conversa impunha.
--   T64 análise research exige conversa; estado terminal carimba finished_at e não reabre
--   T65 DAG válido: dependência só de nó já existente no mesmo plano (ciclo impossível), tarefa do
--       plano da própria análise, definição congelada, execução da própria análise
--   T66 replan limitado: versão derivada, plano anterior superseded, replan_count contado pelo banco
--   T67 relatório final exige evidência material + evidence_hash; blocked não; imutável
--   T63 gates de tool (família, política, plano mínimo, escopo) valem por analysis_id sem conversa
-- Ordem: T64–T67 primeiro (colunas existentes → vermelho na asserção), T63 por último (coluna nova).
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_analysis.sql [plexo_service]
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

CREATE OR REPLACE FUNCTION pg_temp.expect_count(p_sql text, p_n bigint, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_n bigint;
BEGIN
  EXECUTE 'SELECT count(*) FROM (' || p_sql || ') q' INTO v_n;
  IF v_n <> p_n THEN
    RAISE EXCEPTION 'FALHOU: "%" esperava % linha(s), veio %', p_label, p_n, v_n;
  END IF;
  RAISE NOTICE 'ok   · % (% linha(s))', p_label, v_n;
END;
$$;

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixtures
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('63636363-0000-0000-0000-000000000001', 't63@synapta.com.br', 'Teste F6', 'active');
INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('63636363-0000-0000-0000-00000000000a', 'personal', 'Escopo F6', '63636363-0000-0000-0000-000000000001'),
       ('63636363-0000-0000-0000-00000000000b', 'personal', 'Outro escopo', '63636363-0000-0000-0000-000000000001');

-- prompt do analista aprovado NA transação (gate T15 não depende do estado do dev)
UPDATE llm.prompt_versions
   SET compliance_status = 'approved', approved_at = now(), approved_by = '63636363-0000-0000-0000-000000000001'
 WHERE code = 'agent.analista.system' AND effective_to IS NULL;

INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start)
VALUES ('63636363-0000-0000-0000-0000000000c1', '63636363-0000-0000-0000-00000000000a',
        '63636363-0000-0000-0000-000000000001', 'analista', 'free');

-- tools sintéticas: quant (ok), quant com plano mínimo essential, orcamento (família proibida ao analista)
INSERT INTO tools.tools (code, family, display_name, description, param_schema, min_plan)
VALUES ('quant.t63',      'quant',     'T63 quant',     'sintética', '{"type":"object"}'::jsonb, 'free'),
       ('quant.t63_pago', 'quant',     'T63 pago',      'sintética', '{"type":"object"}'::jsonb, 'essential'),
       ('orcamento.t63',  'orcamento', 'T63 orcamento', 'sintética', '{"type":"object"}'::jsonb, 'free');
INSERT INTO tools.tool_versions (id, tool_code, semver, git_sha, source_sha256)
VALUES ('63636363-0000-0000-0000-0000000000e1', 'quant.t63',      '1.0.0', repeat('a', 40), repeat('1', 64)),
       ('63636363-0000-0000-0000-0000000000e2', 'quant.t63_pago', '1.0.0', repeat('a', 40), repeat('2', 64)),
       ('63636363-0000-0000-0000-0000000000e3', 'orcamento.t63',  '1.0.0', repeat('a', 40), repeat('3', 64));

INSERT INTO engine.policy_versions (id, code, version, payload, compliance_status)
VALUES ('63636363-0000-0000-0000-0000000000d1', 'T63_DRAFT', 1, '{"x": 1}'::jsonb, 'draft');

-- análise standard sem conversa (como as tools globais) e análise research com conversa
INSERT INTO analysis.analyses (id, scope_id, user_id, question, mode)
VALUES ('63636363-0000-0000-0000-0000000000a1', '63636363-0000-0000-0000-00000000000a',
        '63636363-0000-0000-0000-000000000001', 'standard sem conversa', 'standard');
INSERT INTO analysis.analyses (id, scope_id, user_id, conversation_id, question, mode, cutoff_date)
VALUES ('63636363-0000-0000-0000-0000000000a2', '63636363-0000-0000-0000-00000000000a',
        '63636363-0000-0000-0000-000000000001', '63636363-0000-0000-0000-0000000000c1',
        'PETR4 em 2026: retorno, correlação com o CDI e reação ao Copom', 'research', current_date);
-- uma terceira análise, de outro escopo (com a sua conversa), para provar que plano/execução não cruzam análises
INSERT INTO agents.conversations (id, scope_id, user_id, agent_code, plan_code_at_start)
VALUES ('63636363-0000-0000-0000-0000000000c2', '63636363-0000-0000-0000-00000000000b',
        '63636363-0000-0000-0000-000000000001', 'analista', 'free');
INSERT INTO analysis.analyses (id, scope_id, user_id, conversation_id, question, mode)
VALUES ('63636363-0000-0000-0000-0000000000a3', '63636363-0000-0000-0000-00000000000b',
        '63636363-0000-0000-0000-000000000001', '63636363-0000-0000-0000-0000000000c2', 'outra análise', 'standard');

-- ================================================================ TESTE 64
-- Análise research nasce ligada a uma conversa (é dela que os gates tiram agente e plano).
SELECT pg_temp.expect_fail($sql$
  INSERT INTO analysis.analyses (scope_id, user_id, question, mode)
  VALUES ('63636363-0000-0000-0000-00000000000a', '63636363-0000-0000-0000-000000000001', 'sem conversa', 'research');
$sql$, 'T64  análise research sem conversation_id');

UPDATE analysis.analyses SET status = 'final' WHERE id = '63636363-0000-0000-0000-0000000000a1';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.analyses WHERE id = '63636363-0000-0000-0000-0000000000a1' AND finished_at IS NOT NULL
$sql$, 1, 'T64b estado terminal carimba finished_at');

SELECT pg_temp.expect_fail($sql$
  UPDATE analysis.analyses SET status = 'executing' WHERE id = '63636363-0000-0000-0000-0000000000a1';
$sql$, 'T64c análise terminal não reabre');

-- ================================================================ TESTE 65
-- DAG: dependência só de nó já existente no mesmo plano; tarefa do plano da própria análise;
-- definição congelada; task succeeded aponta execução da própria análise.
INSERT INTO analysis.plans (id, analysis_id, dsl_version, plan)
VALUES ('63636363-0000-0000-0000-0000000000f1', '63636363-0000-0000-0000-0000000000a2', '1', '{"nodes": []}'::jsonb);
INSERT INTO analysis.plans (id, analysis_id, dsl_version, plan)
VALUES ('63636363-0000-0000-0000-0000000000f9', '63636363-0000-0000-0000-0000000000a3', '1', '{"nodes": []}'::jsonb);

INSERT INTO analysis.tasks (id, analysis_id, plan_id, node_id, tool_code, depends_on, criticality)
VALUES ('63636363-0000-0000-0000-000000000011', '63636363-0000-0000-0000-0000000000a2',
        '63636363-0000-0000-0000-0000000000f1', 'a', 'quant.t63', '{}', 'required');
INSERT INTO analysis.tasks (analysis_id, plan_id, node_id, tool_code, depends_on, criticality)
VALUES ('63636363-0000-0000-0000-0000000000a2', '63636363-0000-0000-0000-0000000000f1', 'b', 'quant.t63', '{a}', 'important');
INSERT INTO analysis.tasks (analysis_id, plan_id, node_id, tool_code, depends_on, criticality)
VALUES ('63636363-0000-0000-0000-0000000000a2', '63636363-0000-0000-0000-0000000000f1', 'c', 'quant.t63', '{a,b}', 'optional');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.tasks WHERE plan_id = '63636363-0000-0000-0000-0000000000f1'
$sql$, 3, 'T65  DAG a → b → c aceito (dependências inseridas em ordem topológica)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO analysis.tasks (analysis_id, plan_id, node_id, tool_code, depends_on)
  VALUES ('63636363-0000-0000-0000-0000000000a2', '63636363-0000-0000-0000-0000000000f1', 'd', 'quant.t63', '{zz}');
$sql$, 'T65a dependência de nó inexistente no plano');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO analysis.tasks (analysis_id, plan_id, node_id, tool_code, depends_on)
  VALUES ('63636363-0000-0000-0000-0000000000a2', '63636363-0000-0000-0000-0000000000f1', 'e', 'quant.t63', '{e}');
$sql$, 'T65b nó que depende de si mesmo (ciclo)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO analysis.tasks (analysis_id, plan_id, node_id, tool_code, depends_on)
  VALUES ('63636363-0000-0000-0000-0000000000a2', '63636363-0000-0000-0000-0000000000f9', 'x', 'quant.t63', '{}');
$sql$, 'T65c tarefa apontando plano de OUTRA análise');

SELECT pg_temp.expect_fail($sql$
  UPDATE analysis.tasks SET tool_code = 'orcamento.t63' WHERE id = '63636363-0000-0000-0000-000000000011';
$sql$, 'T65d definição da tarefa (tool/depends_on/params) é congelada');

SELECT pg_temp.expect_fail($sql$
  UPDATE analysis.tasks SET status = 'succeeded', finished_at = now() WHERE id = '63636363-0000-0000-0000-000000000011';
$sql$, 'T65e succeeded sem tool_execution_id (CHECK da 20)');

-- ================================================================ TESTE 66
-- Replan: versão derivada pelo banco, anterior superseded/inativo, replan_count contado pelo banco,
-- excedente recusado (replans_bounded: max_replans = 2).
INSERT INTO analysis.plans (id, analysis_id, dsl_version, plan)
VALUES ('63636363-0000-0000-0000-0000000000f2', '63636363-0000-0000-0000-0000000000a2', '1', '{"nodes": ["v2"]}'::jsonb);
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.plans
   WHERE id = '63636363-0000-0000-0000-0000000000f1' AND NOT is_active
     AND superseded_by = '63636363-0000-0000-0000-0000000000f2'
$sql$, 1, 'T66  plano v1 fica inativo e superseded pelo v2');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.plans WHERE id = '63636363-0000-0000-0000-0000000000f2' AND version = 2 AND is_active
$sql$, 1, 'T66a versão do plano novo é derivada pelo banco (2)');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.analyses WHERE id = '63636363-0000-0000-0000-0000000000a2' AND replan_count = 1
$sql$, 1, 'T66b replan_count contado pelo banco (1)');

INSERT INTO analysis.plans (id, analysis_id, dsl_version, plan, version)
VALUES ('63636363-0000-0000-0000-0000000000f3', '63636363-0000-0000-0000-0000000000a2', '1', '{"nodes": ["v3"]}'::jsonb, 99);
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.plans WHERE id = '63636363-0000-0000-0000-0000000000f3' AND version = 3
$sql$, 1, 'T66c versão explícita é ignorada — o banco deriva (3)');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.analyses WHERE id = '63636363-0000-0000-0000-0000000000a2' AND replan_count = 2
$sql$, 1, 'T66d replan_count = 2');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO analysis.plans (analysis_id, dsl_version, plan)
  VALUES ('63636363-0000-0000-0000-0000000000a2', '1', '{"nodes": ["v4"]}'::jsonb);
$sql$, 'T66e terceiro replan excede max_replans (replans_bounded)');

SELECT pg_temp.expect_fail($sql$
  UPDATE analysis.plans SET superseded_by = id WHERE id = '63636363-0000-0000-0000-0000000000f3';
$sql$, 'T66f plano não supersede a si mesmo');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.plans WHERE analysis_id = '63636363-0000-0000-0000-0000000000a2' AND is_active
$sql$, 1, 'T66g continua havendo exatamente um plano ativo');

-- ================================================================ TESTE 67
-- Relatório final exige evidência material e evidence_hash; blocked não; publicado é imutável.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO analysis.reports (analysis_id, content_md, evidence_hash, status)
  VALUES ('63636363-0000-0000-0000-0000000000a2', 'sem evidência', repeat('c', 64), 'final');
$sql$, 'T67  relatório final sem nenhuma evidência material');

INSERT INTO analysis.reports (id, analysis_id, content_md, status)
VALUES ('63636363-0000-0000-0000-000000000071', '63636363-0000-0000-0000-0000000000a2', 'bloqueado por orçamento', 'blocked');
DO $$ BEGIN RAISE NOTICE 'ok   · T67a relatório blocked não exige evidência'; END $$;

INSERT INTO analysis.evidence_findings (analysis_id, kind, finding, provenance)
VALUES ('63636363-0000-0000-0000-0000000000a2', 'quantitative', '{"metricas": {"retorno_acumulado_pct": 37.1}}'::jsonb,
        '[{"tool_execution_id": "63636363-0000-0000-0000-000000000099"}]'::jsonb);

SELECT pg_temp.expect_fail($sql$
  INSERT INTO analysis.reports (analysis_id, content_md, status)
  VALUES ('63636363-0000-0000-0000-0000000000a2', 'sem hash', 'final');
$sql$, 'T67b relatório final sem evidence_hash');

INSERT INTO analysis.reports (id, analysis_id, content_md, evidence_hash, status)
VALUES ('63636363-0000-0000-0000-000000000072', '63636363-0000-0000-0000-0000000000a2', 'relatório fundamentado', repeat('c', 64), 'final_with_warnings');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.reports
   WHERE id = '63636363-0000-0000-0000-000000000071' AND superseded_by = '63636363-0000-0000-0000-000000000072'
$sql$, 1, 'T67c relatório novo supersede o anterior');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM analysis.reports WHERE id = '63636363-0000-0000-0000-000000000072' AND version = 2
$sql$, 1, 'T67d versão do relatório derivada pelo banco (2)');

SELECT pg_temp.expect_fail($sql$
  UPDATE analysis.reports SET content_md = 'editado' WHERE id = '63636363-0000-0000-0000-000000000072';
$sql$, 'T67e relatório publicado é imutável (freeze da 20)');

SELECT pg_temp.expect_fail($sql$
  UPDATE analysis.reports SET superseded_by = id WHERE id = '63636363-0000-0000-0000-000000000072';
$sql$, 'T67f relatório não supersede a si mesmo');

-- ================================================================ TESTE 63
-- Execução ligada a uma análise (job, sem conversa na linha): os gates valem pela conversa da análise.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO tools.tool_executions (tool_version_id, scope_id, analysis_id, requested_params, input_hash)
  VALUES ('63636363-0000-0000-0000-0000000000e3', '63636363-0000-0000-0000-00000000000a',
          '63636363-0000-0000-0000-0000000000a2', '{}'::jsonb, repeat('4', 64));
$sql$, 'T63  família orcamento na análise do Analista (gate T18 pela análise)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO tools.tool_executions (tool_version_id, scope_id, analysis_id, requested_params, input_hash, policy_version_ids)
  VALUES ('63636363-0000-0000-0000-0000000000e1', '63636363-0000-0000-0000-00000000000a',
          '63636363-0000-0000-0000-0000000000a2', '{}'::jsonb, repeat('5', 64),
          ARRAY['63636363-0000-0000-0000-0000000000d1']::uuid[]);
$sql$, 'T63a política não aprovada (gate 29a pela análise)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO tools.tool_executions (tool_version_id, scope_id, analysis_id, requested_params, input_hash)
  VALUES ('63636363-0000-0000-0000-0000000000e2', '63636363-0000-0000-0000-00000000000a',
          '63636363-0000-0000-0000-0000000000a2', '{}'::jsonb, repeat('6', 64));
$sql$, 'T63b tool essential em conversa free (gate 29b pela análise)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO tools.tool_executions (tool_version_id, scope_id, analysis_id, requested_params, input_hash)
  VALUES ('63636363-0000-0000-0000-0000000000e1', '63636363-0000-0000-0000-00000000000b',
          '63636363-0000-0000-0000-0000000000a2', '{}'::jsonb, repeat('7', 64));
$sql$, 'T63c escopo da execução diferente do escopo da análise');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO tools.tool_executions (tool_version_id, scope_id, analysis_id, requested_params, input_hash)
  VALUES ('63636363-0000-0000-0000-0000000000e1', '63636363-0000-0000-0000-00000000000a',
          '63636363-0000-0000-0000-0000000000a1', '{}'::jsonb, repeat('8', 64));
$sql$, 'T63d análise sem conversa não sustenta os gates');

INSERT INTO tools.tool_executions (id, tool_version_id, scope_id, analysis_id, requested_params, input_hash)
VALUES ('63636363-0000-0000-0000-000000000099', '63636363-0000-0000-0000-0000000000e1',
        '63636363-0000-0000-0000-00000000000a', '63636363-0000-0000-0000-0000000000a2', '{}'::jsonb, repeat('9', 64));
DO $$ BEGIN RAISE NOTICE 'ok   · T63e execução da própria análise, família e plano corretos, aceita'; END $$;

-- a task só fecha apontando execução da própria análise
INSERT INTO tools.tool_executions (id, tool_version_id, scope_id, analysis_id, requested_params, input_hash)
VALUES ('63636363-0000-0000-0000-000000000098', '63636363-0000-0000-0000-0000000000e1',
        '63636363-0000-0000-0000-00000000000b', '63636363-0000-0000-0000-0000000000a3', '{}'::jsonb, repeat('0', 64));
SELECT pg_temp.expect_fail($sql$
  UPDATE analysis.tasks SET status = 'succeeded', finished_at = now(),
         tool_execution_id = '63636363-0000-0000-0000-000000000098'
   WHERE id = '63636363-0000-0000-0000-000000000011';
$sql$, 'T63f task fechada com execução de OUTRA análise');
UPDATE analysis.tasks SET status = 'succeeded', finished_at = now(),
       tool_execution_id = '63636363-0000-0000-0000-000000000099'
 WHERE id = '63636363-0000-0000-0000-000000000011';
DO $$ BEGIN RAISE NOTICE 'ok   · T63g task fechada com execução da própria análise'; END $$;

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Pipeline do Analista (32) concluído: gates valem pela análise,'
\echo ' DAG e replan limitados pelo banco, relatório final é fundamentado.'
\echo '================================================================'
