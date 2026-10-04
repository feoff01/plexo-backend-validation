-- =============================================================================
-- PLEXO · 35_market_expectations.sql — Expectativas de mercado (Focus/BCB) [F13b]
-- -----------------------------------------------------------------------------
-- O agente sabia o que a Selic É (série do SGS) e o que o Copom DISSE (camada documental, 34).
-- Faltava o que o mercado PROJETA — a terceira perna para explicar cenário sem opinar.
--
-- Fonte: Sistema de Expectativas de Mercado do Banco Central (pesquisa Focus), OData aberto em
-- olinda.bcb.gov.br, sem chave. Cada linha é a estatística de UMA data de coleta para UM horizonte:
-- mediana, média, desvio padrão, mínimo, máximo e quantos respondentes — nunca a projeção da Plexo.
--
-- Fica em `market` (não em `docs`) porque é SÉRIE NUMÉRICA, ao lado do SGS. Sem RLS: referência
-- global, como o resto de market (ver 31). Append-only: estatística publicada não se reescreve;
-- revisão do BCB entra como coleta nova.
-- =============================================================================
BEGIN;

CREATE TABLE market.market_expectations (
  id             uuid PRIMARY KEY DEFAULT core.new_id(),
  indicador      text NOT NULL,               -- 'Selic', 'IPCA', 'Câmbio', 'PIB Total'
  detalhe        text,                        -- IndicadorDetalhe (ex.: 'Exportações')
  data_coleta    date NOT NULL,               -- data da estatística (as_of que vai para o cliente)
  referencia     text NOT NULL,               -- horizonte projetado: '2026', '2027'…
  mediana        numeric(18,6),
  media          numeric(18,6),
  desvio_padrao  numeric(18,6),
  minimo         numeric(18,6),
  maximo         numeric(18,6),
  respondentes   smallint,
  ingestion_batch_id uuid REFERENCES market.ingestion_batches(id),
  created_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT expectations_estatistica_coerente CHECK (
    (minimo IS NULL OR maximo IS NULL OR minimo <= maximo)
    AND (desvio_padrao IS NULL OR desvio_padrao >= 0)
    AND (respondentes IS NULL OR respondentes >= 0)
  )
);

-- Chave natural: `detalhe` é nulo na maioria dos indicadores, então entra por COALESCE no índice.
CREATE UNIQUE INDEX expectations_natural_uk ON market.market_expectations
  (indicador, coalesce(detalhe, ''), data_coleta, referencia);
CREATE INDEX expectations_indicador_idx ON market.market_expectations
  (indicador, data_coleta DESC, referencia);

CREATE TRIGGER expectations_append_only BEFORE UPDATE OR DELETE ON market.market_expectations
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

COMMENT ON TABLE market.market_expectations IS
  '[F13b] Pesquisa Focus (BCB): o que o mercado projeta, por data de coleta e horizonte. Append-only.';
COMMENT ON COLUMN market.market_expectations.data_coleta IS
  '[F13b] Data da estatística no BCB — é ela que vira `as_of` na citação, nunca a data da ingestão.';

-- A 28 já concedeu DML por DEFAULT PRIVILEGES em market; o REVOKE derivado do catálogo, porém,
-- já rodou e não alcança tabela nova. Fecha-se à mão, como a 33 fez.
REVOKE UPDATE, DELETE ON market.market_expectations FROM plexo_app, plexo_service;

COMMIT;
