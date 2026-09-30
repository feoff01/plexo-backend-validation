-- =============================================================================
-- SYNAPTA · 08_budget.sql
-- Orçamento: fluxos de caixa, taxa de poupança, dívidas, reserva.
--
-- NOTA DE ESCOPO (decisão nº 4 do README): §4.5 é decisão de ago/2026 e o
-- onboarding já está inflado (P04). Este arquivo está completo, mas se o
-- Orçamento não entrar no 1º MVP, ele fica na gaveta sem afetar nada —
-- nenhum outro schema depende dele em FK. A Fundação (06) lê renda/despesa
-- de identity.user_profiles e dívidas/reserva daqui QUANDO existirem.
-- =============================================================================

BEGIN;

CREATE TYPE budget.cash_flow_kind AS ENUM ('entrada', 'saida');

CREATE TYPE budget.debt_kind AS ENUM (
  'cartao_rotativo', 'cheque_especial', 'emprestimo_pessoal', 'consignado',
  'financiamento_imovel', 'financiamento_veiculo', 'fies', 'outro'
);

-- -----------------------------------------------------------------------------
-- Categorias — taxonomia própria + mapeamento de categorias do Open Finance
-- -----------------------------------------------------------------------------
CREATE TABLE budget.categories (
  code          core.slug PRIMARY KEY,
  display_name  text NOT NULL,
  flow          budget.cash_flow_kind NOT NULL,
  parent_code   core.slug REFERENCES budget.categories(code),
  is_essential  boolean NOT NULL DEFAULT false,   -- essencial vs. estilo de vida
  sort_order    smallint NOT NULL DEFAULT 0,
  is_active     boolean NOT NULL DEFAULT true
);

-- -----------------------------------------------------------------------------
-- Eventos de caixa — entrada manual ou derivada do Open Finance
-- -----------------------------------------------------------------------------
CREATE TABLE budget.cash_events (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id      uuid NOT NULL REFERENCES identity.scopes(id),
  flow          budget.cash_flow_kind NOT NULL,
  category_code core.slug REFERENCES budget.categories(code),
  amount_brl    core.money_brl NOT NULL CHECK (amount_brl > 0),
  occurred_on   date NOT NULL,
  description   text,
  is_recurring  boolean NOT NULL DEFAULT false,
  recurring_item_id uuid,                     -- FK adicionada abaixo
  origin        text NOT NULL DEFAULT 'manual'
                CHECK (origin IN ('manual','open_finance','import','estimado')),
  account_id    uuid REFERENCES wealth.accounts(id),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cash_events_scope_month_idx ON budget.cash_events (scope_id, occurred_on DESC);

-- Itens recorrentes (salário, aluguel, assinatura) — geram eventos projetados
CREATE TABLE budget.recurring_items (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id      uuid NOT NULL REFERENCES identity.scopes(id),
  flow          budget.cash_flow_kind NOT NULL,
  category_code core.slug REFERENCES budget.categories(code),
  description   text NOT NULL,
  amount_brl    core.money_brl NOT NULL,
  day_of_month  smallint CHECK (day_of_month BETWEEN 1 AND 31),
  starts_on     date NOT NULL,
  ends_on       date,
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX recurring_items_scope_idx ON budget.recurring_items (scope_id) WHERE is_active;

ALTER TABLE budget.cash_events
  ADD CONSTRAINT cash_events_recurring_fk
  FOREIGN KEY (recurring_item_id) REFERENCES budget.recurring_items(id);

-- -----------------------------------------------------------------------------
-- Resumo mensal — a taxa de poupança que alimenta Fundação e projeções
-- -----------------------------------------------------------------------------
CREATE TABLE budget.monthly_summaries (
  scope_id       uuid NOT NULL REFERENCES identity.scopes(id),
  month          date NOT NULL,               -- dia 1 do mês
  income_brl     core.money_brl NOT NULL DEFAULT 0,
  expense_brl    core.money_brl NOT NULL DEFAULT 0,
  essential_expense_brl core.money_brl,
  surplus_brl    core.money_brl GENERATED ALWAYS AS (income_brl - expense_brl) STORED,
  savings_rate   numeric(6,4),                -- surplus / income; NULL quando income = 0
  run_id         uuid REFERENCES engine.runs(id),
  computed_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_id, month),
  CONSTRAINT month_is_month_start CHECK (month = date_trunc('month', month)::date)
);

-- -----------------------------------------------------------------------------
-- Dívidas — insumo direto do semáforo de Fundação (dívida cara > CDI+X)
-- -----------------------------------------------------------------------------
CREATE TABLE budget.debts (
  id                uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id          uuid NOT NULL REFERENCES identity.scopes(id),
  kind              budget.debt_kind NOT NULL,
  description       text,
  outstanding_brl   core.money_brl NOT NULL,
  annual_rate       core.rate_annual,            -- 0.14 = 14% a.a.
  monthly_payment_brl core.money_brl,
  remaining_installments smallint,
  is_expensive      boolean,                     -- marcado pelo motor vs. FOUNDATION_THRESHOLDS
  opened_on         date,
  settled_at        timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX debts_scope_idx ON budget.debts (scope_id) WHERE settled_at IS NULL;
CREATE TRIGGER debts_touch BEFORE UPDATE ON budget.debts
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- -----------------------------------------------------------------------------
-- Reserva de emergência — configuração por escopo; o status vive na Fundação
-- -----------------------------------------------------------------------------
CREATE TABLE budget.reserve_settings (
  scope_id           uuid PRIMARY KEY REFERENCES identity.scopes(id),
  target_months      numeric(4,1) NOT NULL DEFAULT 6.0,
  monthly_cost_override_brl core.money_brl,     -- se o usuário quiser fixar o custo mensal
  reserve_account_ids uuid[] NOT NULL DEFAULT '{}',  -- contas marcadas como reserva
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER reserve_settings_touch BEFORE UPDATE ON budget.reserve_settings
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- -----------------------------------------------------------------------------
-- SEEDS — categorias mínimas
-- -----------------------------------------------------------------------------
INSERT INTO budget.categories (code, display_name, flow, is_essential, sort_order) VALUES
  ('salario',        'Salário',              'entrada', false, 0),
  ('renda_extra',    'Renda extra',          'entrada', false, 1),
  ('rendimentos',    'Rendimentos',          'entrada', false, 2),
  ('moradia',        'Moradia',              'saida',   true,  10),
  ('alimentacao',    'Alimentação',          'saida',   true,  11),
  ('transporte',     'Transporte',           'saida',   true,  12),
  ('saude',          'Saúde',                'saida',   true,  13),
  ('educacao',       'Educação',             'saida',   true,  14),
  ('lazer',          'Lazer',                'saida',   false, 20),
  ('assinaturas',    'Assinaturas',          'saida',   false, 21),
  ('dividas',        'Dívidas',              'saida',   true,  22),
  ('outros_gastos',  'Outros',               'saida',   false, 99);

COMMIT;
