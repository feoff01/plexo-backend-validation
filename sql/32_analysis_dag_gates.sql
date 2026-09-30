-- =============================================================================
-- SYNAPTA · 32_analysis_dag_gates.sql — [6ª onda] O pipeline do Analista research é executado pelo banco
-- -----------------------------------------------------------------------------
-- A 20 modelou plans/tasks/reports e a F5 passou a registrar toda pergunta em analysis.analyses.
-- Na F6 o DAG roda num JOB (fora da requisição, retomável) — e o que antes a conversa impunha
-- precisa valer pela análise:
--   (a) tools.tool_executions.analysis_id: os gates de família (18), política aprovada e plano
--       mínimo (29) passam a resolver agente/plano pela CONVERSA DA ANÁLISE quando a execução não
--       traz conversation_id; análise sem conversa não sustenta gate ⇒ recusada; escopo da
--       execução = escopo da análise;
--   (b) analysis.tasks: params e error_detail (checkpoint completo sem reler o plano); dependência
--       só de nó JÁ EXISTENTE no mesmo plano (o compiler insere em ordem topológica — ciclo é
--       impossível por construção, sem recursão diferida); tarefa do plano da própria análise;
--       definição (tool/depends_on/params/criticality) congelada; task fecha apontando execução
--       da própria análise; finalizada tem finished_at;
--   (c) plans/reports: versão DERIVADA pelo banco (max+1), anterior superseded/inativo na mesma
--       transação, ninguém supersede a si mesmo; plano v>1 incrementa analyses.replan_count — e o
--       CHECK replans_bounded (20) recusa o excedente: o teto de replan é do banco;
--   (d) relatório final/final_with_warnings exige evidence_hash e ≥1 evidência MATERIAL da análise
--       (quantitative/documentary); blocked não;
--   (e) análise research exige conversa; estado terminal carimba finished_at e não reabre;
--   (f) índice llm.model_calls(analysis_id);
--   (g) RLS nas tabelas-filhas (plans/tasks/evidence_findings/reports) por EXISTS na análise — a API
--       /analyses lê sob plexo_app e o isolamento deixa de depender do JOIN escrito à mão.
-- Sem tabela nova. Depende de 18, 19, 20, 29.
-- =============================================================================
BEGIN;

-- -----------------------------------------------------------------------------
-- (a) Execução ligada à análise
-- -----------------------------------------------------------------------------
ALTER TABLE tools.tool_executions
  ADD COLUMN analysis_id uuid REFERENCES analysis.analyses(id);
CREATE INDEX tool_executions_analysis_idx ON tools.tool_executions (analysis_id)
  WHERE analysis_id IS NOT NULL;

COMMENT ON COLUMN tools.tool_executions.analysis_id IS
  '[6ª onda] Análise (analysis.analyses) que pediu a execução. Sem conversation_id, os gates de família/política/plano '
  'resolvem agente e plano pela conversa da análise; análise sem conversa não sustenta gate.';

-- Contexto de julgamento de uma execução: pela conversa, senão pela conversa da análise; NULL = global.
CREATE OR REPLACE FUNCTION tools.execution_context(p_conversation uuid, p_analysis uuid,
  OUT agent_code agents.agent_code, OUT plan_code billing.plan_code, OUT scope_id uuid, OUT conversation_id uuid)
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF p_conversation IS NOT NULL THEN
    SELECT c.agent_code, c.plan_code_at_start, c.scope_id, c.id
      INTO agent_code, plan_code, scope_id, conversation_id
    FROM agents.conversations c WHERE c.id = p_conversation;
    RETURN;
  END IF;
  IF p_analysis IS NULL THEN
    RETURN;   -- execução global (warmup/backfill): sem agente, sem plano
  END IF;
  SELECT c.agent_code, c.plan_code_at_start, a.scope_id, c.id
    INTO agent_code, plan_code, scope_id, conversation_id
  FROM analysis.analyses a
  LEFT JOIN agents.conversations c ON c.id = a.conversation_id
  WHERE a.id = p_analysis;
  IF conversation_id IS NULL THEN
    RAISE EXCEPTION 'Execução ligada à análise % sem conversa: não há agente nem plano para os gates', p_analysis
      USING ERRCODE = '23514';
  END IF;
END;
$$;

-- Gates pela ANÁLISE: os gates da 18/29 seguem intactos (julgam pela conversa e retornam cedo sem ela);
-- este trigger cobre a execução que chega só com analysis_id — família, política aprovada, plano mínimo —
-- e, em qualquer caso, escopo/conversa coerentes com a análise.
CREATE OR REPLACE FUNCTION tools.assert_execution_analysis() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_scope   uuid;
  v_conv    uuid;
  v_ctx     record;
  v_allowed text[];
  v_family  text;
  v_min     billing.plan_code;
  v_code    core.slug;
  v_bad     int;
BEGIN
  IF NEW.analysis_id IS NULL THEN RETURN NEW; END IF;
  SELECT a.scope_id, a.conversation_id INTO v_scope, v_conv FROM analysis.analyses a WHERE a.id = NEW.analysis_id;
  IF NEW.scope_id IS DISTINCT FROM v_scope THEN
    RAISE EXCEPTION 'Execução no escopo % ligada à análise % de outro escopo', NEW.scope_id, NEW.analysis_id
      USING ERRCODE = '23514';
  END IF;
  IF NEW.conversation_id IS NOT NULL THEN
    IF v_conv IS NOT NULL AND NEW.conversation_id <> v_conv THEN
      RAISE EXCEPTION 'Execução na conversa % ligada à análise % de outra conversa', NEW.conversation_id, NEW.analysis_id
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;   -- com conversa, os gates da 18/29 já julgam
  END IF;

  SELECT (tools.execution_context(NULL, NEW.analysis_id)).* INTO v_ctx;   -- análise sem conversa ⇒ 23514

  SELECT d.allowed_tool_families INTO v_allowed FROM agents.agent_definitions d WHERE d.code = v_ctx.agent_code;
  SELECT t.family::text, t.min_plan, t.code INTO v_family, v_min, v_code
  FROM tools.tool_versions v JOIN tools.tools t ON t.code = v.tool_code WHERE v.id = NEW.tool_version_id;
  IF NOT (v_family = ANY (v_allowed)) THEN
    RAISE EXCEPTION 'Agente % não pode invocar tool da família % (permitidas: %) — pela análise %',
      v_ctx.agent_code, v_family, v_allowed, NEW.analysis_id USING ERRCODE = '23514';
  END IF;
  IF v_ctx.plan_code < v_min THEN
    RAISE EXCEPTION 'Tool % exige plano mínimo %; a conversa da análise foi aberta no plano %',
      v_code, v_min, v_ctx.plan_code USING ERRCODE = '23514';
  END IF;
  IF cardinality(NEW.policy_version_ids) > 0 THEN
    SELECT count(*) INTO v_bad FROM engine.policy_versions p
    WHERE p.id = ANY(NEW.policy_version_ids) AND p.compliance_status <> 'approved';
    IF v_bad > 0 THEN
      RAISE EXCEPTION 'Execução da análise % referencia % política(s) não aprovada(s) por compliance',
        NEW.analysis_id, v_bad USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER tool_executions_analysis_gate BEFORE INSERT ON tools.tool_executions
  FOR EACH ROW EXECUTE FUNCTION tools.assert_execution_analysis();

-- -----------------------------------------------------------------------------
-- (b) Tasks — o checkpoint do executor
-- -----------------------------------------------------------------------------
ALTER TABLE analysis.tasks
  ADD COLUMN params jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN error_detail text,
  ADD CONSTRAINT task_params_object CHECK (jsonb_typeof(params) = 'object'),
  ADD CONSTRAINT task_finished_has_ts CHECK (status IN ('pending','ready','running') OR finished_at IS NOT NULL);

CREATE OR REPLACE FUNCTION analysis.assert_task_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_plan_analysis uuid; v_dep text;
BEGIN
  SELECT p.analysis_id INTO v_plan_analysis FROM analysis.plans p WHERE p.id = NEW.plan_id;
  IF v_plan_analysis IS DISTINCT FROM NEW.analysis_id THEN
    RAISE EXCEPTION 'Tarefa % aponta plano de outra análise', NEW.node_id USING ERRCODE = '23514';
  END IF;
  FOREACH v_dep IN ARRAY NEW.depends_on LOOP
    IF v_dep = NEW.node_id THEN
      RAISE EXCEPTION 'Tarefa % depende de si mesma', NEW.node_id USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM analysis.tasks t WHERE t.plan_id = NEW.plan_id AND t.node_id = v_dep) THEN
      RAISE EXCEPTION 'Tarefa % depende de % que não existe (ainda) no plano — insira em ordem topológica',
        NEW.node_id, v_dep USING ERRCODE = '23514';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$;
CREATE TRIGGER tasks_insert_gate BEFORE INSERT ON analysis.tasks
  FOR EACH ROW EXECUTE FUNCTION analysis.assert_task_insert();

CREATE OR REPLACE FUNCTION analysis.assert_task_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_exec_analysis uuid;
BEGIN
  IF (to_jsonb(NEW) - 'status' - 'attempt' - 'tool_execution_id' - 'error_code' - 'error_detail' - 'started_at' - 'finished_at')
     IS DISTINCT FROM
     (to_jsonb(OLD) - 'status' - 'attempt' - 'tool_execution_id' - 'error_code' - 'error_detail' - 'started_at' - 'finished_at') THEN
    RAISE EXCEPTION 'analysis.tasks %: definição da tarefa (tool, dependências, params) é congelada', OLD.id
      USING ERRCODE = '42501';
  END IF;
  IF NEW.tool_execution_id IS NOT NULL AND NEW.tool_execution_id IS DISTINCT FROM OLD.tool_execution_id THEN
    SELECT e.analysis_id INTO v_exec_analysis FROM tools.tool_executions e WHERE e.id = NEW.tool_execution_id;
    IF v_exec_analysis IS DISTINCT FROM NEW.analysis_id THEN
      RAISE EXCEPTION 'Tarefa % aponta execução de outra análise (ou sem análise)', NEW.node_id USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER tasks_update_gate BEFORE UPDATE ON analysis.tasks
  FOR EACH ROW EXECUTE FUNCTION analysis.assert_task_update();

-- -----------------------------------------------------------------------------
-- (c) Versões de plano e relatório: derivadas, supersessão atômica, replan contado
-- -----------------------------------------------------------------------------
ALTER TABLE analysis.plans
  ADD CONSTRAINT plans_no_self_supersede CHECK (superseded_by IS NULL OR superseded_by <> id),
  ADD CONSTRAINT plans_superseded_inactive CHECK (superseded_by IS NULL OR NOT is_active);
ALTER TABLE analysis.reports
  ADD CONSTRAINT reports_no_self_supersede CHECK (superseded_by IS NULL OR superseded_by <> id);

CREATE OR REPLACE FUNCTION analysis.plans_new_version() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_max int;
BEGIN
  SELECT coalesce(max(version), 0) INTO v_max FROM analysis.plans WHERE analysis_id = NEW.analysis_id;
  NEW.version := v_max + 1;          -- versão é derivada; valor informado é ignorado
  NEW.is_active := true;
  NEW.superseded_by := NULL;
  -- desativa o anterior aqui (plans_one_active é conferido no INSERT); superseded_by entra no AFTER
  UPDATE analysis.plans SET is_active = false WHERE analysis_id = NEW.analysis_id AND is_active;
  IF NEW.version > 1 THEN
    -- replans_bounded (20) recusa o excedente: o teto é do banco
    UPDATE analysis.analyses SET replan_count = replan_count + 1 WHERE id = NEW.analysis_id;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER plans_new_version BEFORE INSERT ON analysis.plans
  FOR EACH ROW EXECUTE FUNCTION analysis.plans_new_version();

CREATE OR REPLACE FUNCTION analysis.plans_supersede() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE analysis.plans SET superseded_by = NEW.id
   WHERE analysis_id = NEW.analysis_id AND id <> NEW.id AND superseded_by IS NULL;
  RETURN NULL;
END;
$$;
CREATE TRIGGER plans_supersede AFTER INSERT ON analysis.plans
  FOR EACH ROW EXECUTE FUNCTION analysis.plans_supersede();

CREATE OR REPLACE FUNCTION analysis.reports_new_version() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_max int;
BEGIN
  SELECT coalesce(max(version), 0) INTO v_max FROM analysis.reports WHERE analysis_id = NEW.analysis_id;
  NEW.version := v_max + 1;
  NEW.superseded_by := NULL;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION analysis.reports_supersede() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE analysis.reports SET superseded_by = NEW.id
   WHERE analysis_id = NEW.analysis_id AND superseded_by IS NULL AND id <> NEW.id;
  RETURN NULL;
END;
$$;

-- -----------------------------------------------------------------------------
-- (d) Relatório final é fundamentado
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analysis.assert_report_grounded() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IN ('final', 'final_with_warnings') THEN
    IF NEW.evidence_hash IS NULL THEN
      RAISE EXCEPTION 'Relatório % da análise % sem evidence_hash', NEW.status, NEW.analysis_id USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM analysis.evidence_findings f
                   WHERE f.analysis_id = NEW.analysis_id AND f.kind IN ('quantitative', 'documentary')) THEN
      RAISE EXCEPTION 'Relatório % da análise % sem nenhuma evidência material (quantitative/documentary)',
        NEW.status, NEW.analysis_id USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
-- ordem alfabética dos triggers BEFORE INSERT: "reports_a_grounded" antes de "reports_b_version"
CREATE TRIGGER reports_a_grounded BEFORE INSERT ON analysis.reports
  FOR EACH ROW EXECUTE FUNCTION analysis.assert_report_grounded();
CREATE TRIGGER reports_b_version BEFORE INSERT ON analysis.reports
  FOR EACH ROW EXECUTE FUNCTION analysis.reports_new_version();
CREATE TRIGGER reports_supersede AFTER INSERT ON analysis.reports
  FOR EACH ROW EXECUTE FUNCTION analysis.reports_supersede();

-- -----------------------------------------------------------------------------
-- (e) Análise: research exige conversa; terminal carimba finished_at e não reabre
-- -----------------------------------------------------------------------------
ALTER TABLE analysis.analyses
  ADD CONSTRAINT research_has_conversation CHECK (mode <> 'research' OR conversation_id IS NOT NULL);

CREATE OR REPLACE FUNCTION analysis.analyses_status_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_terminais analysis.analysis_status[] := ARRAY['final','final_with_warnings','blocked','failed','cancelled']::analysis.analysis_status[];
BEGIN
  IF OLD.status = ANY (v_terminais) AND NEW.status <> OLD.status THEN
    RAISE EXCEPTION 'Análise % está em estado terminal (%) e não reabre', OLD.id, OLD.status USING ERRCODE = '23514';
  END IF;
  IF NEW.status = ANY (v_terminais) AND NOT (OLD.status = ANY (v_terminais)) THEN
    NEW.finished_at := coalesce(NEW.finished_at, clock_timestamp());
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER analyses_status_guard BEFORE UPDATE OF status ON analysis.analyses
  FOR EACH ROW EXECUTE FUNCTION analysis.analyses_status_guard();

-- -----------------------------------------------------------------------------
-- (f) Índice para o custo por análise
-- -----------------------------------------------------------------------------
CREATE INDEX model_calls_analysis_idx ON llm.model_calls (analysis_id) WHERE analysis_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- (g) RLS nas tabelas-filhas: isolamento pelo escopo da análise
-- -----------------------------------------------------------------------------
ALTER TABLE analysis.plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis.plans FORCE ROW LEVEL SECURITY;
CREATE POLICY plans_isolation ON analysis.plans FOR ALL
  USING (core.is_service() OR EXISTS (SELECT 1 FROM analysis.analyses a
         WHERE a.id = plans.analysis_id AND a.scope_id::text = current_setting('app.scope_id', true)))
  WITH CHECK (core.is_service() OR EXISTS (SELECT 1 FROM analysis.analyses a
         WHERE a.id = plans.analysis_id AND a.scope_id::text = current_setting('app.scope_id', true)));

ALTER TABLE analysis.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis.tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY tasks_isolation ON analysis.tasks FOR ALL
  USING (core.is_service() OR EXISTS (SELECT 1 FROM analysis.analyses a
         WHERE a.id = tasks.analysis_id AND a.scope_id::text = current_setting('app.scope_id', true)))
  WITH CHECK (core.is_service() OR EXISTS (SELECT 1 FROM analysis.analyses a
         WHERE a.id = tasks.analysis_id AND a.scope_id::text = current_setting('app.scope_id', true)));

ALTER TABLE analysis.evidence_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis.evidence_findings FORCE ROW LEVEL SECURITY;
CREATE POLICY evidence_isolation ON analysis.evidence_findings FOR ALL
  USING (core.is_service() OR EXISTS (SELECT 1 FROM analysis.analyses a
         WHERE a.id = evidence_findings.analysis_id AND a.scope_id::text = current_setting('app.scope_id', true)))
  WITH CHECK (core.is_service() OR EXISTS (SELECT 1 FROM analysis.analyses a
         WHERE a.id = evidence_findings.analysis_id AND a.scope_id::text = current_setting('app.scope_id', true)));

ALTER TABLE analysis.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis.reports FORCE ROW LEVEL SECURITY;
CREATE POLICY reports_isolation ON analysis.reports FOR ALL
  USING (core.is_service() OR EXISTS (SELECT 1 FROM analysis.analyses a
         WHERE a.id = reports.analysis_id AND a.scope_id::text = current_setting('app.scope_id', true)))
  WITH CHECK (core.is_service() OR EXISTS (SELECT 1 FROM analysis.analyses a
         WHERE a.id = reports.analysis_id AND a.scope_id::text = current_setting('app.scope_id', true)));

COMMENT ON FUNCTION tools.execution_context(uuid, uuid) IS
  '[6ª onda] Agente/plano/escopo que julgam uma execução: pela conversa, senão pela conversa da análise; NULL = global.';
COMMENT ON FUNCTION analysis.assert_task_insert() IS
  '[6ª onda] Tarefa só depende de nó já existente no mesmo plano (ordem topológica ⇒ sem ciclo) e do plano da própria análise.';
COMMENT ON FUNCTION analysis.plans_new_version() IS
  '[6ª onda] Versão derivada (max+1), plano anterior superseded/inativo; v>1 conta replan (replans_bounded recusa o excedente).';
COMMENT ON FUNCTION analysis.assert_report_grounded() IS
  '[6ª onda] Relatório final/final_with_warnings exige evidence_hash e ≥1 evidência material da análise.';

COMMIT;
