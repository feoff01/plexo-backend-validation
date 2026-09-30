-- =============================================================================
-- PLEXO · testes das regras invioláveis — sessões de autenticação (T68–T72, 33_identity_sessions)
--   T68 identity.autenticar_sessao só devolve sessão viva de usuário ativo com membership válida
--   T69 identity.sessions sob plexo_app: lê só as próprias, nunca escreve (RLS + REVOKE)
--   T70 identity.login_attempts é append-only e invisível para plexo_app
--   T71 sessions_guard: token/usuário/criação imutáveis; sessão revogada não volta; expires_at > created_at
--   T72 identity.membro_do_escopo: dono ou membro aceito não revogado; convite pendente e revogado = falso
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_identity.sql [plexo_service]
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

CREATE OR REPLACE FUNCTION pg_temp.expect_bool(p_sql text, p_expected boolean, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v boolean;
BEGIN
  EXECUTE p_sql INTO v;
  IF v IS DISTINCT FROM p_expected THEN
    RAISE EXCEPTION 'FALHOU: "%" — esperado %, obtido %', p_label, p_expected, v;
  END IF;
  RAISE NOTICE 'ok   · % (= %)', p_label, v;
END;
$$;

BEGIN;
SET LOCAL app.role = 'service';   -- fixtures como serviço/administrador

-- ---------------------------------------------------------------- fixtures
-- U1 ativo (dono de S1; convidado sem aceite em S2; membro revogado em S3)
-- U2 ativo (dono de S2 e S3, sem linha em scope_members)
-- U3 suspenso (dono de S4)
INSERT INTO identity.users (id, email, full_name, status) VALUES
  ('68680000-0000-4000-8000-000000000001', 'u1-t68@plexo.local', 'Usuária Um',   'active'),
  ('68680000-0000-4000-8000-000000000002', 'u2-t68@plexo.local', 'Usuário Dois', 'active'),
  ('68680000-0000-4000-8000-000000000003', 'u3-t68@plexo.local', 'Usuário Três', 'suspended');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id) VALUES
  ('68680000-0000-4000-8000-00000000000a', 'personal', 'S1', '68680000-0000-4000-8000-000000000001'),
  ('68680000-0000-4000-8000-00000000000b', 'personal', 'S2', '68680000-0000-4000-8000-000000000002'),
  ('68680000-0000-4000-8000-00000000000c', 'family',   'S3', '68680000-0000-4000-8000-000000000002'),
  ('68680000-0000-4000-8000-00000000000d', 'personal', 'S4', '68680000-0000-4000-8000-000000000003');

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at, revoked_at) VALUES
  ('68680000-0000-4000-8000-00000000000a', '68680000-0000-4000-8000-000000000001', 'owner', now(), NULL),
  ('68680000-0000-4000-8000-00000000000b', '68680000-0000-4000-8000-000000000001', 'adult', NULL,  NULL),
  ('68680000-0000-4000-8000-00000000000c', '68680000-0000-4000-8000-000000000001', 'adult', now() - interval '2 days', now() - interval '1 day');

-- sessões: a viva · b expirada · c revogada · d de usuário suspenso · e sem membership aceita · f de U2
INSERT INTO identity.sessions (id, user_id, scope_id, token_hash, created_at, last_seen_at, expires_at, revoked_at) VALUES
  ('68680000-0000-4000-8000-0000000000a1', '68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000a', repeat('a', 64), now(), now(), now() + interval '1 day', NULL),
  ('68680000-0000-4000-8000-0000000000b1', '68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000a', repeat('b', 64), now() - interval '2 days', now() - interval '2 days', now() - interval '1 day', NULL),
  ('68680000-0000-4000-8000-0000000000c1', '68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000a', repeat('c', 64), now(), now(), now() + interval '1 day', now()),
  ('68680000-0000-4000-8000-0000000000d1', '68680000-0000-4000-8000-000000000003', '68680000-0000-4000-8000-00000000000d', repeat('d', 64), now(), now(), now() + interval '1 day', NULL),
  ('68680000-0000-4000-8000-0000000000e1', '68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000b', repeat('e', 64), now(), now(), now() + interval '1 day', NULL),
  ('68680000-0000-4000-8000-0000000000f1', '68680000-0000-4000-8000-000000000002', '68680000-0000-4000-8000-00000000000b', repeat('f', 64), now(), now(), now() + interval '1 day', NULL);

-- ================================================================ TESTE 68
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.autenticar_sessao(repeat('a', 64)) $sql$, 1,
  'T68a sessão viva de usuário ativo com membership autentica');
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.autenticar_sessao(repeat('b', 64)) $sql$, 0,
  'T68b sessão expirada não autentica');
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.autenticar_sessao(repeat('c', 64)) $sql$, 0,
  'T68c sessão revogada não autentica');
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.autenticar_sessao(repeat('d', 64)) $sql$, 0,
  'T68d usuário suspenso não autentica');
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.autenticar_sessao(repeat('e', 64)) $sql$, 0,
  'T68e sessão em escopo sem membership aceita não autentica');
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.autenticar_sessao(repeat('9', 64)) $sql$, 0,
  'T68f token desconhecido não autentica');

-- ================================================================ TESTE 72 (função de membership)
SELECT pg_temp.expect_bool($sql$ SELECT identity.membro_do_escopo('68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000a') $sql$, true,
  'T72a dono com linha owner aceita é membro');
SELECT pg_temp.expect_bool($sql$ SELECT identity.membro_do_escopo('68680000-0000-4000-8000-000000000002', '68680000-0000-4000-8000-00000000000b') $sql$, true,
  'T72b dono sem linha em scope_members é membro');
SELECT pg_temp.expect_bool($sql$ SELECT identity.membro_do_escopo('68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000b') $sql$, false,
  'T72c convite pendente (sem accepted_at) não é membro');
SELECT pg_temp.expect_bool($sql$ SELECT identity.membro_do_escopo('68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000c') $sql$, false,
  'T72d membro revogado não é membro');
SELECT pg_temp.expect_bool($sql$ SELECT identity.membro_do_escopo('68680000-0000-4000-8000-000000000002', '68680000-0000-4000-8000-00000000000a') $sql$, false,
  'T72e terceiro não é membro');

-- ================================================================ TESTE 71 (guard, como serviço)
SELECT pg_temp.expect_fail($sql$
  UPDATE identity.sessions SET revoked_at = NULL WHERE id = '68680000-0000-4000-8000-0000000000c1';
$sql$, 'T71a sessão revogada não volta');
SELECT pg_temp.expect_fail($sql$
  UPDATE identity.sessions SET token_hash = repeat('1', 64) WHERE id = '68680000-0000-4000-8000-0000000000a1';
$sql$, 'T71b token_hash é imutável');
SELECT pg_temp.expect_fail($sql$
  UPDATE identity.sessions SET user_id = '68680000-0000-4000-8000-000000000002' WHERE id = '68680000-0000-4000-8000-0000000000a1';
$sql$, 'T71c user_id é imutável');
SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.sessions (user_id, scope_id, token_hash, created_at, expires_at)
  VALUES ('68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000a', repeat('2', 64), now(), now() - interval '1 hour');
$sql$, 'T71d expires_at anterior a created_at é rejeitado');
SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.sessions (user_id, scope_id, token_hash, expires_at)
  VALUES ('68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000a', repeat('a', 64), now() + interval '1 day');
$sql$, 'T71e token_hash é único');
DO $$
DECLARE n int;
BEGIN
  UPDATE identity.sessions SET last_seen_at = now(), expires_at = now() + interval '2 days'
   WHERE id = '68680000-0000-4000-8000-0000000000a1';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FALHOU T71f: renovação da sessão viva deveria atingir 1 linha, atingiu %', n; END IF;
  UPDATE identity.sessions SET revoked_at = now(), revoked_reason = 'logout'
   WHERE id = '68680000-0000-4000-8000-0000000000f1';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FALHOU T71g: revogação deveria atingir 1 linha, atingiu %', n; END IF;
  RAISE NOTICE 'ok   · T71f/g serviço renova e revoga sessão viva';
END $$;

-- ================================================================ TESTE 70 (login_attempts, como serviço)
INSERT INTO identity.login_attempts (email_hash, ip_address, ok, reason)
VALUES (repeat('7', 64), '127.0.0.1', false, 'senha_invalida');
SELECT pg_temp.expect_fail($sql$
  UPDATE identity.login_attempts SET ok = true WHERE email_hash = repeat('7', 64);
$sql$, 'T70a login_attempts não aceita UPDATE');
SELECT pg_temp.expect_fail($sql$
  DELETE FROM identity.login_attempts WHERE email_hash = repeat('7', 64);
$sql$, 'T70b login_attempts não aceita DELETE');

-- ================================================================ TESTE 69 (RLS sob plexo_app)
SET ROLE plexo_app;
SET LOCAL app.role = 'user';
SET LOCAL app.user_id = '68680000-0000-4000-8000-000000000001';
SET LOCAL app.scope_id = '68680000-0000-4000-8000-00000000000a';

SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.sessions $sql$, 4,
  'T69a plexo_app vê só as sessões do próprio usuário (a, b, c, e)');
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.sessions WHERE user_id = '68680000-0000-4000-8000-000000000002' $sql$, 0,
  'T69b sessão de outro usuário não existe para plexo_app');
SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.sessions (user_id, scope_id, token_hash, expires_at)
  VALUES ('68680000-0000-4000-8000-000000000001', '68680000-0000-4000-8000-00000000000a', repeat('3', 64), now() + interval '1 day');
$sql$, 'T69c plexo_app não cria sessão');
SELECT pg_temp.expect_fail($sql$
  UPDATE identity.sessions SET expires_at = now() + interval '30 days' WHERE id = '68680000-0000-4000-8000-0000000000a1';
$sql$, 'T69d plexo_app não estende sessão');
SELECT pg_temp.expect_fail($sql$
  DELETE FROM identity.sessions WHERE id = '68680000-0000-4000-8000-0000000000a1';
$sql$, 'T69e plexo_app não apaga sessão');
SELECT pg_temp.expect_fail($sql$
  SELECT 1 FROM identity.login_attempts;
$sql$, 'T70c plexo_app não lê login_attempts');
SELECT pg_temp.expect_fail($sql$
  INSERT INTO identity.login_attempts (email_hash, ok) VALUES (repeat('8', 64), true);
$sql$, 'T70d plexo_app não grava login_attempts');
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM identity.autenticar_sessao(repeat('f', 64)) $sql$, 0,
  'T69f sob plexo_app, autenticar_sessao de outro usuário devolve nada (RLS na função invoker)');

RESET ROLE;
ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Sessões de autenticação: cada "ok" acima é um caminho de'
\echo ' sequestro, extensão ou reativação de sessão que o banco recusa.'
\echo '================================================================'
