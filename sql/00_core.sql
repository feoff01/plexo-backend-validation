-- =============================================================================
-- SYNAPTA · 00_core.sql
-- Fundação: extensões, schemas, domains financeiros e funções transversais.
--
-- CONVENÇÕES (valem para todo o banco):
--   · Dinheiro é numeric, NUNCA float.
--   · timestamptz sempre; date para data de negócio (D-1).
--   · UUID v7 quando disponível (PG 18+), v4 como fallback — core.new_id().
--   · Append-only via core.forbid_update_delete(), nunca só por convenção.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid(), digest()

-- -----------------------------------------------------------------------------
-- Schemas — espelham os serviços do monolito modular (§11.2)
-- -----------------------------------------------------------------------------
CREATE SCHEMA core;
CREATE SCHEMA identity;
CREATE SCHEMA billing;
CREATE SCHEMA market;
CREATE SCHEMA wealth;
CREATE SCHEMA engine;
CREATE SCHEMA diagnostics;
CREATE SCHEMA planning;
CREATE SCHEMA budget;
CREATE SCHEMA content;
CREATE SCHEMA copilot;
CREATE SCHEMA ledger;
CREATE SCHEMA analytics;
CREATE SCHEMA audit;

-- -----------------------------------------------------------------------------
-- Domains — o tipo carrega a regra
-- -----------------------------------------------------------------------------
CREATE DOMAIN core.money_brl   AS numeric(18,2);
CREATE DOMAIN core.quantity    AS numeric(28,10);
CREATE DOMAIN core.weight      AS numeric(8,6)  CHECK (VALUE >= 0 AND VALUE <= 1);
CREATE DOMAIN core.rate_annual AS numeric(9,6);                 -- 0.145 = 14,5% a.a.
CREATE DOMAIN core.confidence  AS numeric(4,3)  CHECK (VALUE >= 0 AND VALUE <= 1);
CREATE DOMAIN core.currency    AS char(3)       CHECK (VALUE ~ '^[A-Z]{3}$');
CREATE DOMAIN core.hash_hex    AS char(64)      CHECK (VALUE ~ '^[0-9a-f]{64}$');
CREATE DOMAIN core.email       AS text          CHECK (VALUE ~* '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$');
CREATE DOMAIN core.slug        AS text          CHECK (VALUE ~ '^[a-z0-9][a-z0-9._-]*$' AND length(VALUE) <= 120);
CREATE DOMAIN core.config_code AS text          CHECK (VALUE ~ '^[A-Z][A-Z0-9_]*$' AND length(VALUE) <= 60);

COMMENT ON DOMAIN core.money_brl IS
  'Dinheiro NUNCA é float. numeric(18,2) cobre até centenas de trilhões com centavos.';

-- -----------------------------------------------------------------------------
-- core.new_id() — UUID v7 (ordenável por tempo) quando o servidor tiver;
-- v4 como fallback. Corpo decidido em tempo de migração, custo zero por chamada.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE p.proname = 'uuidv7' AND n.nspname = 'pg_catalog') THEN
    EXECUTE 'CREATE FUNCTION core.new_id() RETURNS uuid LANGUAGE sql VOLATILE
             PARALLEL SAFE AS $f$ SELECT uuidv7() $f$';
  ELSE
    EXECUTE 'CREATE FUNCTION core.new_id() RETURNS uuid LANGUAGE sql VOLATILE
             PARALLEL SAFE AS $f$ SELECT gen_random_uuid() $f$';
  END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- Funções de trigger transversais
-- -----------------------------------------------------------------------------
CREATE FUNCTION core.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

CREATE FUNCTION core.forbid_update_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '%.% é append-only — % não é permitido',
    TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = '42501';
END;
$$;

-- Hash canônico de payloads jsonb. jsonb já normaliza ordem de chaves e
-- espaços, então payload::text é determinístico — condição para IMMUTABLE
-- e, portanto, para uso em colunas geradas (policy_versions.content_hash).
CREATE FUNCTION core.canonical_hash(payload jsonb) RETURNS core.hash_hex
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT encode(digest(convert_to(payload::text, 'UTF8'), 'sha256'), 'hex')::core.hash_hex
$$;

-- -----------------------------------------------------------------------------
-- [validação PG real] Bypass de RLS para o serviço — amarrado ao PAPEL de banco.
-- Antes, as políticas comparavam current_setting('app.role') = 'service': uma
-- string que qualquer conexão (inclusive a da API) podia setar. Agora o bypass
-- exige as DUAS coisas: a sessão declarar app.role='service' E o papel corrente
-- ser membro de plexo_service (criado em 28_roles_grants). A API (plexo_app) não
-- escala por GUC nem por SQL injection. Sem o papel existir, é sempre falso.
-- -----------------------------------------------------------------------------
CREATE FUNCTION core.is_service() RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT current_setting('app.role', true) = 'service'
     AND EXISTS (SELECT 1 FROM pg_roles r
                 WHERE r.rolname = 'plexo_service'
                   AND pg_has_role(current_user, r.oid, 'MEMBER'))
$$;

-- -----------------------------------------------------------------------------
-- Particionamento mensal — usada por 14_rls_partitions e pelo job de manutenção.
-- Cria as partições [from_month, from_month + months) e a partição DEFAULT
-- (nenhuma escrita falha por partição ausente; a DEFAULT é válvula de escape).
-- -----------------------------------------------------------------------------
CREATE FUNCTION core.ensure_month_partitions(parent regclass, from_month date, months int)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  v_start date := date_trunc('month', from_month)::date;
  v_month date;
  v_name  text;
  v_schema text;
  v_table  text;
BEGIN
  SELECT n.nspname, c.relname INTO v_schema, v_table
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
    END IF;
  END LOOP;

  v_name := v_table || '_default';
  IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE c.relname = v_name AND n.nspname = v_schema) THEN
    EXECUTE format('CREATE TABLE %I.%I PARTITION OF %I.%I DEFAULT',
      v_schema, v_name, v_schema, v_table);
  END IF;
END;
$$;

COMMENT ON FUNCTION core.ensure_month_partitions IS
  'Decisão pendente (README §6.1): pg_partman vs. cron próprio. Enquanto isso, '
  'esta função + um job mensal cobrem o MVP. A partição DEFAULT garante que '
  'nenhuma escrita falhe — mover linhas dela para a partição certa é manutenção.';

COMMIT;
