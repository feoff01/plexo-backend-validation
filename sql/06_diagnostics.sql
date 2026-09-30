-- =============================================================================
-- SYNAPTA · 06_diagnostics.sql
-- Raio-X: Fundação, score, findings e ações.
--
-- O PROBLEMA CENTRAL DO DESENHO
-- O job das 22h recalcula findings todo dia. A ação tem estado que PRECISA sobreviver
-- ao recálculo: cooldown de 90d, supressão após 2 recusas, "não entendi" acumulado.
-- Se cada run criar um finding novo, a regra §16.5 nunca dispara — o cooldown reseta
-- toda madrugada e o usuário recebe eternamente a ação que já dispensou duas vezes.
--
-- SOLUÇÃO: `finding_key` determinístico (ex.: 'custo.taxa_fundo_alta:<instrument_id>').
--   diagnostics.findings          -> 1 linha por finding LÓGICO, estável no tempo
--   diagnostics.finding_observations -> 1 linha por RUN (série temporal do mesmo finding)
--   diagnostics.actions           -> estado do usuário, ancorado no finding lógico
-- =============================================================================

BEGIN;

CREATE TYPE diagnostics.finding_family AS ENUM (
  'fundacao','custo','risco','tributacao','alocacao','planejamento','estrutura','liquidez'
);

CREATE TYPE diagnostics.severity AS ENUM ('info','baixa','media','alta','critica');

CREATE TYPE diagnostics.action_state AS ENUM (
  'nova','vista','em_andamento','concluida','dispensada','suprimida','expirada'
);

CREATE TYPE diagnostics.dismissal_reason AS ENUM (
  'ja_fiz','nao_concordo','nao_agora','nao_entendi'
);
COMMENT ON TYPE diagnostics.dismissal_reason IS
  '§4.1 — "não entendi" é o motivo mais valioso do produto: dispara revisão de copy '
  'daquele finding, não requeue da ação.';

CREATE TYPE diagnostics.foundation_light AS ENUM ('verde','amarelo','vermelho');

-- -----------------------------------------------------------------------------
-- Taxonomia (~90 tipos) como DADO — permite ir de 19 → 45 → 90 sem migração
-- -----------------------------------------------------------------------------
CREATE TABLE diagnostics.finding_types (
  code               core.slug PRIMARY KEY,
  family             diagnostics.finding_family NOT NULL,
  display_name       text NOT NULL,
  default_severity   diagnostics.severity NOT NULL DEFAULT 'media',
  min_plan           billing.plan_code NOT NULL DEFAULT 'advanced',
  is_quantifiable    boolean NOT NULL DEFAULT true,
  execution_friction smallint NOT NULL DEFAULT 3 CHECK (execution_friction BETWEEN 1 AND 5),
  copy_version       text NOT NULL DEFAULT 'v1',
  copy_review_needed boolean NOT NULL DEFAULT false,   -- levantada por "não entendi"
  requires_transactions boolean NOT NULL DEFAULT false,
  requires_open_finance boolean NOT NULL DEFAULT false,
  is_active          boolean NOT NULL DEFAULT true,
  implemented_at     date,
  policy_version_id  uuid REFERENCES engine.policy_versions(id),
  notes              text
);
CREATE INDEX finding_types_family_idx ON diagnostics.finding_types (family) WHERE is_active;

COMMENT ON COLUMN diagnostics.finding_types.min_plan IS
  '§16.4 — o gate vive no OUTPUT (D10). O Free calcula tudo e revela um Top-3 curado; '
  'o restante vira revelação estrutural quantificada (quantos e quanto), nunca blur.';

-- -----------------------------------------------------------------------------
-- Findings — entidade LÓGICA, estável entre runs
-- -----------------------------------------------------------------------------
CREATE TABLE diagnostics.findings (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id           uuid NOT NULL REFERENCES identity.scopes(id),
  finding_type_code  core.slug NOT NULL REFERENCES diagnostics.finding_types(code),
  finding_key        text NOT NULL,             -- determinístico: tipo + entidade alvo
  subject_kind       text,                      -- 'instrument','account','goal','issuer','scope'
  subject_id         uuid,
  severity           diagnostics.severity NOT NULL,
  confidence         core.confidence NOT NULL,
  impact_brl_year    core.money_brl,
  execution_friction smallint NOT NULL DEFAULT 3,
  -- §4.1: score = (impacto × confiança) / atrito
  priority_score     numeric(18,6) GENERATED ALWAYS AS (
                       CASE WHEN execution_friction > 0
                            THEN (coalesce(impact_brl_year,0) * confidence) / execution_friction
                            ELSE 0 END) STORED,
  evidence           jsonb NOT NULL DEFAULT '{}'::jsonb,
  quantification     jsonb NOT NULL DEFAULT '{}'::jsonb,
  first_detected_at  timestamptz NOT NULL DEFAULT now(),
  last_detected_at   timestamptz NOT NULL DEFAULT now(),
  first_run_id       uuid NOT NULL REFERENCES engine.runs(id),
  last_run_id        uuid NOT NULL REFERENCES engine.runs(id),
  is_current         boolean NOT NULL DEFAULT true,
  -- governança de recusa vive AQUI, não na ação: a ação é reemitida a cada run,
  -- o finding é estável. Contador na ação zeraria a cada madrugada (§16.5).
  dismissal_count    smallint NOT NULL DEFAULT 0,
  cooldown_until     date,
  permanently_suppressed boolean NOT NULL DEFAULT false,
  resolved_at        timestamptz,
  resolution         text CHECK (resolution IN ('acted','disappeared','superseded','invalidated'))
);
CREATE UNIQUE INDEX findings_key_uk ON diagnostics.findings (scope_id, finding_key);
CREATE INDEX findings_scope_current_idx ON diagnostics.findings (scope_id, priority_score DESC)
  WHERE is_current AND NOT permanently_suppressed;
CREATE INDEX findings_type_idx ON diagnostics.findings (finding_type_code);

COMMENT ON COLUMN diagnostics.findings.finding_key IS
  'Chave de identidade lógica gerada pelo motor, estável entre execuções. '
  'Formato: "<tipo>:<subject_kind>:<subject_id>". É o que permite ao recálculo diário '
  'atualizar o finding em vez de recriá-lo — e é o que faz cooldown e supressão existirem.';

-- Série temporal: o mesmo finding observado em runs sucessivos
CREATE TABLE diagnostics.finding_observations (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  finding_id      uuid NOT NULL REFERENCES diagnostics.findings(id) ON DELETE CASCADE,
  run_id          uuid NOT NULL REFERENCES engine.runs(id),
  observed_on     date NOT NULL,
  severity        diagnostics.severity NOT NULL,
  confidence      core.confidence NOT NULL,
  impact_brl_year core.money_brl,
  payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (finding_id, run_id)
);
CREATE INDEX finding_observations_date_idx ON diagnostics.finding_observations (finding_id, observed_on DESC);
CREATE TRIGGER finding_observations_append_only BEFORE UPDATE OR DELETE
  ON diagnostics.finding_observations FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
REVOKE UPDATE, DELETE ON diagnostics.finding_observations FROM PUBLIC;   -- [3ª onda] padrão T10

-- -----------------------------------------------------------------------------
-- Ações — a máquina de estado do produto
-- -----------------------------------------------------------------------------
CREATE TABLE diagnostics.actions (
  id                uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id          uuid NOT NULL REFERENCES identity.scopes(id),
  finding_id        uuid NOT NULL REFERENCES diagnostics.findings(id),
  state             diagnostics.action_state NOT NULL DEFAULT 'nova',
  -- §16.5: 5 blocos obrigatórios. Falta um => a ação NÃO É EXIBIDA.
  blocks            jsonb NOT NULL,
  min_plan          billing.plan_code NOT NULL DEFAULT 'advanced',
  impact_brl_year   core.money_brl,
  is_featured       boolean NOT NULL DEFAULT false,
  featured_at       timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  viewed_at         timestamptz,
  started_at        timestamptz,
  completed_at      timestamptz,
  dismissed_at      timestamptz,
  dismissal_reason  diagnostics.dismissal_reason,
  dismissal_count   smallint NOT NULL DEFAULT 0,
  cooldown_until    date,
  permanently_suppressed boolean NOT NULL DEFAULT false,
  due_date          date,               -- só quando existe prazo REAL (come-cotas, exercício)
  run_id            uuid NOT NULL REFERENCES engine.runs(id),
  updated_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT action_five_blocks CHECK (
    blocks ?& array['gatilho','evidencia','quantificacao','passo','porque_agora']
  ),
  CONSTRAINT action_dismissal_needs_reason CHECK (
    (state <> 'dispensada') OR (dismissal_reason IS NOT NULL)
  ),
  CONSTRAINT action_completed_has_timestamp CHECK (
    (state <> 'concluida') OR (completed_at IS NOT NULL)
  )
);

-- §16.5 / §4.1 — MÁXIMO 1 AÇÃO ATIVA EXIBIDA, sempre.
CREATE UNIQUE INDEX actions_one_featured_per_scope
  ON diagnostics.actions (scope_id) WHERE is_featured;

CREATE INDEX actions_scope_state_idx ON diagnostics.actions (scope_id, state, created_at DESC);
CREATE INDEX actions_finding_idx ON diagnostics.actions (finding_id);
CREATE UNIQUE INDEX actions_open_per_finding
  ON diagnostics.actions (finding_id)
  WHERE state IN ('nova','vista','em_andamento');

CREATE TRIGGER actions_touch BEFORE UPDATE ON diagnostics.actions
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON CONSTRAINT action_five_blocks ON diagnostics.actions IS
  '§16.5 — "Card sem quantificação é ruído". A regra vira constraint porque regra que vive '
  'só no serviço vaza no primeiro backfill ou script de suporte.';

-- Log append-only de transições
CREATE TABLE diagnostics.action_events (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  action_id   uuid NOT NULL REFERENCES diagnostics.actions(id) ON DELETE CASCADE,
  scope_id    uuid NOT NULL REFERENCES identity.scopes(id),
  from_state  diagnostics.action_state,
  to_state    diagnostics.action_state NOT NULL,
  actor       text NOT NULL CHECK (actor IN ('user','system','job','admin')),
  actor_user_id uuid REFERENCES identity.users(id),
  reason      diagnostics.dismissal_reason,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  metadata    jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX action_events_action_idx ON diagnostics.action_events (action_id, occurred_at);
CREATE INDEX action_events_scope_idx  ON diagnostics.action_events (scope_id, occurred_at DESC);
CREATE TRIGGER action_events_append_only BEFORE UPDATE OR DELETE
  ON diagnostics.action_events FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
REVOKE UPDATE, DELETE ON diagnostics.action_events FROM PUBLIC;          -- [3ª onda] padrão T10

-- Cooldown de 90 dias + supressão permanente após 2 recusas (§16.5)
CREATE OR REPLACE FUNCTION diagnostics.apply_dismissal_rules() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_cooldown_days  int;
  v_max_dismissals int;
  v_count          smallint;
  v_type_code      core.slug;
BEGIN
  IF NEW.state <> 'dispensada' THEN RETURN NEW; END IF;
  IF TG_OP = 'UPDATE' AND OLD.state = 'dispensada'
     AND OLD.dismissal_reason IS NOT DISTINCT FROM NEW.dismissal_reason THEN
    RETURN NEW;   -- reafirmação da mesma recusa, não conta de novo
  END IF;

  SELECT coalesce((payload->>'cooldown_days')::int, 90),
         coalesce((payload->>'max_dismissals')::int, 2)
    INTO v_cooldown_days, v_max_dismissals
  FROM engine.policy_versions
  WHERE code = 'ACTION_GOVERNANCE' AND effective_to IS NULL
  ORDER BY effective_from DESC LIMIT 1;

  v_cooldown_days  := coalesce(v_cooldown_days, 90);
  v_max_dismissals := coalesce(v_max_dismissals, 2);

  -- o contador é do FINDING
  UPDATE diagnostics.findings
     SET dismissal_count = dismissal_count + 1,
         cooldown_until  = (current_date + (v_cooldown_days || ' days')::interval)::date,
         permanently_suppressed = (dismissal_count + 1) >= v_max_dismissals
   WHERE id = NEW.finding_id
   RETURNING dismissal_count, permanently_suppressed, finding_type_code
   INTO v_count, NEW.permanently_suppressed, v_type_code;

  NEW.dismissed_at    := coalesce(NEW.dismissed_at, now());
  NEW.dismissal_count := v_count;
  NEW.cooldown_until  := (current_date + (v_cooldown_days || ' days')::interval)::date;
  NEW.is_featured     := false;
  IF NEW.permanently_suppressed THEN
    NEW.state := 'suprimida';
  END IF;

  -- "não entendi" marca o TIPO para revisão de copy, não a ação (§4.1)
  IF NEW.dismissal_reason = 'nao_entendi' THEN
    UPDATE diagnostics.finding_types SET copy_review_needed = true WHERE code = v_type_code;
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER actions_dismissal_rules BEFORE INSERT OR UPDATE ON diagnostics.actions
  FOR EACH ROW EXECUTE FUNCTION diagnostics.apply_dismissal_rules();

-- -----------------------------------------------------------------------------
-- Fundação — sempre acima do score (§16.3)
-- -----------------------------------------------------------------------------
CREATE TABLE diagnostics.foundation_status (
  scope_id             uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date           date NOT NULL,
  run_id               uuid NOT NULL REFERENCES engine.runs(id),
  monthly_cost_brl     core.money_brl,
  reserve_amount_brl   core.money_brl,
  reserve_months       numeric(6,2),
  reserve_target_months numeric(6,2),
  reserve_light        diagnostics.foundation_light NOT NULL,
  expensive_debt_brl   core.money_brl NOT NULL DEFAULT 0,
  expensive_debt_max_rate core.rate_annual,
  debt_light           diagnostics.foundation_light NOT NULL,
  investable_surplus_brl core.money_brl,
  overall_light        diagnostics.foundation_light NOT NULL,
  is_critical          boolean NOT NULL,
  computed_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_id, as_of_date)
);

-- Score da carteira — desativado quando a Fundação está crítica
CREATE TABLE diagnostics.portfolio_scores (
  scope_id       uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date     date NOT NULL,
  run_id         uuid NOT NULL REFERENCES engine.runs(id),
  score          numeric(5,2) CHECK (score BETWEEN 0 AND 100),
  is_disabled    boolean NOT NULL DEFAULT false,
  disabled_reason text CHECK (disabled_reason IN ('fundacao_critica','cobertura_insuficiente','dados_insuficientes')),
  components     jsonb NOT NULL DEFAULT '{}'::jsonb,
  computed_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_id, as_of_date),
  CONSTRAINT score_disabled_xor_value CHECK (
    (is_disabled AND score IS NULL AND disabled_reason IS NOT NULL)
    OR (NOT is_disabled AND score IS NOT NULL)
  )
);

COMMENT ON CONSTRAINT score_disabled_xor_value ON diagnostics.portfolio_scores IS
  '§16.1.8 / D11 — "Fundação sempre acima do score; score DESATIVADO se Fundação crítica". '
  'Não é score baixo: é ausência de score. O banco não permite gravar as duas coisas.';

-- Cobertura da análise (§4.1)
CREATE TABLE diagnostics.coverage_reports (
  scope_id          uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date        date NOT NULL,
  run_id            uuid NOT NULL REFERENCES engine.runs(id),
  total_value_brl   core.money_brl NOT NULL,
  covered_value_brl core.money_brl NOT NULL,
  coverage_pct      numeric(6,4) NOT NULL,
  uncovered_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {"coe": 12000, "previdencia": 45000}
  computed_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_id, as_of_date)
);

-- Revelação estrutural quantificada do paywall (§4.15) — o que o Free vê do que não vê
CREATE TABLE diagnostics.gate_reveals (
  scope_id            uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date          date NOT NULL,
  run_id              uuid NOT NULL REFERENCES engine.runs(id),
  visible_count       int NOT NULL,
  hidden_count        int NOT NULL,
  hidden_impact_brl_year core.money_brl NOT NULL,
  hidden_families     text[] NOT NULL DEFAULT '{}',
  PRIMARY KEY (scope_id, as_of_date)
);

COMMENT ON TABLE diagnostics.gate_reveals IS
  '§4.15 — mostra O QUE foi encontrado e QUANTO vale; esconde por que e como resolver. '
  'Sem blur. Esta tabela é literalmente o artefato do fake-door de validação de WTP.';

COMMIT;
