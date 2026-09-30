-- =============================================================================
-- PLEXO · testes das regras invioláveis — carteira: rollup × detalhe (T117–T120, 53)
--   T117 rollup que discorda das posições do mesmo dia é RECUSADO
--   T118 rollup sem posição nenhuma é aceito (escopo que só declarou o agregado)
--   T119 a comparação é por DIA — rollup de ontem não é medido contra as posições de hoje
--   T120 o detalhe continua append-only: não se faz o rollup "bater" reescrevendo a posição
--
-- POR QUE ESTE ARQUIVO EXISTE
--   Em 2026-08-30 a conta de demonstração respondeu, na mesma tela, duas coisas
--   incompatíveis: o prompt do agente recebia "investível R$ 780.000" (de
--   `estate.v_net_worth`, que lê `wealth.portfolio_snapshots`) e a tool de composição
--   devolvia "não há posição registrada no escopo" (de `wealth.holdings_snapshots`).
--   Duas fontes para o mesmo fato, uma populada, e NADA no banco obrigando as duas a
--   concordarem. O modelo teve de administrar a contradição sozinho — e não havia
--   resposta certa a dar.
--
--   A regra que nasce aqui é a mais simples possível: **havendo detalhe, o agregado é
--   o detalhe.** Não é o agregado que manda; é o detalhe que existe e o agregado que
--   resume. Um rollup que discorda das posições do mesmo dia não é uma imprecisão —
--   é um número que vai para o prompt do agente e para a tela do cliente afirmando
--   algo que a carteira não diz.
--
--   Não vale só na aplicação porque o único escritor de holdings do repositório é um
--   arquivo de seed, e o próximo será um importador de extrato. Regra que vive no
--   serviço vaza no primeiro backfill — é o mesmo argumento do `action_five_blocks`.
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_carteira.sql [plexo_service]
-- Termina em ROLLBACK — não deixa resíduo.
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
END $$;

CREATE OR REPLACE FUNCTION pg_temp.expect_count(p_sql text, p_expected bigint, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v bigint;
BEGIN
  EXECUTE 'SELECT count(*) FROM (' || p_sql || ') q' INTO v;
  IF v <> p_expected THEN
    RAISE EXCEPTION 'FALHOU: "%" — esperado % linha(s), obtido %', p_label, p_expected, v;
  END IF;
  RAISE NOTICE 'ok   · % (% linha(s), como esperado)', p_label, v;
END $$;

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixture (prefixo 1117 = T117)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('11170000-0000-4000-8000-000000000001', 't117-titular@teste.local', 'Titular T117', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('11170000-0000-4000-8000-000000000002', 'personal', 'Pessoal T117',
        '11170000-0000-4000-8000-000000000001'),
       -- escopo irmão, que declara agregado e nunca teve posição: é o caso legítimo do T118
       ('11170000-0000-4000-8000-000000000003', 'personal', 'Só o agregado T118',
        '11170000-0000-4000-8000-000000000001');

INSERT INTO wealth.accounts (id, scope_id, kind, label, institution_name, opened_at)
VALUES ('11170000-0000-4000-8000-000000000011', '11170000-0000-4000-8000-000000000002',
        'corretora', 'Corretora T117', 'Instituição T117', current_date - 365);

INSERT INTO market.instruments (id, kind, name, ticker, asset_class_code)
VALUES ('11170000-0000-4000-8000-000000000021', 'acao', 'Ação T117 A', 'T117A', 'acoes_br'),
       ('11170000-0000-4000-8000-000000000022', 'cdb',  'CDB T117 B',  'T117B', 'selic');

-- Duas posições somando 150.000. É contra esta soma que o rollup será medido.
INSERT INTO wealth.holdings_snapshots
  (scope_id, account_id, instrument_id, as_of_date, quantity, unit_price, value_brl, avg_cost, origin)
VALUES ('11170000-0000-4000-8000-000000000002', '11170000-0000-4000-8000-000000000011',
        '11170000-0000-4000-8000-000000000021', current_date, 2000, 45.00, 90000.00, 38.50, 'manual'),
       ('11170000-0000-4000-8000-000000000002', '11170000-0000-4000-8000-000000000011',
        '11170000-0000-4000-8000-000000000022', current_date, NULL, NULL, 60000.00, NULL, 'manual');

-- ================================================================ TESTE 117
-- O defeito real, virado teste: o agregado afirma 780.000 e o detalhe soma 150.000.
-- Era exatamente esta divergência que chegava ao prompt do agente como um número e à
-- tool como outro. Um único defeito de distância do caminho feliz: mesma data, mesmo
-- escopo, mesmas posições — só o total é que mente.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO wealth.portfolio_snapshots (scope_id, as_of_date, total_brl, invested_brl, cash_brl)
  VALUES ('11170000-0000-4000-8000-000000000002', current_date, 780000.00, 780000.00, 0.00);
$sql$, 'T117 rollup afirmando 780.000 com 150.000 em posições no mesmo dia');

-- Divergência pequena também é divergência: dois centavos já são um número que ninguém
-- refaz somando a carteira. A tolerância é de UM centavo, para absorver arredondamento
-- de numeric na soma, e nada além disso.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO wealth.portfolio_snapshots (scope_id, as_of_date, total_brl, invested_brl, cash_brl)
  VALUES ('11170000-0000-4000-8000-000000000002', current_date, 150000.02, 150000.02, 0.00);
$sql$, 'T117b rollup dois centavos acima da soma das posições');

-- Caminho feliz: bate na casa do centavo, entra.
INSERT INTO wealth.portfolio_snapshots
  (scope_id, as_of_date, total_brl, invested_brl, cash_brl, by_asset_class, by_account)
VALUES ('11170000-0000-4000-8000-000000000002', current_date, 150000.00, 90000.00, 60000.00,
        '{"acoes_br": 90000, "selic": 60000}'::jsonb, '{"corretora": 150000}'::jsonb);

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM wealth.portfolio_snapshots
   WHERE scope_id = '11170000-0000-4000-8000-000000000002'
     AND as_of_date = current_date AND total_brl = 150000.00
$sql$, 1, 'T117c rollup que bate com o detalhe entra');

-- ================================================================ TESTE 118
-- O outro lado da regra, e o que impede que ela quebre metade do repositório: um escopo
-- que ainda não abriu a carteira, mas já declarou quanto tem, continua válido. As seis
-- personas da F16 vivem assim. A regra é "havendo detalhe, o agregado é o detalhe" —
-- não "todo agregado exige detalhe", que seria proibir o cliente de dizer o total antes
-- de listar as posições.
INSERT INTO wealth.portfolio_snapshots (scope_id, as_of_date, total_brl, invested_brl, cash_brl)
VALUES ('11170000-0000-4000-8000-000000000003', current_date, 2100000.00, 2100000.00, 0.00);

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM wealth.portfolio_snapshots
   WHERE scope_id = '11170000-0000-4000-8000-000000000003' AND total_brl = 2100000.00
$sql$, 1, 'T118 rollup sem posição nenhuma no escopo é aceito');

-- ================================================================ TESTE 119
-- A data é parte da chave nos dois lados, e a comparação é por DIA. Um rollup de ontem
-- não é medido contra as posições de hoje — senão toda ingestão nova invalidaria o
-- histórico, que é justamente o que `as_of_date` existe para preservar.
INSERT INTO wealth.portfolio_snapshots (scope_id, as_of_date, total_brl, invested_brl, cash_brl)
VALUES ('11170000-0000-4000-8000-000000000002', current_date - 1, 128000.00, 128000.00, 0.00);

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM wealth.portfolio_snapshots
   WHERE scope_id = '11170000-0000-4000-8000-000000000002'
     AND as_of_date = current_date - 1 AND total_brl = 128000.00
$sql$, 1, 'T119 rollup de outro dia não é medido contra as posições de hoje');

-- E o dia que passa a TER posição volta a valer a regra, inclusive no UPDATE:
INSERT INTO wealth.holdings_snapshots
  (scope_id, account_id, instrument_id, as_of_date, value_brl, origin)
VALUES ('11170000-0000-4000-8000-000000000002', '11170000-0000-4000-8000-000000000011',
        '11170000-0000-4000-8000-000000000021', current_date - 1, 128000.00, 'manual');

SELECT pg_temp.expect_fail($sql$
  UPDATE wealth.portfolio_snapshots SET total_brl = 500000.00
   WHERE scope_id = '11170000-0000-4000-8000-000000000002' AND as_of_date = current_date - 1;
$sql$, 'T119b UPDATE do rollup para um total que o detalhe do dia não sustenta');

-- ================================================================ TESTE 120
-- O detalhe segue append-only (C7): não se conserta a carteira reescrevendo o passado.
-- Este teste está aqui, e não no arquivo do wealth, porque é o par da regra nova — se
-- o detalhe fosse editável, bastaria reescrever a posição para fazer qualquer rollup
-- "bater", e o gate do T117 viraria decoração.
SELECT pg_temp.expect_fail($sql$
  UPDATE wealth.holdings_snapshots SET value_brl = 780000.00
   WHERE scope_id = '11170000-0000-4000-8000-000000000002' AND as_of_date = current_date;
$sql$, 'T120 UPDATE em posição já registrada, para fazer o rollup bater');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM wealth.holdings_snapshots
   WHERE scope_id = '11170000-0000-4000-8000-000000000002' AND as_of_date = current_date;
$sql$, 'T120b DELETE de posição para esvaziar o dia e liberar qualquer rollup');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Havendo detalhe, o agregado é o detalhe. Um rollup que discorda'
\echo ' das posições do mesmo dia não é imprecisão: é o número que vai'
\echo ' para o prompt do agente afirmando o que a carteira não diz.'
\echo '================================================================'
