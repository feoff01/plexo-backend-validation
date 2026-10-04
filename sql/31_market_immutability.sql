-- =============================================================================
-- SYNAPTA · 31_market_immutability.sql — [5ª onda] Séries de mercado que não mudam por baixo do Analista
-- -----------------------------------------------------------------------------
-- market.* (04) modelou preços D-1, índices, câmbio e proventos com proveniência por lote, mas nada
-- impedia UPDATE/DELETE: um preço "corrigido" em silêncio quebra a reprodutibilidade que
-- engine.runs.input_hash e tools.tool_executions.input_hash prometem. Com o Analista (F5) lendo
-- essas séries para fundamentar análises, o BANCO passa a impor:
--   (a) append-only em prices, index_values, fx_rates, corporate_actions (trigger incondicional
--       core.forbid_update_delete + REVOKE derivado, padrão da 28) — correção é linha nova
--       (outro lote/fonte) ou evento corporativo de ajuste, nunca reescrita;
--   (b) validade estrutural: fechamento > 0 (yield pode ser negativo), nenhuma data futura
--       (trigger, não CHECK: current_date não é imutável);
--   (c) proveniência verificável: prices.ingestion_batch_id passa a ser FK (FK SAINDO da
--       particionada é permitida — a decisão da 04 proíbe FK apontando PARA ela);
--   (d) lote de ingestão: succeeded exige rows_ingested; finalizado exige finished_at e é
--       imutável (padrão tools.freeze_finished_execution); o mesmo arquivo (source, dataset,
--       file_hash) nunca produz dois lotes succeeded — a idempotência da ingestão é do banco;
--   (e) cobertura de partições: 10 anos retroativos em market.prices, ANTES de qualquer backfill
--       (partição nova só nasce se a DEFAULT não tiver linha conflitante; o serviço não tem CREATE).
-- Sem RLS: market.* é referência global (sem scope_id/user_id).
-- =============================================================================
BEGIN;

-- -----------------------------------------------------------------------------
-- (e) Partições retroativas primeiro — a DEFAULT ainda está vazia e o REVOKE derivado abaixo
--     precisa enxergar as partições já criadas (trigger clonado).
-- -----------------------------------------------------------------------------
SELECT core.ensure_month_partitions('market.prices',
         (date_trunc('month', current_date) - interval '10 years')::date, 120);

-- -----------------------------------------------------------------------------
-- (b) Validade estrutural
-- -----------------------------------------------------------------------------
ALTER TABLE market.prices
  ADD CONSTRAINT price_close_positive CHECK (kind = 'yield' OR value > 0);

ALTER TABLE market.corporate_actions
  ADD CONSTRAINT corporate_action_factor_positive CHECK (factor IS NULL OR factor > 0),
  ADD CONSTRAINT corporate_action_amount_non_negative CHECK (amount_per_unit IS NULL OR amount_per_unit >= 0);

-- Série de mercado nunca tem data no futuro (D-1 é o contrato do produto). A coluna de data vem
-- por argumento do trigger para servir a prices (price_date) e index_values (value_date).
CREATE OR REPLACE FUNCTION market.assert_not_future() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_data date;
BEGIN
  EXECUTE format('SELECT ($1).%I', TG_ARGV[0]) USING NEW INTO v_data;
  IF v_data > current_date THEN
    RAISE EXCEPTION '%.%: % = % está no futuro — série de mercado é D-1',
      TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_ARGV[0], v_data USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER prices_not_future BEFORE INSERT ON market.prices
  FOR EACH ROW EXECUTE FUNCTION market.assert_not_future('price_date');
CREATE TRIGGER index_values_not_future BEFORE INSERT ON market.index_values
  FOR EACH ROW EXECUTE FUNCTION market.assert_not_future('value_date');

-- -----------------------------------------------------------------------------
-- (c) Proveniência verificável
-- -----------------------------------------------------------------------------
ALTER TABLE market.prices
  ADD CONSTRAINT prices_batch_fk FOREIGN KEY (ingestion_batch_id) REFERENCES market.ingestion_batches(id);

-- -----------------------------------------------------------------------------
-- (d) Lotes de ingestão
-- -----------------------------------------------------------------------------
ALTER TABLE market.ingestion_batches
  ADD CONSTRAINT batch_finished_has_timestamp CHECK (status = 'running' OR finished_at IS NOT NULL),
  ADD CONSTRAINT batch_succeeded_has_rows CHECK (status <> 'succeeded' OR rows_ingested IS NOT NULL);

CREATE UNIQUE INDEX ingestion_batches_file_uk
  ON market.ingestion_batches (source_code, dataset, file_hash)
  WHERE status = 'succeeded' AND file_hash IS NOT NULL;

CREATE OR REPLACE FUNCTION market.freeze_finished_batch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'market.ingestion_batches é append-only — lote é trilha de proveniência'
      USING ERRCODE = '42501';
  END IF;
  IF OLD.status IN ('succeeded','failed','partial') THEN
    RAISE EXCEPTION 'market.ingestion_batches % já finalizado é imutável', OLD.id
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER ingestion_batches_freeze BEFORE UPDATE OR DELETE ON market.ingestion_batches
  FOR EACH ROW EXECUTE FUNCTION market.freeze_finished_batch();

-- -----------------------------------------------------------------------------
-- (a) Append-only nas séries — trigger no pai particionado é clonado nas partições existentes e
--     futuras; o REVOKE derivado abaixo fecha também o acesso direto às partições.
-- -----------------------------------------------------------------------------
CREATE TRIGGER prices_append_only BEFORE UPDATE OR DELETE ON market.prices
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
CREATE TRIGGER index_values_append_only BEFORE UPDATE OR DELETE ON market.index_values
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
CREATE TRIGGER fx_rates_append_only BEFORE UPDATE OR DELETE ON market.fx_rates
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
CREATE TRIGGER corporate_actions_append_only BEFORE UPDATE OR DELETE ON market.corporate_actions
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- Mesmo mecanismo da 28, restrito ao schema market: onde o trigger é incondicional, nem o
-- serviço tem UPDATE/DELETE (inclui partições, cujo trigger clonado aparece em pg_trigger).
DO $$
DECLARE t record;
BEGIN
  FOR t IN
    SELECT n.nspname, c.relname,
           bool_or((tg.tgtype & 16) > 0) AS upd,
           bool_or((tg.tgtype &  8) > 0) AS del
    FROM pg_trigger tg
    JOIN pg_class     c ON c.oid = tg.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE tg.tgfoid = 'core.forbid_update_delete'::regproc
      AND NOT tg.tgisinternal
      AND tg.tgqual IS NULL
      AND n.nspname = 'market'
    GROUP BY 1, 2
  LOOP
    IF t.upd THEN EXECUTE format('REVOKE UPDATE ON %I.%I FROM plexo_app, plexo_service', t.nspname, t.relname); END IF;
    IF t.del THEN EXECUTE format('REVOKE DELETE ON %I.%I FROM plexo_app, plexo_service', t.nspname, t.relname); END IF;
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- Fontes oficiais usadas pela ingestão (F5): dados públicos, uso conforme os termos do provedor.
-- -----------------------------------------------------------------------------
UPDATE market.data_sources
   SET base_url = 'https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados',
       license_note = 'Séries do SGS/Banco Central — dados públicos; uso conforme termos do provedor.'
 WHERE code = 'bacen_sgs';
UPDATE market.data_sources
   SET base_url = 'https://bvmf.bmfbovespa.com.br/InstDados/SerHist/',
       license_note = 'COTAHIST (série histórica de cotações da B3) — arquivo público; uso conforme termos da B3, sem redistribuição.'
 WHERE code = 'b3';

COMMENT ON FUNCTION market.assert_not_future() IS
  '[5ª onda] Série de mercado nunca tem data futura (D-1 é o contrato); coluna de data por TG_ARGV[0].';
COMMENT ON FUNCTION market.freeze_finished_batch() IS
  '[5ª onda] Lote de ingestão finalizado (succeeded/failed/partial) é imutável; DELETE nunca.';
COMMENT ON INDEX market.ingestion_batches_file_uk IS
  '[5ª onda] Idempotência da ingestão: um arquivo (source, dataset, file_hash) só vira UM lote succeeded.';
COMMENT ON TRIGGER prices_append_only ON market.prices IS
  '[5ª onda] Preço é append-only: correção = linha nova em outro lote/fonte, nunca UPDATE.';

COMMIT;
