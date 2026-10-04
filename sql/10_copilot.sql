-- =============================================================================
-- SYNAPTA · 10_copilot.sql
-- Copiloto contextual: a interface de linguagem natural SOBRE os números do app.
--
-- REGRA ESTRUTURAL (§16.1.5): o Copiloto LÊ números; NUNCA os calcula.
-- cited_refs registra exatamente QUAIS números (runs, findings, snapshots)
-- fundamentaram cada resposta — sem referência citável, a resposta é
-- "não tenho esse dado", nunca improviso.
--
-- NOTA: o Copiloto (este schema) é a interface embutida nas telas do app.
-- A camada de AGENTES (17_agents em diante) é o produto conversacional novo,
-- com tools próprias. Convivem; uma eventual unificação é decisão de produto.
-- =============================================================================

BEGIN;

CREATE TYPE copilot.message_role AS ENUM ('user', 'assistant', 'system');

CREATE TABLE copilot.conversations (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id      uuid NOT NULL REFERENCES identity.scopes(id),
  user_id       uuid NOT NULL REFERENCES identity.users(id),
  context_page  text,                          -- 'raiox','objetivo:<id>','carteira'
  started_at    timestamptz NOT NULL DEFAULT now(),
  last_message_at timestamptz,
  message_count int NOT NULL DEFAULT 0,
  ended_at      timestamptz
);
CREATE INDEX copilot_conversations_scope_idx ON copilot.conversations (scope_id, started_at DESC);

CREATE TABLE copilot.messages (
  id              uuid PRIMARY KEY DEFAULT core.new_id(),
  conversation_id uuid NOT NULL REFERENCES copilot.conversations(id) ON DELETE CASCADE,
  scope_id        uuid NOT NULL REFERENCES identity.scopes(id),
  seq             int NOT NULL,
  role            copilot.message_role NOT NULL,
  content         text NOT NULL,
  -- §16.1.5: as referências citadas — o QUE fundamenta a resposta
  cited_refs      jsonb NOT NULL DEFAULT '[]'::jsonb,
  model           text,
  input_tokens    int,
  output_tokens   int,
  latency_ms      int,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (conversation_id, seq),
  CONSTRAINT cited_refs_is_array CHECK (jsonb_typeof(cited_refs) = 'array')
);
CREATE INDEX copilot_messages_conversation_idx ON copilot.messages (conversation_id, seq);
CREATE TRIGGER copilot_messages_append_only BEFORE UPDATE OR DELETE ON copilot.messages
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- Contador de uso mensal — o gate 'copiloto_limite' lê daqui vs. entitlements
CREATE TABLE copilot.usage_counters (
  scope_id       uuid NOT NULL REFERENCES identity.scopes(id),
  period_month   date NOT NULL,
  question_count int NOT NULL DEFAULT 0,
  PRIMARY KEY (scope_id, period_month),
  CONSTRAINT copilot_period_is_month CHECK (period_month = date_trunc('month', period_month)::date)
);

CREATE OR REPLACE FUNCTION copilot.count_user_question() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.role = 'user' THEN
    INSERT INTO copilot.usage_counters (scope_id, period_month, question_count)
    VALUES (NEW.scope_id, date_trunc('month', now())::date, 1)
    ON CONFLICT (scope_id, period_month)
    DO UPDATE SET question_count = copilot.usage_counters.question_count + 1;
  END IF;
  UPDATE copilot.conversations
     SET message_count = message_count + 1, last_message_at = NEW.created_at
   WHERE id = NEW.conversation_id;
  RETURN NEW;
END;
$$;
CREATE TRIGGER copilot_messages_count AFTER INSERT ON copilot.messages
  FOR EACH ROW EXECUTE FUNCTION copilot.count_user_question();

-- Guardrails de vocabulário (fronteira RCVM: diagnóstico, nunca recomendação)
CREATE TABLE copilot.guardrail_events (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  conversation_id uuid REFERENCES copilot.conversations(id) ON DELETE CASCADE,
  message_id      uuid REFERENCES copilot.messages(id),
  scope_id        uuid NOT NULL REFERENCES identity.scopes(id),
  kind            text NOT NULL CHECK (kind IN
                    ('vocabulario_proibido','pedido_recomendacao','fora_de_contexto',
                     'sem_referencia_citavel','prompt_injection_suspeita')),
  action_taken    text NOT NULL CHECK (action_taken IN ('bloqueado','reescrito','avisado','registrado')),
  details         jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER copilot_guardrails_append_only BEFORE UPDATE OR DELETE ON copilot.guardrail_events
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- Feedback por resposta (👍/👎 alimenta revisão de prompts e de copy)
CREATE TABLE copilot.message_feedback (
  message_id  uuid PRIMARY KEY REFERENCES copilot.messages(id) ON DELETE CASCADE,
  scope_id    uuid NOT NULL REFERENCES identity.scopes(id),
  user_id     uuid NOT NULL REFERENCES identity.users(id),
  helpful     boolean NOT NULL,
  comment     text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

COMMIT;
