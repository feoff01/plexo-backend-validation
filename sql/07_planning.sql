-- =============================================================================
-- SYNAPTA · 07_planning.sql
-- Objetivos, Portfolio Builder, Carteiras Modelo, drift 5/25 e roteamento de aporte.
--
-- REGRAS INVIOLÁVEIS DESTE ARQUIVO
--   · D27: UMA carteira-alvo ativa por escopo — índice único parcial (T7).
--   · §16.2: pesos da carteira-alvo somam 1,000 — constraint trigger DIFERIDA (T14):
--     valida no COMMIT, permitindo inserir as linhas uma a uma dentro da transação.
--   · §4.6: "Carteiras Modelo", NUNCA "Recomendadas" — o CHECK recusa o nome (T8).
--     Parece pedante; é jurídico. "Recomendação" é ato regulado (RCVM 19).
-- =============================================================================

BEGIN;

CREATE TYPE planning.goal_status AS ENUM ('rascunho','ativa','pausada','concluida','arquivada');

CREATE TYPE planning.target_origin AS ENUM ('builder','carteira_modelo','importada','ajuste_manual');

CREATE TYPE planning.target_status AS ENUM ('draft','active','superseded','archived');

-- -----------------------------------------------------------------------------
-- Objetivos e projeções (Monte Carlo por objetivo)
-- -----------------------------------------------------------------------------
CREATE TABLE planning.goals (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id           uuid NOT NULL REFERENCES identity.scopes(id),
  created_by         uuid REFERENCES identity.users(id),
  name               text NOT NULL,
  kind               text NOT NULL CHECK (kind IN
                       ('aposentadoria','imovel','educacao','reserva_oportunidade','viagem','outro')),
  target_amount_brl  core.money_brl NOT NULL,
  target_date        date NOT NULL,
  monthly_contribution_brl core.money_brl,
  priority           smallint NOT NULL DEFAULT 1,
  status             planning.goal_status NOT NULL DEFAULT 'ativa',
  linked_account_ids uuid[] NOT NULL DEFAULT '{}',
  notes              text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  archived_at        timestamptz
);
CREATE INDEX goals_scope_idx ON planning.goals (scope_id) WHERE status = 'ativa';
CREATE TRIGGER goals_touch BEFORE UPDATE ON planning.goals
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TABLE planning.goal_projections (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  goal_id        uuid NOT NULL REFERENCES planning.goals(id) ON DELETE CASCADE,
  scope_id       uuid NOT NULL REFERENCES identity.scopes(id),
  run_id         uuid NOT NULL REFERENCES engine.runs(id),
  as_of_date     date NOT NULL,
  success_prob   numeric(5,4) CHECK (success_prob BETWEEN 0 AND 1),
  p10_brl        core.money_brl,
  p50_brl        core.money_brl,
  p90_brl        core.money_brl,
  required_monthly_brl core.money_brl,      -- aporte necessário p/ prob-alvo
  assumptions    jsonb NOT NULL DEFAULT '{}'::jsonb,
  artifact_id    uuid REFERENCES engine.artifacts(id),   -- fan chart no S3
  computed_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (goal_id, run_id)
);
CREATE INDEX goal_projections_goal_idx ON planning.goal_projections (goal_id, as_of_date DESC);

-- -----------------------------------------------------------------------------
-- Carteira-alvo — a saída do Builder. UMA ativa por escopo (D27).
-- -----------------------------------------------------------------------------
CREATE TABLE planning.target_portfolios (
  id              uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id        uuid NOT NULL REFERENCES identity.scopes(id),
  origin          planning.target_origin NOT NULL,
  status          planning.target_status NOT NULL DEFAULT 'draft',
  suitability_assessment_id uuid REFERENCES identity.suitability_assessments(id),
  model_portfolio_version_id uuid,          -- FK adicionada abaixo (ordem de criação)
  run_id          uuid REFERENCES engine.runs(id),
  rationale       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  activated_at    timestamptz,
  superseded_at   timestamptz,
  superseded_by   uuid REFERENCES planning.target_portfolios(id),
  CONSTRAINT active_has_activation CHECK (status <> 'active' OR activated_at IS NOT NULL)
);
-- D27 como constraint, não convenção (T7)
CREATE UNIQUE INDEX target_one_active_per_scope
  ON planning.target_portfolios (scope_id) WHERE status = 'active';
CREATE INDEX target_portfolios_scope_idx ON planning.target_portfolios (scope_id, created_at DESC);

COMMENT ON INDEX planning.target_one_active_per_scope IS
  'D27 — duas carteiras-alvo ativas tornariam drift, aporte e score ambíguos. '
  'Trocar de alvo = nova linha active + antiga superseded, na mesma transação.';

-- Alocações da carteira-alvo — pesos por classe, soma = 1,000 (§16.2)
CREATE TABLE planning.target_allocations (
  target_portfolio_id uuid NOT NULL REFERENCES planning.target_portfolios(id) ON DELETE CASCADE,
  asset_class_code    core.slug NOT NULL REFERENCES market.asset_classes(code),
  weight              core.weight NOT NULL,
  band_lower          core.weight,           -- banda de rebalanceamento (5/25)
  band_upper          core.weight,
  PRIMARY KEY (target_portfolio_id, asset_class_code)
);

CREATE OR REPLACE FUNCTION planning.assert_weights_sum_one() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_portfolio uuid;
  v_sum       numeric;
BEGIN
  v_portfolio := coalesce(NEW.target_portfolio_id, OLD.target_portfolio_id);
  SELECT sum(weight) INTO v_sum
  FROM planning.target_allocations WHERE target_portfolio_id = v_portfolio;

  IF v_sum IS NOT NULL AND abs(v_sum - 1.0) > 0.0005 THEN
    RAISE EXCEPTION 'Pesos da carteira-alvo % somam % (esperado 1,000 ±0,0005) — §16.2',
      v_portfolio, v_sum USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;
-- DIFERIDA: dentro da transação insere-se linha a linha; a soma vale no COMMIT (T14)
CREATE CONSTRAINT TRIGGER target_allocations_sum_one
  AFTER INSERT OR UPDATE OR DELETE ON planning.target_allocations
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION planning.assert_weights_sum_one();

-- -----------------------------------------------------------------------------
-- Carteiras Modelo — globais, versionadas, com disclaimer versionado
-- -----------------------------------------------------------------------------
CREATE TABLE planning.model_portfolios (
  code               core.slug PRIMARY KEY,
  display_name       text NOT NULL,
  strategy           text NOT NULL,          -- 'Renda', 'Crescimento', 'Preservação'
  description        text,
  risk_profile       identity.risk_profile,
  disclaimer_version text NOT NULL,
  is_active          boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL DEFAULT now(),
  -- §4.6 / T8: o nome proibido. Não é estilo, é fronteira regulatória.
  CONSTRAINT model_name_never_recomendada CHECK (display_name !~* 'recomendad')
);

CREATE TABLE planning.model_portfolio_versions (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  model_code         core.slug NOT NULL REFERENCES planning.model_portfolios(code),
  version            int NOT NULL,
  run_id             uuid REFERENCES engine.runs(id),      -- run global que a gerou
  rationale          text,
  published_at       timestamptz,
  retired_at         timestamptz,
  UNIQUE (model_code, version)
);
CREATE UNIQUE INDEX model_versions_one_current
  ON planning.model_portfolio_versions (model_code)
  WHERE published_at IS NOT NULL AND retired_at IS NULL;

CREATE TABLE planning.model_portfolio_holdings (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  model_version_id  uuid NOT NULL REFERENCES planning.model_portfolio_versions(id) ON DELETE CASCADE,
  asset_class_code  core.slug NOT NULL REFERENCES market.asset_classes(code),
  instrument_id     uuid REFERENCES market.instruments(id),  -- NULL = alocação por classe
  weight            core.weight NOT NULL
);
-- unicidade com NULL tratado (instrumento nulo = linha "da classe")
CREATE UNIQUE INDEX model_holdings_uk ON planning.model_portfolio_holdings
  (model_version_id, asset_class_code,
   coalesce(instrument_id, '00000000-0000-0000-0000-000000000000'::uuid));

-- Adoção de Carteira Modelo por um escopo — vira carteira-alvo com origem rastreada
CREATE TABLE planning.model_adoptions (
  id                  uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id            uuid NOT NULL REFERENCES identity.scopes(id),
  model_version_id    uuid NOT NULL REFERENCES planning.model_portfolio_versions(id),
  target_portfolio_id uuid REFERENCES planning.target_portfolios(id),
  disclaimer_version  text NOT NULL,          -- o disclaimer que o usuário VIU
  disclaimer_accepted_at timestamptz NOT NULL DEFAULT now(),
  adopted_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX model_adoptions_scope_idx ON planning.model_adoptions (scope_id, adopted_at DESC);

ALTER TABLE planning.target_portfolios
  ADD CONSTRAINT target_model_version_fk
  FOREIGN KEY (model_portfolio_version_id) REFERENCES planning.model_portfolio_versions(id);

-- -----------------------------------------------------------------------------
-- Drift 5/25 e roteamento inteligente de aporte
-- -----------------------------------------------------------------------------
CREATE TABLE planning.drift_evaluations (
  id                  uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id            uuid NOT NULL REFERENCES identity.scopes(id),
  target_portfolio_id uuid NOT NULL REFERENCES planning.target_portfolios(id),
  run_id              uuid NOT NULL REFERENCES engine.runs(id),
  as_of_date          date NOT NULL,
  max_abs_drift       numeric(8,6),
  max_rel_drift       numeric(8,6),
  breached            boolean NOT NULL DEFAULT false,
  by_class            jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {"selic": {"atual":0.42,"alvo":0.40,...}}
  computed_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (scope_id, as_of_date, target_portfolio_id)
);

CREATE TABLE planning.contribution_routings (
  id                  uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id            uuid NOT NULL REFERENCES identity.scopes(id),
  target_portfolio_id uuid NOT NULL REFERENCES planning.target_portfolios(id),
  run_id              uuid NOT NULL REFERENCES engine.runs(id),
  amount_brl          core.money_brl NOT NULL,
  suggestion          jsonb NOT NULL,          -- {"selic": 600, "ipca": 400}
  rationale           jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at          timestamptz NOT NULL DEFAULT now(),
  accepted_at         timestamptz,
  dismissed_at        timestamptz
);
CREATE INDEX contribution_routings_scope_idx ON planning.contribution_routings (scope_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- Calendário patrimonial e simulações de cenário
-- -----------------------------------------------------------------------------
CREATE TABLE planning.calendar_events (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id     uuid NOT NULL REFERENCES identity.scopes(id),
  kind         text NOT NULL CHECK (kind IN
                 ('come_cotas','vencimento','exercicio_opcao','ipo_reserva','pagamento_provento',
                  'darf','revisao_semestral','outro')),
  title        text NOT NULL,
  event_date   date NOT NULL,
  instrument_id uuid REFERENCES market.instruments(id),
  amount_brl   core.money_brl,
  source       text NOT NULL DEFAULT 'system' CHECK (source IN ('system','user')),
  finding_id   uuid REFERENCES diagnostics.findings(id),
  dismissed_at timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX calendar_events_scope_idx ON planning.calendar_events (scope_id, event_date);

-- Simulações "e se" (gate de paywall 'simulacao_cenario')
CREATE TABLE planning.scenario_simulations (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id     uuid NOT NULL REFERENCES identity.scopes(id),
  goal_id      uuid REFERENCES planning.goals(id),
  run_id       uuid REFERENCES engine.runs(id),
  inputs       jsonb NOT NULL,                 -- {"aporte_extra": 1000, "aposentar_em": 2042}
  outputs      jsonb,
  created_by   uuid REFERENCES identity.users(id),
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scenario_simulations_scope_idx ON planning.scenario_simulations (scope_id, created_at DESC);

COMMIT;
