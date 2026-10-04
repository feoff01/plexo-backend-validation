-- =============================================================================
-- SYNAPTA · 03_billing.sql
-- Planos, entitlements (TIER_CONFIG como DADO — §16.8.2), assinaturas.
--
-- REGRAS ESTRUTURAIS
--   · §16.4: downgrade NUNCA apaga dado. Downgrade é filtro de leitura
--     (entitlements), não deleção. Por isso nenhum ON DELETE CASCADE parte daqui.
--   · Preços são [PENDENTE] no documento de contexto. billing.plan_prices
--     está pronta e VAZIA — chutar número no seed criaria âncora falsa.
--   · O gate F5: plano Wealth existe no enum, mas requires_cvm_authorization
--     o mantém invendável até a autorização sair.
-- =============================================================================

BEGIN;

CREATE TYPE billing.plan_code AS ENUM ('free', 'essential', 'advanced', 'wealth');

CREATE TYPE billing.billing_interval AS ENUM ('monthly', 'annual');

CREATE TYPE billing.subscription_status AS ENUM (
  'trialing', 'active', 'past_due', 'paused', 'canceled', 'expired'
);

CREATE TYPE billing.payment_status AS ENUM (
  'pending', 'paid', 'failed', 'refunded', 'chargeback'
);

-- -----------------------------------------------------------------------------
-- Planos — linha por plano; regras de acesso viram entitlements (dado)
-- -----------------------------------------------------------------------------
CREATE TABLE billing.plans (
  code                        billing.plan_code PRIMARY KEY,
  display_name                text NOT NULL,
  description                 text,
  is_purchasable              boolean NOT NULL DEFAULT false,
  requires_cvm_authorization  boolean NOT NULL DEFAULT false,   -- F5: Wealth bloqueado
  max_scopes                  smallint,
  sort_order                  smallint NOT NULL DEFAULT 0,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER plans_touch BEFORE UPDATE ON billing.plans
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- Preços versionados — PRONTA E VAZIA de propósito (preço é [PENDENTE])
CREATE TABLE billing.plan_prices (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  plan_code      billing.plan_code NOT NULL REFERENCES billing.plans(code),
  interval       billing.billing_interval NOT NULL,
  currency       core.currency NOT NULL DEFAULT 'BRL',
  amount_cents   int NOT NULL CHECK (amount_cents >= 0),
  effective_from timestamptz NOT NULL DEFAULT now(),
  effective_to   timestamptz,
  experiment_variant text,          -- preço de teste A/B aparece AQUI, com trilha
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE UNIQUE INDEX plan_prices_one_current
  ON billing.plan_prices (plan_code, interval, currency)
  WHERE effective_to IS NULL AND experiment_variant IS NULL;

-- -----------------------------------------------------------------------------
-- Entitlements — TIER_CONFIG como dado. O produto lê daqui, nunca de if/else.
-- Ex.: ('free','raiox_findings_visiveis','3'), ('essential','copilot_perguntas_mes','100')
-- -----------------------------------------------------------------------------
CREATE TABLE billing.entitlements (
  plan_code   billing.plan_code NOT NULL REFERENCES billing.plans(code),
  feature     core.slug NOT NULL,
  limit_value text,                 -- número, 'true'/'false' ou 'unlimited'
  config      jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (plan_code, feature)
);
CREATE TRIGGER entitlements_touch BEFORE UPDATE ON billing.entitlements
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE billing.entitlements IS
  '§16.4 — o gate vive no OUTPUT. Mudar o limite do Free de 3 para 5 findings '
  'visíveis é um UPDATE aqui, não um deploy. O fake-door de F3 depende disso.';

-- -----------------------------------------------------------------------------
-- Assinaturas — o escopo assina, não o usuário (coerente com C1)
-- -----------------------------------------------------------------------------
CREATE TABLE billing.subscriptions (
  id                    uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id              uuid NOT NULL REFERENCES identity.scopes(id),
  payer_user_id         uuid NOT NULL REFERENCES identity.users(id),
  plan_code             billing.plan_code NOT NULL REFERENCES billing.plans(code),
  interval              billing.billing_interval NOT NULL,
  status                billing.subscription_status NOT NULL DEFAULT 'trialing',
  plan_price_id         uuid REFERENCES billing.plan_prices(id),
  provider              text,                       -- 'stripe','pagarme','mercadopago'
  provider_customer_id  text,
  provider_subscription_id text,
  trial_ends_at         timestamptz,
  current_period_start  timestamptz,
  current_period_end    timestamptz,
  cancel_at_period_end  boolean NOT NULL DEFAULT false,
  canceled_at           timestamptz,
  started_at            timestamptz NOT NULL DEFAULT now(),
  ended_at              timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX subscriptions_one_active_per_scope
  ON billing.subscriptions (scope_id)
  WHERE status IN ('trialing','active','past_due');
CREATE INDEX subscriptions_provider_idx ON billing.subscriptions (provider, provider_subscription_id);
CREATE TRIGGER subscriptions_touch BEFORE UPDATE ON billing.subscriptions
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- Histórico de transições (upgrade/downgrade/churn — insumo direto de P01)
CREATE TABLE billing.subscription_events (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  subscription_id uuid NOT NULL REFERENCES billing.subscriptions(id),
  scope_id        uuid NOT NULL REFERENCES identity.scopes(id),
  event           text NOT NULL CHECK (event IN
                    ('created','trial_started','activated','upgraded','downgraded',
                     'payment_failed','paused','resumed','cancel_scheduled','canceled','expired')),
  from_plan       billing.plan_code,
  to_plan         billing.plan_code,
  reason          text,
  occurred_at     timestamptz NOT NULL DEFAULT now(),
  metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX subscription_events_sub_idx ON billing.subscription_events (subscription_id, occurred_at);
CREATE TRIGGER subscription_events_append_only BEFORE UPDATE OR DELETE
  ON billing.subscription_events FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- -----------------------------------------------------------------------------
-- Faturas e pagamentos
-- -----------------------------------------------------------------------------
CREATE TABLE billing.invoices (
  id               uuid PRIMARY KEY DEFAULT core.new_id(),
  subscription_id  uuid NOT NULL REFERENCES billing.subscriptions(id),
  scope_id         uuid NOT NULL REFERENCES identity.scopes(id),
  provider_invoice_id text,
  amount_cents     int NOT NULL CHECK (amount_cents >= 0),
  currency         core.currency NOT NULL DEFAULT 'BRL',
  period_start     date,
  period_end       date,
  due_at           timestamptz,
  status           billing.payment_status NOT NULL DEFAULT 'pending',
  issued_at        timestamptz NOT NULL DEFAULT now(),
  paid_at          timestamptz,
  nfse_key         text,             -- nota fiscal, quando emitida
  metadata         jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX invoices_subscription_idx ON billing.invoices (subscription_id, issued_at DESC);

CREATE TABLE billing.payments (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  invoice_id     uuid NOT NULL REFERENCES billing.invoices(id),
  provider       text NOT NULL,
  provider_payment_id text,
  method         text CHECK (method IN ('pix','credit_card','boleto')),
  amount_cents   int NOT NULL CHECK (amount_cents >= 0),
  status         billing.payment_status NOT NULL DEFAULT 'pending',
  attempted_at   timestamptz NOT NULL DEFAULT now(),
  confirmed_at   timestamptz,
  failure_code   text,
  metadata       jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX payments_invoice_idx ON billing.payments (invoice_id);

-- Webhooks crus do provedor — a verdade vem de fora, guardamos como chegou
CREATE TABLE billing.provider_webhook_events (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  provider     text NOT NULL,
  event_type   text NOT NULL,
  provider_event_id text,
  payload      jsonb NOT NULL,
  received_at  timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  processing_error text,
  UNIQUE (provider, provider_event_id)
);
CREATE TRIGGER webhook_events_append_guard BEFORE DELETE
  ON billing.provider_webhook_events FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- Cupons/descontos (lançamento, parcerias)
CREATE TABLE billing.discount_codes (
  code           text PRIMARY KEY,
  description    text,
  percent_off    numeric(5,2) CHECK (percent_off > 0 AND percent_off <= 100),
  amount_off_cents int CHECK (amount_off_cents > 0),
  applies_to_plan billing.plan_code,
  max_redemptions int,
  redeemed_count  int NOT NULL DEFAULT 0,
  valid_from     timestamptz NOT NULL DEFAULT now(),
  valid_until    timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (percent_off IS NOT NULL OR amount_off_cents IS NOT NULL)
);

-- -----------------------------------------------------------------------------
-- SEEDS — planos existem desde o dia zero; preços NÃO (são [PENDENTE])
-- -----------------------------------------------------------------------------
INSERT INTO billing.plans (code, display_name, description, is_purchasable, requires_cvm_authorization, max_scopes, sort_order) VALUES
  ('free',      'Free',      'Raio-X com Top-3 curado, 1 objetivo, Copiloto limitado', true,  false, 1, 0),
  ('essential', 'Essential', 'Raio-X completo, objetivos, Carteiras Modelo, Copiloto ampliado', true, false, 1, 1),
  ('advanced',  'Advanced',  'Tudo do Essential + Family Office (escopos), concentração cruzada', true, false, 5, 2),
  ('wealth',    'Wealth',    'Camada consultiva humana — bloqueado até autorização CVM', false, true, 10, 3);

INSERT INTO billing.entitlements (plan_code, feature, limit_value) VALUES
  ('free',      'raiox_findings_visiveis',  '3'),
  ('free',      'goals_max',                '1'),
  ('free',      'copilot_perguntas_mes',    '10'),
  ('free',      'family_office',            'false'),
  ('essential', 'raiox_findings_visiveis',  'unlimited'),
  ('essential', 'goals_max',                'unlimited'),
  ('essential', 'copilot_perguntas_mes',    '100'),
  ('essential', 'family_office',            'false'),
  ('advanced',  'raiox_findings_visiveis',  'unlimited'),
  ('advanced',  'goals_max',                'unlimited'),
  ('advanced',  'copilot_perguntas_mes',    'unlimited'),
  ('advanced',  'family_office',            'true'),
  ('wealth',    'raiox_findings_visiveis',  'unlimited'),
  ('wealth',    'goals_max',                'unlimited'),
  ('wealth',    'copilot_perguntas_mes',    'unlimited'),
  ('wealth',    'family_office',            'true');

COMMIT;
