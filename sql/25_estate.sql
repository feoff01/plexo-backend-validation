-- =============================================================================
-- SYNAPTA · 25_estate.sql
-- Patrimônio ALÉM da carteira: imóvel, empresa, veículo, previdência fechada.
--
-- O PROBLEMA
--   wealth (05) modela o que passa por conta e instrumento. Mas a riqueza da
--   pessoa costuma ser:
--       R$   800 mil em investimentos   ← wealth sabe
--       R$ 1,8 milhão em imóvel          ← ninguém sabe
--       R$   400 mil em empresa          ← ninguém sabe
--       R$   100 mil em veículo          ← ninguém sabe
--       R$   500 mil em previdência      ← às vezes
--   Sem isso, "concentração" é uma métrica sobre 30% do patrimônio, e o
--   diagnóstico de um cliente com 70% do patrimônio em tijolo está errado.
--
-- AS DUAS ARMADILHAS, FECHADAS NO BANCO
--   1. PATRIMÔNIO BRUTO SEM PASSIVO É MENTIRA. Imóvel de R$ 1,8 mi com
--      R$ 900 mil de financiamento é R$ 900 mil. Ativo marcado como onerado
--      EXIGE a dívida vinculada (CHECK) — e a view desconta.
--   2. DUPLA CONTAGEM. Previdência que já aparece em wealth.accounts não pode
--      somar de novo aqui: `also_in_wealth` marca e a view exclui.
--
-- E A REGRA DE LEITURA
--   Patrimônio total ≠ capital investível. O Builder aloca sobre
--   `investivel_brl`; a casa da família não é uma classe de ativo.
--
-- Depende de: 00_core, 01_identity, 05_wealth, 08_budget (debts),
--             22_assertions, 23_household, 24_income.
-- =============================================================================

BEGIN;

CREATE SCHEMA estate;

CREATE TYPE estate.asset_kind AS ENUM (
  'imovel_residencial', 'imovel_comercial', 'terreno', 'imovel_rural',
  'veiculo', 'participacao_empresa', 'previdencia_fechada',
  'obra_arte_colecionavel', 'direito_a_receber', 'cripto_autocustodia',
  'equipamento_profissional', 'outro'
);

CREATE TYPE estate.liquidity_tier AS ENUM (
  'imediata',    -- D0/D+1
  'ate_30d',
  'ate_12m',
  'acima_12m',
  'iliquido'     -- participação em empresa fechada, obra de arte
);

CREATE TYPE estate.valuation_method AS ENUM (
  'declarado', 'avaliacao_profissional', 'indice_referencia',
  'custo_aquisicao', 'multiplo_receita', 'tabela_referencia', 'marcacao_mercado'
);

CREATE TYPE estate.asset_status AS ENUM ('ativo', 'vendido', 'baixado', 'em_inventario');

-- -----------------------------------------------------------------------------
-- Ativos não financeiros
-- -----------------------------------------------------------------------------
CREATE TABLE estate.assets (
  id                   uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id             uuid NOT NULL REFERENCES identity.scopes(id),
  owner_member_id      uuid REFERENCES household.members(id),
  kind                 estate.asset_kind NOT NULL,
  label                text NOT NULL,
  ownership_share      core.weight NOT NULL DEFAULT 1.0
                       CHECK (ownership_share > 0),
  liquidity            estate.liquidity_tier NOT NULL,

  acquired_on          date,
  acquisition_cost_brl core.money_brl CHECK (acquisition_cost_brl >= 0),

  -- armadilha 1: ônus exige o passivo do lado
  is_encumbered        boolean NOT NULL DEFAULT false,
  linked_debt_id       uuid REFERENCES budget.debts(id),

  -- coerência com a renda: aluguel declarado aqui aparece em budget também
  generates_income     boolean NOT NULL DEFAULT false,
  income_source_id     uuid REFERENCES budget.income_sources(id),

  is_primary_residence boolean NOT NULL DEFAULT false,
  -- armadilha 2: já contabilizado em wealth? então não soma de novo
  also_in_wealth       boolean NOT NULL DEFAULT false,
  wealth_account_id    uuid REFERENCES wealth.accounts(id),

  status               estate.asset_status NOT NULL DEFAULT 'ativo',
  disposed_on          date,
  disposal_amount_brl  core.money_brl,

  assertion_id         uuid REFERENCES context.assertions(id),
  origin               text NOT NULL DEFAULT 'usuario'
                       CHECK (origin IN ('usuario','onboarding','import',
                                         'confirmacao_contexto','operador')),
  notes                text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT encumbered_needs_debt CHECK (
    NOT is_encumbered OR linked_debt_id IS NOT NULL
  ),
  CONSTRAINT income_asset_needs_source CHECK (
    NOT generates_income OR income_source_id IS NOT NULL
  ),
  CONSTRAINT in_wealth_needs_account CHECK (
    NOT also_in_wealth OR wealth_account_id IS NOT NULL
  ),
  CONSTRAINT residence_is_property CHECK (
    NOT is_primary_residence OR kind IN ('imovel_residencial','imovel_rural')
  ),
  CONSTRAINT disposed_has_date CHECK (
    status <> 'vendido' OR disposed_on IS NOT NULL
  )
);
CREATE INDEX assets_scope_idx ON estate.assets (scope_id) WHERE status = 'ativo';
CREATE INDEX assets_kind_idx  ON estate.assets (scope_id, kind);
CREATE UNIQUE INDEX assets_one_primary_residence
  ON estate.assets (scope_id) WHERE is_primary_residence AND status = 'ativo';

CREATE TRIGGER assets_touch BEFORE UPDATE ON estate.assets
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER assets_assertion_gate BEFORE INSERT OR UPDATE ON estate.assets
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_confirmed('assertion_id');

COMMENT ON CONSTRAINT encumbered_needs_debt ON estate.assets IS
  'A conta que quase todo app erra: soma o valor do imóvel e ignora o saldo '
  'devedor. Marcou como onerado, aponta a dívida — a view desconta.';

COMMENT ON COLUMN estate.assets.also_in_wealth IS
  'Previdência PGBL/VGBL e cripto em exchange normalmente já vivem em '
  'wealth.accounts. Marcar aqui documenta a existência sem somar duas vezes.';

-- Ponteiros cruzados têm que ser do MESMO escopo (RLS não checa FK).
CREATE OR REPLACE FUNCTION estate.assert_asset_refs_same_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_scope uuid;
BEGIN
  IF NEW.owner_member_id IS NOT NULL THEN
    SELECT scope_id INTO v_scope FROM household.members WHERE id = NEW.owner_member_id;
    IF v_scope IS DISTINCT FROM NEW.scope_id THEN
      RAISE EXCEPTION 'Membro % é de outro escopo', NEW.owner_member_id USING ERRCODE = '23514';
    END IF;
  END IF;
  IF NEW.linked_debt_id IS NOT NULL THEN
    SELECT scope_id INTO v_scope FROM budget.debts WHERE id = NEW.linked_debt_id;
    IF v_scope IS DISTINCT FROM NEW.scope_id THEN
      RAISE EXCEPTION 'Dívida % é de outro escopo', NEW.linked_debt_id USING ERRCODE = '23514';
    END IF;
  END IF;
  IF NEW.income_source_id IS NOT NULL THEN
    SELECT scope_id INTO v_scope FROM budget.income_sources WHERE id = NEW.income_source_id;
    IF v_scope IS DISTINCT FROM NEW.scope_id THEN
      RAISE EXCEPTION 'Fonte de renda % é de outro escopo', NEW.income_source_id USING ERRCODE = '23514';
    END IF;
  END IF;
  IF NEW.wealth_account_id IS NOT NULL THEN
    SELECT scope_id INTO v_scope FROM wealth.accounts WHERE id = NEW.wealth_account_id;
    IF v_scope IS DISTINCT FROM NEW.scope_id THEN
      RAISE EXCEPTION 'Conta % é de outro escopo', NEW.wealth_account_id USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER assets_scope_gate BEFORE INSERT OR UPDATE ON estate.assets
  FOR EACH ROW EXECUTE FUNCTION estate.assert_asset_refs_same_scope();

-- -----------------------------------------------------------------------------
-- Avaliações — point-in-time, APPEND-ONLY (mesma regra do C7 de wealth)
-- -----------------------------------------------------------------------------
CREATE TABLE estate.valuations (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  asset_id     uuid NOT NULL REFERENCES estate.assets(id) ON DELETE CASCADE,
  scope_id     uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date   date NOT NULL,
  value_brl    core.money_brl NOT NULL CHECK (value_brl >= 0),
  method       estate.valuation_method NOT NULL,
  confidence   core.confidence NOT NULL DEFAULT 0.5,
  source_ref   jsonb NOT NULL DEFAULT '{}'::jsonb,
  assertion_id uuid REFERENCES context.assertions(id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (asset_id, as_of_date)
);
CREATE INDEX valuations_asset_idx ON estate.valuations (asset_id, as_of_date DESC);
CREATE INDEX valuations_scope_idx ON estate.valuations (scope_id, as_of_date DESC);

-- C7 estendido: reavaliar é linha nova em data nova.
CREATE TRIGGER valuations_append_only BEFORE UPDATE OR DELETE ON estate.valuations
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

CREATE TRIGGER valuations_assertion_gate BEFORE INSERT ON estate.valuations
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_confirmed('assertion_id');

COMMENT ON TABLE estate.valuations IS
  'O imóvel "valia R$ 1,8 mi" em que data, por qual método, com que confiança. '
  'Sem isso, o patrimônio do cliente muda de valor retroativamente e nenhum '
  'relatório antigo se reproduz.';

-- -----------------------------------------------------------------------------
-- Views
-- -----------------------------------------------------------------------------
CREATE VIEW estate.v_current_valuations WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT DISTINCT ON (v.asset_id)
       v.asset_id, v.scope_id, v.as_of_date, v.value_brl, v.method, v.confidence
FROM estate.valuations v
ORDER BY v.asset_id, v.as_of_date DESC;

-- Patrimônio consolidado. A coluna que importa para o Builder é investivel_brl.
CREATE VIEW estate.v_net_worth WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
WITH fin AS (
  SELECT DISTINCT ON (scope_id) scope_id, as_of_date, total_brl
  FROM wealth.portfolio_snapshots
  ORDER BY scope_id, as_of_date DESC
),
nao_fin AS (
  SELECT a.scope_id,
         (sum(cv.value_brl * a.ownership_share))::core.money_brl AS bruto_brl,
         (sum(cv.value_brl * a.ownership_share) FILTER (
           WHERE a.liquidity = 'iliquido'))::core.money_brl      AS iliquido_brl,
         (sum(cv.value_brl * a.ownership_share) FILTER (
           WHERE a.kind IN ('imovel_residencial','imovel_comercial',
                            'terreno','imovel_rural')))::core.money_brl AS imoveis_brl,
         count(*)                                               AS ativos_count
  FROM estate.assets a
  JOIN estate.v_current_valuations cv ON cv.asset_id = a.id
  WHERE a.status = 'ativo' AND NOT a.also_in_wealth
  GROUP BY a.scope_id
),
passivo AS (
  SELECT scope_id, sum(outstanding_brl)::core.money_brl AS passivo_brl
  FROM budget.debts
  WHERE settled_at IS NULL
  GROUP BY scope_id
)
SELECT s.id AS scope_id,
       coalesce(fin.total_brl, 0)::core.money_brl        AS investivel_brl,
       coalesce(nao_fin.bruto_brl, 0)::core.money_brl    AS nao_financeiro_brl,
       coalesce(nao_fin.imoveis_brl, 0)::core.money_brl  AS imoveis_brl,
       coalesce(nao_fin.iliquido_brl, 0)::core.money_brl AS iliquido_brl,
       coalesce(passivo.passivo_brl, 0)::core.money_brl  AS passivo_brl,
       (coalesce(fin.total_brl, 0)
        + coalesce(nao_fin.bruto_brl, 0)
        - coalesce(passivo.passivo_brl, 0))::core.money_brl AS patrimonio_liquido_brl,
       CASE WHEN coalesce(fin.total_brl, 0) + coalesce(nao_fin.bruto_brl, 0) > 0
            THEN round(coalesce(nao_fin.iliquido_brl, 0)
                       / (coalesce(fin.total_brl, 0) + coalesce(nao_fin.bruto_brl, 0)), 4)
       END                                               AS iliquido_share,
       fin.as_of_date                                    AS financeiro_as_of,
       coalesce(nao_fin.ativos_count, 0)                 AS ativos_nao_financeiros
FROM identity.scopes s
LEFT JOIN fin      ON fin.scope_id      = s.id
LEFT JOIN nao_fin  ON nao_fin.scope_id  = s.id
LEFT JOIN passivo  ON passivo.scope_id  = s.id;

COMMENT ON VIEW estate.v_net_worth IS
  'investivel_brl é o que o Builder aloca. patrimonio_liquido_brl é o que o '
  'cliente chama de "quanto eu tenho". São números diferentes e a confusão '
  'entre eles produz carteira errada — a view separa na origem.';

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE estate.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE estate.assets FORCE  ROW LEVEL SECURITY;
CREATE POLICY assets_isolation ON estate.assets FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE estate.valuations ENABLE ROW LEVEL SECURITY;
ALTER TABLE estate.valuations FORCE  ROW LEVEL SECURITY;
CREATE POLICY valuations_isolation ON estate.valuations FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

COMMIT;
