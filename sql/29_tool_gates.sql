-- =============================================================================
-- SYNAPTA · 29_tool_gates.sql
-- [5ª onda — backend de agentes] Dois gates que faltavam em tools.tool_executions,
-- fechando no BANCO o que até aqui só o serviço prometia (mesmo argumento do C4:
-- regra que vive só no serviço vaza no primeiro endpoint novo):
--
--   (a) PROVENIÊNCIA DE POLÍTICA + GATE DE COMPLIANCE — espelho de
--       engine.runs_policy_gate (§16.6/C6): execução ligada a uma conversa é
--       client-facing; as políticas que alimentaram o cálculo ficam registradas
--       em policy_version_ids e TODAS precisam estar aprovadas. Execução global
--       (conversation_id NULL: warmup/backfill) fica de fora, como no engine.
--       Lista vazia é permitida (tool sem premissa de política) — a honestidade
--       da lista é auditável por resolved_params._policies.
--
--   (b) PLANO MÍNIMO DA TOOL — tools.tools.min_plan existia desde 18_tools mas
--       nenhum trigger o aplicava. Agora vale contra o plano CONGELADO da
--       conversa (plan_code_at_start, point-in-time — mesma régua da cota).
--       A ordem do enum billing.plan_code (free < essential < advanced < wealth)
--       é a ordem de comparação.
--
-- Depende de: 02_engine (policy_versions), 03_billing (plan_code), 17_agents
-- (conversations), 18_tools (tool_executions). Aplicada via Alembic (0029).
-- =============================================================================

BEGIN;

ALTER TABLE tools.tool_executions
  ADD COLUMN policy_version_ids uuid[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN tools.tool_executions.policy_version_ids IS
  'Políticas (engine.policy_versions.id) cujas premissas alimentaram esta execução. '
  'Com conversation_id, o gate exige todas aprovadas — o cliente nunca lê número '
  'calculado sobre premissa que compliance não viu. Espelho de engine.runs.policy_version_ids.';

-- ---------------------------------------------------------------- (a) compliance
CREATE OR REPLACE FUNCTION tools.assert_execution_policies_approved() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_bad int;
BEGIN
  IF NEW.conversation_id IS NULL OR cardinality(NEW.policy_version_ids) = 0 THEN
    RETURN NEW;
  END IF;
  SELECT count(*) INTO v_bad
  FROM engine.policy_versions p
  WHERE p.id = ANY(NEW.policy_version_ids) AND p.compliance_status <> 'approved';
  IF v_bad > 0 THEN
    RAISE EXCEPTION
      'Execução client-facing referencia % política(s) não aprovada(s) por compliance (espelho de engine.runs_policy_gate)',
      v_bad USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER tool_executions_policy_gate BEFORE INSERT ON tools.tool_executions
  FOR EACH ROW EXECUTE FUNCTION tools.assert_execution_policies_approved();

-- ---------------------------------------------------------------- (b) plano mínimo
CREATE OR REPLACE FUNCTION tools.assert_min_plan() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_min  billing.plan_code;
  v_code core.slug;
  v_plan billing.plan_code;
BEGIN
  IF NEW.conversation_id IS NULL THEN
    RETURN NEW;   -- execução global (warmup/backfill) não tem plano
  END IF;
  SELECT t.min_plan, t.code INTO v_min, v_code
  FROM tools.tool_versions v
  JOIN tools.tools t ON t.code = v.tool_code
  WHERE v.id = NEW.tool_version_id;
  SELECT c.plan_code_at_start INTO v_plan
  FROM agents.conversations c WHERE c.id = NEW.conversation_id;
  IF v_plan < v_min THEN
    RAISE EXCEPTION
      'Tool % exige plano mínimo %; a conversa foi aberta no plano % (paywall, mesma família da cota)',
      v_code, v_min, v_plan USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER tool_executions_min_plan_gate BEFORE INSERT ON tools.tool_executions
  FOR EACH ROW EXECUTE FUNCTION tools.assert_min_plan();

COMMIT;
