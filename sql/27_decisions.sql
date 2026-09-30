-- =============================================================================
-- SYNAPTA · 27_decisions.sql
-- O que foi apresentado ao cliente, QUANDO, POR QUÊ e COM BASE EM QUÊ.
--
-- O QUE JÁ EXISTIA E POR QUE NÃO BASTAVA
--   engine.runs + engine.artifacts reproduzem o NÚMERO byte a byte.
--   planning.target_portfolios.rationale é um jsonb opaco: ninguém consulta
--   "todas as vezes em que reduzimos ações por causa de uma restrição do cliente".
--   audit.activity_log registra QUEM FEZ, não POR QUÊ.
--   Faltava o elo: o argumento, em linhas, ligado às evidências que o sustentam.
--
-- SOBRE O NOME
--   O schema não se chama `recommendations` de propósito. §4.6/T8 já proíbe a
--   palavra "recomendada" em nome de Carteira Modelo, porque recomendação é ato
--   regulado (RCVM 19). O mesmo CHECK vale aqui, no headline: o registro é do
--   que foi APRESENTADO, não do que foi recomendado. A fronteira é jurídica,
--   e um schema mal nomeado é a primeira coisa que aparece numa fiscalização.
--
-- REGRAS INVIOLÁVEIS
--   C27a — Não existe entrega sem porquê: todo record exige ≥1 rationale_item
--          material (constraint trigger DIFERIDA — insere-se na mesma transação).
--   C27b — Carteira-alvo exige o suitability VIGENTE na hora da apresentação —
--          não um questionário qualquer, não um posterior.
--   C27c — Insumo MATERIAL não pode ser hipótese nem opinião: se aponta para
--          context.assertions, tem que ser modality='fato' + status='confirmado'.
--          É o fecho da onda: "talvez eu compre uma casa" nunca sustenta uma
--          decisão material.
--   C27d — Record é imutável, exceto o desfecho (o cliente adotou? recusou?).
--   C27e — Carteira-alvo não fica 'active' sem registro do porquê (diferida).
--
-- Depende de: 00_core, 01_identity, 02_engine, 03_billing, 07_planning,
--             17_agents, 22_assertions, 26_preferences.
-- =============================================================================

BEGIN;

CREATE SCHEMA decisions;

CREATE TYPE decisions.deliverable_kind AS ENUM (
  'carteira_alvo', 'adocao_modelo', 'roteamento_aporte', 'acao_fundacao',
  'rebalanceamento', 'projecao_objetivo', 'resposta_analista',
  'segunda_opiniao',   -- Assessor avaliando produto indicado por assessor humano
  'relatorio_analise', 'alerta_drift', 'outro'
);

CREATE TYPE decisions.outcome AS ENUM (
  'pendente', 'adotada', 'parcial', 'recusada', 'expirada', 'substituida'
);

CREATE TYPE decisions.driver AS ENUM (
  'suitability', 'objetivo', 'horizonte', 'restricao_cliente', 'liquidez',
  'fundacao', 'concentracao', 'custo', 'tributario', 'drift',
  'contexto_familiar', 'renda', 'patrimonio', 'mercado', 'outro'
);

CREATE TYPE decisions.input_kind AS ENUM (
  'holdings_snapshot', 'portfolio_snapshot', 'estate_valuation',
  'income_summary', 'budget_summary', 'assertion', 'constraint',
  'liquidity_requirement', 'goal', 'finding', 'suitability',
  'policy', 'preco_asof', 'carteira_modelo', 'outro'
);

-- -----------------------------------------------------------------------------
-- O que foi entregue
-- -----------------------------------------------------------------------------
CREATE TABLE decisions.records (
  id                        uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id                  uuid NOT NULL REFERENCES identity.scopes(id),
  user_id                   uuid NOT NULL REFERENCES identity.users(id),
  kind                      decisions.deliverable_kind NOT NULL,
  headline                  text NOT NULL,     -- o que o cliente viu, em uma frase
  target_ref                jsonb NOT NULL DEFAULT '{}'::jsonb,
  target_portfolio_id       uuid REFERENCES planning.target_portfolios(id),
  goal_id                   uuid REFERENCES planning.goals(id),
  engine_run_id             uuid REFERENCES engine.runs(id),
  suitability_assessment_id uuid REFERENCES identity.suitability_assessments(id),
  plan_code                 billing.plan_code,
  agent_message_id          uuid REFERENCES agents.messages(id),
  disclaimer_version        text,
  presented_at              timestamptz NOT NULL DEFAULT now(),

  outcome                   decisions.outcome NOT NULL DEFAULT 'pendente',
  outcome_at                timestamptz,
  outcome_note              text,
  superseded_by             uuid REFERENCES decisions.records(id),
  created_at                timestamptz NOT NULL DEFAULT now(),

  -- mesma fronteira do T8: aqui não se "recomenda"
  CONSTRAINT headline_never_recomendada CHECK (headline !~* 'recomend'),
  CONSTRAINT outcome_has_ts CHECK (outcome = 'pendente' OR outcome_at IS NOT NULL),
  CONSTRAINT substituida_has_pointer CHECK (
    outcome <> 'substituida' OR superseded_by IS NOT NULL
  ),
  -- C27b, primeira metade
  CONSTRAINT portfolio_requires_suitability CHECK (
    kind NOT IN ('carteira_alvo','adocao_modelo') OR suitability_assessment_id IS NOT NULL
  ),
  CONSTRAINT no_self_supersede CHECK (superseded_by IS NULL OR superseded_by <> id)
);
CREATE INDEX records_scope_idx ON decisions.records (scope_id, presented_at DESC);
CREATE INDEX records_kind_idx  ON decisions.records (scope_id, kind, presented_at DESC);
CREATE INDEX records_target_idx ON decisions.records (target_portfolio_id)
  WHERE target_portfolio_id IS NOT NULL;
CREATE INDEX records_pending_idx ON decisions.records (scope_id)
  WHERE outcome = 'pendente';

COMMENT ON TABLE decisions.records IS
  'A linha do tempo do relacionamento: tudo que o Synapta colocou na frente do '
  'cliente, com o argumento e a evidência ao lado. É o que responde, dois anos '
  'depois, "por que vocês me sugeriram isso em março de 2027?".';

-- ---------------------------------------------------------------- C27d
CREATE OR REPLACE FUNCTION decisions.assert_record_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.scope_id, NEW.user_id, NEW.kind, NEW.headline, NEW.target_ref,
      NEW.engine_run_id, NEW.suitability_assessment_id, NEW.presented_at)
     IS DISTINCT FROM
     (OLD.scope_id, OLD.user_id, OLD.kind, OLD.headline, OLD.target_ref,
      OLD.engine_run_id, OLD.suitability_assessment_id, OLD.presented_at)
     OR NEW.target_portfolio_id IS DISTINCT FROM OLD.target_portfolio_id
     OR NEW.disclaimer_version  IS DISTINCT FROM OLD.disclaimer_version
     OR NEW.plan_code           IS DISTINCT FROM OLD.plan_code
     OR NEW.agent_message_id    IS DISTINCT FROM OLD.agent_message_id
     OR NEW.goal_id             IS DISTINCT FROM OLD.goal_id
  THEN
    RAISE EXCEPTION
      'C27d — registro de entrega é imutável (%). Só o desfecho muda; o que foi '
      'dito ao cliente, não.', OLD.id USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER records_immutable BEFORE UPDATE ON decisions.records
  FOR EACH ROW EXECUTE FUNCTION decisions.assert_record_immutable();

CREATE TRIGGER records_no_delete BEFORE DELETE ON decisions.records
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- ---------------------------------------------------------------- C27b
-- O suitability tem que ser DO cliente e estar VIGENTE em presented_at.
CREATE OR REPLACE FUNCTION decisions.assert_suitability_in_force() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_user uuid; v_taken timestamptz; v_valid date; v_superseded timestamptz;
BEGIN
  IF NEW.suitability_assessment_id IS NULL THEN RETURN NEW; END IF;

  SELECT user_id, taken_at, valid_until, superseded_at
    INTO v_user, v_taken, v_valid, v_superseded
  FROM identity.suitability_assessments WHERE id = NEW.suitability_assessment_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Suitability % não existe', NEW.suitability_assessment_id
      USING ERRCODE = '23503';
  END IF;
  IF v_user <> NEW.user_id THEN
    RAISE EXCEPTION 'Suitability % é de outro usuário', NEW.suitability_assessment_id
      USING ERRCODE = '23514';
  END IF;
  IF v_taken > NEW.presented_at THEN
    RAISE EXCEPTION
      'C27b — suitability respondido DEPOIS da entrega (% > %). Não se justifica '
      'retroativamente o perfil que sustentou uma carteira.', v_taken, NEW.presented_at
      USING ERRCODE = '23514';
  END IF;
  IF v_superseded IS NOT NULL AND v_superseded <= NEW.presented_at THEN
    RAISE EXCEPTION
      'C27b — suitability já estava superado em % — não era o perfil vigente.',
      NEW.presented_at USING ERRCODE = '23514';
  END IF;
  IF v_valid < NEW.presented_at::date THEN
    RAISE EXCEPTION
      'C27b — suitability vencido em % (validade %). Carteira exige perfil vigente.',
      NEW.presented_at::date, v_valid USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER records_suitability_gate BEFORE INSERT OR UPDATE ON decisions.records
  FOR EACH ROW EXECUTE FUNCTION decisions.assert_suitability_in_force();

-- -----------------------------------------------------------------------------
-- POR QUÊ — o argumento em linhas, não em prosa jsonb
-- -----------------------------------------------------------------------------
CREATE TABLE decisions.rationale_items (
  id          uuid PRIMARY KEY DEFAULT core.new_id(),
  record_id   uuid NOT NULL REFERENCES decisions.records(id) ON DELETE CASCADE,
  seq         smallint NOT NULL,
  driver      decisions.driver NOT NULL,
  claim       text NOT NULL,        -- "sua reserva cobre 4 meses, meta é 6"
  detail      text,
  is_material boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (record_id, seq)
);
CREATE INDEX rationale_driver_idx ON decisions.rationale_items (driver);

CREATE TRIGGER rationale_append_only BEFORE UPDATE OR DELETE ON decisions.rationale_items
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

COMMENT ON COLUMN decisions.rationale_items.driver IS
  'Estruturado justamente para permitir a pergunta agregada: "em quantos casos '
  'a restrição do cliente mudou a alocação?" — impossível com rationale jsonb.';

-- ---------------------------------------------------------------- C27a
CREATE OR REPLACE FUNCTION decisions.assert_record_has_rationale() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM decisions.rationale_items r
    WHERE r.record_id = NEW.id AND r.is_material
  ) THEN
    RAISE EXCEPTION
      'C27a — entrega % sem nenhum motivo material. Se não dá para escrever o '
      'porquê, não dá para mostrar ao cliente.', NEW.id USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER records_need_rationale
  AFTER INSERT ON decisions.records
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION decisions.assert_record_has_rationale();

-- -----------------------------------------------------------------------------
-- COM BASE EM QUÊ — a proveniência
-- -----------------------------------------------------------------------------
CREATE TABLE decisions.inputs (
  id                       uuid PRIMARY KEY DEFAULT core.new_id(),
  record_id                uuid NOT NULL REFERENCES decisions.records(id) ON DELETE CASCADE,
  input_kind               decisions.input_kind NOT NULL,
  ref                      jsonb NOT NULL DEFAULT '{}'::jsonb,
  assertion_id             uuid REFERENCES context.assertions(id),
  constraint_id            uuid REFERENCES preferences.constraints(id),
  finding_id               uuid REFERENCES diagnostics.findings(id),
  as_of                    date,
  is_material              boolean NOT NULL DEFAULT false,
  created_at               timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT assertion_input_has_ref CHECK (
    input_kind <> 'assertion' OR assertion_id IS NOT NULL
  ),
  CONSTRAINT constraint_input_has_ref CHECK (
    input_kind <> 'constraint' OR constraint_id IS NOT NULL
  ),
  CONSTRAINT finding_input_has_ref CHECK (
    input_kind <> 'finding' OR finding_id IS NOT NULL
  )
);
CREATE INDEX inputs_record_idx ON decisions.inputs (record_id);
CREATE INDEX inputs_assertion_idx ON decisions.inputs (assertion_id)
  WHERE assertion_id IS NOT NULL;

CREATE TRIGGER inputs_append_only BEFORE UPDATE OR DELETE ON decisions.inputs
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- ---------------------------------------------------------------- C27c
-- O fecho da onda 22–27.
CREATE OR REPLACE FUNCTION decisions.assert_material_input_is_fact() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_mod context.assertion_modality;
  v_st  context.assertion_status;
  v_sup timestamptz;
BEGIN
  IF NOT NEW.is_material OR NEW.assertion_id IS NULL THEN RETURN NEW; END IF;

  SELECT modality, status, superseded_at INTO v_mod, v_st, v_sup
  FROM context.assertions WHERE id = NEW.assertion_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Asserção % não existe', NEW.assertion_id USING ERRCODE = '23503';
  END IF;

  IF v_mod <> 'fato' OR v_st <> 'confirmado' OR v_sup IS NOT NULL THEN
    RAISE EXCEPTION
      'C27c — insumo material apoiado em "%" (status %). Decisão material se '
      'apoia em FATO CONFIRMADO. Hipótese e opinião entram como is_material=false '
      'ou viram pergunta ao cliente antes.', v_mod, v_st
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER inputs_material_gate BEFORE INSERT ON decisions.inputs
  FOR EACH ROW EXECUTE FUNCTION decisions.assert_material_input_is_fact();

-- ---------------------------------------------------------------- C27e
-- Nenhuma carteira-alvo ATIVA sem registro do porquê. DIFERIDA: o serviço
-- insere carteira + record na mesma transação; a validação roda no COMMIT.
CREATE OR REPLACE FUNCTION decisions.assert_active_target_has_record() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM decisions.records d
    WHERE d.target_portfolio_id = NEW.id
      AND d.kind IN ('carteira_alvo','adocao_modelo')
  ) THEN
    RAISE EXCEPTION
      'C27e — carteira-alvo % ativada sem decisions.records. Carteira sem '
      'justificativa registrada não vai para o ar.', NEW.id USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER target_active_needs_record
  AFTER INSERT OR UPDATE ON planning.target_portfolios
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  WHEN (NEW.status = 'active')
  EXECUTE FUNCTION decisions.assert_active_target_has_record();

-- -----------------------------------------------------------------------------
-- View — a linha do tempo do cliente
-- -----------------------------------------------------------------------------
CREATE VIEW decisions.v_client_timeline WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT d.id, d.scope_id, d.user_id, d.kind, d.headline, d.presented_at,
       d.outcome, d.outcome_at, d.plan_code,
       -- DISTINCT obrigatório: o LEFT JOIN duplo multiplica linhas
       -- (rationale × inputs) e count() simples inflaria os dois números.
       count(DISTINCT r.id) FILTER (WHERE r.is_material)  AS motivos_materiais,
       count(DISTINCT i.id) FILTER (WHERE i.is_material)  AS insumos_materiais,
       array_agg(DISTINCT r.driver) FILTER (WHERE r.is_material) AS drivers
FROM decisions.records d
LEFT JOIN decisions.rationale_items r ON r.record_id = d.id
LEFT JOIN decisions.inputs i          ON i.record_id = d.id
GROUP BY d.id;

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE decisions.records ENABLE ROW LEVEL SECURITY;
ALTER TABLE decisions.records FORCE  ROW LEVEL SECURITY;
CREATE POLICY records_isolation ON decisions.records FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

-- rationale_items e inputs não têm scope_id: herdam pelo record_id (CASCADE).
-- Acesso direto é sempre via JOIN com decisions.records, já protegida.

COMMIT;
