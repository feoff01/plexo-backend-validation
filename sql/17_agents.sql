-- =============================================================================
-- SYNAPTA · 17_agents.sql
-- Núcleo conversacional dos agentes: Analista IA, Assessor IA, Educador
-- (e o agente interno de Contexto Pessoal, que não conversa — só lê).
--
-- DECISÃO CENTRAL: os três agentes visíveis compartilham o MESMO esqueleto.
-- Todos fazem: pergunta → LLM entende → despacha para código pronto (tools.*)
-- → código roda → LLM sintetiza o output. O que muda entre agentes é a
-- FAMÍLIA de tools permitida e o prompt. Logo: uma estrutura, não três.
--
-- Depende de: 00_core (helpers/domains), 01_identity, 02_engine (policy_versions),
--             03_billing (billing.plan_code).
-- FKs para tools.* e llm.* são adicionadas em 18 e 19 (dependência circular).
--
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS agents;

CREATE TYPE agents.agent_code AS ENUM ('analista', 'assessor', 'educador', 'contexto');

CREATE TYPE agents.conversation_status AS ENUM (
  'aberta',       -- usuário conversando
  'encerrada',    -- turno final entregue; elegível para o agente de Contexto
  'processada',   -- agente de Contexto extraiu sinais (ou nada encontrou)
  'arquivada'
);

CREATE TYPE agents.message_role AS ENUM ('user', 'agent', 'system', 'tool');

-- -----------------------------------------------------------------------------
-- Definição dos agentes — configuração como DADO, não como código (§16.8.2)
-- -----------------------------------------------------------------------------
CREATE TABLE agents.agent_definitions (
  code                      agents.agent_code PRIMARY KEY,
  display_name              text NOT NULL,
  description               text,
  is_user_facing            boolean NOT NULL DEFAULT true,
  min_plan                  billing.plan_code NOT NULL DEFAULT 'free',
  -- famílias de tools que este agente pode invocar (valores de tools.tool_family,
  -- validados por trigger em 18_tools — o enum ainda não existe aqui)
  allowed_tool_families     text[] NOT NULL DEFAULT '{}',
  -- prompt de sistema vigente; FK para llm.prompt_versions adicionada em 19_llm
  active_prompt_version_id  uuid,
  max_replans               smallint NOT NULL DEFAULT 2,
  is_active                 boolean NOT NULL DEFAULT true,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER agent_definitions_touch BEFORE UPDATE ON agents.agent_definitions
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE agents.agent_definitions IS
  'Os 3 agentes visíveis + o agente de Contexto (is_user_facing = false). '
  'O que diferencia um agente é prompt + famílias de tools + limites — tudo dado, '
  'nada hardcoded. Criar um 4º agente visível é um INSERT, não um deploy.';

-- -----------------------------------------------------------------------------
-- Conversas
-- -----------------------------------------------------------------------------
CREATE TABLE agents.conversations (
  id                  uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id            uuid NOT NULL REFERENCES identity.scopes(id),
  user_id             uuid NOT NULL REFERENCES identity.users(id),
  agent_code          agents.agent_code NOT NULL REFERENCES agents.agent_definitions(code),
  -- snapshot do plano no início da conversa: a cota é julgada contra o plano
  -- que valia QUANDO a pergunta foi feita (point-in-time, como suitability)
  plan_code_at_start  billing.plan_code NOT NULL,
  status              agents.conversation_status NOT NULL DEFAULT 'aberta',
  title               text,
  message_count       int NOT NULL DEFAULT 0,
  started_at          timestamptz NOT NULL DEFAULT now(),
  last_message_at     timestamptz,
  ended_at            timestamptz,
  processed_at        timestamptz,      -- quando o agente de Contexto concluiu
  metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at          timestamptz NOT NULL DEFAULT now(),

  -- o agente de Contexto não conversa: ele lê conversas dos outros
  CONSTRAINT conversation_not_with_contexto CHECK (agent_code <> 'contexto'),
  CONSTRAINT conversation_ended_has_ts CHECK (status NOT IN ('encerrada','processada') OR ended_at IS NOT NULL),
  CONSTRAINT conversation_processed_has_ts CHECK (status <> 'processada' OR processed_at IS NOT NULL)
);
CREATE INDEX conversations_scope_idx  ON agents.conversations (scope_id, started_at DESC);
CREATE INDEX conversations_agent_idx  ON agents.conversations (agent_code, started_at DESC);
CREATE INDEX conversations_pending_context_idx ON agents.conversations (ended_at)
  WHERE status = 'encerrada';
CREATE TRIGGER conversations_touch BEFORE UPDATE ON agents.conversations
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON COLUMN agents.conversations.plan_code_at_start IS
  'Point-in-time do plano. Sem isto, um upgrade no meio do mês reescreve o passado '
  'da cota — mesmo princípio de identity.suitability_assessments.';

-- -----------------------------------------------------------------------------
-- Mensagens — APPEND-ONLY. Conversa é registro, não rascunho.
-- (O agente de Contexto e a auditoria dependem de a conversa ser imutável.)
-- -----------------------------------------------------------------------------
CREATE TABLE agents.messages (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  conversation_id    uuid NOT NULL REFERENCES agents.conversations(id) ON DELETE CASCADE,
  scope_id           uuid NOT NULL REFERENCES identity.scopes(id),
  seq                int  NOT NULL,
  role               agents.message_role NOT NULL,
  content            text,
  content_json       jsonb,
  -- proveniência do turno (FKs adicionadas em 18 e 19):
  tool_execution_id  uuid,     -- qual código rodou para produzir este turno
  model_call_id      uuid,     -- qual chamada de LLM redigiu este turno
  cited_refs         jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at         timestamptz NOT NULL DEFAULT now(),

  UNIQUE (conversation_id, seq),
  CONSTRAINT message_has_content CHECK (content IS NOT NULL OR content_json IS NOT NULL),
  CONSTRAINT cited_refs_is_array CHECK (jsonb_typeof(cited_refs) = 'array')
);
CREATE INDEX messages_conversation_idx ON agents.messages (conversation_id, seq);
CREATE TRIGGER messages_append_only BEFORE UPDATE OR DELETE ON agents.messages
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- -----------------------------------------------------------------------------
-- Cota por agente/plano — contador mensal + regra vinda de policy_versions
-- -----------------------------------------------------------------------------
CREATE TABLE agents.usage_counters (
  scope_id        uuid NOT NULL REFERENCES identity.scopes(id),
  agent_code      agents.agent_code NOT NULL,
  period_month    date NOT NULL,               -- sempre dia 1 do mês
  question_count  int NOT NULL DEFAULT 0,
  PRIMARY KEY (scope_id, agent_code, period_month),
  CONSTRAINT period_is_month_start CHECK (period_month = date_trunc('month', period_month)::date)
);

-- Cota vive em engine.policy_versions('AGENT_QUOTAS'), alterável sem deploy,
-- no mesmo padrão de FAMILY_LIMITS. Payload:
--   {"free": {"analista": 10, "assessor": 10, "educador": 20},
--    "essential": {"analista": 100, ...}, "advanced": {}}
-- Chave ausente = ilimitado. A pergunta excedente é REJEITADA na escrita —
-- a aplicação intercepta o erro 23514 e mostra o paywall (gate → analytics).
CREATE OR REPLACE FUNCTION agents.enforce_question_quota() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_agent  agents.agent_code;
  v_plan   billing.plan_code;
  v_scope  uuid;
  v_limit  int;
  v_count  int;
BEGIN
  SELECT c.agent_code, c.plan_code_at_start, c.scope_id
    INTO v_agent, v_plan, v_scope
  FROM agents.conversations c WHERE c.id = NEW.conversation_id;

  -- scope da mensagem valida contra o da conversa, para QUALQUER role
  IF NEW.scope_id IS DISTINCT FROM v_scope THEN
    RAISE EXCEPTION 'Mensagem com scope_id % divergente da conversa (%)', NEW.scope_id, v_scope
      USING ERRCODE = '23514';
  END IF;

  -- cota só conta pergunta do usuário
  IF NEW.role <> 'user' THEN RETURN NEW; END IF;

  SELECT (payload #>> ARRAY[v_plan::text, v_agent::text])::int INTO v_limit
  FROM engine.policy_versions
  WHERE code = 'AGENT_QUOTAS' AND effective_to IS NULL
  ORDER BY effective_from DESC LIMIT 1;

  INSERT INTO agents.usage_counters (scope_id, agent_code, period_month, question_count)
  VALUES (v_scope, v_agent, date_trunc('month', now())::date, 1)
  ON CONFLICT (scope_id, agent_code, period_month)
  DO UPDATE SET question_count = agents.usage_counters.question_count + 1
  RETURNING question_count INTO v_count;

  IF v_limit IS NOT NULL AND v_count > v_limit THEN
    RAISE EXCEPTION 'Cota mensal do agente % excedida (% de %) para o plano %',
      v_agent, v_count, v_limit, v_plan
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER messages_quota BEFORE INSERT ON agents.messages
  FOR EACH ROW EXECUTE FUNCTION agents.enforce_question_quota();

-- Manutenção do contador da conversa
CREATE OR REPLACE FUNCTION agents.bump_conversation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE agents.conversations
     SET message_count = message_count + 1,
         last_message_at = NEW.created_at
   WHERE id = NEW.conversation_id;
  RETURN NULL;
END;
$$;
CREATE TRIGGER messages_bump AFTER INSERT ON agents.messages
  FOR EACH ROW EXECUTE FUNCTION agents.bump_conversation();

-- -----------------------------------------------------------------------------
-- Guardrails — cada bloqueio/reescrita é registro, não log perdido
-- -----------------------------------------------------------------------------
CREATE TABLE agents.guardrail_events (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  conversation_id  uuid REFERENCES agents.conversations(id) ON DELETE CASCADE,
  message_id       uuid REFERENCES agents.messages(id),
  scope_id         uuid NOT NULL REFERENCES identity.scopes(id),
  kind             text NOT NULL CHECK (kind IN (
                     'vocabulario_proibido',      -- ex.: "recomendo", "garantido"
                     'pedido_recomendacao',       -- fronteira RCVM: diagnóstico, não recomendação
                     'fora_de_escopo',
                     'prompt_injection_suspeita',
                     'limite_orcamento_llm',
                     'outro')),
  action_taken     text NOT NULL CHECK (action_taken IN ('bloqueado','reescrito','avisado','registrado')),
  details          jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX guardrail_events_kind_idx ON agents.guardrail_events (kind, occurred_at DESC);
CREATE TRIGGER guardrail_events_append_only BEFORE UPDATE OR DELETE ON agents.guardrail_events
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- -----------------------------------------------------------------------------
-- RLS — mesma convenção do restante do banco: GUCs app.scope_id / app.role
-- -----------------------------------------------------------------------------
ALTER TABLE agents.conversations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents.conversations   FORCE  ROW LEVEL SECURITY;
CREATE POLICY conversations_isolation ON agents.conversations FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE agents.messages        ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents.messages        FORCE  ROW LEVEL SECURITY;
CREATE POLICY messages_isolation ON agents.messages FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE agents.usage_counters  ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents.usage_counters  FORCE  ROW LEVEL SECURITY;
CREATE POLICY usage_counters_isolation ON agents.usage_counters FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE agents.guardrail_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents.guardrail_events FORCE  ROW LEVEL SECURITY;
CREATE POLICY guardrail_events_isolation ON agents.guardrail_events FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

-- -----------------------------------------------------------------------------
-- SEEDS
-- -----------------------------------------------------------------------------
INSERT INTO agents.agent_definitions
  (code, display_name, description, is_user_facing, min_plan, allowed_tool_families)
VALUES
  ('analista', 'Analista IA',
   'Testa teses e explica movimentos de mercado com métodos quantitativos auditáveis. '
   'O LLM escolhe QUAL análise rodar; quem calcula são tools determinísticas.',
   true,  'free', ARRAY['quant','dados']),
  ('assessor', 'Assessor IA',
   'Planejamento financeiro e orçamentário; segunda opinião sobre produtos '
   'recomendados por terceiros (custo, adequação, conflito de interesse).',
   true,  'free', ARRAY['planejamento','orcamento','produto']),
  ('educador', 'Educador',
   'Educação financeira em linguagem simples, ancorada em conteúdo aprovado por compliance.',
   true,  'free', ARRAY['educacao']),
  ('contexto', 'Contexto Pessoal',
   'Agente interno. Lê conversas ENCERRADAS, extrai sinais e gera PROPOSTAS de '
   'mudança — nunca aplica nada sem confirmação do usuário (ver 21_context.sql).',
   false, 'free', ARRAY[]::text[]);

-- Cotas nascem como policy em DRAFT — números são [PENDENTE] até pricing fechar.
-- O trigger de cota lê a política vigente independentemente de aprovação
-- (cota é config operacional, não premissa metodológica client-facing).
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('AGENT_QUOTAS', 1, '{
  "free":      {"analista": 3,   "assessor": 5,   "educador": 10},
  "essential": {"analista": 30,  "assessor": 50,  "educador": 100},
  "advanced":  {}
}'::jsonb, 'draft');

COMMIT;
