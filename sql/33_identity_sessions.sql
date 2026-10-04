-- =============================================================================
-- PLEXO · 33 — Sessões de autenticação [F7 — tela do Copiloto]
--
-- Auth própria, sessão OPACA no servidor: o browser guarda só um token aleatório em
-- cookie httpOnly; aqui fica o sha256 dele. Revogar = uma linha; expirar = uma coluna.
-- Nada de JWT: não há segredo compartilhado a vazar e toda sessão é auditável/revogável.
--
--   · identity.sessions        — uma linha por login; guard impede reativar/trocar token
--   · identity.login_attempts  — append-only, sem user_id (PII mínima), base do rate limit
--   · identity.membro_do_escopo(user, scope) — dono ou membro aceito não revogado
--   · identity.autenticar_sessao(token_hash)  — a ÚNICA porta de entrada da API
--
-- Papéis: plexo_app só LÊ as próprias sessões (RLS) e nunca escreve; login_attempts é
-- invisível para ele. Escrita = plexo_service (a rota /auth roda como serviço).
-- A 28 já concedeu DML por DEFAULT PRIVILEGES — os REVOKEs abaixo fecham o que ela abriu.
-- =============================================================================
BEGIN;

CREATE TABLE identity.sessions (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  user_id        uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  scope_id       uuid NOT NULL REFERENCES identity.scopes(id),   -- escopo ATIVO da sessão (troca via /auth/escopo)
  token_hash     core.hash_hex NOT NULL UNIQUE,                  -- sha256 do token opaco; o token nunca é gravado
  created_at     timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  expires_at     timestamptz NOT NULL,
  revoked_at     timestamptz,
  revoked_reason text,
  ip_address     inet,
  user_agent     text,
  CONSTRAINT sessions_expira_depois CHECK (expires_at > created_at)
);
CREATE INDEX sessions_user_idx    ON identity.sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX sessions_expires_idx ON identity.sessions (expires_at);

COMMENT ON TABLE identity.sessions IS
  'Sessão opaca de autenticação (F7). token_hash = sha256 do cookie plx_sessao. '
  'Expiração deslizante: last_seen_at/expires_at avançam no uso; revogação é definitiva.';

CREATE FUNCTION identity.sessions_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.token_hash <> OLD.token_hash OR NEW.user_id <> OLD.user_id OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'sessão: token, usuário e criação são imutáveis' USING ERRCODE = '23514';
  END IF;
  IF OLD.revoked_at IS NOT NULL THEN
    RAISE EXCEPTION 'sessão revogada não volta' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sessions_guard BEFORE UPDATE ON identity.sessions
  FOR EACH ROW EXECUTE FUNCTION identity.sessions_guard();

-- Tentativas de login: sem user_id de propósito (não vaza se o e-mail existe; sem RLS a exigir).
CREATE TABLE identity.login_attempts (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  email_hash  core.hash_hex NOT NULL,       -- sha256 do e-mail normalizado
  ip_address  inet,
  ok          boolean NOT NULL,
  reason      text
);
CREATE INDEX login_attempts_email_idx ON identity.login_attempts (email_hash, occurred_at DESC);
CREATE INDEX login_attempts_ip_idx    ON identity.login_attempts (ip_address, occurred_at DESC);
CREATE TRIGGER login_attempts_append_only BEFORE UPDATE OR DELETE ON identity.login_attempts
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- Dono do escopo, ou membro com convite aceito e não revogado; escopo arquivado não conta.
CREATE FUNCTION identity.membro_do_escopo(p_user uuid, p_scope uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM identity.scopes s
    WHERE s.id = p_scope AND s.archived_at IS NULL
      AND (s.owner_user_id = p_user
           OR EXISTS (SELECT 1 FROM identity.scope_members m
                      WHERE m.scope_id = s.id AND m.user_id = p_user
                        AND m.accepted_at IS NOT NULL AND m.revoked_at IS NULL))
  )
$$;

-- Porta de entrada da API: sessão viva + usuário ativo + membership válida no escopo ativo.
-- SECURITY INVOKER (padrão): sob plexo_app a RLS reduz a leitura às próprias sessões;
-- a API chama sob plexo_service.
CREATE FUNCTION identity.autenticar_sessao(p_token_hash core.hash_hex)
RETURNS TABLE (session_id uuid, user_id uuid, scope_id uuid, expires_at timestamptz, last_seen_at timestamptz)
LANGUAGE sql STABLE AS $$
  SELECT s.id, s.user_id, s.scope_id, s.expires_at, s.last_seen_at
  FROM identity.sessions s
  JOIN identity.users u ON u.id = s.user_id
  WHERE s.token_hash = p_token_hash
    AND s.revoked_at IS NULL
    AND s.expires_at > statement_timestamp()   -- não now(): dentro de uma transação longa (testes) o tempo tem de andar
    AND u.status = 'active' AND u.deleted_at IS NULL
    AND identity.membro_do_escopo(s.user_id, s.scope_id)
$$;

-- ---------------------------------------------------------------- RLS
ALTER TABLE identity.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity.sessions FORCE  ROW LEVEL SECURITY;
CREATE POLICY sessions_self ON identity.sessions FOR ALL
  USING (core.is_service() OR user_id::text = current_setting('app.user_id', true))
  WITH CHECK (core.is_service());

-- ---------------------------------------------------------------- privilégios
REVOKE INSERT, UPDATE, DELETE ON identity.sessions FROM plexo_app;
REVOKE ALL ON identity.login_attempts FROM plexo_app;
REVOKE UPDATE, DELETE ON identity.login_attempts FROM plexo_service;
REVOKE USAGE, SELECT ON SEQUENCE identity.login_attempts_id_seq FROM plexo_app;

COMMIT;
