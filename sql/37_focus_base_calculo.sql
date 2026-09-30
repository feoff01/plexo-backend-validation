-- =============================================================================
-- PLEXO · 37_focus_base_calculo.sql — `baseCalculo` na chave do Focus [F13b]
-- -----------------------------------------------------------------------------
-- Achado da verificação: o Focus publica, para a MESMA data de coleta e o MESMO horizonte, duas
-- estatísticas distintas — `baseCalculo=0` (janela de 30 dias) e `baseCalculo=1` (5 dias úteis),
-- com número de respondentes diferente (145 × 72 na coleta de 2026-08-21 para a Selic de 2026).
-- A chave natural da 35 não continha essa coluna: as duas colapsavam e a ingestão guardava a que
-- chegasse primeiro — número silenciosamente errado, que é o pior tipo de erro aqui.
--
-- A 35 já está aplicada e não se edita; a correção é este arquivo.
-- Coluna ANULÁVEL de propósito: as linhas ingeridas antes desta migration têm base desconhecida e
-- ficam com NULL — a tool não as cita. O sentinela -1 no índice existe só para NULL não se repetir.
-- =============================================================================
BEGIN;

ALTER TABLE market.market_expectations ADD COLUMN base_calculo smallint;
COMMENT ON COLUMN market.market_expectations.base_calculo IS
  '[F13b] Janela da estatística no BCB: 0 = últimos 30 dias, 1 = últimos 5 dias úteis. NULL = linha anterior à 37, base desconhecida (não citável).';

DROP INDEX market.expectations_natural_uk;
CREATE UNIQUE INDEX expectations_natural_uk ON market.market_expectations
  (indicador, coalesce(detalhe, ''), data_coleta, referencia, coalesce(base_calculo, -1));

COMMIT;
