-- =============================================================================
-- SYNAPTA · 09_content.sql
-- Sinais (5 partes), Cartas, notificações e aprovações de compliance.
--
-- REGRA INVIOLÁVEL DESTE ARQUIVO (T12)
--   §4.1: máximo 2 push por semana POR ESCOPO. O excedente NÃO é descartado:
--   é GRAVADO COMO SUPRIMIDO. A diferença importa — o produto precisa saber
--   o que deixou de enviar para calibrar o motor de Sinais.
-- =============================================================================

BEGIN;

CREATE TYPE content.notification_channel AS ENUM ('push', 'email', 'inapp', 'whatsapp');

CREATE TYPE content.review_status AS ENUM ('draft', 'pending_review', 'approved', 'rejected');

-- -----------------------------------------------------------------------------
-- Sinais — as 5 partes são COLUNAS, não texto livre (§4.9)
-- -----------------------------------------------------------------------------
CREATE TABLE content.signals (
  id                   uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id             uuid NOT NULL REFERENCES identity.scopes(id),
  run_id               uuid NOT NULL REFERENCES engine.runs(id),
  kind                 text NOT NULL,          -- 'come_cotas_proximo','vencimento','drift_breach',...
  -- as 5 partes obrigatórias do Sinal:
  o_que_aconteceu      text NOT NULL,
  o_que_significa      text NOT NULL,
  impacto_na_carteira  text NOT NULL,
  precisa_agir         boolean NOT NULL,
  proximo_passo        text,                   -- obrigatório QUANDO precisa_agir
  relevance_score      numeric(6,3),
  instrument_id        uuid REFERENCES market.instruments(id),
  finding_id           uuid REFERENCES diagnostics.findings(id),
  valid_until          date,
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT signal_action_has_step CHECK (NOT precisa_agir OR proximo_passo IS NOT NULL)
);
CREATE INDEX signals_scope_idx ON content.signals (scope_id, created_at DESC);

COMMENT ON TABLE content.signals IS
  '§4.9 — Sinal sem as 5 partes é notícia, e notícia é o que a Synapta prometeu NÃO ser. '
  'precisa_agir=false é resposta válida e frequente: "não precisa fazer nada" é o produto.';

-- -----------------------------------------------------------------------------
-- Cartas (mensais/trimestrais) e relatórios compartilháveis
-- -----------------------------------------------------------------------------
CREATE TABLE content.letters (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id       uuid REFERENCES identity.scopes(id),   -- NULL = carta geral (todos)
  kind           text NOT NULL CHECK (kind IN ('mensal_personalizada','trimestral_geral','extraordinaria')),
  period_start   date NOT NULL,
  period_end     date NOT NULL,
  title          text NOT NULL,
  body_md        text NOT NULL,
  run_id         uuid REFERENCES engine.runs(id),
  review_status  content.review_status NOT NULL DEFAULT 'draft',
  reviewed_by    uuid REFERENCES identity.users(id),
  reviewed_at    timestamptz,
  published_at   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (period_end >= period_start),
  CHECK (published_at IS NULL OR review_status = 'approved')
);
CREATE INDEX letters_scope_idx ON content.letters (scope_id, period_end DESC);

CREATE TABLE content.user_reports (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id      uuid NOT NULL REFERENCES identity.scopes(id),
  kind          text NOT NULL CHECK (kind IN ('raiox_pdf','carta_pdf','resumo_anual')),
  run_id        uuid REFERENCES engine.runs(id),
  storage_key   text NOT NULL,                 -- S3 do PDF gerado
  share_token   text UNIQUE,                   -- link compartilhável; NULL = privado
  share_expires_at timestamptz,
  generated_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at    timestamptz
);
CREATE INDEX user_reports_scope_idx ON content.user_reports (scope_id, generated_at DESC);

-- Conteúdo educacional (base do Educador e dos links "entenda por quê")
CREATE TABLE content.education_contents (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  slug           core.slug NOT NULL UNIQUE,
  title          text NOT NULL,
  body_md        text NOT NULL,
  level          text NOT NULL DEFAULT 'basico' CHECK (level IN ('basico','intermediario','avancado')),
  tags           text[] NOT NULL DEFAULT '{}',
  review_status  content.review_status NOT NULL DEFAULT 'draft',
  reviewed_by    uuid REFERENCES identity.users(id),
  reviewed_at    timestamptz,
  published_at   timestamptz,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (published_at IS NULL OR review_status = 'approved')
);
CREATE TRIGGER education_contents_touch BEFORE UPDATE ON content.education_contents
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- Trilha de aprovação de compliance para QUALQUER conteúdo client-facing
CREATE TABLE content.compliance_reviews (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  subject_kind  text NOT NULL CHECK (subject_kind IN ('letter','education','signal_template','notification_template','prompt')),
  subject_id    uuid NOT NULL,
  decision      content.review_status NOT NULL,
  reviewer_id   uuid REFERENCES identity.users(id),
  notes         text,
  decided_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX compliance_reviews_subject_idx ON content.compliance_reviews (subject_kind, subject_id, decided_at DESC);
CREATE TRIGGER compliance_reviews_append_only BEFORE UPDATE OR DELETE
  ON content.compliance_reviews FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- -----------------------------------------------------------------------------
-- Notificações — com o teto de push COMO TRIGGER (T12)
-- -----------------------------------------------------------------------------
CREATE TABLE content.notifications (
  id               uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id         uuid NOT NULL REFERENCES identity.scopes(id),
  user_id          uuid NOT NULL REFERENCES identity.users(id),
  channel          content.notification_channel NOT NULL,
  subject_kind     text NOT NULL CHECK (subject_kind IN
                     ('signal','action','letter','calendar','system','billing')),
  subject_id       uuid,
  title            text NOT NULL,
  body             text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  scheduled_for    timestamptz,
  sent_at          timestamptz,
  delivered_at     timestamptz,
  read_at          timestamptz,
  suppressed_at    timestamptz,
  suppressed_reason text
);
CREATE INDEX notifications_scope_idx ON content.notifications (scope_id, created_at DESC);
CREATE INDEX notifications_pending_idx ON content.notifications (scheduled_for)
  WHERE sent_at IS NULL AND suppressed_at IS NULL;

-- Preferências por usuário/canal
CREATE TABLE content.notification_preferences (
  user_id     uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  channel     content.notification_channel NOT NULL,
  enabled     boolean NOT NULL DEFAULT true,
  quiet_hours int4range,                       -- ex.: [22,8)
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, channel)
);
CREATE TRIGGER notification_preferences_touch BEFORE UPDATE ON content.notification_preferences
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- §4.1 / T12: teto de push por semana. Limite vive em policy NOTIFICATION_LIMITS
-- (default 2). O 3º push da semana É GRAVADO, com suppressed_at preenchido —
-- o serviço de envio só despacha linhas com suppressed_at IS NULL.
CREATE OR REPLACE FUNCTION content.enforce_push_cap() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_limit int;
  v_sent  int;
BEGIN
  IF NEW.channel <> 'push' OR NEW.suppressed_at IS NOT NULL THEN
    RETURN NEW;
  END IF;

  SELECT coalesce((payload->>'max_push_per_week')::int, 2) INTO v_limit
  FROM engine.policy_versions
  WHERE code = 'NOTIFICATION_LIMITS' AND effective_to IS NULL
  ORDER BY effective_from DESC LIMIT 1;
  v_limit := coalesce(v_limit, 2);

  SELECT count(*) INTO v_sent
  FROM content.notifications
  WHERE scope_id = NEW.scope_id
    AND channel = 'push'
    AND suppressed_at IS NULL
    AND created_at >= date_trunc('week', now());

  IF v_sent >= v_limit THEN
    NEW.suppressed_at     := now();
    NEW.suppressed_reason := format('teto_semanal_%s_push', v_limit);
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER notifications_push_cap BEFORE INSERT ON content.notifications
  FOR EACH ROW EXECUTE FUNCTION content.enforce_push_cap();

COMMENT ON FUNCTION content.enforce_push_cap IS
  '§4.1 — "análise contínua, comunicação disciplinada". O excedente vira linha suprimida, '
  'não descarte: sem o registro do que NÃO foi enviado, o motor de Sinais não calibra.';

COMMIT;
