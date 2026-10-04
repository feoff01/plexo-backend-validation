-- =============================================================================
-- SYNAPTA · 28_roles_grants.sql
-- Papéis de aplicação (NOLOGIN) e privilégios.
--
-- Até aqui o banco só conhecia o papel administrador — que na Aiven carrega
-- BYPASSRLS. Ou seja: FORCE ROW LEVEL SECURITY existia, mas ninguém passava por
-- ele. Esta migration cria a fronteira real:
--
--   plexo_app      — API/web. NOBYPASSRLS. Enxerga só o escopo/usuário dos GUCs
--                    app.scope_id / app.user_id. Declarar app.role='service' não
--                    lhe dá nada (ver core.is_service em 00_core).
--   plexo_service  — jobs, backfills, motor. NOBYPASSRLS. core.is_service() só é
--                    verdadeira para MEMBRO deste papel com app.role='service'
--                    na sessão — a intenção precisa ser declarada.
--
-- Logins com senha NÃO ficam no repositório. Ops cria o login e concede:
--   GRANT plexo_app     TO <login_da_api>;
--   GRANT plexo_service TO <login_dos_jobs>;
--
-- Privilégio segue o padrão T10 (trigger + privilégio): toda tabela cujo trigger
-- core.forbid_update_delete é INCONDICIONAL (sem WHEN) perde UPDATE/DELETE para
-- os dois papéis — lista derivada do catálogo, não mantida à mão.
--
-- Fora daqui, de propósito: REFRESH MATERIALIZED VIEW (exige o dono — job roda
-- como administrador) e privilégio em partições criadas no futuro por
-- core.ensure_month_partitions (acesso via tabela-pai usa o privilégio do pai;
-- ALTER DEFAULT PRIVILEGES cobre o DML básico das filhas novas).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Papéis (idempotente: papel é global ao cluster, pode preexistir)
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'plexo_app') THEN
    CREATE ROLE plexo_app     NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION INHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'plexo_service') THEN
    CREATE ROLE plexo_service NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION INHERIT;
  END IF;
  -- Quem migra pode assumir os papéis (SET ROLE) para testar, sem herdar
  -- privilégios deles. Em provedor com createrole_self_grant isso já vale;
  -- em PG local o superusuário não precisa. Falha aqui não é fatal.
  BEGIN
    EXECUTE format('GRANT plexo_app, plexo_service TO %I WITH SET TRUE, INHERIT FALSE', current_user);
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'GRANT dos papéis ao migrador ignorado: %', sqlerrm;
  END;
END $$;

-- -----------------------------------------------------------------------------
-- Privilégios: USAGE nos schemas, DML nas tabelas/views, sequences, defaults
-- -----------------------------------------------------------------------------
DO $$
DECLARE s text; t record;
BEGIN
  FOREACH s IN ARRAY ARRAY[
    'core','identity','engine','billing','market','wealth','diagnostics','planning',
    'budget','content','copilot','ledger','analytics','audit',
    'agents','tools','llm','analysis','context',
    'household','estate','preferences','decisions'] LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO plexo_app, plexo_service', s);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO plexo_app, plexo_service', s);
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO plexo_app, plexo_service', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO plexo_app, plexo_service', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO plexo_app, plexo_service', s);
  END LOOP;

  -- Append-only por privilégio: onde o trigger core.forbid_update_delete é
  -- incondicional, nem o serviço tem UPDATE/DELETE. Inclui partições filhas
  -- (trigger clonado) — acesso direto à partição também fica fechado.
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
    GROUP BY 1, 2
  LOOP
    IF t.upd THEN EXECUTE format('REVOKE UPDATE ON %I.%I FROM plexo_app, plexo_service', t.nspname, t.relname); END IF;
    IF t.del THEN EXECUTE format('REVOKE DELETE ON %I.%I FROM plexo_app, plexo_service', t.nspname, t.relname); END IF;
  END LOOP;
END $$;

COMMENT ON ROLE plexo_app IS
  'Papel da API. NOBYPASSRLS; isolamento por app.scope_id/app.user_id. Nunca recebe LOGIN direto — conceda a um login.';
COMMENT ON ROLE plexo_service IS
  'Papel de jobs/motor. NOBYPASSRLS; core.is_service() exige membro deste papel E app.role=service.';

COMMIT;
