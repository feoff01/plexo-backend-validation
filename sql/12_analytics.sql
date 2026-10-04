-- =============================================================================
-- SYNAPTA · 12_analytics.sql
--
-- Este schema não é "nice to have". É o instrumento da prioridade nº 1 do negócio.
--
-- P01  "WTP não validada — risco-mãe. ARR em escala varia 3,75× só por conversão e ARPU."
-- §4.13 MÉTRICA-MÃE DO PRODUTO: % de usuários com ≥1 ação concluída em D+14.
-- §4.15 "Este gate É exatamente o artefato de fake-door para validar WTP."
--
-- Sem estas tabelas, sobe-se a plataforma inteira e continua-se sem a única resposta
-- que importa. O fake-door é uma tabela, não uma landing page.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Eventos — particionado por mês
-- -----------------------------------------------------------------------------
CREATE TABLE analytics.events (
  id           uuid NOT NULL DEFAULT core.new_id(),
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  name         text NOT NULL,
  user_id      uuid,
  scope_id     uuid,
  anonymous_id text,
  session_id   text,
  source       text NOT NULL DEFAULT 'web' CHECK (source IN ('web','ios','android','server','job','landing')),
  app_version  text,
  props        jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (occurred_at, id)
) PARTITION BY RANGE (occurred_at);
CREATE INDEX events_name_idx ON analytics.events (name, occurred_at DESC);
CREATE INDEX events_user_idx ON analytics.events (user_id, occurred_at DESC);
CREATE INDEX events_props_gin ON analytics.events USING gin (props jsonb_path_ops);

COMMENT ON TABLE analytics.events IS
  'Sem FK para identity de propósito: eventos de landing e de usuário anônimo precisam '
  'existir antes do cadastro. A costura anônimo→usuário é feita por anonymous_id.';

-- [3ª onda] Evento analítico é fato histórico: append-only, como audit.activity_log.
-- A costura anônimo→usuário é feita em LEITURA (por anonymous_id), nunca reescrevendo
-- o evento. Retenção é DROP de partição, que o REVOKE não impede.
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON analytics.events
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
REVOKE UPDATE, DELETE ON analytics.events FROM PUBLIC;

-- -----------------------------------------------------------------------------
-- PAYWALL / FAKE-DOOR — o artefato de validação de WTP
-- -----------------------------------------------------------------------------
CREATE TABLE analytics.paywall_impressions (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  occurred_at        timestamptz NOT NULL DEFAULT now(),
  user_id            uuid REFERENCES identity.users(id),
  scope_id           uuid REFERENCES identity.scopes(id),
  anonymous_id       text,
  gate_code          text NOT NULL,     -- 'raiox_4o_finding','adotar_modelo','2o_objetivo',
                                        -- 'simulacao_cenario','copiloto_limite'
  -- a revelação estrutural quantificada mostrada (§4.15)
  hidden_count       int,
  hidden_impact_brl_year core.money_brl,
  hidden_families    text[],
  -- o preço efetivamente exibido — indispensável para o teste
  plan_shown         billing.plan_code,
  interval_shown     billing.billing_interval,
  price_shown_cents  int,
  experiment_variant text,
  -- resultado
  clicked            boolean NOT NULL DEFAULT false,
  clicked_at         timestamptz,
  checkout_started_at timestamptz,
  converted_subscription_id uuid REFERENCES billing.subscriptions(id),
  converted_at       timestamptz
);
CREATE INDEX paywall_gate_idx ON analytics.paywall_impressions (gate_code, occurred_at DESC);
CREATE INDEX paywall_variant_idx ON analytics.paywall_impressions (experiment_variant, plan_shown)
  WHERE experiment_variant IS NOT NULL;
CREATE INDEX paywall_user_idx ON analytics.paywall_impressions (user_id, occurred_at DESC);

COMMENT ON TABLE analytics.paywall_impressions IS
  '§4.15 — "publicar, medir clique, não cobrar ainda". price_shown_cents e '
  'hidden_impact_brl_year na MESMA linha são o que permite responder: a conversão responde '
  'ao preço ou ao valor revelado? Nenhuma outra tabela responde isso.';

-- -----------------------------------------------------------------------------
-- van Westendorp — 4 perguntas, literalmente 4 colunas
-- -----------------------------------------------------------------------------
CREATE TABLE analytics.wtp_surveys (
  id                uuid PRIMARY KEY DEFAULT core.new_id(),
  user_id           uuid REFERENCES identity.users(id),
  email             core.email,
  anonymous_id      text,
  plan_context      billing.plan_code,
  too_cheap_cents   int CHECK (too_cheap_cents >= 0),
  cheap_cents       int CHECK (cheap_cents >= 0),
  expensive_cents   int CHECK (expensive_cents >= 0),
  too_expensive_cents int CHECK (too_expensive_cents >= 0),
  portfolio_band    text,      -- '<100k','100k-300k','300k-1M','1M-3M','>3M'
  is_investor       boolean,
  current_advisor   text,
  submitted_at      timestamptz NOT NULL DEFAULT now(),
  survey_version    text NOT NULL DEFAULT 'v1',
  CHECK (too_cheap_cents IS NULL OR cheap_cents IS NULL OR too_cheap_cents <= cheap_cents),
  CHECK (expensive_cents IS NULL OR too_expensive_cents IS NULL OR expensive_cents <= too_expensive_cents)
);
CREATE INDEX wtp_surveys_band_idx ON analytics.wtp_surveys (portfolio_band, submitted_at DESC);

COMMENT ON TABLE analytics.wtp_surveys IS
  'P01 prioridade máxima. portfolio_band cruzado com as 4 respostas é o que testa se a '
  'banda-alvo R$100k–3M tem WTP homogênea — o conflito C05 do documento de contexto.';

-- -----------------------------------------------------------------------------
-- Experimentos
-- -----------------------------------------------------------------------------
CREATE TABLE analytics.experiments (
  code        core.slug PRIMARY KEY,
  hypothesis  text NOT NULL,
  metric      text NOT NULL,          -- métrica primária de decisão
  variants    text[] NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  ended_at    timestamptz,
  decision    text,
  decided_at  timestamptz
);

CREATE TABLE analytics.experiment_assignments (
  experiment_code core.slug NOT NULL REFERENCES analytics.experiments(code),
  subject_kind    text NOT NULL CHECK (subject_kind IN ('user','anonymous','scope')),
  subject_id      text NOT NULL,
  variant         text NOT NULL,
  assigned_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (experiment_code, subject_kind, subject_id)
);

-- -----------------------------------------------------------------------------
-- Funil de onboarding — mede o "principal vazamento de conversão" (P04)
-- -----------------------------------------------------------------------------
CREATE TABLE analytics.onboarding_steps (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  user_id       uuid REFERENCES identity.users(id),
  anonymous_id  text,
  track         identity.onboard_track,
  step_code     text NOT NULL,      -- 'intro','renda','dividas','patrimonio','objetivos',
                                    -- 'voce_investe','custo_inacao','suitability','raiox','output'
  step_index    smallint NOT NULL,
  entered_at    timestamptz NOT NULL DEFAULT now(),
  completed_at  timestamptz,
  abandoned_at  timestamptz,
  fields_filled smallint,
  time_on_step_ms int,
  skipped       boolean NOT NULL DEFAULT false
);
CREATE INDEX onboarding_steps_user_idx ON analytics.onboarding_steps (user_id, step_index);
CREATE INDEX onboarding_steps_funnel_idx ON analytics.onboarding_steps (step_code, entered_at DESC);

-- Captura de lead na landing (calculadoras)
CREATE TABLE analytics.leads (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  email         core.email,
  anonymous_id  text,
  source        text,
  campaign      text,
  calculator    text,           -- 'rota','comissao_oculta','concentracao'
  inputs        jsonb NOT NULL DEFAULT '{}'::jsonb,
  computed_output jsonb,
  converted_user_id uuid REFERENCES identity.users(id),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX leads_email_idx ON analytics.leads (email);

COMMIT;
