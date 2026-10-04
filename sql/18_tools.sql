-- =============================================================================
-- SYNAPTA · 18_tools.sql
-- Registro dos "códigos prontos" — o coração do fluxo desenhado:
--   LLM entende a pergunta → preenche os PARÂMETROS de uma tool registrada
--   → a tool (código determinístico, versionado, testado) roda
--   → o output volta para o LLM sintetizar.
--
-- O LLM nunca calcula. Ele escolhe a tool e preenche o param_schema.
-- Mesmo padrão de proveniência de engine.engine_versions: git_sha + hash do
-- fonte, para provar qual código exato produziu qual número (RCVM 19 art. 17).
--
-- Depende de: 00_core, 01_identity, 03_billing, 17_agents.
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS tools;

CREATE TYPE tools.tool_family AS ENUM (
  'quant',          -- returns, volatility, beta, correlação, event study, regressão...
  'dados',          -- séries de preço/macro, comparativos, rankings factuais
  'planejamento',   -- projeções de objetivo, aposentadoria, aportes
  'orcamento',      -- taxa de poupança, reserva, dívida
  'produto',        -- decomposição de custo de produto, comparação de alternativas
  'educacao',       -- glossário, exemplos didáticos, simuladores simples
  'util'            -- resolução de entidade, formatação, câmbio pontual
);

CREATE TYPE tools.execution_status AS ENUM (
  'running', 'succeeded', 'failed', 'timeout', 'cancelled'
);

-- -----------------------------------------------------------------------------
-- Catálogo de tools — o que o planner "enxerga" (tool discovery)
-- -----------------------------------------------------------------------------
CREATE TABLE tools.tools (
  code                  core.slug PRIMARY KEY,       -- 'quant.event_study', 'produto.custo_fundo'
  family                tools.tool_family NOT NULL,
  display_name          text NOT NULL,
  description           text NOT NULL,               -- o LLM lê isto para escolher a tool
  param_schema          jsonb NOT NULL,              -- JSON Schema; exportado como tool definition
  output_schema         jsonb,
  is_deterministic      boolean NOT NULL DEFAULT true,
  requires_market_data  boolean NOT NULL DEFAULT false,
  min_plan              billing.plan_code NOT NULL DEFAULT 'free',
  is_active             boolean NOT NULL DEFAULT true,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT param_schema_is_object CHECK (jsonb_typeof(param_schema) = 'object')
);
CREATE INDEX tools_family_idx ON tools.tools (family) WHERE is_active;

COMMENT ON COLUMN tools.tools.param_schema IS
  'Um schema, duas funções: contrato interno (validação Pydantic no serviço) e '
  'restrição de decodificação do LLM (tool_choice forçado). Nunca manter cópia '
  'manual do schema no prompt.';

-- -----------------------------------------------------------------------------
-- Versões — sincronizadas do registro por decorator no deploy
-- -----------------------------------------------------------------------------
CREATE TABLE tools.tool_versions (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  tool_code      core.slug NOT NULL REFERENCES tools.tools(code),
  semver         text NOT NULL CHECK (semver ~ '^\d+\.\d+\.\d+(-[\w.]+)?$'),
  git_sha        char(40) NOT NULL,
  source_sha256  core.hash_hex NOT NULL,   -- hash do módulo, mesma prova de engine_versions
  source_uri     text,
  changelog      text,
  published_at   timestamptz NOT NULL DEFAULT now(),
  deprecated_at  timestamptz,
  UNIQUE (tool_code, semver)
);
CREATE UNIQUE INDEX tool_versions_one_current
  ON tools.tool_versions (tool_code) WHERE deprecated_at IS NULL;

-- -----------------------------------------------------------------------------
-- Execuções — cada rodada de código é auditável e cacheável
-- -----------------------------------------------------------------------------
CREATE TABLE tools.tool_executions (
  id                        uuid PRIMARY KEY DEFAULT core.new_id(),
  tool_version_id           uuid NOT NULL REFERENCES tools.tool_versions(id),
  scope_id                  uuid REFERENCES identity.scopes(id),  -- NULL = execução global (warmup/backfill)
  conversation_id           uuid REFERENCES agents.conversations(id),
  requested_params          jsonb NOT NULL,   -- o que o LLM preencheu (pós-validação Pydantic)
  resolved_params           jsonb,            -- pós-resolução de entidade (ticker → asset_id, datas)
  input_hash                core.hash_hex NOT NULL,
  output_hash               core.hash_hex,
  status                    tools.execution_status NOT NULL DEFAULT 'running',
  cache_hit                 boolean NOT NULL DEFAULT false,
  cached_from_execution_id  uuid REFERENCES tools.tool_executions(id),
  output_payload            jsonb,
  storage_key               text,             -- S3 quando o output é grande demais
  error_code                text,
  error_detail              text,
  started_at                timestamptz NOT NULL DEFAULT now(),
  finished_at               timestamptz,
  duration_ms               int,
  CONSTRAINT cache_hit_has_source CHECK (NOT cache_hit OR cached_from_execution_id IS NOT NULL),
  CONSTRAINT finished_has_ts CHECK (status IN ('running') OR finished_at IS NOT NULL)
);
CREATE INDEX tool_executions_cache_idx ON tools.tool_executions (tool_version_id, input_hash)
  WHERE status = 'succeeded';
CREATE INDEX tool_executions_conversation_idx ON tools.tool_executions (conversation_id)
  WHERE conversation_id IS NOT NULL;
CREATE INDEX tool_executions_scope_idx ON tools.tool_executions (scope_id, started_at DESC)
  WHERE scope_id IS NOT NULL;

-- Execução finalizada é imutável (mesmo espírito de engine.runs_freeze)
CREATE OR REPLACE FUNCTION tools.freeze_finished_execution() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'tools.tool_executions é append-only' USING ERRCODE = '42501';
  END IF;
  IF OLD.status IN ('succeeded','failed','timeout','cancelled') THEN
    RAISE EXCEPTION 'tools.tool_executions % já finalizada é imutável', OLD.id
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER tool_executions_freeze BEFORE UPDATE OR DELETE ON tools.tool_executions
  FOR EACH ROW EXECUTE FUNCTION tools.freeze_finished_execution();

-- -----------------------------------------------------------------------------
-- REGRA INVIOLÁVEL: agente só invoca tool de família permitida.
-- (Educador não roda event study; Analista não mexe em orçamento.)
-- Regra no BANCO porque regra que vive só no serviço vaza no primeiro
-- endpoint novo — mesmo argumento do C4 do desenho original.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION tools.assert_family_allowed() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_agent    agents.agent_code;
  v_allowed  text[];
  v_family   text;
BEGIN
  IF NEW.conversation_id IS NULL THEN RETURN NEW; END IF;

  SELECT c.agent_code, d.allowed_tool_families
    INTO v_agent, v_allowed
  FROM agents.conversations c
  JOIN agents.agent_definitions d ON d.code = c.agent_code
  WHERE c.id = NEW.conversation_id;

  SELECT t.family::text INTO v_family
  FROM tools.tool_versions v
  JOIN tools.tools t ON t.code = v.tool_code
  WHERE v.id = NEW.tool_version_id;

  IF NOT (v_family = ANY (v_allowed)) THEN
    RAISE EXCEPTION 'Agente % não pode invocar tool da família % (permitidas: %)',
      v_agent, v_family, v_allowed
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER tool_executions_family_gate BEFORE INSERT ON tools.tool_executions
  FOR EACH ROW EXECUTE FUNCTION tools.assert_family_allowed();

-- Proveniência do turno: mensagem aponta para a execução que a fundamentou
ALTER TABLE agents.messages
  ADD CONSTRAINT messages_tool_execution_fk
  FOREIGN KEY (tool_execution_id) REFERENCES tools.tool_executions(id);

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE tools.tool_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tools.tool_executions FORCE  ROW LEVEL SECURITY;
CREATE POLICY tool_executions_isolation ON tools.tool_executions FOR ALL
  USING (core.is_service()
         OR (scope_id IS NOT NULL AND scope_id::text = current_setting('app.scope_id', true)))
  WITH CHECK (core.is_service()
         OR (scope_id IS NOT NULL AND scope_id::text = current_setting('app.scope_id', true)));

-- Catálogo (tools, tool_versions) é dado de referência: sem RLS, leitura livre.
-- O seed do catálogo NÃO vive em migration: é sincronizado do registro por
-- decorator no deploy (código é a fonte da verdade; o banco é o espelho auditável).

COMMIT;
