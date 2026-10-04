-- =============================================================================
-- SYNAPTA · 11_ledger.sql
-- Ledger de Valor Realizado — a prova de que a Synapta se paga.
--
-- AS TRÊS REGRAS INVIOLÁVEIS DESTE ARQUIVO
--   T9  · §16.1.6: RETORNO DE MERCADO NÃO ENTRA. O mecanismo é o mais forte
--         possível: o valor 'retorno_mercado' NÃO EXISTE no enum. Não é
--         validação — é impossibilidade de representação.
--   T10 · §4.11: append-only. Errou? ESTORNO (linha nova negativa), não UPDATE.
--         Trigger + REVOKE: nem o owner escapa sem esforço deliberado.
--   T11 · §13.6: valor sem metodologia gravada não entra. O CHECK exige a
--         chave 'formula' no jsonb — quem não sabe explicar o número, não grava.
-- =============================================================================

BEGIN;

-- 'retorno_mercado' está deliberadamente AUSENTE. §16.1.6: "o Ledger mede o que
-- a Synapta FEZ pelo cliente, não o que o mercado fez pela carteira".
CREATE TYPE ledger.value_category AS ENUM (
  'custo_evitado',          -- migração de fundo caro, corretagem eliminada
  'imposto_evitado',        -- come-cotas, compensação de prejuízo, isenções
  'juros_divida_evitados',  -- quitação de dívida cara antes de investir
  'risco_reduzido',         -- desconcentração quantificada
  'rebalanceamento',        -- disciplina 5/25 executada
  'aporte_otimizado',       -- roteamento inteligente vs. aporte ingênuo
  'estorno'                 -- correção: linha nova, referenciando a original
);

CREATE TYPE ledger.entry_status AS ENUM ('provisorio', 'consolidado', 'estornado');

-- -----------------------------------------------------------------------------
-- Lançamentos — append-only, com metodologia obrigatória
-- -----------------------------------------------------------------------------
CREATE TABLE ledger.value_entries (
  id           uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id     uuid NOT NULL REFERENCES identity.scopes(id),
  category     ledger.value_category NOT NULL,
  amount_brl   core.money_brl NOT NULL,
  occurred_on  date NOT NULL,
  run_id       uuid NOT NULL REFERENCES engine.runs(id),
  action_id    uuid REFERENCES diagnostics.actions(id),   -- valor nasce de ação concluída
  finding_id   uuid REFERENCES diagnostics.findings(id),
  -- §13.6 / T11: a metodologia É o lançamento. Sem 'formula', não entra.
  methodology  jsonb NOT NULL,
  status       ledger.entry_status NOT NULL DEFAULT 'provisorio',
  reverses_entry_id uuid REFERENCES ledger.value_entries(id),
  created_at   timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT methodology_has_formula CHECK (
    jsonb_typeof(methodology) = 'object' AND methodology ? 'formula'
  ),
  CONSTRAINT estorno_references_entry CHECK (
    (category = 'estorno') = (reverses_entry_id IS NOT NULL)
  ),
  CONSTRAINT estorno_is_negative CHECK (
    category <> 'estorno' OR amount_brl < 0
  )
);
CREATE INDEX value_entries_scope_idx ON ledger.value_entries (scope_id, occurred_on DESC);
CREATE INDEX value_entries_category_idx ON ledger.value_entries (category);
CREATE INDEX value_entries_action_idx ON ledger.value_entries (action_id) WHERE action_id IS NOT NULL;

-- T10: append-only por trigger E por privilégio
CREATE TRIGGER value_entries_append_only BEFORE UPDATE OR DELETE ON ledger.value_entries
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
REVOKE UPDATE, DELETE ON ledger.value_entries FROM PUBLIC;

COMMENT ON TABLE ledger.value_entries IS
  '§4.11 — o Ledger é o argumento de renovação da assinatura: "a Synapta se pagou X vezes '
  'este ano". Por isso a barra é alta: metodologia gravada, categoria fechada, append-only. '
  'Um Ledger inflado ou editável destruiria exatamente a confiança que ele existe para criar.';

-- -----------------------------------------------------------------------------
-- Rollup mensal — o que a Barra de Valor lê
-- -----------------------------------------------------------------------------
CREATE TABLE ledger.monthly_rollups (
  scope_id       uuid NOT NULL REFERENCES identity.scopes(id),
  month          date NOT NULL,
  total_brl      core.money_brl NOT NULL DEFAULT 0,
  by_category    jsonb NOT NULL DEFAULT '{}'::jsonb,
  entries_count  int NOT NULL DEFAULT 0,
  cumulative_brl core.money_brl NOT NULL DEFAULT 0,   -- desde o início do escopo
  run_id         uuid REFERENCES engine.runs(id),
  computed_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_id, month),
  CONSTRAINT rollup_month_is_month_start CHECK (month = date_trunc('month', month)::date)
);

COMMIT;
