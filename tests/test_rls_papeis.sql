-- =============================================================================
-- SYNAPTA · testes de RLS sob PAPÉIS REAIS (T41–T50)
-- Até a Etapa 3 da validação, tudo rodava como administrador — que na Aiven tem
-- BYPASSRLS. Nenhuma política era exercitada. Aqui cada teste assume o papel
-- de aplicação (SET ROLE plexo_app / plexo_service, criados em 28_roles_grants)
-- e prova que o BANCO isola — não a aplicação.
-- Rodar com: psql -d synapta -v ON_ERROR_STOP=1 -f tests/test_rls_papeis.sql
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

-- conta linhas que o papel atual ENXERGA e compara com o esperado
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

BEGIN;
SET LOCAL app.role = 'service';   -- fixtures como administrador (BYPASSRLS)

-- ---------------------------------------------------------------- fixtures
-- Dois usuários, dois escopos pessoais, um dado financeiro em cada.
INSERT INTO identity.users (id, email, full_name, status) VALUES
  ('a1a1a1a1-0000-0000-0000-000000000001', 'u1@synapta.com.br', 'Usuária Um',  'active'),
  ('a1a1a1a1-0000-0000-0000-000000000002', 'u2@synapta.com.br', 'Usuário Dois', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id) VALUES
  ('b1b1b1b1-0000-0000-0000-000000000001', 'personal', 'Pessoal U1', 'a1a1a1a1-0000-0000-0000-000000000001'),
  ('b1b1b1b1-0000-0000-0000-000000000002', 'personal', 'Pessoal U2', 'a1a1a1a1-0000-0000-0000-000000000002');

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at) VALUES
  ('b1b1b1b1-0000-0000-0000-000000000001', 'a1a1a1a1-0000-0000-0000-000000000001', 'owner', now()),
  ('b1b1b1b1-0000-0000-0000-000000000002', 'a1a1a1a1-0000-0000-0000-000000000002', 'owner', now());

INSERT INTO identity.user_profiles (user_id, is_investor) VALUES
  ('a1a1a1a1-0000-0000-0000-000000000001', true),
  ('a1a1a1a1-0000-0000-0000-000000000002', false);

INSERT INTO wealth.accounts (id, scope_id, kind, label) VALUES
  ('c1c1c1c1-0000-0000-0000-000000000001', 'b1b1b1b1-0000-0000-0000-000000000001', 'corretora', 'Conta U1'),
  ('c1c1c1c1-0000-0000-0000-000000000002', 'b1b1b1b1-0000-0000-0000-000000000002', 'corretora', 'Conta U2');

INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('d1d1d1d1-0000-0000-0000-000000000001', '1.0.0', repeat('a',40), repeat('b',64));

INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date,
                         policy_version_ids, is_client_facing) VALUES
  ('e1e1e1e1-0000-0000-0000-000000000001', 'b1b1b1b1-0000-0000-0000-000000000001', 'raiox',
   'd1d1d1d1-0000-0000-0000-000000000001', repeat('1',64), current_date, '{}', false),
  ('e1e1e1e1-0000-0000-0000-000000000002', 'b1b1b1b1-0000-0000-0000-000000000002', 'raiox',
   'd1d1d1d1-0000-0000-0000-000000000001', repeat('2',64), current_date, '{}', false);

INSERT INTO ledger.value_entries (id, scope_id, category, amount_brl, occurred_on, run_id, methodology) VALUES
  ('f1f1f1f1-0000-0000-0000-000000000001', 'b1b1b1b1-0000-0000-0000-000000000001', 'custo_evitado', 1000,
   current_date, 'e1e1e1e1-0000-0000-0000-000000000001', '{"formula":"a"}'::jsonb),
  ('f1f1f1f1-0000-0000-0000-000000000002', 'b1b1b1b1-0000-0000-0000-000000000002', 'custo_evitado', 2000,
   current_date, 'e1e1e1e1-0000-0000-0000-000000000002', '{"formula":"b"}'::jsonb);

-- cartas: geral publicada (pública), geral em rascunho (invisível), pessoal de U2
INSERT INTO content.letters (scope_id, kind, period_start, period_end, title, body_md, review_status, published_at) VALUES
  (NULL, 'trimestral_geral', current_date - 90, current_date, 'Carta geral publicada', '...', 'approved', now()),
  (NULL, 'trimestral_geral', current_date - 90, current_date, 'Carta geral rascunho',  '...', 'draft',    NULL),
  ('b1b1b1b1-0000-0000-0000-000000000002', 'mensal_personalizada', current_date - 30, current_date,
   'Carta pessoal de U2', '...', 'approved', now());

-- ================================================================ TESTE 41
-- Isolamento por escopo sob o papel da API: U1 no escopo S1.
SET LOCAL ROLE plexo_app;
SET LOCAL app.role     = 'user';
SET LOCAL app.user_id  = 'a1a1a1a1-0000-0000-0000-000000000001';
SET LOCAL app.scope_id = 'b1b1b1b1-0000-0000-0000-000000000001';

SELECT pg_temp.expect_count($sql$SELECT 1 FROM wealth.accounts$sql$, 1,
  'T41  plexo_app no escopo S1 enxerga só a conta de S1');
SELECT pg_temp.expect_count($sql$SELECT 1 FROM wealth.accounts WHERE scope_id = 'b1b1b1b1-0000-0000-0000-000000000002'$sql$, 0,
  'T41b filtrar explicitamente pelo escopo alheio devolve zero');
SELECT pg_temp.expect_count($sql$SELECT 1 FROM identity.scopes$sql$, 1,
  'T41c plexo_app enxerga só o escopo do qual é dono/membro');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO wealth.accounts (scope_id, kind, label)
  VALUES ('b1b1b1b1-0000-0000-0000-000000000002', 'corretora', 'invasão');
$sql$, 'T41d INSERT em escopo alheio (WITH CHECK)');

DO $$
DECLARE n int;
BEGIN
  UPDATE wealth.accounts SET label = 'invadida' WHERE scope_id = 'b1b1b1b1-0000-0000-0000-000000000002';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 0 THEN RAISE EXCEPTION 'FALHOU T41e: UPDATE atingiu % linha(s) de outro escopo', n; END IF;
  DELETE FROM wealth.accounts WHERE scope_id = 'b1b1b1b1-0000-0000-0000-000000000002';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 0 THEN RAISE EXCEPTION 'FALHOU T41e: DELETE atingiu % linha(s) de outro escopo', n; END IF;
  RAISE NOTICE 'ok   · T41e UPDATE/DELETE em escopo alheio atingem 0 linhas';
END $$;

-- ================================================================ TESTE 42
-- Sabotagem: a API "se declara" service pelo GUC. Não pode bastar.
SET LOCAL app.role = 'service';
SELECT pg_temp.expect_count($sql$SELECT 1 FROM wealth.accounts$sql$, 1,
  'T42  plexo_app com app.role=service continua preso ao próprio escopo');
SELECT pg_temp.expect_fail($sql$
  INSERT INTO content.letters (scope_id, kind, period_start, period_end, title, body_md)
  VALUES (NULL, 'trimestral_geral', current_date, current_date, 'carta forjada', '...');
$sql$, 'T42b plexo_app com app.role=service não grava carta (WITH CHECK só service)');
SET LOCAL app.role = 'user';

-- sem escopo selecionado, não há nada a ver
SET LOCAL app.scope_id = '';
SELECT pg_temp.expect_count($sql$SELECT 1 FROM wealth.accounts$sql$, 0,
  'T42c plexo_app sem app.scope_id não enxerga linha nenhuma');
SET LOCAL app.scope_id = 'b1b1b1b1-0000-0000-0000-000000000001';

-- ================================================================ TESTE 43
-- O papel de serviço enxerga tudo — mas só quando a sessão declara a intenção.
RESET ROLE;
SET LOCAL ROLE plexo_service;
SET LOCAL app.role = 'service';
-- Conta só os escopos DESTA fixture: o banco de dev é compartilhado e acumula dado commitado
-- (a persona da F12 adicionou contas e a contagem global virou 4). O que o teste prova é que o
-- serviço ATRAVESSA escopo — não que a tabela tenha exatamente 2 linhas no mundo.
SELECT pg_temp.expect_count($sql$SELECT 1 FROM wealth.accounts
  WHERE scope_id IN ('b1b1b1b1-0000-0000-0000-000000000001',
                     'b1b1b1b1-0000-0000-0000-000000000002')$sql$, 2,
  'T43  plexo_service + app.role=service enxerga os dois escopos');
SET LOCAL app.role = 'user';
SELECT pg_temp.expect_count($sql$SELECT 1 FROM wealth.accounts$sql$, 1,
  'T43b plexo_service SEM app.role=service fica preso ao escopo do GUC');
SET LOCAL app.role = 'service';

-- ================================================================ TESTE 44
-- Tabelas por USUÁRIO (PII): U1 não lê nem escreve o perfil de U2.
RESET ROLE;
SET LOCAL ROLE plexo_app;
SET LOCAL app.role = 'user';
SELECT pg_temp.expect_count($sql$SELECT 1 FROM identity.users$sql$, 1,
  'T44  plexo_app enxerga só o próprio identity.users');
SELECT pg_temp.expect_count($sql$SELECT 1 FROM identity.user_profiles$sql$, 1,
  'T44b plexo_app enxerga só o próprio user_profiles');
DO $$
DECLARE n int;
BEGIN
  UPDATE identity.user_profiles SET is_investor = true
   WHERE user_id = 'a1a1a1a1-0000-0000-0000-000000000002';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 0 THEN RAISE EXCEPTION 'FALHOU T44c: UPDATE atingiu o perfil de outro usuário (% linha(s))', n; END IF;
  RAISE NOTICE 'ok   · T44c UPDATE no perfil de outro usuário atinge 0 linhas';
END $$;
SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.consents (user_id, kind, document_version, granted)
  VALUES ('a1a1a1a1-0000-0000-0000-000000000002', 'marketing_email', 'termos-v1', true);
$sql$, 'T44d INSERT de consentimento em nome de outro usuário');

-- ================================================================ TESTE 45
-- Cartas: geral publicada é pública; rascunho e carta pessoal alheia, não.
SELECT pg_temp.expect_count($sql$SELECT 1 FROM content.letters$sql$, 1,
  'T45  plexo_app vê 1 carta: a geral publicada (não o rascunho, não a pessoal de U2)');

-- ================================================================ TESTE 46
-- Append-only também por PRIVILÉGIO: nem o papel de serviço tem UPDATE/DELETE.
RESET ROLE;
SET LOCAL ROLE plexo_service;
SET LOCAL app.role = 'service';
SELECT pg_temp.expect_fail($sql$
  UPDATE ledger.value_entries SET amount_brl = 1 WHERE id = 'f1f1f1f1-0000-0000-0000-000000000001';
$sql$, 'T46  plexo_service UPDATE no Ledger (sem privilégio, além do trigger)');
SELECT pg_temp.expect_fail($sql$
  DELETE FROM audit.activity_log WHERE true;
$sql$, 'T46b plexo_service DELETE no activity_log');

-- ================================================================ TESTE 47
-- VIEWS: por padrão rodam com os privilégios do DONO (administrador, BYPASSRLS).
-- Sem security_invoker, a view vaza todos os escopos para a API.
RESET ROLE;
SET LOCAL ROLE plexo_app;
SET LOCAL app.role = 'user';
SELECT pg_temp.expect_count($sql$SELECT 1 FROM ledger.v_scope_totals$sql$, 1,
  'T47  view ledger.v_scope_totals respeita RLS do papel que consulta');
RESET ROLE;
SET LOCAL ROLE plexo_service;
SET LOCAL app.role = 'service';
-- Gêmeo do T43: sob serviço nada filtra, então a contagem tem de ser dos escopos DESTA fixture.
-- Passava por acidente (ledger vazio no dev); a primeira linha de ledger commitada quebraria.
SELECT pg_temp.expect_count($sql$SELECT 1 FROM ledger.v_scope_totals
  WHERE scope_id IN ('b1b1b1b1-0000-0000-0000-000000000001',
                     'b1b1b1b1-0000-0000-0000-000000000002')$sql$, 2,
  'T47b a mesma view, sob plexo_service, mostra os dois escopos');

-- ================================================================ TESTE 48
-- Papel da API não cria objetos nem lê o que não lhe foi concedido.
RESET ROLE;
SET LOCAL ROLE plexo_app;
SET LOCAL app.role = 'user';
SELECT pg_temp.expect_fail($sql$ CREATE TABLE wealth.tabela_intrusa (id int); $sql$,
  'T48  plexo_app CREATE TABLE no schema');

-- ================================================================ TESTE 49
-- Cobertura viva: toda tabela com scope_id ou user_id tem RLS (exceção: analytics.events).
RESET ROLE;
DO $$
DECLARE faltam text;
BEGIN
  SELECT string_agg(n.nspname||'.'||c.relname, ', ' ORDER BY 1) INTO faltam
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE c.relkind IN ('r','p') AND NOT c.relispartition
    AND n.nspname NOT IN ('public','pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg\_%'
    AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0
                AND NOT a.attisdropped AND a.attname IN ('scope_id','user_id'))
    AND NOT c.relrowsecurity
    AND (n.nspname, c.relname) <> ('analytics','events');
  IF faltam IS NOT NULL THEN
    RAISE EXCEPTION 'FALHOU T49: tabelas com dado de cliente e sem RLS: %', faltam;
  END IF;
  RAISE NOTICE 'ok   · T49 toda tabela com scope_id/user_id tem RLS (exceção documentada: analytics.events)';
END $$;

-- ================================================================ TESTE 50
-- Nenhum papel de aplicação escapa de RLS por atributo.
DO $$
DECLARE v text;
BEGIN
  SELECT string_agg(rolname, ', ') INTO v FROM pg_roles
   WHERE rolname IN ('plexo_app','plexo_service') AND (rolbypassrls OR rolsuper);
  IF v IS NOT NULL THEN RAISE EXCEPTION 'FALHOU T50: papel com BYPASSRLS/SUPERUSER: %', v; END IF;
  IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('plexo_app','plexo_service')) <> 2 THEN
    RAISE EXCEPTION 'FALHOU T50: papéis plexo_app/plexo_service não existem';
  END IF;
  RAISE NOTICE 'ok   · T50 plexo_app e plexo_service existem, sem BYPASSRLS e sem SUPERUSER';
END $$;

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' RLS sob papéis reais concluído. Cada "ok" acima é um vazamento'
\echo ' que o banco recusa — para a API, para o serviço e para as views.'
\echo '================================================================'
