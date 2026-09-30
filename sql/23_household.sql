-- =============================================================================
-- SYNAPTA · 23_household.sql
-- O núcleo familiar — versão OBJETIVA.
--
-- POR QUE ISSO EXISTE
--   "Posso parar de trabalhar aos 55?" não se responde olhando a carteira.
--   Depende de quantas pessoas dependem dessa renda, até quando, e do que
--   já está contratado (faculdade do filho em 2031, aposentadoria do cônjuge).
--   identity.scopes já resolve QUEM ACESSA. Falta QUEM DEPENDE.
--
-- O QUE FICOU DE FORA — DE PROPÓSITO
--   `persons` + `relationships` + `dependents` → colapsados em UMA tabela:
--       relação e dependência são atributos do membro, não entidades.
--   `residences`   → é patrimônio: estate.assets kind='imovel_*' (25).
--   `employments`  → é renda: budget.income_sources com employer_name (24).
--   `income_sources` → 24.
--   `obligations`  → budget.debts (dívida) ou budget.recurring_items (mensalidade).
--   Duas tabelas fazem o trabalho de oito. Cada entidade a mais é uma tela a
--   mais no onboarding — e o onboarding já está inflado (P04).
--
-- A REGRA DESTE ARQUIVO
--   Evento de vida no banco é o que ACONTECEU ou o que tem data CONTRATADA.
--   "Talvez eu me case" é context.assertions com modality='hipotese'. Aqui não entra.
--
-- Depende de: 00_core, 01_identity, 07_planning (goals), 22_assertions.
-- =============================================================================

BEGIN;

CREATE SCHEMA household;

CREATE TYPE household.relation AS ENUM (
  'titular', 'conjuge', 'filho', 'enteado', 'pai_mae', 'irmao',
  'outro_dependente', 'outro'
);

CREATE TYPE household.dependency AS ENUM ('nao', 'parcial', 'total');

CREATE TYPE household.member_origin AS ENUM (
  'usuario', 'onboarding', 'confirmacao_contexto', 'operador'
);

-- 'ocorrido' e 'programado' — só isso. Dúvida vive em context.assertions.
CREATE TYPE household.event_certainty AS ENUM ('ocorrido', 'programado');

CREATE TYPE household.life_event_kind AS ENUM (
  'casamento', 'uniao_estavel', 'divorcio', 'nascimento_filho',
  'entrada_faculdade', 'saida_de_casa', 'aposentadoria', 'mudanca_emprego',
  'perda_emprego', 'heranca', 'doenca_grave', 'obito',
  'compra_imovel', 'venda_imovel', 'mudanca_de_pais', 'outro'
);

-- -----------------------------------------------------------------------------
-- Membros — quem depende deste dinheiro, e até quando
-- -----------------------------------------------------------------------------
CREATE TABLE household.members (
  id                  uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id            uuid NOT NULL REFERENCES identity.scopes(id),
  user_id             uuid REFERENCES identity.users(id),  -- NULL: não usa o app
  relation            household.relation NOT NULL,
  display_name        text NOT NULL,

  -- LGPD/minimização: quando só a faixa etária importa, grave apenas o ano.
  birth_date          date,
  birth_year          smallint CHECK (birth_year BETWEEN 1900 AND 2100),

  dependency          household.dependency NOT NULL DEFAULT 'nao',
  dependency_until    date,                 -- fim previsto: maioridade, formatura
  contributes_income  boolean NOT NULL DEFAULT false,
  in_consolidation    boolean NOT NULL DEFAULT true,   -- entra nos totais do escopo?

  assertion_id        uuid REFERENCES context.assertions(id),
  origin              household.member_origin NOT NULL DEFAULT 'usuario',
  notes               text,

  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  ended_at            timestamptz,          -- saiu do núcleo (divórcio, independência)
  ended_reason        text,

  CONSTRAINT birth_once CHECK (birth_date IS NULL OR birth_year IS NULL),
  CONSTRAINT dependency_until_needs_dependency CHECK (
    dependency_until IS NULL OR dependency <> 'nao'
  ),
  CONSTRAINT titular_is_user CHECK (relation <> 'titular' OR user_id IS NOT NULL),
  CONSTRAINT ended_has_ts CHECK (ended_reason IS NULL OR ended_at IS NOT NULL)
);

-- Um titular por escopo. Dois titulares tornariam "renda da casa" ambíguo.
CREATE UNIQUE INDEX members_one_titular
  ON household.members (scope_id)
  WHERE relation = 'titular' AND ended_at IS NULL;

CREATE INDEX members_scope_idx ON household.members (scope_id) WHERE ended_at IS NULL;
CREATE INDEX members_dependents_idx ON household.members (scope_id, dependency_until)
  WHERE dependency <> 'nao' AND ended_at IS NULL;

CREATE TRIGGER members_touch BEFORE UPDATE ON household.members
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- C22: linha vinda de conversa só existe com fato CONFIRMADO por trás
CREATE TRIGGER members_assertion_gate BEFORE INSERT OR UPDATE ON household.members
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_confirmed('assertion_id');

COMMENT ON TABLE household.members IS
  'Colapsa persons + relationships + dependents. O que interessa ao planejamento '
  'não é a árvore genealógica: é quantas pessoas dependem desta renda e até quando.';

COMMENT ON COLUMN household.members.dependency_until IS
  'A data que transforma "tenho dois filhos" em número: é ela que define por '
  'quantos anos a despesa da casa não cai — insumo direto da pergunta '
  '"posso parar de trabalhar aos 55?".';

-- O titular tem que ser membro do escopo em identity.scope_members —
-- senão a família vira uma lista de nomes sem vínculo com quem acessa.
CREATE OR REPLACE FUNCTION household.assert_titular_is_scope_member() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.relation <> 'titular' OR NEW.ended_at IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM identity.scope_members sm
    WHERE sm.scope_id = NEW.scope_id AND sm.user_id = NEW.user_id
      AND sm.revoked_at IS NULL
  ) THEN
    RAISE EXCEPTION
      'Titular do núcleo (%) não é membro ativo do escopo %',
      NEW.user_id, NEW.scope_id USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER members_titular_gate BEFORE INSERT OR UPDATE ON household.members
  FOR EACH ROW EXECUTE FUNCTION household.assert_titular_is_scope_member();

-- -----------------------------------------------------------------------------
-- Eventos de vida — só o que aconteceu ou tem data contratada
-- -----------------------------------------------------------------------------
CREATE TABLE household.life_events (
  id                  uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id            uuid NOT NULL REFERENCES identity.scopes(id),
  member_id           uuid REFERENCES household.members(id),
  kind                household.life_event_kind NOT NULL,
  certainty           household.event_certainty NOT NULL,
  occurred_on         date,
  scheduled_on        date,
  financial_impact_brl core.money_brl,
  description         text,
  goal_id             uuid REFERENCES planning.goals(id),  -- virou objetivo?
  assertion_id        uuid REFERENCES context.assertions(id),
  origin              household.member_origin NOT NULL DEFAULT 'usuario',
  created_at          timestamptz NOT NULL DEFAULT now(),

  -- a regra do arquivo, como constraint
  CONSTRAINT event_date_matches_certainty CHECK (
    (certainty = 'ocorrido'   AND occurred_on  IS NOT NULL AND scheduled_on IS NULL)
    OR
    (certainty = 'programado' AND scheduled_on IS NOT NULL AND occurred_on  IS NULL)
  )
);
CREATE INDEX life_events_scope_idx ON household.life_events (scope_id, kind);
CREATE INDEX life_events_upcoming_idx ON household.life_events (scope_id, scheduled_on)
  WHERE certainty = 'programado';

CREATE TRIGGER life_events_assertion_gate BEFORE INSERT OR UPDATE ON household.life_events
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_confirmed('assertion_id');

-- Ponteiros cruzados no mesmo escopo (RLS não valida FK; papel service menos ainda)
CREATE OR REPLACE FUNCTION household.assert_event_refs_same_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_scope uuid;
BEGIN
  IF NEW.member_id IS NOT NULL THEN
    SELECT scope_id INTO v_scope FROM household.members WHERE id = NEW.member_id;
    IF v_scope IS DISTINCT FROM NEW.scope_id THEN
      RAISE EXCEPTION 'Membro % é de outro escopo', NEW.member_id USING ERRCODE = '23514';
    END IF;
  END IF;
  IF NEW.goal_id IS NOT NULL THEN
    SELECT scope_id INTO v_scope FROM planning.goals WHERE id = NEW.goal_id;
    IF v_scope IS DISTINCT FROM NEW.scope_id THEN
      RAISE EXCEPTION 'Objetivo % é de outro escopo', NEW.goal_id USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER life_events_scope_gate BEFORE INSERT OR UPDATE ON household.life_events
  FOR EACH ROW EXECUTE FUNCTION household.assert_event_refs_same_scope();

COMMENT ON CONSTRAINT event_date_matches_certainty ON household.life_events IS
  'Evento de vida é fato com data. "Talvez eu compre uma casa" não tem lugar aqui — '
  'é context.assertions modality=hipotese, com likelihood. Promover hipótese a '
  'evento exige confirmação do cliente (C22).';

-- -----------------------------------------------------------------------------
-- View — o resumo que Fundação, projeção e agentes leem
-- -----------------------------------------------------------------------------
CREATE VIEW household.v_summary WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT
  m.scope_id,
  count(*) FILTER (WHERE m.relation <> 'titular')                       AS members_count,
  count(*) FILTER (WHERE m.dependency <> 'nao')                         AS dependents_count,
  count(*) FILTER (WHERE m.dependency = 'total')                        AS full_dependents_count,
  count(*) FILTER (WHERE m.contributes_income)                          AS earners_count,
  min(m.dependency_until) FILTER (WHERE m.dependency <> 'nao')          AS first_dependency_ends_on,
  max(m.dependency_until) FILTER (WHERE m.dependency <> 'nao')          AS last_dependency_ends_on,
  min(coalesce(extract(year FROM age(m.birth_date))::int,
               extract(year FROM current_date)::int - m.birth_year))    AS youngest_age,
  bool_or(m.relation = 'conjuge')                                       AS has_partner
FROM household.members m
WHERE m.ended_at IS NULL AND m.in_consolidation
GROUP BY m.scope_id;

COMMENT ON VIEW household.v_summary IS
  'Substitui identity.user_profiles.dependents_count quando o núcleo existe: '
  'lá é um número digitado uma vez; aqui é derivado e datado. Em caso de '
  'divergência, esta view manda.';

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE household.members ENABLE ROW LEVEL SECURITY;
ALTER TABLE household.members FORCE  ROW LEVEL SECURITY;
CREATE POLICY members_isolation ON household.members FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE household.life_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE household.life_events FORCE  ROW LEVEL SECURITY;
CREATE POLICY life_events_isolation ON household.life_events FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

COMMIT;
