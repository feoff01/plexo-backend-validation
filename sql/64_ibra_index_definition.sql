-- =============================================================================
-- PLEXO · 64_ibra_index_definition.sql — registra IBrA para universo auditável [FQ5.6]
--
-- Não carrega carteira nem altera instrumentos. O snapshot oficial entra por ingestão append-only
-- em market.index_weights; is_in_universe é projetado operacionalmente depois de um lote GREEN.
-- =============================================================================
BEGIN;

INSERT INTO market.index_definitions (code, display_name, unit, source_code, sgs_series_id)
VALUES ('ibra', 'Índice Brasil Amplo B3', 'pontos', 'b3', NULL)
ON CONFLICT (code) DO NOTHING;

COMMIT;
