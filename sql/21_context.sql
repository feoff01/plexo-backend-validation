-- =============================================================================
-- SYNAPTA · 21_context.sql
-- O quarto agente: Contexto Pessoal. Lê conversas ENCERRADAS, extrai sinais
-- e gera PROPOSTAS de mudança no contexto do cliente.
--
-- A REGRA-ESTRELA DESTE ARQUIVO (inviolável, no banco, não no serviço):
--
--   O agente de Contexto NUNCA aplica mudança sozinho.
--   1. Toda proposta só chega a 'aplicada' se o PRÓPRIO usuário confirmou.
--   2. Proposta de PERFIL DE RISCO exige, além da confirmação, um NOVO
--      suitability_assessment respondido DEPOIS da proposta.
--
-- Por quê: suitability é registro regulatório point-in-time; e o cliente
-- jamais pode descobrir que a carteira mudou porque ele desabafou numa
-- conversa. Inferência gera proposta; só confirmação gera fato.
--
-- Depende de: 00_core, 01_identity (suitability_assessments), 17_agents, 19_llm.
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS context;

CREATE TYPE context.signal_kind AS ENUM (
  'mudanca_tolerancia_risco',
  'novo_objetivo',
  'mudanca_horizonte',
  'evento_de_vida',          -- casamento, filho, doença, herança...
  'mudanca_renda',
  'mudanca_despesa',
  'nova_divida',
  'mencao_aposentadoria',
  'mudanca_dependentes',
  'outro'
);

CREATE TYPE context.proposal_kind AS ENUM (
  'suitability_risk_profile',   -- caminho especial: exige novo suitability
  'goal_create',
  'goal_update',
  'profile_field',              -- renda, despesa, dependentes em user_profiles
  'budget_field',
  'outro'
);

CREATE TYPE context.proposal_status AS ENUM (
  'proposta', 'confirmada', 'aplicada', 'rejeitada', 'expirada'
);

-- -----------------------------------------------------------------------------
-- Execuções de extração — uma por conversa encerrada, assíncrona
-- -----------------------------------------------------------------------------
CREATE TABLE context.extraction_runs (
  id               uuid PRIMARY KEY DEFAULT core.new_id(),
  conversation_id  uuid NOT NULL REFERENCES agents.conversations(id),
  scope_id         uuid NOT NULL REFERENCES identity.scopes(id),
  model_call_id    uuid REFERENCES llm.model_calls(id),
  status           text NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','succeeded','failed')),
  signals_found    int NOT NULL DEFAULT 0,
  started_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz
);
-- Reprocessar após falha é permitido; sucesso é um só por conversa
CREATE UNIQUE INDEX extraction_one_success
  ON context.extraction_runs (conversation_id) WHERE status = 'succeeded';
CREATE INDEX extraction_scope_idx ON context.extraction_runs (scope_id, started_at DESC);

-- GATE: o Contexto não lê conversa aberta. Encerrou, virou registro; aí sim.
CREATE OR REPLACE FUNCTION context.assert_conversation_ended() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_ended timestamptz;
BEGIN
  SELECT ended_at INTO v_ended FROM agents.conversations WHERE id = NEW.conversation_id;
  IF v_ended IS NULL THEN
    RAISE EXCEPTION 'Contexto não processa conversa aberta (%)', NEW.conversation_id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER extraction_requires_ended BEFORE INSERT ON context.extraction_runs
  FOR EACH ROW EXECUTE FUNCTION context.assert_conversation_ended();

-- Sucesso da extração marca a conversa como processada
CREATE OR REPLACE FUNCTION context.mark_conversation_processed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE agents.conversations
     SET status = 'processada', processed_at = now()
   WHERE id = NEW.conversation_id AND status = 'encerrada';
  RETURN NULL;
END;
$$;
CREATE TRIGGER extraction_marks_processed AFTER UPDATE ON context.extraction_runs
  FOR EACH ROW
  WHEN (NEW.status = 'succeeded' AND OLD.status <> 'succeeded')
  EXECUTE FUNCTION context.mark_conversation_processed();

-- -----------------------------------------------------------------------------
-- Sinais — o que o Contexto DETECTOU. Sinal sem evidência não existe.
-- -----------------------------------------------------------------------------
CREATE TABLE context.signals (
  id                    uuid PRIMARY KEY DEFAULT core.new_id(),
  extraction_run_id     uuid NOT NULL REFERENCES context.extraction_runs(id) ON DELETE CASCADE,
  scope_id              uuid NOT NULL REFERENCES identity.scopes(id),
  user_id               uuid NOT NULL REFERENCES identity.users(id),
  kind                  context.signal_kind NOT NULL,
  summary               text NOT NULL,
  confidence            core.confidence NOT NULL,
  evidence_message_ids  uuid[] NOT NULL,   -- as mensagens exatas que sustentam o sinal
  payload               jsonb NOT NULL DEFAULT '{}'::jsonb,
  detected_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT signal_needs_evidence CHECK (cardinality(evidence_message_ids) > 0)
);
CREATE INDEX signals_scope_idx ON context.signals (scope_id, detected_at DESC);
CREATE TRIGGER signals_append_only BEFORE UPDATE OR DELETE ON context.signals
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- Evidência tem que apontar para mensagens REAIS da MESMA conversa do run.
-- (uuid[] não aceita FK; o trigger fecha o buraco.)
CREATE OR REPLACE FUNCTION context.assert_evidence_messages() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_conversation uuid;
  v_valid        int;
BEGIN
  SELECT conversation_id INTO v_conversation
  FROM context.extraction_runs WHERE id = NEW.extraction_run_id;

  SELECT count(*) INTO v_valid
  FROM agents.messages m
  WHERE m.id = ANY (NEW.evidence_message_ids)
    AND m.conversation_id = v_conversation;

  IF v_valid <> cardinality(NEW.evidence_message_ids) THEN
    RAISE EXCEPTION
      'Sinal referencia mensagens inexistentes ou de outra conversa (% válidas de %)',
      v_valid, cardinality(NEW.evidence_message_ids)
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER signals_evidence_gate BEFORE INSERT ON context.signals
  FOR EACH ROW EXECUTE FUNCTION context.assert_evidence_messages();

-- -----------------------------------------------------------------------------
-- Propostas de mudança — a saída ÚNICA do agente de Contexto
-- -----------------------------------------------------------------------------
CREATE TABLE context.change_proposals (
  id                       uuid PRIMARY KEY DEFAULT core.new_id(),
  signal_id                uuid NOT NULL REFERENCES context.signals(id),
  scope_id                 uuid NOT NULL REFERENCES identity.scopes(id),
  user_id                  uuid NOT NULL REFERENCES identity.users(id),
  kind                     context.proposal_kind NOT NULL,
  target_ref               jsonb NOT NULL,   -- {"table":"identity.user_profiles","field":"monthly_income_brl"} ou {"goal_id":...}
  current_value            jsonb,
  proposed_value           jsonb NOT NULL,
  rationale                text NOT NULL,    -- exibido ao usuário: "você mencionou que..."
  status                   context.proposal_status NOT NULL DEFAULT 'proposta',
  proposed_at              timestamptz NOT NULL DEFAULT now(),
  expires_at               date,             -- proposta velha morre, não assombra
  confirmed_at             timestamptz,
  confirmed_by             uuid REFERENCES identity.users(id),
  applied_at               timestamptz,
  -- OBRIGATÓRIO quando kind = 'suitability_risk_profile':
  applied_suitability_id   uuid REFERENCES identity.suitability_assessments(id),
  rejected_at              timestamptz,
  rejection_note           text,

  -- (1) aplicar exige confirmar — SEM EXCEÇÃO, para qualquer kind
  CONSTRAINT apply_requires_confirmation CHECK (
    status <> 'aplicada' OR (confirmed_at IS NOT NULL AND applied_at IS NOT NULL)
  ),
  -- (2) quem confirma mudança do próprio contexto é o PRÓPRIO usuário
  CONSTRAINT self_confirmation_only CHECK (
    confirmed_by IS NULL OR confirmed_by = user_id
  ),
  CONSTRAINT confirmed_has_actor CHECK (
    confirmed_at IS NULL OR confirmed_by IS NOT NULL
  ),
  -- (3) perfil de risco aplicado exige novo suitability referenciado
  CONSTRAINT risk_apply_requires_suitability CHECK (
    kind <> 'suitability_risk_profile' OR status <> 'aplicada'
      OR applied_suitability_id IS NOT NULL
  ),
  CONSTRAINT rejected_has_ts CHECK (status <> 'rejeitada' OR rejected_at IS NOT NULL)
);
CREATE INDEX proposals_scope_status_idx ON context.change_proposals (scope_id, status, proposed_at DESC);
CREATE INDEX proposals_pending_idx ON context.change_proposals (user_id)
  WHERE status = 'proposta';

COMMENT ON TABLE context.change_proposals IS
  'O Contexto propõe; o usuário dispõe. A UI mostra: "Notei que você mencionou X. '
  'Quer atualizar Y?" — e a resposta do usuário é o que move proposta → confirmada. '
  'Aplicação grava em audit.activity_log com a proveniência (signal → messages).';

-- O trigger que fecha as brechas que o CHECK não alcança:
-- o suitability referenciado tem que ser DO usuário e POSTERIOR à proposta
-- (senão bastaria apontar um questionário antigo e burlar a regra).
CREATE OR REPLACE FUNCTION context.assert_risk_change_confirmed() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_suit_user  uuid;
  v_taken_at   timestamptz;
BEGIN
  IF NEW.status <> 'aplicada' OR NEW.kind <> 'suitability_risk_profile' THEN
    RETURN NEW;
  END IF;

  SELECT user_id, taken_at INTO v_suit_user, v_taken_at
  FROM identity.suitability_assessments
  WHERE id = NEW.applied_suitability_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Proposta de risco aplicada sem suitability válido' USING ERRCODE = '23514';
  END IF;
  IF v_suit_user <> NEW.user_id THEN
    RAISE EXCEPTION 'Suitability % pertence a outro usuário', NEW.applied_suitability_id
      USING ERRCODE = '23514';
  END IF;
  IF v_taken_at < NEW.proposed_at THEN
    RAISE EXCEPTION
      'Suitability anterior à proposta (%). Mudança de perfil de risco exige REFAZER '
      'o questionário — inferência de conversa não altera perfil regulatório.',
      v_taken_at USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER proposals_risk_gate BEFORE INSERT OR UPDATE ON context.change_proposals
  FOR EACH ROW EXECUTE FUNCTION context.assert_risk_change_confirmed();

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE context.extraction_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE context.extraction_runs FORCE  ROW LEVEL SECURITY;
CREATE POLICY extraction_isolation ON context.extraction_runs FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE context.signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE context.signals FORCE  ROW LEVEL SECURITY;
CREATE POLICY signals_isolation ON context.signals FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE context.change_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE context.change_proposals FORCE  ROW LEVEL SECURITY;
CREATE POLICY proposals_isolation ON context.change_proposals FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

-- Parâmetros da extração como policy (limiar de confiança, validade da proposta)
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('CONTEXT_EXTRACTION', 1, '{
  "min_confidence_para_proposta": 0.7,
  "validade_proposta_dias": 30,
  "max_propostas_pendentes_por_escopo": 5
}'::jsonb, 'draft');

COMMIT;
