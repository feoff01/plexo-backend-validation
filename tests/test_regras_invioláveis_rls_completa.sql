-- =============================================================================
-- PLEXO · testes das regras invioláveis — a RLS que faltava (T130–T134, 56)
--   T130 toda PARTIÇÃO de um pai com RLS tem RLS própria
--   T131 ler a partição DIRETO não vaza escopo
--   T132 filha que chega ao cliente por FK filtra pelo dono — e a escrita continua
--   T133 `plexo_app` não lê tabela interna
--   T134 nada com dado de cliente fica sem cobertura, e a isenção tem MOTIVO
--
-- POR QUE ESTE ARQUIVO EXISTE
--   O T49 (`test_rls_papeis.sql`) afirma que "toda tabela com scope_id/user_id tem RLS", e é
--   verdade. O problema é o que ele NÃO olha, e as duas omissões estão escritas nele:
--
--     AND NOT c.relispartition                          -- exclui partições
--     AND a.attname IN ('scope_id','user_id')           -- só quem tem a coluna
--
--   `wealth.holdings_snapshots` e `audit.activity_log` têm RLS no PAI e em ZERO das 15
--   partições de cada. No PostgreSQL, consultar a partição pelo pai aplica a política do
--   pai; consultar a PARTIÇÃO DIRETO aplica a da partição — e não havia nenhuma. Medido no
--   banco real em 2026-08-30, sob `plexo_app` com um escopo fixado:
--
--     wealth.holdings_snapshots       →   1 escopo
--     wealth.holdings_snapshots_202608 →  2 escopos
--     audit.activity_log_202608        →  263 linhas
--
--   E a segunda omissão deixa de fora as oito tabelas que chegam ao cliente por FK, entre
--   elas `diagnostics.finding_observations` (que a F19 passou a escrever, com o impacto em
--   reais de cada cliente) e `engine.artifacts` (que o próprio cabeçalho da 02 descreve como
--   guardando "fan chart, séries de Monte Carlo").
--
--   Havia teste. Ele olhava para o lado certo do problema errado — a mesma forma do defeito
--   das views (migration 55), e é por isso que o T134 afirma a PROPRIEDADE sobre o catálogo
--   em vez de conferir uma lista.
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_rls_completa.sql [papel]
-- Termina em ROLLBACK — não deixa resíduo.
-- =============================================================================
\set QUIET on
SET client_min_messages = notice;

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

-- ================================================================ TESTE 130
-- A propriedade, não a lista: se o PAI protege, a FILHA protege. Uma partição nova criada
-- pelo job mensal que nascer sem política falha aqui.
SELECT pg_temp.expect_count($sql$
  SELECT n.nspname || '.' || filha.relname AS particao_sem_rls
    FROM pg_inherits i
    JOIN pg_class pai   ON pai.oid = i.inhparent
    JOIN pg_class filha ON filha.oid = i.inhrelid
    JOIN pg_namespace n ON n.oid = filha.relnamespace
   WHERE pai.relrowsecurity AND NOT filha.relrowsecurity
$sql$, 0, 'T130 nenhuma partição de pai com RLS ficou sem RLS');

-- E a política, não só a flag: RLS ligada sem política nenhuma nega tudo, o que seria outro
-- defeito — o de quebrar a leitura em vez de filtrá-la.
SELECT pg_temp.expect_count($sql$
  SELECT n.nspname || '.' || filha.relname AS particao_sem_politica
    FROM pg_inherits i
    JOIN pg_class pai   ON pai.oid = i.inhparent
    JOIN pg_class filha ON filha.oid = i.inhrelid
    JOIN pg_namespace n ON n.oid = filha.relnamespace
   WHERE pai.relrowsecurity
     AND NOT EXISTS (SELECT 1 FROM pg_policies p
                      WHERE p.schemaname = n.nspname AND p.tablename = filha.relname)
$sql$, 0, 'T130b toda partição protegida tem política, não só a flag');

-- ---------------------------------------------------------------- fixture (prefixo 1131)
INSERT INTO identity.users (id, email, full_name, status) VALUES
  ('11310000-0000-4000-8000-000000000001', 't131-a@teste.local', 'Cliente A T131', 'active'),
  ('11310000-0000-4000-8000-000000000002', 't131-b@teste.local', 'Cliente B T131', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id) VALUES
  ('11310000-0000-4000-8000-00000000000a', 'personal', 'Pessoal A', '11310000-0000-4000-8000-000000000001'),
  ('11310000-0000-4000-8000-00000000000b', 'personal', 'Pessoal B', '11310000-0000-4000-8000-000000000002');

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at) VALUES
  ('11310000-0000-4000-8000-00000000000a', '11310000-0000-4000-8000-000000000001', 'owner', now()),
  ('11310000-0000-4000-8000-00000000000b', '11310000-0000-4000-8000-000000000002', 'owner', now());

INSERT INTO wealth.accounts (id, scope_id, kind, label, institution_name, opened_at) VALUES
  ('11310000-0000-4000-8000-0000000000a1', '11310000-0000-4000-8000-00000000000a',
   'corretora', 'Corretora A', 'Instituição', current_date - 100),
  ('11310000-0000-4000-8000-0000000000b1', '11310000-0000-4000-8000-00000000000b',
   'corretora', 'Corretora B', 'Instituição', current_date - 100);

INSERT INTO market.instruments (id, kind, name, ticker, asset_class_code)
VALUES ('11310000-0000-4000-8000-000000000021', 'acao', 'Papel T131', 'T131X', 'acoes_br');

-- Uma posição de CADA cliente, no mesmo mês (logo, na mesma partição).
INSERT INTO wealth.holdings_snapshots
  (scope_id, account_id, instrument_id, as_of_date, value_brl, origin) VALUES
  ('11310000-0000-4000-8000-00000000000a', '11310000-0000-4000-8000-0000000000a1',
   '11310000-0000-4000-8000-000000000021', current_date, 111111.00, 'manual'),
  ('11310000-0000-4000-8000-00000000000b', '11310000-0000-4000-8000-0000000000b1',
   '11310000-0000-4000-8000-000000000021', current_date, 222222.00, 'manual');

-- ---------------------------------------------------------------- fixture das filhas por FK
INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('11310000-0000-4000-8000-000000000031', '1.4.0', repeat('3', 40), repeat('b', 64));

INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date, is_client_facing)
VALUES ('11310000-0000-4000-8000-00000000003a', '11310000-0000-4000-8000-00000000000a',
        'raiox', '11310000-0000-4000-8000-000000000031', repeat('4', 64), current_date, false),
       ('11310000-0000-4000-8000-00000000003b', '11310000-0000-4000-8000-00000000000b',
        'raiox', '11310000-0000-4000-8000-000000000031', repeat('5', 64), current_date, false);

INSERT INTO engine.run_inputs (run_id, ref_kind, ref_id, ref_hash) VALUES
  ('11310000-0000-4000-8000-00000000003a', 'price_asof', '11310000-0000-4000-8000-000000000021', repeat('6', 64)),
  ('11310000-0000-4000-8000-00000000003b', 'price_asof', '11310000-0000-4000-8000-000000000021', repeat('7', 64));

INSERT INTO diagnostics.findings
  (id, scope_id, finding_type_code, finding_key, severity, confidence, impact_brl_year,
   execution_friction, quantification, first_run_id, last_run_id) VALUES
  ('11310000-0000-4000-8000-00000000004a', '11310000-0000-4000-8000-00000000000a',
   'custo.taxa_fundo_alta', 'custo.taxa_fundo_alta:instrument:a', 'alta', 0.9, 1000, 2,
   '{"custo_ano_brl": 1000}'::jsonb,
   '11310000-0000-4000-8000-00000000003a', '11310000-0000-4000-8000-00000000003a'),
  ('11310000-0000-4000-8000-00000000004b', '11310000-0000-4000-8000-00000000000b',
   'custo.taxa_fundo_alta', 'custo.taxa_fundo_alta:instrument:b', 'alta', 0.9, 2000, 2,
   '{"custo_ano_brl": 2000}'::jsonb,
   '11310000-0000-4000-8000-00000000003b', '11310000-0000-4000-8000-00000000003b');

INSERT INTO diagnostics.finding_observations
  (finding_id, run_id, observed_on, severity, confidence, impact_brl_year) VALUES
  ('11310000-0000-4000-8000-00000000004a', '11310000-0000-4000-8000-00000000003a',
   current_date, 'alta', 0.9, 1000),
  ('11310000-0000-4000-8000-00000000004b', '11310000-0000-4000-8000-00000000003b',
   current_date, 'alta', 0.9, 2000);

-- ================================================================ TESTE 131
-- Sob serviço, a partição derivada tem os DOIS escopos. É esta linha que impede o teste de
-- passar vazio: se o fixture deixar de cair na partição consultada, ele falha AQUI, dizendo
-- "a partição não recebeu o fixture", em vez de mais adiante fingindo que a RLS filtrou.
SELECT pg_temp.expect_count(format($sql$
  SELECT DISTINCT h.scope_id FROM %s h
   WHERE h.value_brl IN (111111.00, 222222.00)
$sql$, (SELECT tableoid::regclass FROM wealth.holdings_snapshots WHERE value_brl = 111111.00)),
  2, 'T131 pré-condição: a partição do mês recebeu os dois escopos do fixture');

SET LOCAL ROLE plexo_app;
SET LOCAL app.role = 'user';
SET LOCAL app.scope_id = '11310000-0000-4000-8000-00000000000a';
SET LOCAL app.user_id  = '11310000-0000-4000-8000-000000000001';

SELECT pg_temp.expect_count($sql$
  SELECT DISTINCT scope_id FROM wealth.holdings_snapshots
   WHERE value_brl IN (111111.00, 222222.00)
$sql$, 1, 'T131a pelo PAI, o cliente vê só o próprio escopo (já era assim)');

-- O bypass: a MESMA pergunta, feita à partição. Antes da 56 devolvia os dois.
--
-- A partição é DERIVADA do dado (`tableoid`), nunca escrita à mão. O nome fixo que estava aqui
-- (`wealth.holdings_snapshots_202608`, escrito em 2026-08-30) virou uma bomba-relógio: o fixture
-- insere com `current_date`, então em 1º de setembro as linhas passaram a cair em `_202609` e a
-- pergunta ia para uma partição VAZIA. O teste devolvia 0 e acusava a RLS por um erro de
-- calendário dele mesmo — e teria voltado a "passar" sozinho em agosto de 2027.
--
-- A conferência sob `plexo_service` acima existe pelo mesmo motivo: sem ela, uma partição errada
-- ou vazia é indistinguível de "a política filtrou", e o teste passaria vazio no dia em que o
-- fixture parasse de chegar lá. Primeiro se prova que os DOIS escopos estão na partição; só então
-- perguntar sob `plexo_app` tem sentido.
SELECT pg_temp.expect_count(format($sql$
  SELECT DISTINCT h.scope_id FROM %s h
   WHERE h.value_brl IN (111111.00, 222222.00)
$sql$, (SELECT tableoid::regclass FROM wealth.holdings_snapshots WHERE value_brl = 111111.00)),
  1, 'T131 pela PARTIÇÃO direto, o cliente vê só o próprio escopo');

-- ================================================================ TESTE 132
-- As filhas por FK: o dono está a uma junção de distância, e a política precisa segui-la.
SELECT pg_temp.expect_count($sql$
  SELECT run_id FROM engine.run_inputs
   WHERE ref_hash IN (repeat('6', 64), repeat('7', 64))
$sql$, 1, 'T132a engine.run_inputs filtra pelo escopo do run');

SELECT pg_temp.expect_count($sql$
  SELECT o.finding_id FROM diagnostics.finding_observations o
   WHERE o.impact_brl_year IN (1000, 2000)
$sql$, 1, 'T132b diagnostics.finding_observations filtra pelo escopo do finding');

RESET ROLE;
SET LOCAL app.role = 'service';

-- ================================================================ TESTE 133
-- Tabela interna: o papel de aplicação não deve nem poder lê-la. `audit.pii_access` é o
-- registro de acesso a PII (LGPD art. 37) — quem olhou o CPF de quem, e por quê. Política de
-- escopo aqui seria errada: a tabela cruza usuários por natureza. O certo é não conceder.
SELECT pg_temp.expect_count($sql$
  SELECT t.tabela FROM (VALUES
      ('audit.pii_access'), ('billing.provider_webhook_events'),
      ('content.compliance_reviews'), ('docs.document_reviews'),
      ('engine.golden_masters'), ('analytics.events'), ('analytics.leads'),
      ('analytics.experiments'), ('analytics.experiment_assignments')
    ) AS t(tabela)
   WHERE has_table_privilege('plexo_app', t.tabela, 'SELECT')
$sql$, 0, 'T133 plexo_app não lê nenhuma tabela interna');

-- ================================================================ TESTE 134
-- A REDE. Toda tabela dos schemas de dado de cliente: ou tem RLS, ou está isenta COM MOTIVO.
-- A isenção vira dado explícito no COMMENT, e não silêncio por formato de coluna — que foi o
-- que deixou 58 tabelas passarem pelo T49 e pelo validador ao mesmo tempo.
SELECT pg_temp.expect_count($sql$
  SELECT n.nspname || '.' || c.relname AS sem_rls_e_sem_motivo
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE c.relkind IN ('r','p')
     AND n.nspname IN ('wealth','diagnostics','planning','budget','context','estate',
                       'preferences','household','decisions','ledger','copilot','agents')
     AND NOT c.relrowsecurity
     AND has_table_privilege('plexo_app', c.oid, 'SELECT')
     AND coalesce(obj_description(c.oid, 'pg_class'), '') NOT LIKE '%[sem RLS por desenho]%'
$sql$, 0, 'T134 tabela de dado de cliente sem RLS só passa com motivo declarado no COMMENT');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Consultar a partição DIRETO aplica a política DA PARTIÇÃO, não'
\echo ' a do pai. Trinta delas não tinham nenhuma — e o T49 as excluía'
\echo ' por construção (`AND NOT c.relispartition`). Havia teste; ele'
\echo ' olhava para o lado certo do problema errado.'
\echo '================================================================'
