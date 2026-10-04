-- =============================================================================
-- SYNAPTA · 20_analysis.sql
-- A profundidade exclusiva do Analista IA (Blueprint v2.1 §4, §8, §13.4, §23).
--
-- No MVP, um "plano" pode conter UMA tool — e o Analista fica idêntico aos
-- outros agentes. Quando a pergunta exigir DAG multi-tool (event study +
-- benchmark + macro em paralelo), o schema já comporta sem migração.
--
-- analysis.tasks É a tabela de checkpoint do executor (§8): retomar uma
-- análise após restart = SELECT tasks WHERE status = 'succeeded'.
--
-- Depende de: 00_core, 01_identity, 17_agents, 18_tools, 19_llm.
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TYPE analysis.analysis_status AS ENUM (
  'received', 'normalized', 'planned', 'plan_validated', 'compiled',
  'executing', 'partial_failure', 'needs_replan',
  'validating', 'evidence_ready', 'synthesizing',
  'final', 'final_with_warnings', 'blocked', 'failed', 'cancelled'
);

CREATE TYPE analysis.task_status AS ENUM (
  'pending', 'ready', 'running', 'succeeded', 'failed', 'skipped', 'cancelled'
);

CREATE TYPE analysis.task_criticality AS ENUM ('required', 'important', 'optional');

-- -----------------------------------------------------------------------------
-- Análises — uma pergunta profunda do usuário
-- -----------------------------------------------------------------------------
CREATE TABLE analysis.analyses (
  id               uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id         uuid NOT NULL REFERENCES identity.scopes(id),
  user_id          uuid NOT NULL REFERENCES identity.users(id),
  conversation_id  uuid REFERENCES agents.conversations(id),
  question         text NOT NULL,
  intent           jsonb,                 -- IntentSpec normalizado
  mode             text NOT NULL DEFAULT 'standard' CHECK (mode IN ('standard','research')),
  cutoff_date      date,                  -- point-in-time: published_at <= cutoff
  status           analysis.analysis_status NOT NULL DEFAULT 'received',
  replan_count     smallint NOT NULL DEFAULT 0,
  max_replans      smallint NOT NULL DEFAULT 2,
  budget           jsonb NOT NULL DEFAULT '{}'::jsonb,  -- envelope: max_usd, max_tokens, max_tasks
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  CONSTRAINT replans_bounded CHECK (replan_count <= max_replans)
);
CREATE INDEX analyses_scope_idx  ON analysis.analyses (scope_id, created_at DESC);
CREATE INDEX analyses_status_idx ON analysis.analyses (status)
  WHERE status NOT IN ('final','final_with_warnings','blocked','failed','cancelled');
CREATE TRIGGER analyses_touch BEFORE UPDATE ON analysis.analyses
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON CONSTRAINT replans_bounded ON analysis.analyses IS
  '§4.3 — replanning é permitido, mas LIMITADO. Loop ilimitado de LLM é proibido '
  'por desenho; o banco recusa o excedente antes que a fatura descubra.';

-- -----------------------------------------------------------------------------
-- Planos — o AnalysisPlan validado. Plano executado é imutável;
-- replan = versão nova apontando supersede.
-- -----------------------------------------------------------------------------
CREATE TABLE analysis.plans (
  id                     uuid PRIMARY KEY DEFAULT core.new_id(),
  analysis_id            uuid NOT NULL REFERENCES analysis.analyses(id) ON DELETE CASCADE,
  version                int NOT NULL DEFAULT 1,
  dsl_version            text NOT NULL,
  plan                   jsonb NOT NULL,        -- AnalysisPlan (pós-validação Pydantic)
  planner_model_call_id  uuid REFERENCES llm.model_calls(id),
  validation_report      jsonb NOT NULL DEFAULT '{}'::jsonb,
  estimated_cost_usd     numeric(12,6),
  is_active              boolean NOT NULL DEFAULT true,
  superseded_by          uuid REFERENCES analysis.plans(id),
  created_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (analysis_id, version)
);
CREATE UNIQUE INDEX plans_one_active ON analysis.plans (analysis_id) WHERE is_active;

-- Imutável exceto os campos de supersessão
CREATE OR REPLACE FUNCTION analysis.freeze_plan() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'analysis.plans é append-only (replan = nova versão)' USING ERRCODE = '42501';
  END IF;
  IF (to_jsonb(NEW) - 'is_active' - 'superseded_by')
     IS DISTINCT FROM (to_jsonb(OLD) - 'is_active' - 'superseded_by') THEN
    RAISE EXCEPTION 'analysis.plans %: só is_active/superseded_by podem mudar', OLD.id
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER plans_freeze BEFORE UPDATE OR DELETE ON analysis.plans
  FOR EACH ROW EXECUTE FUNCTION analysis.freeze_plan();

-- -----------------------------------------------------------------------------
-- Tasks — o DAG compilado + checkpoints do executor
-- -----------------------------------------------------------------------------
CREATE TABLE analysis.tasks (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  analysis_id        uuid NOT NULL REFERENCES analysis.analyses(id) ON DELETE CASCADE,
  plan_id            uuid NOT NULL REFERENCES analysis.plans(id),
  node_id            text NOT NULL,             -- id do nó na DSL
  tool_code          core.slug REFERENCES tools.tools(code),
  depends_on         text[] NOT NULL DEFAULT '{}',   -- node_ids; ciclo é barrado no compiler
  criticality        analysis.task_criticality NOT NULL DEFAULT 'required',
  status             analysis.task_status NOT NULL DEFAULT 'pending',
  attempt            smallint NOT NULL DEFAULT 0,
  tool_execution_id  uuid REFERENCES tools.tool_executions(id),  -- proveniência do resultado
  error_code         text,
  started_at         timestamptz,
  finished_at        timestamptz,
  UNIQUE (plan_id, node_id),
  CONSTRAINT succeeded_has_execution CHECK (status <> 'succeeded' OR tool_execution_id IS NOT NULL)
);
CREATE INDEX tasks_analysis_status_idx ON analysis.tasks (analysis_id, status);

COMMENT ON CONSTRAINT succeeded_has_execution ON analysis.tasks IS
  'Task concluída sem apontar a execução que a produziu não é resultado, é boato. '
  'É esta FK que costura o DAG à trilha auditável de tools.tool_executions.';

-- -----------------------------------------------------------------------------
-- Evidence findings — o EvidenceBundle desmontado em linhas (§13.4)
-- REGRA INVIOLÁVEL: afirmação material sem proveniência NÃO ENTRA (§2.2).
-- -----------------------------------------------------------------------------
CREATE TABLE analysis.evidence_findings (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  analysis_id  uuid NOT NULL REFERENCES analysis.analyses(id) ON DELETE CASCADE,
  kind         text NOT NULL CHECK (kind IN
                 ('quantitative','documentary','contradiction','warning','missing','methodology')),
  finding      jsonb NOT NULL,   -- {metric, value, uncertainty} ou {claim, excerpt_summary, ...}
  provenance   jsonb NOT NULL DEFAULT '[]'::jsonb,  -- tool_execution_ids, document refs
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT provenance_is_array CHECK (jsonb_typeof(provenance) = 'array'),
  CONSTRAINT material_needs_provenance CHECK (
    kind IN ('warning','missing','methodology') OR jsonb_array_length(provenance) > 0
  )
);
CREATE INDEX evidence_analysis_idx ON analysis.evidence_findings (analysis_id, kind);
CREATE TRIGGER evidence_append_only BEFORE UPDATE OR DELETE ON analysis.evidence_findings
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- -----------------------------------------------------------------------------
-- Relatórios — publicado é imutável; correção = nova versão + superseded_by
-- -----------------------------------------------------------------------------
CREATE TABLE analysis.reports (
  id                       uuid PRIMARY KEY DEFAULT core.new_id(),
  analysis_id              uuid NOT NULL REFERENCES analysis.analyses(id) ON DELETE CASCADE,
  version                  int NOT NULL DEFAULT 1,
  content_md               text NOT NULL,
  report_schema_version    text NOT NULL DEFAULT 'v1',
  synthesis_model_call_id  uuid REFERENCES llm.model_calls(id),
  evidence_hash            core.hash_hex,   -- hash do bundle que fundamentou o texto
  status                   text NOT NULL DEFAULT 'final'
                           CHECK (status IN ('final','final_with_warnings','blocked')),
  superseded_by            uuid REFERENCES analysis.reports(id),
  published_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (analysis_id, version)
);

CREATE OR REPLACE FUNCTION analysis.freeze_report() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'analysis.reports é append-only' USING ERRCODE = '42501';
  END IF;
  IF (to_jsonb(NEW) - 'superseded_by') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_by') THEN
    RAISE EXCEPTION 'analysis.reports %: relatório publicado é imutável (nova versão + superseded_by)',
      OLD.id USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER reports_freeze BEFORE UPDATE OR DELETE ON analysis.reports
  FOR EACH ROW EXECUTE FUNCTION analysis.freeze_report();

-- Fecha a referência pendente de 19_llm
ALTER TABLE llm.model_calls
  ADD CONSTRAINT model_calls_analysis_fk
  FOREIGN KEY (analysis_id) REFERENCES analysis.analyses(id);

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE analysis.analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis.analyses FORCE  ROW LEVEL SECURITY;
CREATE POLICY analyses_isolation ON analysis.analyses FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

-- Tabelas-filhas (plans/tasks/evidence/reports) seguem o padrão do banco:
-- sem scope_id próprio, acessadas via JOIN pela camada de serviço
-- (mesmo desenho de diagnostics.finding_observations).

COMMIT;
