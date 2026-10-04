-- =============================================================================
-- SYNAPTA · 01_identity.sql
-- Usuários, ESCOPOS (decisão estrutural §4.12), perfil, suitability, LGPD.
--
-- DECISÃO CENTRAL: nenhuma tabela financeira referencia user_id.
-- Toda tabela financeira referencia scope_id. Escopo pessoal = escopo com 1 membro.
-- Isso torna Family Office (Advanced) uma feature de leitura, não uma migração.
-- =============================================================================

BEGIN;

CREATE TYPE identity.user_status   AS ENUM ('pending', 'active', 'suspended', 'deleted');
CREATE TYPE identity.scope_kind    AS ENUM ('personal', 'family', 'entity');
CREATE TYPE identity.member_role   AS ENUM ('owner', 'adult', 'dependent', 'viewer');
CREATE TYPE identity.risk_profile  AS ENUM ('conservador', 'moderado', 'arrojado');
CREATE TYPE identity.onboard_track AS ENUM ('a_nao_investe', 'b_ja_investe');
CREATE TYPE identity.consent_kind  AS ENUM (
  'terms', 'privacy', 'marketing_email', 'marketing_whatsapp',
  'open_finance', 'data_processing_sensitive'
);

-- -----------------------------------------------------------------------------
-- Usuários
-- -----------------------------------------------------------------------------
CREATE TABLE identity.users (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  email              core.email NOT NULL,
  email_verified_at  timestamptz,
  password_hash      text,                    -- NULL se auth federada
  full_name          text,
  phone_e164         text CHECK (phone_e164 ~ '^\+[1-9]\d{6,14}$'),
  birth_date         date,
  -- LGPD: minimização. CPF só é coletado quando billing exige nota fiscal.
  cpf_sha256         core.hash_hex,           -- para dedupe sem armazenar o dado
  cpf_encrypted      bytea,                   -- pgp_sym_encrypt, chave fora do banco
  status             identity.user_status NOT NULL DEFAULT 'pending',
  locale             text NOT NULL DEFAULT 'pt-BR',
  timezone           text NOT NULL DEFAULT 'America/Sao_Paulo',
  last_seen_at       timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  deleted_at         timestamptz
);
CREATE UNIQUE INDEX users_email_uk ON identity.users (email) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX users_cpf_uk   ON identity.users (cpf_sha256) WHERE cpf_sha256 IS NOT NULL AND deleted_at IS NULL;
CREATE TRIGGER users_touch BEFORE UPDATE ON identity.users
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TABLE identity.auth_identities (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  user_id      uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  provider     text NOT NULL,                 -- 'google', 'apple', 'password'
  provider_uid text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_uid)
);

-- -----------------------------------------------------------------------------
-- ESCOPOS — a raiz de tudo que é financeiro
-- -----------------------------------------------------------------------------
CREATE TABLE identity.scopes (
  id              uuid PRIMARY KEY DEFAULT core.new_id(),
  kind            identity.scope_kind NOT NULL DEFAULT 'personal',
  display_name    text NOT NULL,
  owner_user_id   uuid NOT NULL REFERENCES identity.users(id),
  parent_scope_id uuid REFERENCES identity.scopes(id),  -- família agrega escopos pessoais
  base_currency   core.currency NOT NULL DEFAULT 'BRL',
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  archived_at     timestamptz,
  CHECK (parent_scope_id IS NULL OR parent_scope_id <> id)
);
CREATE INDEX scopes_owner_idx  ON identity.scopes (owner_user_id);
CREATE INDEX scopes_parent_idx ON identity.scopes (parent_scope_id) WHERE parent_scope_id IS NOT NULL;
CREATE TRIGGER scopes_touch BEFORE UPDATE ON identity.scopes
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE identity.scopes IS
  '§4.12 — Family Office é ESCOPO, não aba. O seletor de header (Pessoal/Família/Entidade) '
  'troca o scope_id da sessão; nenhuma tela duplica dado. Escopo familiar agrega escopos '
  'pessoais via parent_scope_id — é isso que permite a concentração cruzada familiar.';

CREATE TABLE identity.scope_members (
  scope_id    uuid NOT NULL REFERENCES identity.scopes(id) ON DELETE CASCADE,
  user_id     uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  role        identity.member_role NOT NULL DEFAULT 'adult',
  permissions jsonb NOT NULL DEFAULT '{}'::jsonb,
  invited_at  timestamptz NOT NULL DEFAULT now(),
  accepted_at timestamptz,
  revoked_at  timestamptz,
  PRIMARY KEY (scope_id, user_id)
);
CREATE INDEX scope_members_user_idx ON identity.scope_members (user_id) WHERE revoked_at IS NULL;

-- Limite de membros do escopo familiar (§16.4 — sugestão: 5, mesmo núcleo).
-- O número vive em engine.policy_versions('FAMILY_LIMITS'); o trigger lê de lá.
CREATE OR REPLACE FUNCTION identity.enforce_member_limit() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_limit int; v_count int;
BEGIN
  SELECT coalesce((payload->>'max_members')::int, 5) INTO v_limit
  FROM engine.policy_versions
  WHERE code = 'FAMILY_LIMITS' AND effective_to IS NULL
  ORDER BY effective_from DESC LIMIT 1;

  SELECT count(*) INTO v_count FROM identity.scope_members
  WHERE scope_id = NEW.scope_id AND revoked_at IS NULL;

  IF v_count > coalesce(v_limit, 5) THEN
    RAISE EXCEPTION 'Escopo % excede o limite de % membros', NEW.scope_id, v_limit
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;
-- Trigger criado em 02_engine.sql (depende de policy_versions).

-- -----------------------------------------------------------------------------
-- Perfil e onboarding
-- -----------------------------------------------------------------------------
CREATE TABLE identity.user_profiles (
  user_id             uuid PRIMARY KEY REFERENCES identity.users(id) ON DELETE CASCADE,
  is_investor         boolean,                       -- a pergunta que decide tudo (§4.14)
  onboarding_track    identity.onboard_track,
  onboarding_step     text,
  onboarding_started_at   timestamptz,
  onboarding_completed_at timestamptz,
  monthly_income_brl  core.money_brl,
  monthly_expense_brl core.money_brl,
  net_worth_brl       core.money_brl,
  dependents_count    smallint,
  acquisition_source  text,
  answers             jsonb NOT NULL DEFAULT '{}'::jsonb,  -- respostas cruas do wizard
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER user_profiles_touch BEFORE UPDATE ON identity.user_profiles
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- -----------------------------------------------------------------------------
-- Suitability — registro regulatório, point-in-time, expira em 24 meses
-- -----------------------------------------------------------------------------
CREATE TABLE identity.suitability_assessments (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  user_id        uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  scope_id       uuid REFERENCES identity.scopes(id),
  questionnaire_version text NOT NULL,               -- versiona as 4 perguntas
  answers        jsonb NOT NULL,
  result         identity.risk_profile NOT NULL,
  score          numeric(6,2),
  taken_at       timestamptz NOT NULL DEFAULT now(),
  valid_until    date NOT NULL,
  superseded_at  timestamptz,
  CHECK (jsonb_typeof(answers) = 'object')
);
CREATE INDEX suitability_user_idx ON identity.suitability_assessments (user_id, taken_at DESC);
CREATE UNIQUE INDEX suitability_one_current
  ON identity.suitability_assessments (user_id) WHERE superseded_at IS NULL;

COMMENT ON TABLE identity.suitability_assessments IS
  'Point-in-time obrigatório: é preciso provar QUAL perfil estava vigente quando cada '
  'carteira-alvo foi gerada. Nunca fazer UPDATE do resultado — sempre nova linha + superseded_at.';

-- -----------------------------------------------------------------------------
-- LGPD
-- -----------------------------------------------------------------------------
CREATE TABLE identity.consents (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  user_id      uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  kind         identity.consent_kind NOT NULL,
  document_version text NOT NULL,                    -- 'termos-v3', 'privacidade-v2'
  granted      boolean NOT NULL,
  granted_at   timestamptz NOT NULL DEFAULT now(),
  revoked_at   timestamptz,
  expires_at   timestamptz,                          -- Open Finance: máx. 12 meses
  ip_address   inet,
  user_agent   text,
  evidence     jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX consents_user_kind_idx ON identity.consents (user_id, kind, granted_at DESC);
CREATE TRIGGER consents_append_only BEFORE UPDATE OR DELETE ON identity.consents
  FOR EACH ROW WHEN (OLD.revoked_at IS NOT NULL) EXECUTE FUNCTION core.forbid_update_delete();

CREATE TABLE identity.erasure_requests (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  user_id       uuid NOT NULL REFERENCES identity.users(id),
  requested_at  timestamptz NOT NULL DEFAULT now(),
  status        text NOT NULL DEFAULT 'received'
                CHECK (status IN ('received','under_review','executed','denied')),
  legal_basis_for_retention text,   -- registros regulatórios têm retenção obrigatória
  executed_at   timestamptz,
  notes         text
);

COMMENT ON TABLE identity.erasure_requests IS
  'Tensão real: §16.4 diz "dados nunca apagados" (downgrade) e a LGPD dá direito à eliminação. '
  'Resolução: downgrade = soft (acesso reduzido); eliminação LGPD = processo formal, '
  'com retenção obrigatória dos artefatos exigidos pela CVM devidamente justificada aqui.';

COMMIT;
