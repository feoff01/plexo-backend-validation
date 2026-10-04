-- =============================================================================
-- PLEXO · 36_focus_source.sql — Fonte de ingestão do Focus [F13b]
-- -----------------------------------------------------------------------------
-- Correção de omissão da 35: a tabela `market.market_expectations` nasceu apontando para
-- `market.ingestion_batches`, cujo `source_code` referencia `market.data_sources` — mas a linha da
-- fonte não foi inserida. Sem ela, `mercado ingerir --fonte focus` quebra na FK, e um banco
-- reconstruído do zero quebraria igual.
--
-- A 35 já está aplicada e migration aplicada não se edita (é a mesma razão do ledger): a correção
-- vem em arquivo novo. A 34 fez certo para o Copom — este arquivo alinha o Focus.
-- =============================================================================
BEGIN;

INSERT INTO market.data_sources (code, display_name, cadence, base_url, license_note)
VALUES ('bacen_focus', 'Banco Central · Focus (expectativas de mercado)', 'semanal',
        'https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata',
        'Sistema de Expectativas de Mercado do BCB — dados abertos; uso conforme termos do provedor, '
        'com atribuição à fonte.')
ON CONFLICT (code) DO NOTHING;

COMMIT;
