-- =============================================================================
-- PLEXO · 62_fundamentals_units.sql — unidade explícita para fundamentos [FQ5]
--
-- `market.fundamentals.value` nasceu genérico na F22. Isso é suficiente para preservar vintages,
-- mas NÃO é suficiente para valuation: sem unidade, 1000 pode ser BRL, milhares de BRL, ações
-- ou percentual. FQ5 fecha essa ambiguidade sem reescrever a migration histórica 61.
--
-- Linhas existentes recebem `raw`: continuam preservadas/replayáveis, porém tools de valuation
-- não as tratam como valor canônico até uma nova ingestão normalizada gravar unidade explícita.
-- =============================================================================

BEGIN;

ALTER TABLE market.fundamentals
  ADD COLUMN value_unit text NOT NULL DEFAULT 'raw'
    CHECK (value_unit IN ('raw','brl','shares','ratio','percent','brl_per_share')),
  ADD COLUMN currency core.currency;

-- A 0061 permitia `instrument_id`, mas a chave única ignorava essa coordenada. Isso tornava
-- impossível armazenar, no mesmo vintage, métricas por classe (ex.: shares_outstanding de ON e PN).
-- PostgreSQL 18 permite NULLS NOT DISTINCT: company-level (instrument_id NULL) continua único e
-- métricas class-specific passam a ser únicas por instrumento.
ALTER TABLE market.fundamentals
  DROP CONSTRAINT fundamentals_vintage_uk;

ALTER TABLE market.fundamentals
  ADD CONSTRAINT fundamentals_vintage_coordinate_uk
  UNIQUE NULLS NOT DISTINCT
    (company_cnpj, instrument_id, reference_date, document_type, scope,
     period_label, metric, availability_date);

ALTER TABLE market.fundamentals
  ADD CONSTRAINT fundamentals_currency_matches_unit CHECK (
    (value_unit IN ('brl','brl_per_share') AND currency IS NOT NULL)
    OR
    (value_unit NOT IN ('brl','brl_per_share') AND currency IS NULL)
  );

COMMENT ON COLUMN market.fundamentals.value_unit IS
  '[FQ5] Unidade canônica do valor. `raw` preserva linhas anteriores/ingestões ainda não normalizadas '
  'e é deliberadamente insuficiente para valuation monetário.';

COMMENT ON COLUMN market.fundamentals.currency IS
  '[FQ5] Moeda obrigatória quando value_unit é brl ou brl_per_share; NULL para shares/ratio/percent/raw.';

COMMIT;
