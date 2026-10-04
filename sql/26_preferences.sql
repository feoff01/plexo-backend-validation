-- =============================================================================
-- SYNAPTA · 26_preferences.sql
-- Restrições e preferências — o que NÃO pode ser sugerido a este cliente.
--
-- POR QUE SUITABILITY NÃO BASTA
--   O questionário devolve 'conservador | moderado | arrojado'. Não cabe nele:
--       "não quero investir em cripto"
--       "não quero dinheiro preso por mais de dois anos"
--       "quero manter pelo menos R$ 150 mil disponíveis"
--       "não invisto em empresa de determinado setor"
--   Isso não é perfil de risco: é MANDATO. E mandato ignorado uma vez destrói
--   a confiança de forma que nenhum retorno recupera.
--
-- AS DUAS REGRAS-ESTRELA
--   C26a — VETO BLOQUEANTE É INVIOLÁVEL NO BANCO. Carteira-alvo, adoção de
--          Carteira Modelo e roteamento de aporte são RECUSADOS se tocarem
--          classe/emissor/instrumento vetado. Não é validação de serviço:
--          é impossibilidade.
--   C26b — RESTRIÇÃO SÓ AFROUXA PELA MÃO DO PRÓPRIO CLIENTE. Revogar exige
--          revoked_by = user_id; rebaixar 'bloqueante' → 'alerta' via UPDATE
--          é proibido (revogue e crie outra, deixando rastro). O sistema
--          nunca "esquece" um veto para viabilizar uma alocação bonita.
--
-- Depende de: 00_core, 01_identity, 04_market, 07_planning, 22_assertions.
-- =============================================================================

BEGIN;

CREATE SCHEMA preferences;

CREATE TYPE preferences.constraint_kind AS ENUM (
  'veto_classe', 'veto_emissor', 'veto_instrumento', 'veto_setor', 'veto_pais',
  'limite_max_classe', 'limite_max_emissor', 'limite_min_caixa',
  'liquidez_minima', 'horizonte_maximo',
  'sem_alavancagem', 'sem_derivativos', 'apenas_isento_ir',
  'esg_exclusao', 'religiosa', 'outro'
);

CREATE TYPE preferences.enforcement AS ENUM (
  'bloqueante',   -- o banco recusa a alocação
  'alerta',       -- passa, mas gera finding
  'informativa'   -- só contexto para o agente
);

CREATE TYPE preferences.constraint_origin AS ENUM (
  'usuario', 'suitability', 'regulatorio', 'operador', 'inferido'
);

-- -----------------------------------------------------------------------------
-- Restrições — alvo em COLUNAS TIPADAS, não em jsonb: o gate precisa de JOIN
-- -----------------------------------------------------------------------------
CREATE TABLE preferences.constraints (
  id               uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id         uuid NOT NULL REFERENCES identity.scopes(id),
  user_id          uuid NOT NULL REFERENCES identity.users(id),
  kind             preferences.constraint_kind NOT NULL,
  enforcement      preferences.enforcement NOT NULL DEFAULT 'bloqueante',
  origin           preferences.constraint_origin NOT NULL DEFAULT 'usuario',

  asset_class_code core.slug REFERENCES market.asset_classes(code),
  issuer_id        uuid REFERENCES market.issuers(id),
  instrument_id    uuid REFERENCES market.instruments(id),
  sector_code      text,
  country_code     char(2),
  threshold        numeric(12,6),      -- teto (peso 0–1) ou prazo (meses)
  params           jsonb NOT NULL DEFAULT '{}'::jsonb,

  reason           text,               -- "questão religiosa", "trabalhei no setor"
  stated_at        timestamptz NOT NULL DEFAULT now(),
  valid_until      date,

  assertion_id     uuid REFERENCES context.assertions(id),
  confirmed_at     timestamptz,
  confirmed_by     uuid REFERENCES identity.users(id),
  revoked_at       timestamptz,
  revoked_by       uuid REFERENCES identity.users(id),
  revoked_reason   text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),

  -- alvo coerente com o tipo
  CONSTRAINT class_target CHECK (
    kind NOT IN ('veto_classe','limite_max_classe') OR asset_class_code IS NOT NULL
  ),
  CONSTRAINT issuer_target CHECK (
    kind NOT IN ('veto_emissor','limite_max_emissor') OR issuer_id IS NOT NULL
  ),
  CONSTRAINT instrument_target CHECK (
    kind <> 'veto_instrumento' OR instrument_id IS NOT NULL
  ),
  CONSTRAINT sector_target  CHECK (kind <> 'veto_setor' OR sector_code  IS NOT NULL),
  CONSTRAINT country_target CHECK (kind <> 'veto_pais'  OR country_code IS NOT NULL),
  CONSTRAINT limit_needs_threshold CHECK (
    kind NOT IN ('limite_max_classe','limite_max_emissor','limite_min_caixa')
    OR (threshold IS NOT NULL AND threshold BETWEEN 0 AND 1)
  ),
  CONSTRAINT horizon_needs_threshold CHECK (
    kind NOT IN ('horizonte_maximo','liquidez_minima') OR threshold IS NOT NULL
  ),

  -- C26b: bloqueante nasce confirmado pelo próprio cliente
  CONSTRAINT blocking_requires_confirmation CHECK (
    enforcement <> 'bloqueante'
    OR (confirmed_at IS NOT NULL AND confirmed_by IS NOT NULL)
  ),
  CONSTRAINT self_confirmation_only CHECK (confirmed_by IS NULL OR confirmed_by = user_id),
  CONSTRAINT self_revocation_only   CHECK (revoked_by   IS NULL OR revoked_by   = user_id),
  CONSTRAINT revoked_has_actor      CHECK (revoked_at IS NULL OR revoked_by IS NOT NULL)
);
CREATE INDEX constraints_active_idx ON preferences.constraints (scope_id, kind)
  WHERE revoked_at IS NULL;
CREATE INDEX constraints_class_idx ON preferences.constraints (scope_id, asset_class_code)
  WHERE revoked_at IS NULL AND asset_class_code IS NOT NULL;

CREATE TRIGGER constraints_touch BEFORE UPDATE ON preferences.constraints
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER constraints_assertion_gate BEFORE INSERT OR UPDATE ON preferences.constraints
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_confirmed('assertion_id');

COMMENT ON TABLE preferences.constraints IS
  'O mandato do cliente. Suitability diz quanto risco ele suporta; isto diz o '
  'que ele não aceita, independentemente de risco. As duas coisas juntas é que '
  'formam a fronteira do que pode ser sugerido.';

-- ---------------------------------------------------------------- C26b
-- Restrição não afrouxa por UPDATE: nem o alvo, nem a força.
CREATE OR REPLACE FUNCTION preferences.assert_not_weakened() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.kind, NEW.scope_id, NEW.user_id) IS DISTINCT FROM
     (OLD.kind, OLD.scope_id, OLD.user_id)
     OR NEW.asset_class_code IS DISTINCT FROM OLD.asset_class_code
     OR NEW.issuer_id     IS DISTINCT FROM OLD.issuer_id
     OR NEW.instrument_id IS DISTINCT FROM OLD.instrument_id
     OR NEW.sector_code   IS DISTINCT FROM OLD.sector_code
     OR NEW.country_code  IS DISTINCT FROM OLD.country_code
  THEN
    RAISE EXCEPTION
      'Alvo de restrição é imutável (%). Revogue e crie outra — o rastro do que '
      'o cliente pediu não pode ser reescrito.', OLD.id USING ERRCODE = '42501';
  END IF;

  IF OLD.enforcement = 'bloqueante' AND NEW.enforcement <> 'bloqueante' THEN
    RAISE EXCEPTION
      'C26b — restrição bloqueante não vira alerta por UPDATE. Revogar exige '
      'revoked_by = user_id; afrouxar em silêncio, não existe.'
      USING ERRCODE = '42501';
  END IF;

  IF OLD.threshold IS NOT NULL AND NEW.threshold IS NOT NULL
     AND NEW.threshold > OLD.threshold
     AND NEW.kind IN ('limite_max_classe','limite_max_emissor') THEN
    RAISE EXCEPTION
      'C26b — teto não sobe por UPDATE (% → %). Revogue e crie outro.',
      OLD.threshold, NEW.threshold USING ERRCODE = '42501';
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER constraints_not_weakened BEFORE UPDATE ON preferences.constraints
  FOR EACH ROW EXECUTE FUNCTION preferences.assert_not_weakened();

-- -----------------------------------------------------------------------------
-- Exigências de liquidez — "quero R$ 150 mil disponíveis", além da reserva
-- -----------------------------------------------------------------------------
CREATE TABLE preferences.liquidity_requirements (
  id                    uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id              uuid NOT NULL REFERENCES identity.scopes(id),
  user_id               uuid NOT NULL REFERENCES identity.users(id),
  label                 text NOT NULL,
  min_amount_brl        core.money_brl CHECK (min_amount_brl >= 0),
  min_months_of_expense numeric(4,1) CHECK (min_months_of_expense >= 0),
  max_notice_days       smallint CHECK (max_notice_days >= 0),
  purpose               text,
  enforcement           preferences.enforcement NOT NULL DEFAULT 'bloqueante',
  assertion_id          uuid REFERENCES context.assertions(id),
  confirmed_at          timestamptz,
  confirmed_by          uuid REFERENCES identity.users(id),
  valid_until           date,
  revoked_at            timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT liquidity_has_a_number CHECK (
    min_amount_brl IS NOT NULL OR min_months_of_expense IS NOT NULL
                               OR max_notice_days IS NOT NULL
  ),
  CONSTRAINT liq_blocking_requires_confirmation CHECK (
    enforcement <> 'bloqueante' OR (confirmed_at IS NOT NULL AND confirmed_by IS NOT NULL)
  ),
  CONSTRAINT liq_self_confirmation CHECK (confirmed_by IS NULL OR confirmed_by = user_id)
);
CREATE INDEX liquidity_scope_idx ON preferences.liquidity_requirements (scope_id)
  WHERE revoked_at IS NULL;

CREATE TRIGGER liquidity_touch BEFORE UPDATE ON preferences.liquidity_requirements
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER liquidity_assertion_gate
  BEFORE INSERT OR UPDATE ON preferences.liquidity_requirements
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_confirmed('assertion_id');

COMMENT ON TABLE preferences.liquidity_requirements IS
  'Diferente de budget.reserve_settings: aquilo é a reserva de emergência '
  '(6 meses de custo). Isto é o piso de conforto do cliente — "quero ver '
  'R$ 150 mil na conta" — e vale mesmo com a reserva completa.';

-- C26b vale aqui também: piso de liquidez não desce por UPDATE.
CREATE OR REPLACE FUNCTION preferences.assert_liquidity_not_weakened() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.enforcement <> 'bloqueante' OR NEW.revoked_at IS NOT NULL THEN
    RETURN NEW;   -- revogar é permitido; afrouxar mantendo ativa, não
  END IF;
  IF NEW.enforcement <> 'bloqueante'
     OR (OLD.min_amount_brl IS NOT NULL AND
         (NEW.min_amount_brl IS NULL OR NEW.min_amount_brl < OLD.min_amount_brl))
     OR (OLD.min_months_of_expense IS NOT NULL AND
         (NEW.min_months_of_expense IS NULL OR
          NEW.min_months_of_expense < OLD.min_months_of_expense))
  THEN
    RAISE EXCEPTION
      'C26b — piso de liquidez bloqueante não desce por UPDATE (%). '
      'Revogue e crie outro, deixando rastro.', OLD.id USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER liquidity_not_weakened BEFORE UPDATE ON preferences.liquidity_requirements
  FOR EACH ROW EXECUTE FUNCTION preferences.assert_liquidity_not_weakened();

-- -----------------------------------------------------------------------------
-- View — o que está valendo agora
-- -----------------------------------------------------------------------------
CREATE VIEW preferences.v_active_constraints WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT id, scope_id, user_id, kind, enforcement, origin,
       asset_class_code, issuer_id, instrument_id, sector_code, country_code,
       threshold, reason, stated_at, valid_until
FROM preferences.constraints
WHERE revoked_at IS NULL
  AND (valid_until IS NULL OR valid_until >= current_date);

-- O gate C26a protege a ESCRITA. Ele não cobre a direção inversa: veto criado
-- DEPOIS de a carteira-alvo já estar ativa. Bloquear a criação do veto seria
-- pior (o cliente restringindo NUNCA pode ser obstruído — espírito do C26b),
-- então a direção inversa vira VIOLAÇÃO VISÍVEL: esta view deve estar vazia,
-- é monitorável, e cada linha aqui é uma carteira que o Builder precisa refazer.
CREATE VIEW preferences.v_violations WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT c.scope_id,
       c.id                    AS constraint_id,
       c.kind,
       c.asset_class_code,
       c.threshold,
       tp.id                   AS target_portfolio_id,
       ta.weight,
       c.stated_at             AS constraint_stated_at,
       tp.activated_at         AS portfolio_activated_at,
       CASE WHEN c.kind = 'veto_classe'
            THEN 'classe vetada presente na carteira-alvo ativa'
            ELSE 'peso acima do teto definido pelo cliente' END AS violation
FROM preferences.constraints c
JOIN planning.target_portfolios tp
  ON tp.scope_id = c.scope_id AND tp.status = 'active'
JOIN planning.target_allocations ta
  ON ta.target_portfolio_id = tp.id
 AND ta.asset_class_code = c.asset_class_code
WHERE c.enforcement = 'bloqueante'
  AND c.revoked_at IS NULL
  AND (c.valid_until IS NULL OR c.valid_until >= current_date)
  AND ( (c.kind = 'veto_classe'       AND ta.weight > 0)
     OR (c.kind = 'limite_max_classe' AND ta.weight > c.threshold) );

COMMENT ON VIEW preferences.v_violations IS
  'Deve ser SEMPRE vazia. Linha aqui = veto aceito depois de carteira ativa que '
  'ainda não foi refeita. É insumo direto de finding e de alerta operacional.';

-- =============================================================================
-- C26a — O GATE. A partir daqui, o banco recusa sugerir o que o cliente vetou.
-- =============================================================================

-- Vetos e tetos que valem AGORA para um escopo, por classe.
CREATE OR REPLACE FUNCTION preferences.check_class_allowed(
  p_scope uuid, p_class core.slug, p_weight numeric, p_where text
) RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE v_reason text; v_threshold numeric;
BEGIN
  IF p_weight IS NULL OR p_weight <= 0 THEN RETURN; END IF;

  SELECT coalesce(c.reason, 'sem motivo registrado') INTO v_reason
  FROM preferences.constraints c
  WHERE c.scope_id = p_scope
    AND c.kind = 'veto_classe'
    AND c.enforcement = 'bloqueante'
    AND c.revoked_at IS NULL
    AND (c.valid_until IS NULL OR c.valid_until >= current_date)
    AND c.asset_class_code = p_class
  LIMIT 1;

  IF FOUND THEN
    RAISE EXCEPTION
      'C26a — % contém a classe "%", vetada pelo cliente (%). Veto bloqueante '
      'só sai por revogação do próprio cliente.', p_where, p_class, v_reason
      USING ERRCODE = '23514';
  END IF;

  SELECT min(c.threshold) INTO v_threshold
  FROM preferences.constraints c
  WHERE c.scope_id = p_scope
    AND c.kind = 'limite_max_classe'
    AND c.enforcement = 'bloqueante'
    AND c.revoked_at IS NULL
    AND (c.valid_until IS NULL OR c.valid_until >= current_date)
    AND c.asset_class_code = p_class;

  IF v_threshold IS NOT NULL AND p_weight > v_threshold THEN
    RAISE EXCEPTION
      'C26a — % aloca % em "%", acima do teto de % definido pelo cliente.',
      p_where, round(p_weight * 100, 2)::text || '%', p_class,
      round(v_threshold * 100, 2)::text || '%'
      USING ERRCODE = '23514';
  END IF;
END;
$$;

-- (1) Carteira-alvo — DIFERIDA, para conviver com o trigger de soma = 1,000 (T14)
CREATE OR REPLACE FUNCTION preferences.assert_target_respects_constraints() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_scope uuid;
BEGIN
  SELECT tp.scope_id INTO v_scope
  FROM planning.target_portfolios tp WHERE tp.id = NEW.target_portfolio_id;
  IF v_scope IS NULL THEN
    -- FAIL-CLOSED. Se o portfólio não é visível daqui (RLS de outra sessão,
    -- ponteiro podre), a resposta é recusar — não deixar passar sem checar.
    -- target_allocations não tem scope_id próprio, então este é o único ponto
    -- em que a checagem pode acontecer.
    RAISE EXCEPTION
      'C26a — não foi possível resolver o escopo da carteira % para validar '
      'restrições do cliente; alocação recusada.', NEW.target_portfolio_id
      USING ERRCODE = '23514';
  END IF;

  PERFORM preferences.check_class_allowed(
    v_scope, NEW.asset_class_code, NEW.weight, 'a carteira-alvo');
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER target_allocations_respect_constraints
  AFTER INSERT OR UPDATE ON planning.target_allocations
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION preferences.assert_target_respects_constraints();

-- (2) Adoção de Carteira Modelo — checa as posições do modelo contra o mandato
CREATE OR REPLACE FUNCTION preferences.assert_adoption_respects_constraints() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
  -- (1) Nível de CLASSE: soma TOTAL por classe, não por linha. Sem isso,
  -- uma classe fatiada em três instrumentos de 15% burlaria um teto de 20%.
  FOR r IN
    SELECT h.asset_class_code, sum(h.weight) AS weight
    FROM planning.model_portfolio_holdings h
    WHERE h.model_version_id = NEW.model_version_id
    GROUP BY h.asset_class_code
  LOOP
    PERFORM preferences.check_class_allowed(
      NEW.scope_id, r.asset_class_code, r.weight, 'a Carteira Modelo adotada');
  END LOOP;

  -- (2) Nível de INSTRUMENTO/EMISSOR: veto pontual
  FOR r IN
    SELECT DISTINCT h.instrument_id
    FROM planning.model_portfolio_holdings h
    WHERE h.model_version_id = NEW.model_version_id
      AND h.instrument_id IS NOT NULL
      AND h.weight > 0
  LOOP
    IF EXISTS (
      SELECT 1 FROM preferences.constraints c
      WHERE c.scope_id = NEW.scope_id
        AND c.enforcement = 'bloqueante'
        AND c.revoked_at IS NULL
        AND (c.valid_until IS NULL OR c.valid_until >= current_date)
        AND ((c.kind = 'veto_instrumento' AND c.instrument_id = r.instrument_id)
          OR (c.kind = 'veto_emissor' AND c.issuer_id = (
                SELECT i.issuer_id FROM market.instruments i WHERE i.id = r.instrument_id)))
    ) THEN
      RAISE EXCEPTION
        'C26a — a Carteira Modelo contém instrumento/emissor vetado pelo cliente.'
        USING ERRCODE = '23514';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$;
CREATE TRIGGER model_adoptions_respect_constraints
  BEFORE INSERT ON planning.model_adoptions
  FOR EACH ROW EXECUTE FUNCTION preferences.assert_adoption_respects_constraints();

-- (3) Roteamento de aporte — não se sugere aporte no que foi vetado
CREATE OR REPLACE FUNCTION preferences.assert_routing_respects_constraints() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE k text; v numeric; v_total numeric := 0;
BEGIN
  IF jsonb_typeof(NEW.suggestion) <> 'object' THEN RETURN NEW; END IF;

  SELECT sum((value #>> '{}')::numeric) INTO v_total
  FROM jsonb_each(NEW.suggestion)
  WHERE jsonb_typeof(value) = 'number';

  FOR k, v IN
    SELECT key, (value #>> '{}')::numeric
    FROM jsonb_each(NEW.suggestion)
    WHERE jsonb_typeof(value) = 'number'
  LOOP
    PERFORM preferences.check_class_allowed(
      NEW.scope_id, k::core.slug,
      CASE WHEN coalesce(v_total, 0) > 0 THEN v / v_total ELSE 0 END,
      'o roteamento de aporte');
  END LOOP;
  RETURN NEW;
END;
$$;
CREATE TRIGGER contribution_routings_respect_constraints
  BEFORE INSERT ON planning.contribution_routings
  FOR EACH ROW EXECUTE FUNCTION preferences.assert_routing_respects_constraints();

COMMENT ON FUNCTION preferences.check_class_allowed IS
  'C26a — o mesmo gate nos três caminhos por onde uma sugestão chega ao cliente. '
  'Um veto que só vale em duas das três portas não é um veto.';

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE preferences.constraints ENABLE ROW LEVEL SECURITY;
ALTER TABLE preferences.constraints FORCE  ROW LEVEL SECURITY;
CREATE POLICY constraints_isolation ON preferences.constraints FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE preferences.liquidity_requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE preferences.liquidity_requirements FORCE  ROW LEVEL SECURITY;
CREATE POLICY liquidity_isolation ON preferences.liquidity_requirements FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

COMMIT;
