-- =============================================================================
-- SYNAPTA · 19_llm.sql
-- A camada de LLM como objeto de domínio: prompts versionados, cada chamada
-- registrada com tokens e custo, e o razão de custo agregado (§18.1 do Blueprint).
--
-- Sem llm.model_calls, você nunca saberá qual agente queima dinheiro, qual
-- mudança de prompt causou qual mudança de resultado (teach workflow §17.3),
-- nem quanto custa uma resposta do Analista vs. do Educador.
--
-- Regra de ouro: o campo usage da RESPOSTA DO PROVEDOR é a verdade do ledger;
-- contagem local de tokens serve só para estimativa de preflight.
--
-- Depende de: 00_core, 01_identity, 02_engine (compliance_status), 17_agents.
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS llm;

CREATE TYPE llm.call_purpose AS ENUM (
  'intencao',           -- entender a pergunta / rotear
  'parametrizacao',     -- preencher param_schema de uma tool (tool_choice forçado)
  'planejamento',       -- gerar AnalysisPlan (Analista, modo profundo)
  'sintese',            -- redigir a resposta a partir do output das tools
  'extracao_contexto',  -- agente de Contexto lendo conversa encerrada
  'classificacao',
  'guardrail',
  'outro'
);

-- -----------------------------------------------------------------------------
-- Prompts versionados com aprovação de compliance — o prompt de um agente
-- client-facing é premissa metodológica tanto quanto RISK_BANDS (§13.6/C6):
-- muda o que o cliente lê. Logo: estado versionado com aprovador e vigência.
-- -----------------------------------------------------------------------------
-- [validação PG real] jsonb_build_object é STABLE no catálogo (aceita qualquer
-- tipo), o que proíbe seu uso direto em coluna GENERATED. Para entrada text o
-- resultado é determinístico; este wrapper declara isso e preserva a semântica:
-- content_hash = canonical_hash de {"template": <template>}.
CREATE FUNCTION llm.prompt_hash(p_template text) RETURNS core.hash_hex
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT core.canonical_hash(jsonb_build_object('template', p_template))
$$;

CREATE TABLE llm.prompt_versions (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  code               core.slug NOT NULL,   -- 'agent.analista.system', 'context.extractor', ...
  version            int  NOT NULL,
  template           text NOT NULL,        -- Jinja2; variáveis declaradas abaixo
  variables          text[] NOT NULL DEFAULT '{}',
  content_hash       core.hash_hex GENERATED ALWAYS AS
                       (llm.prompt_hash(template)) STORED,
  effective_from     timestamptz NOT NULL DEFAULT now(),
  effective_to       timestamptz,
  compliance_status  engine.compliance_status NOT NULL DEFAULT 'draft',
  approved_by        uuid REFERENCES identity.users(id),
  approved_at        timestamptz,
  rejection_reason   text,
  created_by         uuid REFERENCES identity.users(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (code, version),
  CHECK (effective_to IS NULL OR effective_to > effective_from),
  CHECK ((compliance_status = 'approved') = (approved_at IS NOT NULL))
);
CREATE UNIQUE INDEX prompt_one_current ON llm.prompt_versions (code)
  WHERE effective_to IS NULL;

-- Agora o agente pode apontar para seu prompt vigente
ALTER TABLE agents.agent_definitions
  ADD CONSTRAINT agent_prompt_fk
  FOREIGN KEY (active_prompt_version_id) REFERENCES llm.prompt_versions(id);

-- -----------------------------------------------------------------------------
-- GATE: conversa com agente client-facing exige prompt vigente APROVADO.
-- Espelho de engine.runs_policy_gate. O primeiro deploy trava até compliance
-- aprovar os prompts — intencional, mesma filosofia do C6.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION agents.assert_agent_prompt_approved() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_user_facing boolean;
  v_status      engine.compliance_status;
BEGIN
  SELECT d.is_user_facing, p.compliance_status
    INTO v_user_facing, v_status
  FROM agents.agent_definitions d
  LEFT JOIN llm.prompt_versions p ON p.id = d.active_prompt_version_id
  WHERE d.code = NEW.agent_code;

  IF v_user_facing AND (v_status IS DISTINCT FROM 'approved') THEN
    RAISE EXCEPTION
      'Agente % está client-facing com prompt não aprovado por compliance (status: %)',
      NEW.agent_code, coalesce(v_status::text, 'sem prompt')
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER conversations_prompt_gate BEFORE INSERT ON agents.conversations
  FOR EACH ROW EXECUTE FUNCTION agents.assert_agent_prompt_approved();

-- -----------------------------------------------------------------------------
-- Chamadas de modelo — APPEND-ONLY. Uma linha por chamada, gravada ao concluir.
-- -----------------------------------------------------------------------------
CREATE TABLE llm.model_calls (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  purpose            llm.call_purpose NOT NULL,
  provider           text NOT NULL,        -- 'anthropic', 'openai', 'google', 'local'
  model              text NOT NULL,        -- nome exato faturável; NUNCA usado em regra de domínio
  prompt_version_id  uuid REFERENCES llm.prompt_versions(id),
  agent_code         agents.agent_code,
  scope_id           uuid REFERENCES identity.scopes(id),
  conversation_id    uuid REFERENCES agents.conversations(id),
  message_id         uuid REFERENCES agents.messages(id),
  analysis_id        uuid,                 -- FK adicionada em 20_analysis
  request_hash       core.hash_hex,
  input_tokens       int NOT NULL DEFAULT 0 CHECK (input_tokens  >= 0),
  cached_tokens      int NOT NULL DEFAULT 0 CHECK (cached_tokens >= 0),
  output_tokens      int NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  cost_usd           numeric(12,6),
  latency_ms         int,
  status             text NOT NULL DEFAULT 'succeeded'
                     CHECK (status IN ('succeeded','failed','timeout','refused')),
  error_code         text,
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX model_calls_agent_idx        ON llm.model_calls (agent_code, created_at DESC);
CREATE INDEX model_calls_conversation_idx ON llm.model_calls (conversation_id) WHERE conversation_id IS NOT NULL;
CREATE INDEX model_calls_purpose_idx      ON llm.model_calls (purpose, created_at DESC);
CREATE TRIGGER model_calls_append_only BEFORE UPDATE OR DELETE ON llm.model_calls
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

COMMENT ON TABLE llm.model_calls IS
  'Em volume, migrar para particionamento mensal por created_at, no mesmo padrão '
  'de analytics.events. No MVP, tabela simples: FKs apontam para cá e '
  'particionamento cedo complicaria as referências sem necessidade.';

-- Proveniência do turno: mensagem aponta para a chamada que a redigiu
ALTER TABLE agents.messages
  ADD CONSTRAINT messages_model_call_fk
  FOREIGN KEY (model_call_id) REFERENCES llm.model_calls(id);

-- -----------------------------------------------------------------------------
-- Razão de custo agregado (CostLedger §18.1) — upsert diário por referência
-- -----------------------------------------------------------------------------
CREATE TABLE llm.cost_ledger (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope_id              uuid REFERENCES identity.scopes(id),
  ref_kind              text NOT NULL CHECK (ref_kind IN ('conversation','analysis','job')),
  ref_id                uuid NOT NULL,
  as_of_date            date NOT NULL DEFAULT current_date,
  model_calls           int    NOT NULL DEFAULT 0,
  input_tokens          bigint NOT NULL DEFAULT 0,
  cached_tokens         bigint NOT NULL DEFAULT 0,
  output_tokens         bigint NOT NULL DEFAULT 0,
  web_search_calls      int    NOT NULL DEFAULT 0,
  data_provider_calls   int    NOT NULL DEFAULT 0,
  tool_executions       int    NOT NULL DEFAULT 0,
  cpu_seconds           numeric(12,3) NOT NULL DEFAULT 0,
  storage_bytes         bigint NOT NULL DEFAULT 0,
  estimated_usd         numeric(14,6),
  actual_usd            numeric(14,6),
  UNIQUE (ref_kind, ref_id, as_of_date)
);
CREATE INDEX cost_ledger_scope_idx ON llm.cost_ledger (scope_id, as_of_date DESC)
  WHERE scope_id IS NOT NULL;

-- Orçamento por chamada/análise vive em policy, alterável sem deploy
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('LLM_BUDGETS', 1, '{
  "max_output_tokens_por_turno": 4000,
  "max_usd_por_analise": 0.50,
  "max_replans_por_analise": 2,
  "max_model_calls_por_turno": 4
}'::jsonb, 'draft');

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE llm.model_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm.model_calls FORCE  ROW LEVEL SECURITY;
CREATE POLICY model_calls_isolation ON llm.model_calls FOR ALL
  USING (core.is_service()
         OR (scope_id IS NOT NULL AND scope_id::text = current_setting('app.scope_id', true)))
  WITH CHECK (core.is_service()
         OR (scope_id IS NOT NULL AND scope_id::text = current_setting('app.scope_id', true)));

ALTER TABLE llm.cost_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm.cost_ledger FORCE  ROW LEVEL SECURITY;
CREATE POLICY cost_ledger_isolation ON llm.cost_ledger FOR ALL
  USING (core.is_service()
         OR (scope_id IS NOT NULL AND scope_id::text = current_setting('app.scope_id', true)))
  WITH CHECK (core.is_service()
         OR (scope_id IS NOT NULL AND scope_id::text = current_setting('app.scope_id', true)));

-- -----------------------------------------------------------------------------
-- SEEDS — prompts nascem DRAFT. O gate acima trava conversas até aprovação.
-- -----------------------------------------------------------------------------
INSERT INTO llm.prompt_versions (code, version, template, variables, compliance_status)
VALUES
  ('agent.analista.system', 1,
   '[PENDENTE — prompt do Analista IA. Instruções fixas e tool definitions '
   'PRIMEIRO (cache de prefixo); conteúdo variável depois.]',
   ARRAY['contexto_escopo','tools_disponiveis'], 'draft'),
  ('agent.assessor.system', 1,
   '[PENDENTE — prompt do Assessor IA. Vocabulário: diagnóstico e comparação, '
   'nunca recomendação (fronteira RCVM).]',
   ARRAY['contexto_escopo','tools_disponiveis'], 'draft'),
  ('agent.educador.system', 1,
   '[PENDENTE — prompt do Educador. Responde ancorado em conteúdo aprovado; '
   'linguagem simples; nunca opina sobre ativo específico.]',
   ARRAY['contexto_escopo'], 'draft'),
  ('context.extractor', 1,
   '[PENDENTE — prompt do agente de Contexto. Extração estruturada de sinais; '
   'saída restrita ao schema de context.signals; nunca decide, só propõe.]',
   ARRAY['conversa','perfil_atual'], 'draft');

UPDATE agents.agent_definitions d
   SET active_prompt_version_id = p.id
  FROM llm.prompt_versions p
 WHERE p.code = 'agent.' || d.code::text || '.system'
   AND d.code <> 'contexto';

UPDATE agents.agent_definitions d
   SET active_prompt_version_id = p.id
  FROM llm.prompt_versions p
 WHERE p.code = 'context.extractor' AND d.code = 'contexto';

COMMIT;
