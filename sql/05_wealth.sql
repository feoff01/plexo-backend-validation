-- =============================================================================
-- SYNAPTA · 05_wealth.sql
-- Patrimônio: contas, Open Finance, SNAPSHOTS APPEND-ONLY, transações.
--
-- C7 — a regra não negociável deste arquivo:
--   wealth.holdings_snapshots NUNCA sofre UPDATE. Snapshot não capturado hoje
--   não existe depois; snapshot alterado depois destrói o point-in-time.
--   Correção de posição = linha nova em as_of_date novo. Trigger bloqueia.
--
-- Multi-moeda (decisão nº 5 do README): value_brl é CONGELADO no snapshot com
-- fx_rate ao lado. Converter na leitura seria flexível, mas quebraria
-- reprodutibilidade point-in-time. Escolhemos reprodutibilidade.
-- =============================================================================

BEGIN;

CREATE TYPE wealth.account_kind AS ENUM (
  'corretora', 'banco', 'previdencia', 'exterior', 'cripto_exchange', 'manual', 'outro'
);

CREATE TYPE wealth.holding_origin AS ENUM ('manual', 'upload', 'open_finance', 'b3_integracao');

CREATE TYPE wealth.connection_status AS ENUM (
  'pending_consent', 'active', 'expired', 'revoked', 'error'
);

CREATE TYPE wealth.transaction_kind AS ENUM (
  'compra', 'venda', 'aporte', 'resgate', 'dividendo', 'jcp', 'rendimento',
  'taxa', 'imposto', 'transferencia_entrada', 'transferencia_saida', 'ajuste'
);

-- -----------------------------------------------------------------------------
-- Conexões Open Finance — F4 é ATIVAR, não modelar (já nasce pronta)
-- -----------------------------------------------------------------------------
CREATE TABLE wealth.connections (
  id               uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id         uuid NOT NULL REFERENCES identity.scopes(id),
  user_id          uuid NOT NULL REFERENCES identity.users(id),
  provider         text NOT NULL,             -- 'pluggy', 'belvo', 'ofb_direto'
  institution_code text,
  institution_name text,
  status           wealth.connection_status NOT NULL DEFAULT 'pending_consent',
  consent_id       uuid REFERENCES identity.consents(id),   -- LGPD/OFB: máx. 12 meses
  consent_expires_at timestamptz,
  provider_item_id text,
  last_sync_at     timestamptz,
  last_sync_status text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  revoked_at       timestamptz
);
CREATE INDEX connections_scope_idx ON wealth.connections (scope_id) WHERE revoked_at IS NULL;
CREATE TRIGGER connections_touch BEFORE UPDATE ON wealth.connections
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- Execuções de sincronização — cada sync é rastreável
CREATE TABLE wealth.sync_runs (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  connection_id  uuid NOT NULL REFERENCES wealth.connections(id) ON DELETE CASCADE,
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz,
  status         text NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','succeeded','failed','partial')),
  accounts_seen  int,
  holdings_seen  int,
  error_detail   text
);
CREATE INDEX sync_runs_connection_idx ON wealth.sync_runs (connection_id, started_at DESC);

-- -----------------------------------------------------------------------------
-- Contas — a unidade de agregação do extrato
-- -----------------------------------------------------------------------------
CREATE TABLE wealth.accounts (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id       uuid NOT NULL REFERENCES identity.scopes(id),
  kind           wealth.account_kind NOT NULL,
  label          text NOT NULL,               -- 'XP · conta principal'
  institution_name text,
  connection_id  uuid REFERENCES wealth.connections(id),
  currency       core.currency NOT NULL DEFAULT 'BRL',
  is_active      boolean NOT NULL DEFAULT true,
  opened_at      date,
  closed_at      date,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX accounts_scope_idx ON wealth.accounts (scope_id) WHERE is_active;
CREATE TRIGGER accounts_touch BEFORE UPDATE ON wealth.accounts
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- Uploads de extrato/nota (origem 'upload' dos snapshots)
CREATE TABLE wealth.statement_uploads (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id     uuid NOT NULL REFERENCES identity.scopes(id),
  account_id   uuid REFERENCES wealth.accounts(id),
  uploaded_by  uuid NOT NULL REFERENCES identity.users(id),
  file_name    text NOT NULL,
  file_hash    core.hash_hex NOT NULL,
  storage_key  text NOT NULL,                -- S3
  parse_status text NOT NULL DEFAULT 'pending'
               CHECK (parse_status IN ('pending','parsed','failed','partial')),
  parsed_rows  int,
  uploaded_at  timestamptz NOT NULL DEFAULT now(),
  parsed_at    timestamptz
);
CREATE INDEX statement_uploads_scope_idx ON wealth.statement_uploads (scope_id, uploaded_at DESC);

-- -----------------------------------------------------------------------------
-- HOLDINGS SNAPSHOTS — o coração do patrimônio. APPEND-ONLY. Particionado.
-- (partições criadas em 14_rls_partitions)
-- -----------------------------------------------------------------------------
CREATE TABLE wealth.holdings_snapshots (
  id            uuid NOT NULL DEFAULT core.new_id(),
  scope_id      uuid NOT NULL,
  account_id    uuid NOT NULL,
  instrument_id uuid NOT NULL,
  as_of_date    date NOT NULL,
  quantity      core.quantity,
  unit_price    numeric(20,8),
  gross_value   numeric(18,2),               -- na moeda do instrumento
  currency      core.currency NOT NULL DEFAULT 'BRL',
  fx_rate       numeric(20,8),               -- congelado no snapshot (decisão nº 5)
  value_brl     core.money_brl NOT NULL,     -- congelado: reprodutibilidade point-in-time
  avg_cost      numeric(20,8),
  origin        wealth.holding_origin NOT NULL,
  sync_run_id   uuid,
  upload_id     uuid,
  ingested_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (as_of_date, id)
) PARTITION BY RANGE (as_of_date);
CREATE UNIQUE INDEX holdings_natural_uk
  ON wealth.holdings_snapshots (as_of_date, scope_id, account_id, instrument_id, origin);
CREATE INDEX holdings_scope_date_idx ON wealth.holdings_snapshots (scope_id, as_of_date DESC);
CREATE INDEX holdings_instrument_idx ON wealth.holdings_snapshots (instrument_id, as_of_date DESC);

-- C7: correção é linha nova em as_of_date novo. UPDATE/DELETE não existem.
CREATE TRIGGER holdings_append_only BEFORE UPDATE OR DELETE ON wealth.holdings_snapshots
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

COMMENT ON TABLE wealth.holdings_snapshots IS
  'C7/P08 — snapshot não capturado hoje não existe depois; snapshot alterado depois '
  'destrói o point-in-time que a CVM e o próprio Ledger exigem. Sem FK para market/identity '
  'de propósito: tabela particionada quente; integridade garantida na escrita pelo serviço.';

-- Rollup diário por escopo — a Barra de Rumo lê daqui a cada page load
CREATE TABLE wealth.portfolio_snapshots (
  scope_id        uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date      date NOT NULL,
  total_brl       core.money_brl NOT NULL,
  invested_brl    core.money_brl,
  cash_brl        core.money_brl,
  by_asset_class  jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"selic": 120000, ...}
  by_account      jsonb NOT NULL DEFAULT '{}'::jsonb,
  delta_1d_brl    core.money_brl,
  run_id          uuid REFERENCES engine.runs(id),
  computed_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_id, as_of_date)
);

COMMENT ON TABLE wealth.portfolio_snapshots IS
  'C7 — a Barra de Rumo mostra "Δ desde a última visita" a cada page load e não pode '
  'varrer partição de holdings. Rollup gravado pelo job diário junto com o snapshot.';

-- -----------------------------------------------------------------------------
-- Transações — extrato (necessário p/ custo médio, IR e findings de comportamento)
-- -----------------------------------------------------------------------------
CREATE TABLE wealth.transactions (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id      uuid NOT NULL REFERENCES identity.scopes(id),
  account_id    uuid NOT NULL REFERENCES wealth.accounts(id),
  instrument_id uuid REFERENCES market.instruments(id),
  kind          wealth.transaction_kind NOT NULL,
  trade_date    date NOT NULL,
  settle_date   date,
  quantity      core.quantity,
  unit_price    numeric(20,8),
  gross_brl     core.money_brl,
  fees_brl      core.money_brl NOT NULL DEFAULT 0,
  taxes_brl     core.money_brl NOT NULL DEFAULT 0,
  net_brl       core.money_brl NOT NULL,
  origin        wealth.holding_origin NOT NULL DEFAULT 'manual',
  external_id   text,                        -- id no provedor OFB — dedupe
  description   text,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX transactions_external_uk
  ON wealth.transactions (account_id, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX transactions_scope_date_idx ON wealth.transactions (scope_id, trade_date DESC);
CREATE INDEX transactions_instrument_idx ON wealth.transactions (instrument_id) WHERE instrument_id IS NOT NULL;

-- Saldos de conta (caixa em conta, não investido)
CREATE TABLE wealth.account_balances (
  account_id  uuid NOT NULL REFERENCES wealth.accounts(id) ON DELETE CASCADE,
  scope_id    uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date  date NOT NULL,
  balance     numeric(18,2) NOT NULL,
  currency    core.currency NOT NULL DEFAULT 'BRL',
  balance_brl core.money_brl NOT NULL,
  origin      wealth.holding_origin NOT NULL DEFAULT 'manual',
  ingested_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, as_of_date, origin)
);
CREATE TRIGGER account_balances_append_only BEFORE UPDATE OR DELETE ON wealth.account_balances
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

COMMIT;
