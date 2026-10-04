-- =============================================================================
-- SYNAPTA · 04_market.sql
-- Dados de mercado: instrumentos, preços D-1 (particionado), índices, FX,
-- e PROVENIÊNCIA — de onde veio cada número (§16.1.10 se estende aos insumos).
--
-- DECISÕES
--   · D-1 é contrato do produto: price_date é date, não timestamp.
--   · Nenhuma FK aponta PARA tabela particionada (prices) — proveniência via
--     engine.run_inputs (ref_kind='price_asof'), mesmo padrão do motor.
--   · is_in_universe: o universo analisável (cobertura §4.1) é atributo do
--     instrumento, lido por diagnostics.coverage_reports.
-- =============================================================================

BEGIN;

CREATE TYPE market.instrument_kind AS ENUM (
  'acao', 'fundo', 'etf', 'fii', 'tesouro', 'cdb', 'lci_lca', 'cri_cra',
  'debenture', 'bdr', 'previdencia', 'coe', 'cripto', 'poupanca', 'conta', 'outro'
);

CREATE TYPE market.price_kind AS ENUM ('close', 'quota', 'unit_price', 'yield', 'index_level');

-- -----------------------------------------------------------------------------
-- Fontes de dados e lotes de ingestão — a proveniência dos insumos
-- -----------------------------------------------------------------------------
CREATE TABLE market.data_sources (
  code          core.slug PRIMARY KEY,      -- 'b3', 'cvm_fundos', 'bacen_sgs', 'anbima'
  display_name  text NOT NULL,
  cadence       text NOT NULL CHECK (cadence IN ('diaria','semanal','mensal','eventual')),
  base_url      text,
  license_note  text,
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE market.ingestion_batches (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  source_code   core.slug NOT NULL REFERENCES market.data_sources(code),
  dataset       text NOT NULL,              -- 'cotacoes', 'informes_fundos', 'sgs_selic'
  reference_date date,
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  status        text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','succeeded','failed','partial')),
  rows_ingested int,
  file_hash     core.hash_hex,              -- hash do arquivo cru — reproduzibilidade
  storage_key   text,                       -- S3 do arquivo cru
  error_detail  text
);
CREATE INDEX ingestion_batches_source_idx ON market.ingestion_batches (source_code, reference_date DESC);

-- -----------------------------------------------------------------------------
-- Classes de ativo — vocabulário do produto (Builder, alocações, score)
-- -----------------------------------------------------------------------------
CREATE TABLE market.asset_classes (
  code          core.slug PRIMARY KEY,      -- 'selic','ipca','prefixado','acoes_br',...
  display_name  text NOT NULL,
  group_name    text NOT NULL,              -- 'renda_fixa','renda_variavel','alternativos','caixa'
  sort_order    smallint NOT NULL DEFAULT 0,
  is_active     boolean NOT NULL DEFAULT true
);

-- -----------------------------------------------------------------------------
-- Emissores — parent_issuer_id consolida conglomerado (concentração cruzada)
-- -----------------------------------------------------------------------------
CREATE TABLE market.issuers (
  id               uuid PRIMARY KEY DEFAULT core.new_id(),
  name             text NOT NULL,
  cnpj             char(14),
  kind             text CHECK (kind IN ('banco','gestora','empresa','governo','seguradora','outro')),
  parent_issuer_id uuid REFERENCES market.issuers(id),
  fgc_covered      boolean NOT NULL DEFAULT false,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (parent_issuer_id IS NULL OR parent_issuer_id <> id)
);
CREATE UNIQUE INDEX issuers_cnpj_uk ON market.issuers (cnpj) WHERE cnpj IS NOT NULL;

COMMENT ON COLUMN market.issuers.parent_issuer_id IS
  'Consolidação de conglomerado: CDB do Banco X + LCI da financeira do Banco X = mesmo '
  'risco de crédito. É o que faz diagnostics.v_issuer_concentration funcionar de verdade.';

-- -----------------------------------------------------------------------------
-- Instrumentos
-- -----------------------------------------------------------------------------
CREATE TABLE market.instruments (
  id               uuid PRIMARY KEY DEFAULT core.new_id(),
  kind             market.instrument_kind NOT NULL,
  name             text NOT NULL,
  ticker           text,                    -- PETR4, KNRI11...
  isin             char(12),
  cnpj_fundo       char(14),
  issuer_id        uuid REFERENCES market.issuers(id),
  asset_class_code core.slug REFERENCES market.asset_classes(code),
  currency         core.currency NOT NULL DEFAULT 'BRL',
  is_in_universe   boolean NOT NULL DEFAULT false,   -- cobertura de análise (§4.1)
  liquidity_days   smallint,                          -- D+0, D+1, D+30...
  maturity_date    date,
  indexer          text CHECK (indexer IN ('cdi','selic','ipca','prefixado','cambio','outro')),
  metadata         jsonb NOT NULL DEFAULT '{}'::jsonb,  -- fatos do screening (§4.7)
  source_code      core.slug REFERENCES market.data_sources(code),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX instruments_ticker_uk ON market.instruments (ticker) WHERE ticker IS NOT NULL;
CREATE UNIQUE INDEX instruments_isin_uk   ON market.instruments (isin)   WHERE isin IS NOT NULL;
CREATE INDEX instruments_class_idx  ON market.instruments (asset_class_code);
CREATE INDEX instruments_issuer_idx ON market.instruments (issuer_id);
CREATE INDEX instruments_universe_idx ON market.instruments (kind) WHERE is_in_universe;
CREATE TRIGGER instruments_touch BEFORE UPDATE ON market.instruments
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- Apelidos/códigos alternativos (o extrato chama de um jeito, a B3 de outro)
CREATE TABLE market.instrument_aliases (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  instrument_id uuid NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
  alias_kind    text NOT NULL CHECK (alias_kind IN ('ticker_antigo','nome_corretora','codigo_b3','codigo_cvm','outro')),
  alias_value   text NOT NULL,
  source_code   core.slug REFERENCES market.data_sources(code),
  UNIQUE (alias_kind, alias_value)
);

-- Fatos de fundos (taxa, benchmark, classe CVM) — insumo do Raio-X de custo
CREATE TABLE market.fund_facts (
  instrument_id      uuid PRIMARY KEY REFERENCES market.instruments(id) ON DELETE CASCADE,
  cvm_class          text,
  benchmark          text,
  management_fee     core.rate_annual,      -- 0.02 = 2% a.a.
  performance_fee    numeric(6,4),
  admin_fee          core.rate_annual,
  net_assets_brl     core.money_brl,
  quota_holders      int,
  first_quota_date   date,
  is_closed          boolean NOT NULL DEFAULT false,
  come_cotas         boolean,
  data_as_of         date,
  source_code        core.slug REFERENCES market.data_sources(code),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER fund_facts_touch BEFORE UPDATE ON market.fund_facts
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- -----------------------------------------------------------------------------
-- Preços D-1 — particionado por mês (partições criadas em 14_rls_partitions)
-- -----------------------------------------------------------------------------
CREATE TABLE market.prices (
  price_date    date NOT NULL,
  instrument_id uuid NOT NULL,              -- sem FK: tabela quente, integridade via ingestão
  kind          market.price_kind NOT NULL DEFAULT 'close',
  value         numeric(20,8) NOT NULL,
  currency      core.currency NOT NULL DEFAULT 'BRL',
  source_code   core.slug NOT NULL,
  ingestion_batch_id uuid,
  PRIMARY KEY (price_date, instrument_id, kind, source_code)
) PARTITION BY RANGE (price_date);
CREATE INDEX prices_instrument_idx ON market.prices (instrument_id, price_date DESC);

COMMENT ON TABLE market.prices IS
  'D-1 é contrato do produto (§4.1): "dados de fechamento, atualizados 1x/dia". '
  'Preço intradiário não existe aqui de propósito.';

-- -----------------------------------------------------------------------------
-- Índices/benchmarks (CDI, IPCA, IBOV, IMA-B) e câmbio
-- -----------------------------------------------------------------------------
CREATE TABLE market.index_definitions (
  code          core.slug PRIMARY KEY,      -- 'cdi','ipca','ibov','ima_b','selic_meta'
  display_name  text NOT NULL,
  unit          text NOT NULL CHECK (unit IN ('taxa_aa','taxa_am','pontos','percentual')),
  source_code   core.slug REFERENCES market.data_sources(code),
  sgs_series_id int                          -- código da série no SGS/Bacen
);

CREATE TABLE market.index_values (
  index_code   core.slug NOT NULL REFERENCES market.index_definitions(code),
  value_date   date NOT NULL,
  value        numeric(20,8) NOT NULL,
  ingestion_batch_id uuid REFERENCES market.ingestion_batches(id),
  PRIMARY KEY (index_code, value_date)
);

CREATE TABLE market.fx_rates (
  base_currency  core.currency NOT NULL,
  quote_currency core.currency NOT NULL,
  rate_date      date NOT NULL,
  rate           numeric(20,8) NOT NULL CHECK (rate > 0),
  source_code    core.slug REFERENCES market.data_sources(code),
  PRIMARY KEY (base_currency, quote_currency, rate_date)
);

-- Proventos e eventos corporativos — necessários para custo médio e IR (V1: mínimo)
CREATE TABLE market.corporate_actions (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  instrument_id uuid NOT NULL REFERENCES market.instruments(id),
  kind          text NOT NULL CHECK (kind IN
                  ('dividendo','jcp','rendimento','desdobramento','grupamento','bonificacao','amortizacao')),
  ex_date       date NOT NULL,
  payment_date  date,
  factor        numeric(16,8),              -- desdobramento/grupamento
  amount_per_unit numeric(20,8),            -- proventos
  source_code   core.slug REFERENCES market.data_sources(code),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX corporate_actions_instr_idx ON market.corporate_actions (instrument_id, ex_date DESC);

-- -----------------------------------------------------------------------------
-- SEEDS — vocabulário mínimo para o produto funcionar (ampliar é INSERT)
-- -----------------------------------------------------------------------------
INSERT INTO market.data_sources (code, display_name, cadence) VALUES
  ('manual',     'Entrada manual do usuário', 'eventual'),
  ('b3',         'B3',                        'diaria'),
  ('cvm_fundos', 'CVM · Informes de fundos',  'diaria'),
  ('bacen_sgs',  'Banco Central · SGS',       'diaria'),
  ('anbima',     'ANBIMA',                    'diaria');

INSERT INTO market.asset_classes (code, display_name, group_name, sort_order) VALUES
  ('caixa',        'Caixa e liquidez',        'caixa',          0),
  ('selic',        'Pós-fixado Selic/CDI',    'renda_fixa',     1),
  ('prefixado',    'Prefixado',               'renda_fixa',     2),
  ('ipca',         'Inflação (IPCA+)',        'renda_fixa',     3),
  ('credito_privado','Crédito privado',       'renda_fixa',     4),
  ('acoes_br',     'Ações Brasil',            'renda_variavel', 5),
  ('acoes_int',    'Ações internacionais',    'renda_variavel', 6),
  ('fii',          'Fundos imobiliários',     'renda_variavel', 7),
  ('multimercado', 'Multimercado',            'alternativos',   8),
  ('cripto',       'Criptoativos',            'alternativos',   9),
  ('previdencia',  'Previdência',             'renda_fixa',    10),
  ('outros',       'Outros',                  'alternativos',  99);

INSERT INTO market.index_definitions (code, display_name, unit, source_code, sgs_series_id) VALUES
  ('cdi',        'CDI',            'taxa_aa',    'bacen_sgs', 4389),
  ('selic_meta', 'Selic meta',     'taxa_aa',    'bacen_sgs', 432),
  ('ipca',       'IPCA (mensal)',  'taxa_am',    'bacen_sgs', 433),
  ('ibov',       'Ibovespa',       'pontos',     'b3',        NULL),
  ('ima_b',      'IMA-B',          'pontos',     'anbima',    NULL);

COMMIT;
