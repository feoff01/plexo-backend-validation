-- =============================================================================
-- SYNAPTA · 02_engine.sql
-- A espinha dorsal de auditabilidade. Nada derivado existe sem um run.
--
-- §16.1.10  "Todo output de motor grava {input_hash, engine_version, params, output_hash}"
-- §16.8.2   "Config-first, zero valores hardcoded"
-- RCVM 19 art. 17 — código-fonte inspecionável, em forma não compilada
--
-- Regra: engine.runs NÃO é audit log. Audit log responde "quem fez o quê".
-- engine.runs responde "como reproduzo, byte a byte, o número que o cliente viu".
-- =============================================================================

BEGIN;

CREATE TYPE engine.compliance_status AS ENUM (
  'draft', 'pending_review', 'approved', 'rejected', 'revoked'
);

CREATE TYPE engine.run_kind AS ENUM (
  'raiox',            -- diagnostics-svc: findings
  'score',            -- score de carteira
  'foundation',       -- semáforo de Fundação
  'builder',          -- build_portfolio / build_consolidated_portfolio
  'projection',       -- Monte Carlo por objetivo
  'drift',            -- compute_drift (5/25)
  'contribution',     -- smart_aporte_routing
  'signals',          -- motor de Sinais
  'ledger',           -- Valor Realizado
  'model_portfolio',  -- Carteiras Modelo
  'coverage'          -- cobertura de análise da carteira
);

CREATE TYPE engine.run_status AS ENUM ('queued','running','succeeded','failed','superseded');

-- -----------------------------------------------------------------------------
-- Versões do pacote synapta-engine (um artefato, dois consumidores — §11.3)
-- -----------------------------------------------------------------------------
CREATE TABLE engine.engine_versions (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  package       text NOT NULL DEFAULT 'synapta-engine',
  semver        text NOT NULL CHECK (semver ~ '^\d+\.\d+\.\d+(-[\w.]+)?$'),
  git_sha       char(40) NOT NULL,
  source_sha256 core.hash_hex NOT NULL,     -- hash do arquivo único, para inspeção CVM
  source_uri    text,                        -- S3 do .py exato publicado
  published_at  timestamptz NOT NULL DEFAULT now(),
  deprecated_at timestamptz,
  notes         text,
  UNIQUE (package, semver)
);

COMMENT ON COLUMN engine.engine_versions.source_sha256 IS
  'Permite provar à CVM que o .py entregue para inspeção é exatamente o que rodou.';

-- -----------------------------------------------------------------------------
-- Política versionada — substitui a flag `validado_por_lucas`
-- -----------------------------------------------------------------------------
CREATE TABLE engine.policy_versions (
  id                uuid PRIMARY KEY DEFAULT core.new_id(),
  code              core.config_code NOT NULL,  -- RISK_BANDS_SYNAPTA, TIER_CONFIG, CONVICTION,
                                          -- GESTOR_VIEW, ASSET_CLASSES, CORR_DEFAULT,
                                          -- PREMISSAS_FALLBACK, FOUNDATION_THRESHOLDS,
                                          -- FAMILY_LIMITS, DRIFT_BANDS, FINDING_SCORING,
                                          -- ACTION_GOVERNANCE, NOTIFICATION_LIMITS
                                          -- (seed em 15; agentes: AGENT_QUOTAS,
                                          --  LLM_BUDGETS, CONTEXT_EXTRACTION em 17/19/21)
  version           int  NOT NULL,
  payload           jsonb NOT NULL,
  content_hash      core.hash_hex GENERATED ALWAYS AS (core.canonical_hash(payload)) STORED,
  effective_from    timestamptz NOT NULL DEFAULT now(),
  effective_to      timestamptz,
  compliance_status engine.compliance_status NOT NULL DEFAULT 'draft',
  approved_by       uuid REFERENCES identity.users(id),
  approved_at       timestamptz,
  rejection_reason  text,
  created_by        uuid REFERENCES identity.users(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (code, version),
  CHECK (effective_to IS NULL OR effective_to > effective_from),
  CHECK ((compliance_status = 'approved') = (approved_at IS NOT NULL))
);
CREATE UNIQUE INDEX policy_one_current ON engine.policy_versions (code)
  WHERE effective_to IS NULL;
CREATE INDEX policy_status_idx ON engine.policy_versions (compliance_status);

COMMENT ON TABLE engine.policy_versions IS
  '§16.8.2 e §13.6. Nenhuma premissa numérica vive em código. A flag histórica '
  '`validado_por_lucas` vira estado versionado com aprovador e data — o que a CVM pede '
  'não é a flag, é a trilha. Run client-facing só pode referenciar política approved.';

-- Trigger de limite de membros (definido em 01, ativado aqui — depende desta tabela)
CREATE CONSTRAINT TRIGGER scope_members_limit
  AFTER INSERT OR UPDATE ON identity.scope_members
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION identity.enforce_member_limit();

-- -----------------------------------------------------------------------------
-- Runs — toda linha derivada do produto aponta para cá
-- -----------------------------------------------------------------------------
CREATE TABLE engine.runs (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id           uuid REFERENCES identity.scopes(id),  -- NULL = run global (ex.: Carteiras Modelo)
  kind               engine.run_kind NOT NULL,
  engine_version_id  uuid NOT NULL REFERENCES engine.engine_versions(id),
  policy_version_ids uuid[] NOT NULL DEFAULT '{}',
  params             jsonb NOT NULL DEFAULT '{}'::jsonb,
  input_hash         core.hash_hex NOT NULL,
  output_hash        core.hash_hex,
  status             engine.run_status NOT NULL DEFAULT 'queued',
  is_client_facing   boolean NOT NULL DEFAULT true,
  as_of_date         date NOT NULL,          -- data de referência dos dados (D-1)
  started_at         timestamptz NOT NULL DEFAULT now(),
  finished_at        timestamptz,
  duration_ms        int,
  error_code         text,
  error_detail       text,
  triggered_by       text NOT NULL DEFAULT 'job'
                     CHECK (triggered_by IN ('user','job','backfill','admin','test')),
  request_id         text
);
CREATE INDEX runs_scope_kind_idx ON engine.runs (scope_id, kind, started_at DESC);
CREATE INDEX runs_input_hash_idx ON engine.runs (kind, input_hash);
CREATE INDEX runs_asof_idx       ON engine.runs (as_of_date DESC);

-- Runs são imutáveis depois de concluídos.
-- [Endurecido na 3ª onda] A versão anterior só bloqueava UPDATE quando o status
-- NÃO mudava — dava para "reabrir" um run finalizado com SET status='queued'.
-- Agora: run finalizado é imutável; a ÚNICA transição permitida é
-- succeeded → superseded (o recálculo diário aposenta o run anterior), e mesmo
-- ela não pode alterar nenhum outro campo (diff via to_jsonb, padrão de 20_analysis).
CREATE OR REPLACE FUNCTION engine.freeze_finished_run() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('succeeded','failed') THEN
    IF NOT (OLD.status = 'succeeded' AND NEW.status = 'superseded') THEN
      RAISE EXCEPTION 'engine.runs % já finalizado é imutável (única transição: succeeded→superseded)',
        OLD.id USING ERRCODE = '42501';
    END IF;
    IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status') THEN
      RAISE EXCEPTION 'engine.runs %: supersedência só pode mudar o status, nada mais',
        OLD.id USING ERRCODE = '42501';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER runs_freeze BEFORE UPDATE ON engine.runs
  FOR EACH ROW EXECUTE FUNCTION engine.freeze_finished_run();

-- Gate regulatório: output ao cliente exige política aprovada por compliance.
CREATE OR REPLACE FUNCTION engine.assert_client_facing_policy() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_bad int;
BEGIN
  IF NOT NEW.is_client_facing THEN RETURN NEW; END IF;
  SELECT count(*) INTO v_bad
  FROM engine.policy_versions p
  WHERE p.id = ANY(NEW.policy_version_ids) AND p.compliance_status <> 'approved';
  IF v_bad > 0 THEN
    RAISE EXCEPTION
      'Run client-facing referencia % política(s) não aprovada(s) por compliance (§16.6)', v_bad
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER runs_policy_gate BEFORE INSERT OR UPDATE ON engine.runs
  FOR EACH ROW EXECUTE FUNCTION engine.assert_client_facing_policy();

-- Grafo de proveniência: de quais dados exatos este run se alimentou.
CREATE TABLE engine.run_inputs (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id     uuid NOT NULL REFERENCES engine.runs(id) ON DELETE CASCADE,
  ref_kind   text NOT NULL,      -- 'holdings_snapshot','price_asof','goal','suitability','budget_month'
  ref_id     uuid,
  ref_date   date,
  ref_hash   core.hash_hex
);
CREATE UNIQUE INDEX run_inputs_uk ON engine.run_inputs (
  run_id, ref_kind,
  coalesce(ref_id, '00000000-0000-0000-0000-000000000000'::uuid),
  coalesce(ref_date, '0001-01-01'::date)
);

-- Artefatos pesados (fan chart, séries de Monte Carlo) — payload inline ou S3.
CREATE TABLE engine.artifacts (
  id          uuid PRIMARY KEY DEFAULT core.new_id(),
  run_id      uuid NOT NULL REFERENCES engine.runs(id) ON DELETE CASCADE,
  kind        text NOT NULL,          -- 'fan_chart','mc_paths','bl_posterior','stress','alloc'
  payload     jsonb,
  storage_key text,                   -- s3://... quando payload é grande demais
  bytes       bigint,
  output_hash core.hash_hex NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (payload IS NOT NULL OR storage_key IS NOT NULL)
);
CREATE INDEX artifacts_run_idx ON engine.artifacts (run_id, kind);
CREATE TRIGGER artifacts_append_only BEFORE UPDATE OR DELETE ON engine.artifacts
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
REVOKE UPDATE, DELETE ON engine.artifacts FROM PUBLIC;   -- [3ª onda] padrão T10: trigger + privilégio

-- Golden-master testing (§11.8) como dado, não como fixture perdida no repo.
CREATE TABLE engine.golden_masters (
  id                uuid PRIMARY KEY DEFAULT core.new_id(),
  case_code         core.slug NOT NULL UNIQUE,
  description       text,
  input_payload     jsonb NOT NULL,
  expected_output_hash core.hash_hex NOT NULL,
  engine_version_id uuid NOT NULL REFERENCES engine.engine_versions(id),
  last_verified_at  timestamptz,
  last_result       text CHECK (last_result IN ('pass','fail'))
);

COMMIT;
