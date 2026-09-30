-- =============================================================================
-- PLEXO · testes das regras invioláveis — RLS nas VIEWS reescritas (T127–T128, 55)
--   T127 `diagnostics.v_client_profile` só mostra o escopo da sessão
--   T128 `context.v_fact_coverage` só mostra o escopo da sessão
--   T129 TODA view dos schemas de dado de cliente declara `security_invoker`
--
-- POR QUE ESTE ARQUIVO EXISTE
--   As duas views nasceram certas. `40_client_profile.sql:251` criou
--   `v_client_profile` com `WITH (security_invoker = true)`, e `38_fact_catalog.sql:590`
--   fez o mesmo com `v_fact_coverage`. Depois, três migrations (44, 45, 47 para a
--   primeira; 43 para a segunda) as reescreveram com `CREATE OR REPLACE VIEW ... AS`,
--   **sem repetir a cláusula** — e o `REPLACE` do PostgreSQL SUBSTITUI as reloptions em
--   vez de mesclá-las. A flag caiu nas quatro vezes, em silêncio.
--
--   O efeito, medido no banco real em 2026-08-30 antes da correção: sob `plexo_app` com
--   `app.scope_id` de UM cliente, `v_client_profile` devolvia **9 escopos** e
--   `v_fact_coverage` devolvia **22**. A tabela por baixo (`diagnostics.client_scores`)
--   devolvia 1 — a RLS estava certa; as views a contornavam, porque view sem
--   `security_invoker` roda com os direitos do DONO, e o dono aqui tem BYPASSRLS.
--
--   Era a decisão nº 1 do projeto ("views com `security_invoker`") desfeita por uma
--   cláusula omitida, e nada percebeu: `tools/validador.py` só olhava `CREATE VIEW`, não
--   `CREATE OR REPLACE VIEW`, e `test_rls_papeis.sql` testava as TABELAS.
--
--   Por isso o T129 não testa duas views: testa a PROPRIEDADE sobre todas elas. Foi a
--   lição da F16 — o que pega o defeito da próxima vez é a rede, não o remendo.
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_views.sql [papel]
-- Termina em ROLLBACK — não deixa resíduo.
-- =============================================================================
\set QUIET on
SET client_min_messages = notice;

CREATE OR REPLACE FUNCTION pg_temp.expect_count(p_sql text, p_expected bigint, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v bigint;
BEGIN
  EXECUTE 'SELECT count(*) FROM (' || p_sql || ') q' INTO v;
  IF v <> p_expected THEN
    RAISE EXCEPTION 'FALHOU: "%" — esperado % linha(s), papel enxergou %', p_label, p_expected, v;
  END IF;
  RAISE NOTICE 'ok   · % (% linha(s), como esperado)', p_label, v;
END $$;

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixture (prefixo 1127)
INSERT INTO identity.users (id, email, full_name, status) VALUES
  ('11270000-0000-4000-8000-000000000001', 't127-a@teste.local', 'Cliente A T127', 'active'),
  ('11270000-0000-4000-8000-000000000002', 't127-b@teste.local', 'Cliente B T127', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id) VALUES
  ('11270000-0000-4000-8000-00000000000a', 'personal', 'Pessoal A', '11270000-0000-4000-8000-000000000001'),
  ('11270000-0000-4000-8000-00000000000b', 'personal', 'Pessoal B', '11270000-0000-4000-8000-000000000002');

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at) VALUES
  ('11270000-0000-4000-8000-00000000000a', '11270000-0000-4000-8000-000000000001', 'owner', now()),
  ('11270000-0000-4000-8000-00000000000b', '11270000-0000-4000-8000-000000000002', 'owner', now());

INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('11270000-0000-4000-8000-000000000003', '1.3.0', repeat('7', 40), repeat('a', 64));

INSERT INTO engine.policy_versions (id, code, version, payload, compliance_status)
VALUES ('11270000-0000-4000-8000-000000000004', 'T127_SCORES', 1, '{}'::jsonb, 'draft');

INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date, is_client_facing)
VALUES ('11270000-0000-4000-8000-00000000001a', '11270000-0000-4000-8000-00000000000a',
        'client_profile', '11270000-0000-4000-8000-000000000003', repeat('1', 64), current_date, false),
       ('11270000-0000-4000-8000-00000000001b', '11270000-0000-4000-8000-00000000000b',
        'client_profile', '11270000-0000-4000-8000-000000000003', repeat('2', 64), current_date, false);

-- Um score para CADA cliente: é o par que torna o vazamento visível como contagem.
INSERT INTO diagnostics.client_scores
  (scope_id, as_of_date, score_code, run_id, value, coverage, confidence, policy_version_id)
VALUES ('11270000-0000-4000-8000-00000000000a', current_date, 'score.fluxo',
        '11270000-0000-4000-8000-00000000001a', 0.70, 0.90, 0.80,
        '11270000-0000-4000-8000-000000000004'),
       ('11270000-0000-4000-8000-00000000000b', current_date, 'score.fluxo',
        '11270000-0000-4000-8000-00000000001b', 0.40, 0.90, 0.80,
        '11270000-0000-4000-8000-000000000004');

-- ================================================================ TESTE 127
SET LOCAL ROLE plexo_app;
SET LOCAL app.role = 'user';
SET LOCAL app.scope_id = '11270000-0000-4000-8000-00000000000a';
-- `app.user_id` também, e não é detalhe: a política de `identity.scopes` chaveia em
-- MEMBERSHIP (owner_user_id ou scope_members), não em `app.scope_id`. `v_fact_coverage`
-- faz CROSS JOIN com `identity.scopes`, então sem o user_id ela devolve zero linha para o
-- próprio dono — o que, na primeira versão deste teste, me fez achar por um minuto que a
-- correção tinha quebrado a tela. O `app_session` da API seta os dois; o teste também tem.
SET LOCAL app.user_id = '11270000-0000-4000-8000-000000000001';

SELECT pg_temp.expect_count($sql$
  SELECT DISTINCT scope_id FROM diagnostics.v_client_profile
   WHERE scope_id IN ('11270000-0000-4000-8000-00000000000a',
                      '11270000-0000-4000-8000-00000000000b')
$sql$, 1, 'T127 v_client_profile devolve só o escopo da sessão');

-- O controle que prova que a RLS da TABELA sempre esteve certa: se este passar e o de
-- cima falhar, o defeito é da view, não da política.
SELECT pg_temp.expect_count($sql$
  SELECT DISTINCT scope_id FROM diagnostics.client_scores
   WHERE scope_id IN ('11270000-0000-4000-8000-00000000000a',
                      '11270000-0000-4000-8000-00000000000b')
$sql$, 1, 'T127b (controle) a tabela client_scores já filtrava corretamente');

-- ================================================================ TESTE 128
-- `v_fact_coverage` faz CROSS JOIN com `identity.scopes`: sem `security_invoker` ela
-- enumera o que FALTA saber sobre todo cliente da base.
SELECT pg_temp.expect_count($sql$
  SELECT DISTINCT scope_id FROM context.v_fact_coverage
   WHERE scope_id IN ('11270000-0000-4000-8000-00000000000a',
                      '11270000-0000-4000-8000-00000000000b')
$sql$, 1, 'T128 v_fact_coverage devolve só o escopo da sessão');

RESET ROLE;
SET LOCAL app.role = 'service';

-- ================================================================ TESTE 129
-- A REDE, não o remendo: toda view dos schemas que guardam dado de cliente precisa
-- declarar `security_invoker`. Uma view nova sem a cláusula, ou uma reescrita que a
-- perca, falha aqui — que é exatamente o que faltou entre a 40 e a 47.
SELECT pg_temp.expect_count($sql$
  SELECT n.nspname || '.' || v.relname AS view_sem_invoker
    FROM pg_class v
    JOIN pg_namespace n ON n.oid = v.relnamespace
   WHERE v.relkind = 'v'
     AND n.nspname IN ('diagnostics','context','wealth','estate','budget','planning',
                       'preferences','household','decisions','analysis','agents','ledger')
     AND NOT coalesce(
           (SELECT true FROM unnest(coalesce(v.reloptions, '{}')) o
             WHERE o = 'security_invoker=true'), false)
$sql$, 0, 'T129 nenhuma view de dado de cliente sem security_invoker');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' View sem `security_invoker` roda com os direitos do DONO, e o'
\echo ' dono tem BYPASSRLS. `CREATE OR REPLACE VIEW` SUBSTITUI as'
\echo ' reloptions: omitir a cláusula na reescrita derruba a regra nº 1'
\echo ' do projeto sem erro nenhum em lugar nenhum.'
\echo '================================================================'
