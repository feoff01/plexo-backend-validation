-- =============================================================================
-- PLEXO · 63_economatica_source.sql — fonte auxiliar Economatica [FQ5.6A]
--
-- Apenas registra provenance. Nenhum raw vendor data é seedado pelo repositório.
-- Economatica não substitui B3/CVM e não recebe prioridade implícita.
-- =============================================================================
BEGIN;

INSERT INTO market.data_sources (code, display_name, cadence, base_url, license_note)
VALUES (
  'economatica',
  'Economatica — export fornecido pelo usuário',
  'eventual',
  NULL,
  'Export fornecido pelo usuário. Uso e redistribuição sujeitos à licença Economatica do cliente; arquivos brutos não são versionados pelo Plexo.'
)
ON CONFLICT (code) DO NOTHING;

COMMIT;
