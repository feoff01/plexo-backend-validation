-- =============================================================================
-- SYNAPTA · 22_assertions.sql
-- A CAMADA EPISTÊMICA. Estende o schema `context` (21) com a memória do que
-- o cliente disse, do que o sistema deduziu — e do quanto cada coisa vale.
--
-- O PROBLEMA QUE ESTE ARQUIVO RESOLVE
--   "Talvez eu compre uma casa" não pode virar um objetivo de compra de imóvel.
--   "Acho que a bolsa vai cair" não pode virar uma restrição de alocação.
--   "Ganho R$ 18 mil" dito em julho não pode valer para sempre.
--   Hoje o banco só tem `context.signals` (o que foi detectado) e
--   `context.change_proposals` (o que foi proposto). Falta o meio: o que o
--   sistema SABE, com que grau, desde quando e com base em quê.
--
-- AS DUAS DIMENSÕES, SEPARADAS DE PROPÓSITO
--   modality = QUE TIPO DE COISA é   → fato · intencao · hipotese · preferencia · opiniao
--   status   = QUEM RESPONDE POR ELA → declarado · inferido · confirmado ·
--                                       conflitante · obsoleto · refutado
--   Uma hipótese confirmada continua sendo hipótese. Confirmar "talvez eu compre
--   uma casa" confirma a DÚVIDA, não a compra. As duas colunas nunca colapsam.
--
-- A REGRA-ESTRELA DESTE ARQUIVO (C22)
--   Tabela estruturada só recebe FATO CONFIRMADO.
--   household.members, budget.income_sources, estate.assets e
--   preferences.constraints carregam `assertion_id`; o gate
--   context.assert_assertion_confirmed() recusa qualquer linha cuja asserção
--   de origem não esteja em modality='fato'|'preferencia' E status='confirmado'.
--   Dúvida mora aqui. Estrutura é o que sobreviveu à confirmação.
--
-- Depende de: 00_core, 01_identity, 17_agents (messages), 21_context.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Vocabulário
-- -----------------------------------------------------------------------------
CREATE TYPE context.assertion_modality AS ENUM (
  'fato',        -- "tenho um apartamento em Pinheiros"
  'intencao',    -- "vou trocar de carro em 2027"        (exige likelihood)
  'hipotese',    -- "talvez eu compre uma casa"           (exige likelihood)
  'preferencia', -- "não quero investir em cripto"
  'opiniao'      -- "acho que a bolsa vai cair"           (nunca vira fato)
);

CREATE TYPE context.assertion_status AS ENUM (
  'declarado',    -- a pessoa disse; ninguém validou
  'inferido',     -- o sistema deduziu; a pessoa não viu
  'confirmado',   -- a pessoa confirmou explicitamente  ← o único que vira estrutura
  'conflitante',  -- contradiz outra asserção vigente
  'obsoleto',     -- passou de valid_until ou foi superada
  'refutado'      -- a pessoa negou
);

CREATE TYPE context.assertion_source AS ENUM (
  'onboarding', 'formulario', 'conversa', 'open_finance',
  'upload', 'inferencia_motor', 'operador'
);

CREATE TYPE context.subject_kind AS ENUM (
  'titular', 'membro', 'renda', 'despesa', 'patrimonio', 'divida',
  'objetivo', 'preferencia', 'contexto_vida', 'mercado',
  'recomendacao_externa',   -- "meu assessor (humano) me indicou o COE X"
  'outro'
);

-- -----------------------------------------------------------------------------
-- context.assertions — uma afirmação sobre o mundo do cliente, datada e com dono
-- -----------------------------------------------------------------------------
CREATE TABLE context.assertions (
  id                   uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id             uuid NOT NULL REFERENCES identity.scopes(id),
  user_id              uuid NOT NULL REFERENCES identity.users(id),

  -- sobre O QUÊ
  subject_kind         context.subject_kind NOT NULL,
  subject_ref          uuid,                 -- household.members.id, estate.assets.id...
  attribute            core.slug NOT NULL,   -- 'renda_mensal', 'compra_imovel', 'aversao_cripto'
  value                jsonb NOT NULL,       -- {"amount": 18000} | {"text": "..."} | {"bool": true}
  unit                 text,                 -- 'BRL', 'meses', 'anos', '%'

  -- COM QUE FORÇA
  modality             context.assertion_modality NOT NULL,
  status               context.assertion_status NOT NULL DEFAULT 'declarado',
  confidence           core.confidence NOT NULL DEFAULT 0.5,  -- quão bem o sistema leu
  likelihood           core.confidence,                        -- chance de se realizar

  -- DE ONDE VEIO
  source               context.assertion_source NOT NULL,
  source_ref           jsonb NOT NULL DEFAULT '{}'::jsonb,
  signal_id            uuid REFERENCES context.signals(id),
  evidence_message_ids uuid[] NOT NULL DEFAULT '{}',

  -- QUANDO VALE
  observed_at          timestamptz NOT NULL DEFAULT now(),
  valid_from           date NOT NULL DEFAULT current_date,
  valid_until          date,                 -- renda sem revisão apodrece

  -- CICLO DE VIDA
  confirmed_at              timestamptz,
  confirmed_by              uuid REFERENCES identity.users(id),
  confirmed_via_proposal_id uuid REFERENCES context.change_proposals(id),
  refuted_at                timestamptz,
  superseded_at             timestamptz,
  superseded_by             uuid REFERENCES context.assertions(id),
  created_at                timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT value_is_object CHECK (jsonb_typeof(value) = 'object'),

  -- "talvez" SEM probabilidade é "sim" disfarçado. O banco recusa.
  CONSTRAINT hypothesis_needs_likelihood CHECK (
    (modality IN ('intencao','hipotese')) = (likelihood IS NOT NULL)
  ),

  -- Opinião nunca é fato sobre o cliente. Se importa para a carteira,
  -- registre como 'preferencia' — e ela vira preferences.constraints (26).
  CONSTRAINT opinion_never_confirmed CHECK (
    modality <> 'opiniao' OR status <> 'confirmado'
  ),

  -- Uma direção só, de propósito: um fato confirmado pode ser DEMOVIDO depois
  -- (obsoleto por expiração/supersessão, conflitante por contradição nova) e o
  -- carimbo confirmed_at fica como história. A forma bidirecional quebraria
  -- exatamente o fluxo principal: confirmar a renda nova por cima da antiga.
  CONSTRAINT confirmed_needs_ts CHECK (status <> 'confirmado' OR confirmed_at IS NOT NULL),
  CONSTRAINT confirmed_ts_matches_history CHECK (
    confirmed_at IS NULL OR status IN ('confirmado','obsoleto','conflitante')
  ),
  CONSTRAINT confirmed_has_actor CHECK (confirmed_at IS NULL OR confirmed_by IS NOT NULL),
  -- quem confirma o próprio contexto é o PRÓPRIO usuário (mesmo padrão do C21)
  CONSTRAINT self_confirmation_only CHECK (confirmed_by IS NULL OR confirmed_by = user_id),
  CONSTRAINT refuted_needs_ts CHECK (status <> 'refutado' OR refuted_at IS NOT NULL),
  CONSTRAINT refuted_ts_matches_history CHECK (
    refuted_at IS NULL OR status IN ('refutado','obsoleto')
  ),
  CONSTRAINT superseded_pair CHECK ((superseded_at IS NULL) = (superseded_by IS NULL)),
  CONSTRAINT no_self_supersede CHECK (superseded_by IS NULL OR superseded_by <> id),
  CONSTRAINT validity_range CHECK (valid_until IS NULL OR valid_until >= valid_from),

  -- o que veio de conversa aponta para as mensagens exatas (padrão de context.signals)
  CONSTRAINT conversation_needs_evidence CHECK (
    source <> 'conversa' OR cardinality(evidence_message_ids) > 0
  )
);

CREATE INDEX assertions_scope_idx ON context.assertions (scope_id, observed_at DESC);
CREATE INDEX assertions_subject_idx
  ON context.assertions (scope_id, subject_kind, attribute)
  WHERE superseded_at IS NULL;
CREATE INDEX assertions_pending_idx ON context.assertions (scope_id, modality)
  WHERE status IN ('declarado','inferido','conflitante');
CREATE INDEX assertions_expiring_idx ON context.assertions (valid_until)
  WHERE valid_until IS NOT NULL AND superseded_at IS NULL
    AND status IN ('declarado','inferido','confirmado');
CREATE INDEX assertions_ref_idx ON context.assertions (subject_ref)
  WHERE subject_ref IS NOT NULL;

COMMENT ON TABLE context.assertions IS
  'Fato, inferência e opinião em colunas separadas. `modality` diz o que a coisa É; '
  '`status` diz quem responde por ela. Confirmar uma hipótese confirma a hipótese, '
  'não o evento. Nada aqui altera carteira: o caminho continua sendo '
  'context.change_proposals → confirmação do usuário → estrutura.';

COMMENT ON COLUMN context.assertions.likelihood IS
  'Probabilidade de a intenção/hipótese se realizar, na leitura do cliente. '
  'Obrigatória para intencao/hipotese e proibida para o resto — é ela que impede '
  '"talvez eu compre uma casa" de virar um objetivo de R$ 800 mil.';

-- ---------------------------------------------------------------- C22a
-- Asserção só NASCE pendente: 'declarado' ou 'inferido'. Confirmação, conflito,
-- refutação e obsolescência são atos POSTERIORES do ciclo de vida. Sem isso,
-- bastaria o extrator inserir status='confirmado' e a regra inteira sumiria.
CREATE OR REPLACE FUNCTION context.assert_not_born_confirmed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status NOT IN ('declarado','inferido') THEN
    RAISE EXCEPTION
      'Asserção nasce "declarado" ou "inferido" — nunca "%". Confirmação é um '
      'segundo ato, com confirmed_by = user_id.', NEW.status
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER assertions_not_born_confirmed BEFORE INSERT ON context.assertions
  FOR EACH ROW EXECUTE FUNCTION context.assert_not_born_confirmed();

-- Evidência tem que apontar para mensagens REAIS de conversas do MESMO escopo.
-- (Mesmo espírito do gate de context.signals; aquele valida por conversa do
-- run, este valida por escopo — asserção pode nascer de qualquer conversa.)
CREATE OR REPLACE FUNCTION context.assert_assertion_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_valid int;
BEGIN
  IF cardinality(NEW.evidence_message_ids) = 0 THEN RETURN NEW; END IF;
  SELECT count(*) INTO v_valid
  FROM agents.messages m
  JOIN agents.conversations c ON c.id = m.conversation_id
  WHERE m.id = ANY (NEW.evidence_message_ids)
    AND c.scope_id = NEW.scope_id;
  IF v_valid <> cardinality(NEW.evidence_message_ids) THEN
    RAISE EXCEPTION
      'Asserção referencia mensagens inexistentes ou de outro escopo (% válidas de %)',
      v_valid, cardinality(NEW.evidence_message_ids) USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER assertions_evidence_gate BEFORE INSERT ON context.assertions
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_evidence();

-- ---------------------------------------------------------------- C22b
-- O conteúdo é imutável. Mudou a renda? Nova asserção + supersessão.
-- Só o ciclo de vida (status, validade, confirmação, supersessão) muda.
CREATE OR REPLACE FUNCTION context.assert_assertion_content_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.scope_id, NEW.user_id, NEW.subject_kind, NEW.attribute,
      NEW.value, NEW.modality, NEW.source, NEW.likelihood, NEW.observed_at,
      NEW.valid_from, NEW.source_ref, NEW.evidence_message_ids)
     IS DISTINCT FROM
     (OLD.scope_id, OLD.user_id, OLD.subject_kind, OLD.attribute,
      OLD.value, OLD.modality, OLD.source, OLD.likelihood, OLD.observed_at,
      OLD.valid_from, OLD.source_ref, OLD.evidence_message_ids)
     OR NEW.subject_ref IS DISTINCT FROM OLD.subject_ref
     OR NEW.unit        IS DISTINCT FROM OLD.unit
     OR NEW.signal_id   IS DISTINCT FROM OLD.signal_id
  THEN
    RAISE EXCEPTION
      'Conteúdo de asserção é imutável (%). Mudança é linha NOVA + superseded_by — '
      'senão o histórico do cliente vira ficção.', OLD.id
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER assertions_content_immutable BEFORE UPDATE ON context.assertions
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_content_immutable();

CREATE TRIGGER assertions_no_delete BEFORE DELETE ON context.assertions
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- ---------------------------------------------------------------- C22c
-- Contradição não é erro de digitação: é informação. Duas afirmações vigentes
-- sobre o mesmo atributo com valores diferentes viram 'conflitante' — e o
-- conflito aparece na UI como pergunta, não como escolha silenciosa do sistema.
CREATE OR REPLACE FUNCTION context.flag_conflicting_assertions() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_hits int;
BEGIN
  IF NEW.modality NOT IN ('fato','preferencia') THEN
    RETURN NULL;   -- hipóteses concorrentes convivem sem conflito
  END IF;

  UPDATE context.assertions a
     SET status = 'conflitante'
   WHERE a.id <> NEW.id
     AND a.scope_id     = NEW.scope_id
     AND a.subject_kind = NEW.subject_kind
     AND a.subject_ref IS NOT DISTINCT FROM NEW.subject_ref
     AND a.attribute    = NEW.attribute
     AND a.modality     = NEW.modality
     AND a.superseded_at IS NULL
     AND a.status IN ('declarado','inferido','confirmado')
     AND a.value <> NEW.value;
  GET DIAGNOSTICS v_hits = ROW_COUNT;

  IF v_hits > 0 THEN
    UPDATE context.assertions SET status = 'conflitante' WHERE id = NEW.id;
  END IF;
  RETURN NULL;
END;
$$;
CREATE TRIGGER assertions_detect_conflict AFTER INSERT ON context.assertions
  FOR EACH ROW EXECUTE FUNCTION context.flag_conflicting_assertions();

-- Confirmar resolve o conflito: as concorrentes viram obsoletas, com ponteiro.
CREATE OR REPLACE FUNCTION context.supersede_siblings_on_confirm() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE context.assertions a
     SET status        = 'obsoleto',
         superseded_at = now(),
         superseded_by = NEW.id
   WHERE a.id <> NEW.id
     AND a.scope_id     = NEW.scope_id
     AND a.subject_kind = NEW.subject_kind
     AND a.subject_ref IS NOT DISTINCT FROM NEW.subject_ref
     AND a.attribute    = NEW.attribute
     AND a.modality     = NEW.modality
     AND a.superseded_at IS NULL
     AND a.status <> 'refutado';   -- refutado morreu refutado; não vira "obsoleto"
  RETURN NULL;
END;
$$;
CREATE TRIGGER assertions_confirm_supersedes AFTER UPDATE ON context.assertions
  FOR EACH ROW
  WHEN (NEW.status = 'confirmado' AND OLD.status IS DISTINCT FROM 'confirmado')
  EXECUTE FUNCTION context.supersede_siblings_on_confirm();

-- ---------------------------------------------------------------- C22 (o gate)
-- Usado por 23/24/25/26. Passa-se o nome da coluna via TG_ARGV.
CREATE OR REPLACE FUNCTION context.assert_assertion_confirmed() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_col text := TG_ARGV[0];
  v_id  uuid;
  v_mod context.assertion_modality;
  v_st  context.assertion_status;
  v_sup timestamptz;
  v_scope uuid;
BEGIN
  v_id := nullif(to_jsonb(NEW) ->> v_col, '')::uuid;
  IF v_id IS NULL THEN
    RETURN NEW;   -- linha digitada direto pelo usuário não precisa de asserção
  END IF;

  SELECT modality, status, superseded_at, scope_id
    INTO v_mod, v_st, v_sup, v_scope
  FROM context.assertions WHERE id = v_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Asserção % não existe', v_id USING ERRCODE = '23503';
  END IF;
  IF v_scope <> (to_jsonb(NEW) ->> 'scope_id')::uuid THEN
    RAISE EXCEPTION 'Asserção % pertence a outro escopo', v_id USING ERRCODE = '23514';
  END IF;
  IF v_mod NOT IN ('fato','preferencia') THEN
    RAISE EXCEPTION
      'C22 — estrutura não recebe "%": intenção, hipótese e opinião ficam em '
      'context.assertions até virarem fato confirmado.', v_mod
      USING ERRCODE = '23514';
  END IF;
  IF v_st <> 'confirmado' OR v_sup IS NOT NULL THEN
    RAISE EXCEPTION
      'C22 — asserção % está em "%" (superseded=%). Estrutura só recebe fato '
      'CONFIRMADO pelo próprio cliente.', v_id, v_st, v_sup IS NOT NULL
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

COMMENT ON FUNCTION context.assert_assertion_confirmed IS
  'C22 — o gate único da onda 22–27. Chamado com o nome da coluna: '
  'EXECUTE FUNCTION context.assert_assertion_confirmed(''assertion_id'').';

-- ---------------------------------------------------------------- validade
-- Chamada pelo job diário: o que venceu vira 'obsoleto' e volta a ser pergunta.
CREATE OR REPLACE FUNCTION context.expire_stale_assertions(p_as_of date DEFAULT current_date)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE v_n int;
BEGIN
  UPDATE context.assertions
     SET status = 'obsoleto'
   WHERE valid_until IS NOT NULL
     AND valid_until < p_as_of
     AND superseded_at IS NULL
     AND status IN ('declarado','inferido','confirmado','conflitante');
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END;
$$;

-- -----------------------------------------------------------------------------
-- Views — o que o resto do banco deve ler
-- -----------------------------------------------------------------------------

-- O que o sistema pode usar como verdade.
CREATE VIEW context.v_current_facts WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT id, scope_id, user_id, subject_kind, subject_ref, attribute, value, unit,
       modality, confidence, observed_at, valid_from, valid_until, confirmed_at
FROM context.assertions
WHERE status = 'confirmado'
  AND superseded_at IS NULL
  AND (valid_until IS NULL OR valid_until >= current_date);

-- O que precisa virar pergunta ao cliente: dúvida, conflito e coisa vencida.
CREATE VIEW context.v_open_questions WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT id, scope_id, user_id, subject_kind, subject_ref, attribute, value,
       modality, status, confidence, likelihood, observed_at, valid_until,
       CASE
         WHEN status = 'conflitante' THEN 'conflito'
         WHEN status = 'obsoleto'    THEN 'vencida'
         WHEN modality IN ('intencao','hipotese') THEN 'em_duvida'
         ELSE 'nao_confirmada'
       END AS reason
FROM context.assertions
WHERE superseded_at IS NULL
  AND status IN ('declarado','inferido','conflitante','obsoleto');

COMMENT ON VIEW context.v_open_questions IS
  'A fila de "me confirma?" da UI. É daqui que sai a diferença entre um assistente '
  'que adivinha e um que pergunta.';

-- -----------------------------------------------------------------------------
-- Ligação com o fluxo de propostas já existente (21)
-- Novos labels: usáveis a partir do próximo COMMIT (PG 12+ permite ADD VALUE
-- em transação, mas não o uso do valor na MESMA transação). Nenhum seed usa.
-- -----------------------------------------------------------------------------
ALTER TYPE context.proposal_kind ADD VALUE IF NOT EXISTS 'assertion_confirm';
ALTER TYPE context.proposal_kind ADD VALUE IF NOT EXISTS 'household_member';
ALTER TYPE context.proposal_kind ADD VALUE IF NOT EXISTS 'income_source';
ALTER TYPE context.proposal_kind ADD VALUE IF NOT EXISTS 'estate_asset';
ALTER TYPE context.proposal_kind ADD VALUE IF NOT EXISTS 'investment_constraint';

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE context.assertions ENABLE ROW LEVEL SECURITY;
ALTER TABLE context.assertions FORCE  ROW LEVEL SECURITY;
CREATE POLICY assertions_isolation ON context.assertions FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

-- -----------------------------------------------------------------------------
-- Policy — validade por atributo e limiares. Nasce draft (filosofia dos seeds).
-- -----------------------------------------------------------------------------
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('CONTEXT_ASSERTIONS', 1, '{
  "validade_dias": {
    "renda_mensal": 180,
    "despesa_mensal": 180,
    "patrimonio_declarado": 365,
    "composicao_familiar": 365,
    "preferencia": null
  },
  "min_confidence_para_perguntar": 0.5,
  "min_likelihood_para_virar_objetivo": 0.8,
  "max_perguntas_abertas_por_escopo": 5
}'::jsonb, 'draft');

COMMIT;
