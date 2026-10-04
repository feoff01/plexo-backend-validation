-- =============================================================================
-- PLEXO · 56_rls_das_particoes_e_das_filhas.sql — a RLS que o gate não olhava
--
-- O DEFEITO, MEDIDO
--
-- `wealth.holdings_snapshots` e `audit.activity_log` têm RLS no PAI e em ZERO das 15 partições
-- de cada. No PostgreSQL, consultar pelo pai aplica a política DO PAI; consultar a PARTIÇÃO
-- DIRETO aplica a DA PARTIÇÃO — e não havia nenhuma. Sob `plexo_app` com um escopo fixado, em
-- 2026-08-30:
--
--   wealth.holdings_snapshots         →   1 escopo
--   wealth.holdings_snapshots_202608  →   2 escopos      <-- o mesmo dado, sem filtro
--   audit.activity_log_202608         → 263 linhas
--
-- A causa é durável e não estava nas partições existentes: `core.ensure_month_partitions`
-- (00_core) cria com `CREATE TABLE ... PARTITION OF` e nunca liga RLS. O COMMENT dela diz que
-- um job mensal a chama — então toda partição futura nasceria igual, e consertar só as trinta
-- seria varrer para debaixo do tapete com data marcada para reaparecer.
--
-- POR QUE NINGUÉM VIU
--
-- O T49 afirma "toda tabela com scope_id/user_id tem RLS", e é verdade. O que ele não olha está
-- escrito nele:
--     AND NOT c.relispartition                    -- exclui partições
--     AND a.attname IN ('scope_id','user_id')     -- só quem tem a coluna
-- A segunda linha também deixa de fora as oito tabelas que chegam ao cliente por FK — entre
-- elas `diagnostics.finding_observations`, que a F19 passou a escrever com o impacto em reais
-- de cada cliente, e `engine.artifacts`, que a 02 descreve guardando "séries de Monte Carlo".
-- Havia teste, e ele olhava para o lado certo do problema errado. É a mesma forma do defeito
-- das views (55), e por isso o T134 afirma a propriedade sobre o CATÁLOGO, não sobre uma lista.
--
-- AS TRÊS PARTES
--   (a) partições: retroativo nas 30 + a função que cria as próximas já protegidas
--   (b) as 8 filhas por FK: política que segue a junção até o dono
--   (c) as 9 internas: `plexo_app` não deveria nem poder lê-las — REVOKE, não política
--
-- SOBRE (c), E POR QUE NÃO É POLÍTICA
--   `audit.pii_access` é o registro de acesso a PII (LGPD art. 37): quem olhou o dado de quem.
--   Filtrar por escopo ali seria destruir o que a tabela é — ela CRUZA usuários por natureza.
--   O mesmo vale para `analytics.*`, cujo próprio COMMENT diz que a costura anônimo→usuário é
--   feita em LEITURA, cruzando `anonymous_id`. Nenhuma delas é tocada por `app/` (verificado):
--   o acesso certo é sob serviço, e o papel de aplicação não precisa dele.
--
-- Depende de: 00_core (ensure_month_partitions), 14_rls_partitions, 28_roles_grants.
-- Testes: tests/test_regras_invioláveis_rls_completa.sql (T130–T134).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- (a.1) Retroativo: toda partição de um pai que já protege passa a proteger igual
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  p record;
  n int := 0;
BEGIN
  FOR p IN
    SELECT nf.nspname AS schema_filha, f.relname AS filha
      FROM pg_inherits i
      JOIN pg_class pai   ON pai.oid = i.inhparent
      JOIN pg_class f     ON f.oid = i.inhrelid
      JOIN pg_namespace nf ON nf.oid = f.relnamespace
     WHERE pai.relrowsecurity AND NOT f.relrowsecurity
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', p.schema_filha, p.filha);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',  p.schema_filha, p.filha);
    -- A MESMA política do pai, não uma variante: divergir aqui criaria dois comportamentos
    -- para o mesmo dado, dependendo de por onde se lê.
    EXECUTE format($p$
      CREATE POLICY scope_isolation ON %I.%I FOR ALL
        USING (core.is_service()
               OR scope_id::text = current_setting('app.scope_id', true))
    $p$, p.schema_filha, p.filha);
    n := n + 1;
  END LOOP;
  RAISE NOTICE '56: RLS aplicada a % partição(ões) que estavam sem', n;
END $$;

-- -----------------------------------------------------------------------------
-- (a.2) E as próximas nascem protegidas — senão o job mensal recria o buraco
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.proteger_particao(p_schema text, p_tabela text, p_pai_protege boolean)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF NOT p_pai_protege THEN
    -- Pai sem RLS é catálogo global (é o caso de `market.prices`): proteger a filha ali seria
    -- inventar um dono para dado que não tem.
    RETURN;
  END IF;
  EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', p_schema, p_tabela);
  EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',  p_schema, p_tabela);
  IF NOT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname = p_schema AND tablename = p_tabela
                    AND policyname = 'scope_isolation') THEN
    EXECUTE format($p$
      CREATE POLICY scope_isolation ON %I.%I FOR ALL
        USING (core.is_service()
               OR scope_id::text = current_setting('app.scope_id', true))
    $p$, p_schema, p_tabela);
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION core.ensure_month_partitions(parent regclass, from_month date, months int)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  v_start date := date_trunc('month', from_month)::date;
  v_month date;
  v_name  text;
  v_schema text;
  v_table  text;
  v_pai_protege boolean;
BEGIN
  SELECT n.nspname, c.relname, c.relrowsecurity INTO v_schema, v_table, v_pai_protege
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE c.oid = parent;

  FOR i IN 0 .. months - 1 LOOP
    v_month := (v_start + (i || ' months')::interval)::date;
    v_name  := format('%s_%s', v_table, to_char(v_month, 'YYYYMM'));
    IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE c.relname = v_name AND n.nspname = v_schema) THEN
      EXECUTE format('CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
        v_schema, v_name, v_schema, v_table,
        v_month, (v_month + interval '1 month')::date);
      PERFORM core.proteger_particao(v_schema, v_name, v_pai_protege);
    END IF;
  END LOOP;

  v_name := v_table || '_default';
  IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE c.relname = v_name AND n.nspname = v_schema) THEN
    EXECUTE format('CREATE TABLE %I.%I PARTITION OF %I.%I DEFAULT',
      v_schema, v_name, v_schema, v_table);
    PERFORM core.proteger_particao(v_schema, v_name, v_pai_protege);
  END IF;
END;
$$;

COMMENT ON FUNCTION core.ensure_month_partitions IS
  '[F19] Cria as partições mensais e a DEFAULT. Desde a migration 56 ela também PROTEGE a '
  'partição criada quando o pai é protegido: sem isso, cada execução mensal reabria o '
  'vazamento — consultar a partição direto aplica a política DELA, não a do pai, e as trinta '
  'que existiam não tinham nenhuma. Decisão pendente (README §6.1): pg_partman vs. cron próprio.';

COMMENT ON FUNCTION core.proteger_particao IS
  '[F19] Liga RLS+FORCE e cria `scope_isolation` numa partição recém-criada, igual à do pai. '
  'Existe separada para que `ensure_month_partitions` continue legível e para que um backfill '
  'manual de partição possa chamá-la sozinha.';

-- -----------------------------------------------------------------------------
-- (b) As filhas que chegam ao cliente por CHAVE ESTRANGEIRA
--
-- `planning.model_portfolio_versions` fica FORA de propósito: carteira modelo é produto
-- GLOBAL, e o `run_id` dela é proveniência de qual execução a publicou, não dono. Política ali
-- esconderia o catálogo de todo mundo — o oposto do que se quer.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  t record;
BEGIN
  FOR t IN
    SELECT * FROM (VALUES
      ('billing',     'payments',             'invoice_id',          'billing.invoices'),
      ('decisions',   'rationale_items',      'record_id',           'decisions.records'),
      ('decisions',   'inputs',               'record_id',           'decisions.records'),
      ('diagnostics', 'finding_observations', 'finding_id',          'diagnostics.findings'),
      ('engine',      'artifacts',            'run_id',              'engine.runs'),
      ('engine',      'run_inputs',           'run_id',              'engine.runs'),
      ('planning',    'target_allocations',   'target_portfolio_id', 'planning.target_portfolios'),
      ('wealth',      'sync_runs',            'connection_id',       'wealth.connections')
    ) AS x(schema_name, table_name, fk_col, pai)
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schema_name, t.table_name);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',  t.schema_name, t.table_name);
    -- `EXISTS` sobre o pai, e não uma cópia do scope_id: duplicar a coluna criaria uma segunda
    -- fonte da verdade sobre de quem é a linha, que é o defeito que a 53 acabou de fechar no
    -- rollup da carteira. A subconsulta atravessa a RLS do pai, então herda a mesma regra.
    --
    -- Vale para ESCRITA também: `FOR ALL` sem `WITH CHECK` usa o `USING` como verificação, e
    -- `second_opinion.py` insere `decisions.records` e depois `rationale_items` na MESMA
    -- transação sob `app_session` — o pai já está lá e visível quando a filha entra.
    EXECUTE format($p$
      CREATE POLICY scope_isolation ON %I.%I FOR ALL
        USING (core.is_service()
               OR EXISTS (SELECT 1 FROM %s pai
                           WHERE pai.id = %I.%I.%I
                             AND pai.scope_id::text = current_setting('app.scope_id', true)))
    $p$, t.schema_name, t.table_name, t.pai, t.schema_name, t.table_name, t.fk_col);
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- (c) O que o papel de aplicação não deveria nem poder ler
--
-- A 28 concedeu `SELECT ... ON ALL TABLES` nos 24 schemas e revogou só UPDATE/DELETE das
-- append-only. Estas nove são internas — nenhuma é tocada por `app/` — e várias cruzam
-- usuários por desenho, o que torna política de escopo a ferramenta errada.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
      'audit.pii_access',                  -- LGPD art. 37: quem acessou PII de quem
      'billing.provider_webhook_events',   -- payload cru do provedor de pagamento
      'billing.discount_codes',            -- cupom é dado comercial, não do cliente
      'content.compliance_reviews',        -- trilha interna de revisão
      'docs.document_reviews',             -- idem (escrita sob serviço, cli.py:672)
      'engine.golden_masters',             -- referência de teste do motor
      'analytics.events',                  -- encerra a exceção do T49
      'analytics.leads',                   -- e-mail de lead: marketing, não produto
      'analytics.experiments',
      'analytics.experiment_assignments'
  ] LOOP
    EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE ON %s FROM plexo_app', t);
  END LOOP;
END $$;

COMMENT ON TABLE audit.pii_access IS
  '[F19] Registro de acesso a PII (LGPD art. 37). `plexo_app` NÃO tem privilégio aqui, e isso é '
  'deliberado: a tabela é sobre quem acessou o dado de quem, então cruza usuários por natureza e '
  'política de escopo a destruiria. Se o direito do art. 18 (o titular ver quem acessou seus '
  'dados) virar produto, ele é endpoint sob serviço, não GRANT ao papel de aplicação.';

COMMIT;
