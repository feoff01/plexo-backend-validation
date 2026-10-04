-- =============================================================================
-- SYNAPTA · testes das regras invioláveis — dados de mercado (T58–T62, 31_market_immutability;
--            T78–T79, 35_market_expectations)
-- O Analista só fundamenta análise em preço que não muda por baixo dele: séries de mercado são
-- append-only, estruturalmente válidas (sem preço zero/negativo de fechamento, sem data futura),
-- lotes de ingestão finalizados são imutáveis e um mesmo arquivo nunca gera dois lotes bem-sucedidos.
-- Cada teste prova que o BANCO recusa — não a aplicação. Roda como admin e sob plexo_service.
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_market.sql [plexo_service]
-- =============================================================================

\set QUIET on
SET client_min_messages = notice;

CREATE OR REPLACE FUNCTION pg_temp.expect_fail(p_sql text, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  BEGIN
    EXECUTE p_sql;
    RAISE EXCEPTION 'FALHOU: "%" deveria ter sido rejeitado pelo banco', p_label;
  EXCEPTION
    WHEN raise_exception THEN
      IF sqlerrm LIKE 'FALHOU:%' THEN RAISE; END IF;
      RAISE NOTICE 'ok   · % (rejeitado: %)', p_label, left(sqlerrm, 70);
    WHEN others THEN
      RAISE NOTICE 'ok   · % (rejeitado: %)', p_label, left(sqlerrm, 70);
  END;
END;
$$;

CREATE OR REPLACE FUNCTION pg_temp.expect_count(p_sql text, p_n bigint, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_n bigint;
BEGIN
  EXECUTE 'SELECT count(*) FROM (' || p_sql || ') q' INTO v_n;
  IF v_n <> p_n THEN
    RAISE EXCEPTION 'FALHOU: "%" esperava % linha(s), veio %', p_label, p_n, v_n;
  END IF;
  RAISE NOTICE 'ok   · % (% linha(s))', p_label, v_n;
END;
$$;

CREATE OR REPLACE FUNCTION pg_temp.expect_true(p_sql text, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v boolean;
BEGIN
  EXECUTE p_sql INTO v;
  IF NOT coalesce(v, false) THEN
    RAISE EXCEPTION 'FALHOU: "%" esperava verdadeiro', p_label;
  END IF;
  RAISE NOTICE 'ok   · %', p_label;
END;
$$;

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixtures
INSERT INTO market.instruments (id, kind, name, ticker, is_in_universe, source_code)
VALUES ('58585858-0000-0000-0000-000000000001', 'acao', 'T58 Petróleo S.A.', 'T58PETR', true, 'b3');

INSERT INTO market.ingestion_batches (id, source_code, dataset, reference_date, file_hash)
VALUES ('58585858-0000-0000-0000-00000000000b', 'b3', 't58-cotacoes', current_date - 1,
        repeat('a', 64));

INSERT INTO market.prices (price_date, instrument_id, kind, value, source_code, ingestion_batch_id)
VALUES (current_date - 1, '58585858-0000-0000-0000-000000000001', 'close', 37.15, 'b3',
        '58585858-0000-0000-0000-00000000000b');

INSERT INTO market.index_values (index_code, value_date, value, ingestion_batch_id)
VALUES ('cdi', current_date - 1, 0.04, '58585858-0000-0000-0000-00000000000b');

INSERT INTO market.fx_rates (base_currency, quote_currency, rate_date, rate, source_code)
VALUES ('USD', 'BRL', current_date - 1, 5.1234, 'bacen_sgs');

INSERT INTO market.corporate_actions (id, instrument_id, kind, ex_date, amount_per_unit, source_code)
VALUES ('58585858-0000-0000-0000-00000000000c', '58585858-0000-0000-0000-000000000001',
        'dividendo', current_date - 1, 0.50, 'b3');

-- ================================================================ TESTE 58
-- Séries de mercado são append-only: preço "corrigido" é linha nova (fonte/lote), nunca UPDATE.
SELECT pg_temp.expect_fail($sql$
  UPDATE market.prices SET value = 99 WHERE instrument_id = '58585858-0000-0000-0000-000000000001';
$sql$, 'T58  UPDATE em market.prices');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM market.prices WHERE instrument_id = '58585858-0000-0000-0000-000000000001';
$sql$, 'T58a DELETE em market.prices');

SELECT pg_temp.expect_fail($sql$
  UPDATE market.index_values SET value = 99 WHERE index_code = 'cdi' AND value_date = current_date - 1;
$sql$, 'T58b UPDATE em market.index_values');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM market.fx_rates WHERE rate_date = current_date - 1 AND base_currency = 'USD';
$sql$, 'T58c DELETE em market.fx_rates');

SELECT pg_temp.expect_fail($sql$
  UPDATE market.corporate_actions SET amount_per_unit = 9 WHERE id = '58585858-0000-0000-0000-00000000000c';
$sql$, 'T58d UPDATE em market.corporate_actions');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.prices WHERE instrument_id = '58585858-0000-0000-0000-000000000001' AND value = 37.15
$sql$, 1, 'T58e o preço original continua lá');

-- ================================================================ TESTE 59
-- Preço estruturalmente válido: fechamento > 0, nunca no futuro; yield negativo é legítimo.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.prices (price_date, instrument_id, kind, value, source_code)
  VALUES (current_date - 2, '58585858-0000-0000-0000-000000000001', 'close', 0, 'b3');
$sql$, 'T59  fechamento igual a zero');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.prices (price_date, instrument_id, kind, value, source_code)
  VALUES (current_date + 1, '58585858-0000-0000-0000-000000000001', 'close', 10, 'b3');
$sql$, 'T59b preço com data futura');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.index_values (index_code, value_date, value)
  VALUES ('cdi', current_date + 1, 0.04);
$sql$, 'T59c valor de índice com data futura');

INSERT INTO market.prices (price_date, instrument_id, kind, value, source_code)
VALUES (current_date - 2, '58585858-0000-0000-0000-000000000001', 'yield', -0.5, 'b3');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.prices WHERE instrument_id = '58585858-0000-0000-0000-000000000001' AND kind = 'yield'
$sql$, 1, 'T59d yield negativo é aceito (taxa pode ser negativa)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.corporate_actions (instrument_id, kind, ex_date, factor, source_code)
  VALUES ('58585858-0000-0000-0000-000000000001', 'desdobramento', current_date - 1, 0, 'b3');
$sql$, 'T59e desdobramento com fator zero');

-- ================================================================ TESTE 60
-- Lote de ingestão: succeeded exige contagem; finalizado é imutável; mesmo arquivo não vira
-- dois lotes bem-sucedidos (a idempotência é do banco, a aplicação só consulta antes).
SELECT pg_temp.expect_fail($sql$
  UPDATE market.ingestion_batches SET status = 'succeeded', finished_at = now()
   WHERE id = '58585858-0000-0000-0000-00000000000b';
$sql$, 'T60  succeeded sem rows_ingested');

SELECT pg_temp.expect_fail($sql$
  UPDATE market.ingestion_batches SET status = 'failed', error_detail = 'x'
   WHERE id = '58585858-0000-0000-0000-00000000000b';
$sql$, 'T60a finalizado sem finished_at');

UPDATE market.ingestion_batches
   SET status = 'succeeded', finished_at = now(), rows_ingested = 1
 WHERE id = '58585858-0000-0000-0000-00000000000b';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.ingestion_batches WHERE id = '58585858-0000-0000-0000-00000000000b' AND status = 'succeeded'
$sql$, 1, 'T60b lote fechado como succeeded com contagem e finished_at');

SELECT pg_temp.expect_fail($sql$
  UPDATE market.ingestion_batches SET error_detail = 'editado depois'
   WHERE id = '58585858-0000-0000-0000-00000000000b';
$sql$, 'T60c UPDATE em lote finalizado');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM market.ingestion_batches WHERE id = '58585858-0000-0000-0000-00000000000b';
$sql$, 'T60d DELETE de lote');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.ingestion_batches (source_code, dataset, reference_date, file_hash, status, finished_at, rows_ingested)
  VALUES ('b3', 't58-cotacoes', current_date - 1, repeat('a', 64), 'succeeded', now(), 1);
$sql$, 'T60e segundo lote succeeded com o mesmo file_hash');

INSERT INTO market.ingestion_batches (source_code, dataset, reference_date, file_hash, status, finished_at, error_detail)
VALUES ('b3', 't58-cotacoes', current_date - 1, repeat('a', 64), 'failed', now(), 'tentativa que falhou');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.ingestion_batches WHERE dataset = 't58-cotacoes' AND file_hash = repeat('a', 64)
$sql$, 2, 'T60f lote failed com o mesmo hash é permitido (reprocesso)');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.prices (price_date, instrument_id, kind, value, source_code, ingestion_batch_id)
  VALUES (current_date - 3, '58585858-0000-0000-0000-000000000001', 'close', 10, 'b3',
          '58585858-0000-0000-0000-0000000000ff');
$sql$, 'T60g preço apontando para lote inexistente');

-- ================================================================ TESTE 61
-- Histórico cabe nas partições: 10 anos de cobertura; preço antigo não cai na DEFAULT.
SELECT pg_temp.expect_true($sql$
  SELECT count(*) >= 120 FROM pg_inherits i
  JOIN pg_class c ON c.oid = i.inhrelid
  WHERE i.inhparent = 'market.prices'::regclass AND c.relname <> 'prices_default'
$sql$, 'T61  market.prices tem pelo menos 120 partições mensais');

INSERT INTO market.prices (price_date, instrument_id, kind, value, source_code)
VALUES ((current_date - interval '9 years')::date, '58585858-0000-0000-0000-000000000001', 'close', 12.34, 'b3');
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.prices
  WHERE instrument_id = '58585858-0000-0000-0000-000000000001' AND value = 12.34
    AND tableoid::regclass::text <> 'market.prices_default'
$sql$, 1, 'T61b preço de 9 anos atrás cai numa partição mensal, não na DEFAULT');

-- ================================================================ TESTE 62
-- Append-only também por privilégio: nem a API nem o serviço têm UPDATE/DELETE nas séries.
SELECT pg_temp.expect_true($sql$
  SELECT NOT bool_or(has_table_privilege(r, t, p))
  FROM unnest(ARRAY['plexo_app','plexo_service']) r,
       unnest(ARRAY['market.prices','market.index_values','market.fx_rates','market.corporate_actions']) t,
       unnest(ARRAY['UPDATE','DELETE']) p
$sql$, 'T62  plexo_app/plexo_service sem UPDATE/DELETE nas 4 séries de mercado');

-- ================================================================ TESTE 78
-- Expectativa publicada não se reescreve: revisão do BCB entra como coleta nova (35).
INSERT INTO market.market_expectations (id, indicador, data_coleta, referencia, mediana, respondentes)
VALUES ('78780000-0000-4000-8000-000000000001', 'Selic', current_date - 1, '2026', 14.00, 41);

SELECT pg_temp.expect_fail($sql$
  UPDATE market.market_expectations SET mediana = 9.99
   WHERE id = '78780000-0000-4000-8000-000000000001';
$sql$, 'T78  expectativa de mercado é append-only (UPDATE)');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM market.market_expectations WHERE id = '78780000-0000-4000-8000-000000000001';
$sql$, 'T78b expectativa de mercado é append-only (DELETE)');

-- ================================================================ TESTE 79
-- Mesma coleta, mesmo indicador, mesmo horizonte: uma linha só (idempotência da ingestão).
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.market_expectations (indicador, data_coleta, referencia, mediana)
  VALUES ('Selic', current_date - 1, '2026', 14.25);
$sql$, 'T79  mesma (indicador, coleta, horizonte) duas vezes');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.market_expectations (indicador, data_coleta, referencia, minimo, maximo)
  VALUES ('IPCA', current_date - 1, '2027', 9.0, 4.0);
$sql$, 'T79b estatística incoerente (mínimo acima do máximo)');

-- ---------------------------------------------------------------- fixtures do acervo (61)
INSERT INTO market.instruments (id, kind, name, ticker, is_in_universe, source_code)
VALUES ('14600000-0000-4000-8000-000000000001', 'acao', 'T146 Papel S.A.', 'T146PAP', true, 'b3');

INSERT INTO market.trading_calendar (calendar_name, calendar_date, is_business_day, source_code)
VALUES ('anbima', DATE '2020-03-10', true, 'anbima');

INSERT INTO market.sector_classification (instrument_id, source_code, reference_date, economic_sector)
VALUES ('14600000-0000-4000-8000-000000000001', 'b3', DATE '2020-01-02', 'Petróleo, Gás e Biocombustíveis');

INSERT INTO market.index_weights (index_code, reference_date, instrument_id, weight_pct)
VALUES ('ibov', DATE '2020-01-02', '14600000-0000-4000-8000-000000000001', 5.5);

INSERT INTO market.yield_curve (curve_name, reference_date, business_days, rate_pct, day_count, source_code)
VALUES ('pre', DATE '2020-01-02', 21, 4.4, 'du_252', 'b3');

INSERT INTO market.fundamentals (company_cnpj, instrument_id, reference_date, availability_date,
                                 document_type, scope, period_label, metric, value, source_code)
VALUES ('00000000000191', '14600000-0000-4000-8000-000000000001', DATE '2023-03-31', DATE '2023-05-15',
        'ITR', 'consolidated', 'Q1', 'net_income', 1000.00, 'cvm_fundos');

-- ================================================================ TESTE 146
-- [F22] O acervo de mercado nasce append-only, como as séries da 31: dado público corrigido é
-- linha nova (outro lote), nunca reescrita. Sem isto, o Analista fundamenta análise em número
-- que muda por baixo dele — e `tool_executions.input_hash` deixa de valer como reprodutibilidade.
SELECT pg_temp.expect_fail($sql$
  UPDATE market.trading_calendar SET is_business_day = false
   WHERE calendar_name = 'anbima' AND calendar_date = DATE '2020-03-10';
$sql$, 'T146  UPDATE em market.trading_calendar');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM market.yield_curve WHERE curve_name = 'pre' AND reference_date = DATE '2020-01-02';
$sql$, 'T146a DELETE em market.yield_curve');

SELECT pg_temp.expect_fail($sql$
  UPDATE market.fundamentals SET value = 9.99 WHERE company_cnpj = '00000000000191';
$sql$, 'T146b UPDATE em market.fundamentals');

SELECT pg_temp.expect_fail($sql$
  UPDATE market.index_weights SET weight_pct = 1 WHERE index_code = 'ibov';
$sql$, 'T146c UPDATE em market.index_weights');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM market.sector_classification
   WHERE instrument_id = '14600000-0000-4000-8000-000000000001';
$sql$, 'T146d DELETE em market.sector_classification');

-- Append-only também por privilégio, como o T62 faz para as séries da 31.
SELECT pg_temp.expect_true($sql$
  SELECT NOT bool_or(has_table_privilege(r, t, p))
  FROM unnest(ARRAY['plexo_app','plexo_service']) r,
       unnest(ARRAY['market.trading_calendar','market.sector_classification','market.index_weights',
                    'market.yield_curve','market.fundamentals']) t,
       unnest(ARRAY['UPDATE','DELETE']) p
$sql$, 'T146e plexo_app/plexo_service sem UPDATE/DELETE nas 5 tabelas do acervo');

-- ================================================================ TESTE 147
-- [F22] Fundamento é POINT-IN-TIME ou não é fundamento. `availability_date` é quando a CVM
-- recebeu o documento; sem ela, um backtest usa balanço antes de ele ter sido publicado — o erro
-- mais caro em análise de fundamento, e o que o GUIA_BANCO do coletor chama de look-ahead.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.fundamentals (company_cnpj, reference_date, document_type, scope,
                                   period_label, metric, value, source_code)
  VALUES ('00000000000191', DATE '2023-06-30', 'ITR', 'consolidated', 'Q2', 'ebitda_derived', 50.0, 'cvm_fundos');
$sql$, 'T147  fundamento sem availability_date');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.fundamentals (company_cnpj, reference_date, availability_date, document_type,
                                   scope, period_label, metric, value, source_code)
  VALUES ('00000000000191', DATE '2023-06-30', DATE '2023-06-01', 'ITR', 'consolidated', 'Q2',
          'ebitda_derived', 50.0, 'cvm_fundos');
$sql$, 'T147a balanço disponível ANTES do fim do período');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.fundamentals
   WHERE company_cnpj = '00000000000191' AND metric = 'net_income'
     AND availability_date = DATE '2023-05-15'
$sql$, 1, 'T147b o fato válido, com a data em que ficou disponível, está lá');

-- ================================================================ TESTE 148
-- [F22] Unidade é constraint, não convenção. A F16 gastou meia sessão num defeito onde
-- percentual e fração foram comparados sem conversão e uma dívida a 400% a.a. pareceu mais
-- barata que o CDI. Curva sem base declarada é a mesma armadilha: 4,4 em 252 dias úteis e 4,4
-- em 360 corridos não são o mesmo número.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.yield_curve (curve_name, reference_date, business_days, rate_pct, source_code)
  VALUES ('pre', DATE '2020-01-03', 42, 4.5, 'b3');
$sql$, 'T148  curva de juros sem day_count');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.yield_curve (curve_name, reference_date, business_days, rate_pct, day_count, source_code)
  VALUES ('pre', DATE '2020-01-03', 42, 4.5, 'dias_uteis', 'b3');
$sql$, 'T148a day_count fora do vocabulário fechado');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.yield_curve (curve_name, reference_date, business_days, rate_pct, day_count, source_code)
  VALUES ('pre', DATE '2020-01-03', 0, 4.5, 'du_252', 'b3');
$sql$, 'T148b vértice com zero dias úteis');

-- ================================================================ TESTE 149
-- [F22] Peso de índice é percentual entre 0 e 100, e feriado com nome não é dia útil. Duas
-- afirmações que o banco pode provar e que, erradas, viram gráfico errado sem aviso.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.index_weights (index_code, reference_date, instrument_id, weight_pct)
  VALUES ('ibov', DATE '2020-01-03', '14600000-0000-4000-8000-000000000001', 150);
$sql$, 'T149  peso de índice acima de 100%');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.index_weights (index_code, reference_date, instrument_id, weight_pct)
  VALUES ('ibov', DATE '2020-01-03', '14600000-0000-4000-8000-000000000001', -1);
$sql$, 'T149a peso de índice negativo');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.trading_calendar (calendar_name, calendar_date, is_business_day, holiday_name, source_code)
  VALUES ('anbima', DATE '2020-12-25', true, 'Natal', 'anbima');
$sql$, 'T149b dia com nome de feriado marcado como dia útil');

-- ================================================================ TESTE 150
-- [F22] Preço ajustado é CALCULADO na leitura, nunca gravado. O `cum_factor` de ontem muda
-- quando um provento é anunciado hoje; materializá-lo em `market.prices` seria reescrever série,
-- que o T58 proíbe. Cenário: fechamento 10,00 na véspera do ex, dividendo de 1,00 na data-ex.
-- Fator = (10,00 − 1,00) / 10,00 = 0,9 — a convenção do mercado, aplicada para trás.
INSERT INTO market.instruments (id, kind, name, ticker, is_in_universe, source_code)
VALUES ('15000000-0000-4000-8000-000000000001', 'acao', 'T150 Dividendo S.A.', 'T150DIV', true, 'b3');

INSERT INTO market.prices (price_date, instrument_id, kind, value, source_code) VALUES
  (DATE '2020-06-01', '15000000-0000-4000-8000-000000000001', 'close', 10.00, 'b3'),
  (DATE '2020-06-02', '15000000-0000-4000-8000-000000000001', 'close', 10.00, 'b3'),
  (DATE '2020-06-03', '15000000-0000-4000-8000-000000000001', 'close',  9.00, 'b3'),
  (DATE '2020-06-04', '15000000-0000-4000-8000-000000000001', 'close',  9.50, 'b3');

INSERT INTO market.corporate_actions (instrument_id, kind, ex_date, amount_per_unit, source_code)
VALUES ('15000000-0000-4000-8000-000000000001', 'dividendo', DATE '2020-06-03', 1.00, 'b3');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.v_precos_ajustados
   WHERE instrument_id = '15000000-0000-4000-8000-000000000001'
     AND price_date = DATE '2020-06-01'
     AND round(close_adj, 4) = 9.0000
$sql$, 1, 'T150  fechamento anterior ao ex é ajustado pelo fator do provento');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.v_precos_ajustados
   WHERE instrument_id = '15000000-0000-4000-8000-000000000001'
     AND price_date = DATE '2020-06-04'
     AND cum_factor = 1 AND round(close_adj, 4) = 9.5000
$sql$, 1, 'T150a a observação mais recente tem fator 1 — o ajuste é retroativo');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.prices
   WHERE instrument_id = '15000000-0000-4000-8000-000000000001'
     AND price_date = DATE '2020-06-01' AND value = 10.00
$sql$, 1, 'T150b o preço CRU continua intacto — o ajuste não reescreveu a série');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.v_fatores_ajuste
   WHERE instrument_id = '15000000-0000-4000-8000-000000000001'
     AND ex_date = DATE '2020-06-03' AND round(cum_factor, 6) = 0.900000
$sql$, 1, 'T150c o fator do evento é (véspera − provento) / véspera');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Dados de mercado (31) concluído: séries append-only e válidas,'
\echo ' lotes finalizados imutáveis, mesmo arquivo nunca ingerido duas vezes.'
\echo ' Acervo de mercado (61): append-only por trigger e por privilégio,'
\echo ' fundamento point-in-time, unidade da curva como constraint,'
\echo ' e preço ajustado calculado na leitura — nunca gravado.'
\echo '================================================================'
