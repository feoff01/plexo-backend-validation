-- =============================================================================
-- SYNAPTA · 13_audit.sql
-- Log de auditoria — QUEM fez O QUÊ. (Não confundir com engine.runs, que
-- responde "como reproduzo o número"; ver C2 no README.)
--
-- Particionado por mês (partições criadas em 14), append-only nos dois níveis:
-- trigger + REVOKE. LGPD: acesso a PII é logado em tabela própria — quem viu
-- CPF/renda de quem, quando, por quê.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Log de atividade — toda mutação relevante do produto passa por aqui
-- -----------------------------------------------------------------------------
CREATE TABLE audit.activity_log (
  id            uuid NOT NULL DEFAULT core.new_id(),
  occurred_at   timestamptz NOT NULL DEFAULT now(),
  actor_kind    text NOT NULL CHECK (actor_kind IN ('user','system','job','admin','support')),
  actor_user_id uuid,
  scope_id      uuid,
  action        text NOT NULL,          -- 'action.dismissed','target.activated','consent.revoked'
  object_kind   text,                   -- 'finding','action','goal','subscription','proposal'
  object_id     uuid,
  details       jsonb NOT NULL DEFAULT '{}'::jsonb,
  request_id    text,
  ip_address    inet,
  user_agent    text,
  PRIMARY KEY (occurred_at, id)
) PARTITION BY RANGE (occurred_at);
CREATE INDEX activity_log_scope_idx ON audit.activity_log (scope_id, occurred_at DESC);
CREATE INDEX activity_log_actor_idx ON audit.activity_log (actor_user_id, occurred_at DESC);
CREATE INDEX activity_log_action_idx ON audit.activity_log (action, occurred_at DESC);

CREATE TRIGGER activity_log_append_only BEFORE UPDATE OR DELETE ON audit.activity_log
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
REVOKE UPDATE, DELETE ON audit.activity_log FROM PUBLIC;

COMMENT ON TABLE audit.activity_log IS
  'Sem FK de propósito (tabela quente, particionada, recebe eventos de sistema '
  'sem usuário). A costura com identity é por id, validada na escrita pelo serviço.';

-- -----------------------------------------------------------------------------
-- Acesso a PII — LGPD art. 37: registro das operações de tratamento
-- -----------------------------------------------------------------------------
CREATE TABLE audit.pii_access (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at    timestamptz NOT NULL DEFAULT now(),
  accessor_user_id uuid,                -- quem viu (admin/suporte) — NULL = job
  accessor_role  text NOT NULL CHECK (accessor_role IN ('admin','support','job','dpo')),
  subject_user_id uuid NOT NULL,        -- de quem era o dado
  fields         text[] NOT NULL,       -- ['cpf','monthly_income_brl']
  purpose        text NOT NULL,         -- 'suporte_ticket_1234','obrigacao_regulatoria'
  request_id     text
);
CREATE INDEX pii_access_subject_idx ON audit.pii_access (subject_user_id, occurred_at DESC);
CREATE TRIGGER pii_access_append_only BEFORE UPDATE OR DELETE ON audit.pii_access
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
REVOKE UPDATE, DELETE ON audit.pii_access FROM PUBLIC;

COMMIT;
