-- =============================================================================
-- SYNAPTA · 14_rls_partitions.sql
-- (a) RLS habilitada e FORÇADA em toda tabela com scope_id.
-- (b) Partições mensais iniciais das 4 tabelas particionadas + DEFAULT.
--
-- CONVENÇÃO DE SESSÃO (contrato com a aplicação):
--   SET app.user_id  = '<uuid>';
--   SET app.scope_id = '<uuid do escopo selecionado no header>';
--   SET app.role     = 'user' | 'service';   -- 'service' = jobs/backfills
--   [validação PG real] 'service' só vale para membro do papel plexo_service
--   (core.is_service, 28_roles_grants). Para plexo_app o GUC não dá nada.
--
-- FORCE ROW LEVEL SECURITY: a política vale até para o dono da tabela.
-- Vazamento entre escopos não é bug de aplicação — é impossibilidade de banco.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- (a) RLS — uma política padrão, aplicada por lista curada
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  t record;
BEGIN
  FOR t IN
    SELECT * FROM (VALUES
      ('identity',    'scope_members'),
      ('identity',    'suitability_assessments'),
      ('engine',      'runs'),
      ('billing',     'subscriptions'),
      ('billing',     'subscription_events'),
      ('billing',     'invoices'),
      ('wealth',      'connections'),
      ('wealth',      'accounts'),
      ('wealth',      'statement_uploads'),
      ('wealth',      'holdings_snapshots'),
      ('wealth',      'portfolio_snapshots'),
      ('wealth',      'transactions'),
      ('wealth',      'account_balances'),
      ('diagnostics', 'findings'),
      ('diagnostics', 'actions'),
      ('diagnostics', 'action_events'),
      ('diagnostics', 'foundation_status'),
      ('diagnostics', 'portfolio_scores'),
      ('diagnostics', 'coverage_reports'),
      ('diagnostics', 'gate_reveals'),
      ('planning',    'goals'),
      ('planning',    'goal_projections'),
      ('planning',    'target_portfolios'),
      ('planning',    'model_adoptions'),
      ('planning',    'drift_evaluations'),
      ('planning',    'contribution_routings'),
      ('planning',    'calendar_events'),
      ('planning',    'scenario_simulations'),
      ('budget',      'cash_events'),
      ('budget',      'recurring_items'),
      ('budget',      'monthly_summaries'),
      ('budget',      'debts'),
      ('budget',      'reserve_settings'),
      ('content',     'signals'),
      ('content',     'user_reports'),
      ('content',     'notifications'),
      ('copilot',     'conversations'),
      ('copilot',     'messages'),
      ('copilot',     'usage_counters'),
      ('copilot',     'guardrail_events'),
      ('copilot',     'message_feedback'),
      ('ledger',      'value_entries'),
      ('ledger',      'monthly_rollups'),
      ('analytics',   'paywall_impressions'),
      ('audit',       'activity_log')
    ) AS x(schema_name, table_name)
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schema_name, t.table_name);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',  t.schema_name, t.table_name);
    EXECUTE format($p$
      CREATE POLICY scope_isolation ON %I.%I FOR ALL
        USING (core.is_service()
               OR scope_id::text = current_setting('app.scope_id', true))
        WITH CHECK (core.is_service()
               OR scope_id::text = current_setting('app.scope_id', true))
    $p$, t.schema_name, t.table_name);
  END LOOP;
END;
$$;

-- identity.scopes não tem scope_id (é o escopo) — política própria:
-- o usuário vê escopos onde é membro não-revogado ou dono; service vê tudo.
ALTER TABLE identity.scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity.scopes FORCE  ROW LEVEL SECURITY;
CREATE POLICY scopes_membership ON identity.scopes FOR ALL
  USING (
    core.is_service()
    OR owner_user_id::text = current_setting('app.user_id', true)
    OR EXISTS (SELECT 1 FROM identity.scope_members m
               WHERE m.scope_id = scopes.id
                 AND m.user_id::text = current_setting('app.user_id', true)
                 AND m.revoked_at IS NULL)
  )
  WITH CHECK (
    core.is_service()
    OR owner_user_id::text = current_setting('app.user_id', true)
  );

COMMENT ON POLICY scopes_membership ON identity.scopes IS
  'scope_members também tem RLS por scope_id; a subconsulta daqui enxerga apenas as '
  'linhas que a política de scope_members permitir — para o papel service, todas.';

-- content.letters: carta GERAL (scope_id NULL) é pública para qualquer usuário
-- autenticado; carta personalizada segue o isolamento padrão.
ALTER TABLE content.letters ENABLE ROW LEVEL SECURITY;
ALTER TABLE content.letters FORCE  ROW LEVEL SECURITY;
CREATE POLICY letters_visibility ON content.letters FOR ALL
  USING (
    core.is_service()
    OR (scope_id IS NULL AND published_at IS NOT NULL)
    OR scope_id::text = current_setting('app.scope_id', true)
  )
  WITH CHECK (core.is_service());

-- -----------------------------------------------------------------------------
-- [validação PG real] (a2) RLS por USUÁRIO — tabelas de PII sem scope_id.
-- Mesma regra, outra chave: o usuário só vê e escreve o que é dele; o serviço,
-- tudo. Sem isto, o papel da API lia o perfil de todos os usuários.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  t record;
BEGIN
  FOR t IN
    SELECT * FROM (VALUES
      ('identity', 'auth_identities'),
      ('identity', 'user_profiles'),
      ('identity', 'consents'),
      ('identity', 'erasure_requests'),
      ('content',  'notification_preferences')
    ) AS x(schema_name, table_name)
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schema_name, t.table_name);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',  t.schema_name, t.table_name);
    EXECUTE format($p$
      CREATE POLICY user_isolation ON %I.%I FOR ALL
        USING (core.is_service() OR user_id::text = current_setting('app.user_id', true))
        WITH CHECK (core.is_service() OR user_id::text = current_setting('app.user_id', true))
    $p$, t.schema_name, t.table_name);
  END LOOP;

  -- analytics pré-cadastro: user_id NULL é evento anônimo — qualquer sessão
  -- grava; só o serviço lê de volta. Com user_id, isolamento normal.
  FOR t IN
    SELECT * FROM (VALUES
      ('analytics', 'onboarding_steps'),
      ('analytics', 'wtp_surveys')
    ) AS x(schema_name, table_name)
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schema_name, t.table_name);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',  t.schema_name, t.table_name);
    EXECUTE format($p$
      CREATE POLICY user_isolation ON %I.%I FOR ALL
        USING (core.is_service() OR user_id::text = current_setting('app.user_id', true))
        WITH CHECK (core.is_service() OR user_id IS NULL
               OR user_id::text = current_setting('app.user_id', true))
    $p$, t.schema_name, t.table_name);
  END LOOP;
END;
$$;

-- identity.users: a chave é o próprio id. Cadastro e login-por-e-mail são
-- operações de serviço (ou a API seta app.user_id com o id que vai inserir).
ALTER TABLE identity.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity.users FORCE  ROW LEVEL SECURITY;
CREATE POLICY users_self ON identity.users FOR ALL
  USING (core.is_service() OR id::text = current_setting('app.user_id', true))
  WITH CHECK (core.is_service() OR id::text = current_setting('app.user_id', true));

-- Observações de escopo:
--   · analytics.events NÃO recebe RLS (eventos anônimos de landing precisam
--     existir antes de haver usuário/escopo; escrita é sempre 'service').
--   · engine.runs entra na lista acima: runs globais (scope_id NULL) ficam
--     visíveis só para 'service' — o usuário nunca consulta runs diretamente,
--     apenas os artefatos derivados.

-- -----------------------------------------------------------------------------
-- (b) Partições mensais: mês passado → +12 meses, mais a DEFAULT
-- -----------------------------------------------------------------------------
SELECT core.ensure_month_partitions('market.prices',
         (date_trunc('month', current_date) - interval '1 month')::date, 14);
SELECT core.ensure_month_partitions('wealth.holdings_snapshots',
         (date_trunc('month', current_date) - interval '1 month')::date, 14);
SELECT core.ensure_month_partitions('analytics.events',
         (date_trunc('month', current_date) - interval '1 month')::date, 14);
SELECT core.ensure_month_partitions('audit.activity_log',
         (date_trunc('month', current_date) - interval '1 month')::date, 14);

COMMIT;
