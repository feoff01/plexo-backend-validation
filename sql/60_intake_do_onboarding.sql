-- =============================================================================
-- SYNAPTA · 60_intake_do_onboarding.sql
-- [22ª onda — F21b] Intake do onboarding: texto/arquivo/áudio → extração por IA →
-- itens PROPOSTOS → confirmação do próprio usuário → fatos e estrutura.
--
-- A cadeia de extração de CONVERSAS (21/22/38/39/58: run → sinal → proposta) fica
-- INTACTA. O intake tem tabelas e gates próprios porque o bullet "Objetivo: carro
-- de 80 mil em 2 anos" é uma ENTIDADE composta (nome+valor+prazo), que não cabe
-- numa change_proposal de UM fato — mas o padrão epistêmico é o MESMO de C21/C22a:
--   · item nasce 'proposto' — nunca confirmado (C60a);
--   · só o PRÓPRIO usuário confirma (self_confirmation_only);
--   · o payload proposto é imutável — o que se confirma é o que a IA propôs (C60b);
--   · a evidência (texto/mídia) congela no recebimento (C60d);
--   · teto de bytes e quota diária são CONFIG (policy ONBOARDING_EXTRACAO, C60c).
-- =============================================================================

BEGIN;

CREATE TYPE context.intake_kind        AS ENUM ('texto', 'arquivo', 'audio');
CREATE TYPE context.intake_status      AS ENUM ('recebido', 'aguardando_provedor', 'falhou', 'extraido');
CREATE TYPE context.intake_item_kind   AS ENUM ('fato', 'objetivo', 'divida', 'bem');
CREATE TYPE context.intake_item_status AS ENUM ('proposto', 'confirmado', 'rejeitado');

-- -----------------------------------------------------------------------------
-- Submissões — o que o cliente enviou, congelado como evidência
-- -----------------------------------------------------------------------------
CREATE TABLE context.intake_submissions (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id      uuid NOT NULL REFERENCES identity.scopes(id),
  user_id       uuid NOT NULL REFERENCES identity.users(id),
  passo         text NOT NULL,                      -- passo do wizard de onde veio
  kind          context.intake_kind NOT NULL,
  body_text     text,                               -- texto direto OU transcrição
  media         bytea,                              -- áudio/arquivo cru (teto por policy)
  media_mime    text,
  media_sha256  core.hash_hex,                      -- mídia sem hash não é evidência
  status        context.intake_status NOT NULL DEFAULT 'recebido',
  error_detail  text,
  extracted_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT texto_tem_corpo CHECK (
    kind <> 'texto' OR (body_text IS NOT NULL AND media IS NULL)
  ),
  CONSTRAINT binario_tem_midia CHECK (
    kind = 'texto' OR (media IS NOT NULL AND media_mime IS NOT NULL AND media_sha256 IS NOT NULL)
  )
);
CREATE INDEX intake_submissions_scope_idx ON context.intake_submissions (scope_id, created_at DESC);
CREATE INDEX intake_submissions_pendentes_idx ON context.intake_submissions (status)
  WHERE status IN ('recebido', 'aguardando_provedor');

COMMENT ON TABLE context.intake_submissions IS
  'F21b — o que o cliente contou no onboarding (texto livre, arquivo ou áudio), congelado. '
  'A extração por IA produz intake_items PROPOSTOS; nada vira fato ou estrutura sem a '
  'confirmação explícita do próprio usuário. Mídia binária vive aqui (bytea) com teto por '
  'policy — sem storage externo no stack, por decisão da etapa (2026-08-31).';
COMMENT ON COLUMN context.intake_submissions.body_text IS
  'Texto direto (kind=texto) ou transcrição preenchida DEPOIS (kind=audio/arquivo). '
  'Uma vez preenchido, imutável (C60d): é a evidência do que os itens propuseram.';

-- -----------------------------------------------------------------------------
-- Itens extraídos — a proposta da IA, um a um, esperando o "sim" do cliente
-- -----------------------------------------------------------------------------
CREATE TABLE context.intake_items (
  id            uuid PRIMARY KEY DEFAULT core.new_id(),
  submission_id uuid NOT NULL REFERENCES context.intake_submissions(id),
  scope_id      uuid NOT NULL REFERENCES identity.scopes(id),
  user_id       uuid NOT NULL REFERENCES identity.users(id),
  seq           int  NOT NULL,
  kind          context.intake_item_kind NOT NULL,
  fact_key      core.slug REFERENCES context.fact_definitions(fact_key),
  payload       jsonb NOT NULL,
  status        context.intake_item_status NOT NULL DEFAULT 'proposto',
  confirmed_at  timestamptz,
  confirmed_by  uuid REFERENCES identity.users(id),
  rejected_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),

  UNIQUE (submission_id, seq),
  CONSTRAINT payload_is_object CHECK (jsonb_typeof(payload) = 'object'),
  CONSTRAINT fato_tem_chave CHECK (kind <> 'fato' OR fact_key IS NOT NULL),
  CONSTRAINT confirmado_carimbado CHECK (
    status <> 'confirmado' OR (confirmed_at IS NOT NULL AND confirmed_by IS NOT NULL)
  ),
  -- quem confirma o próprio contexto é o PRÓPRIO usuário (mesmo padrão do C21/C22)
  CONSTRAINT self_confirmation_only CHECK (confirmed_by IS NULL OR confirmed_by = user_id),
  CONSTRAINT rejeitado_carimbado CHECK (status <> 'rejeitado' OR rejected_at IS NOT NULL)
);
CREATE INDEX intake_items_submission_idx ON context.intake_items (submission_id, seq);
CREATE INDEX intake_items_pendentes_idx ON context.intake_items (scope_id)
  WHERE status = 'proposto';

COMMENT ON TABLE context.intake_items IS
  'Cada bullet que a IA extraiu de uma submissão do onboarding. kind=fato aponta para o '
  'catálogo (vocabulário fechado); objetivo/divida/bem carregam a entidade composta no '
  'payload. Confirmar escreve fato (source=onboarding) ou estrutura (planning.goals, '
  'budget.debts, estate.assets) — nunca antes.';

-- ---------------------------------------------------------------- C60a
-- Item nasce 'proposto', com os carimbos zerados. Sem isso, bastaria o extrator
-- inserir status='confirmado' e o gate epistêmico inteiro sumiria — a mesma razão
-- de existir do C22a nas asserções.
CREATE FUNCTION context.assert_intake_item_nasce_proposto() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status <> 'proposto' THEN
    RAISE EXCEPTION 'C60a — item de intake nasce "proposto", nunca "%". Confirmação é um '
      'segundo ato, do próprio usuário.', NEW.status USING ERRCODE = '23514';
  END IF;
  IF NEW.confirmed_at IS NOT NULL OR NEW.confirmed_by IS NOT NULL OR NEW.rejected_at IS NOT NULL THEN
    RAISE EXCEPTION 'C60a — item recém-proposto não carrega carimbo de decisão'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER intake_items_nascem_propostos BEFORE INSERT ON context.intake_items
  FOR EACH ROW EXECUTE FUNCTION context.assert_intake_item_nasce_proposto();

-- ---------------------------------------------------------------- C60b
-- Transições legais: proposto→confirmado e proposto→rejeitado, e mais nada.
-- Payload e identidade do item são imutáveis SEMPRE: o que o cliente confirma é o
-- que a IA propôs — payload editável quebraria a trilha da confirmação.
CREATE FUNCTION context.assert_intake_item_transicao() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.payload IS DISTINCT FROM OLD.payload
     OR NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.fact_key IS DISTINCT FROM OLD.fact_key
     OR NEW.seq IS DISTINCT FROM OLD.seq
     OR NEW.submission_id IS DISTINCT FROM OLD.submission_id
     OR NEW.scope_id IS DISTINCT FROM OLD.scope_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'C60b — payload e identidade do item são imutáveis; o que se confirma '
      'é o que a IA propôs' USING ERRCODE = '23514';
  END IF;
  IF OLD.status <> 'proposto' THEN
    RAISE EXCEPTION 'C60b — item "%" é terminal e imutável (refazer é nova submissão)',
      OLD.status USING ERRCODE = '23514';
  END IF;
  IF NEW.status NOT IN ('confirmado', 'rejeitado') THEN
    RAISE EXCEPTION 'C60b — de "proposto" só se vai a "confirmado" ou "rejeitado"'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.status = 'rejeitado' AND (NEW.confirmed_at IS NOT NULL OR NEW.confirmed_by IS NOT NULL) THEN
    RAISE EXCEPTION 'C60b — item rejeitado não carrega carimbo de confirmação'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.status = 'confirmado' AND NEW.rejected_at IS NOT NULL THEN
    RAISE EXCEPTION 'C60b — item confirmado não carrega carimbo de rejeição'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER intake_items_transicao BEFORE UPDATE ON context.intake_items
  FOR EACH ROW EXECUTE FUNCTION context.assert_intake_item_transicao();

-- ---------------------------------------------------------------- C60c
-- Teto de bytes e quota diária vêm da policy ONBOARDING_EXTRACAO (config-first,
-- mesmo padrão de identity.enforce_member_limit lendo FAMILY_LIMITS). Fallbacks
-- documentados aqui: 10 MiB por mídia, 20 submissões/dia por escopo.
CREATE FUNCTION context.assert_intake_dentro_da_policy() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_payload   jsonb;
  v_max_bytes bigint;
  v_max_dia   int;
  v_hoje      int;
BEGIN
  SELECT payload INTO v_payload
  FROM engine.policy_versions
  WHERE code = 'ONBOARDING_EXTRACAO' AND effective_to IS NULL
  ORDER BY effective_from DESC LIMIT 1;

  v_max_bytes := coalesce((v_payload ->> 'max_bytes_media')::bigint, 10485760);
  v_max_dia   := coalesce((v_payload ->> 'max_submissoes_por_dia_por_escopo')::int, 20);

  IF NEW.media IS NOT NULL AND octet_length(NEW.media) > v_max_bytes THEN
    RAISE EXCEPTION 'C60c — mídia de % bytes excede o teto de % da policy ONBOARDING_EXTRACAO',
      octet_length(NEW.media), v_max_bytes USING ERRCODE = '23514';
  END IF;

  SELECT count(*) INTO v_hoje FROM context.intake_submissions
  WHERE scope_id = NEW.scope_id AND created_at::date = current_date;
  IF v_hoje >= v_max_dia THEN
    RAISE EXCEPTION 'C60c — escopo % já enviou % submissões hoje (teto da policy: %)',
      NEW.scope_id, v_hoje, v_max_dia USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER intake_submissions_policy_gate BEFORE INSERT ON context.intake_submissions
  FOR EACH ROW EXECUTE FUNCTION context.assert_intake_dentro_da_policy();

-- ---------------------------------------------------------------- C60d
-- A evidência congela no recebimento: mídia, hash, tipo e passo nunca mudam;
-- body_text só transiciona de NULL para valor (a transcrição PREENCHE, não troca).
-- Status anda só para frente: recebido(0) → aguardando_provedor(1) → falhou(2) →
-- extraido(3); falhou→extraido é o retry legítimo depois de plugar o provedor.
CREATE FUNCTION context.assert_intake_submission_transicao() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_rank_old int;
  v_rank_new int;
BEGIN
  IF NEW.media IS DISTINCT FROM OLD.media
     OR NEW.media_mime IS DISTINCT FROM OLD.media_mime
     OR NEW.media_sha256 IS DISTINCT FROM OLD.media_sha256
     OR NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.passo IS DISTINCT FROM OLD.passo
     OR NEW.scope_id IS DISTINCT FROM OLD.scope_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'C60d — mídia, hash, tipo e origem da submissão são imutáveis'
      USING ERRCODE = '23514';
  END IF;
  IF OLD.body_text IS NOT NULL AND NEW.body_text IS DISTINCT FROM OLD.body_text THEN
    RAISE EXCEPTION 'C60d — body_text preenchido é evidência congelada: não se troca nem se apaga'
      USING ERRCODE = '23514';
  END IF;
  v_rank_old := CASE OLD.status WHEN 'recebido' THEN 0 WHEN 'aguardando_provedor' THEN 1
                                WHEN 'falhou' THEN 2 ELSE 3 END;
  v_rank_new := CASE NEW.status WHEN 'recebido' THEN 0 WHEN 'aguardando_provedor' THEN 1
                                WHEN 'falhou' THEN 2 ELSE 3 END;
  IF v_rank_new < v_rank_old THEN
    RAISE EXCEPTION 'C60d — status da submissão não anda para trás (% → %)',
      OLD.status, NEW.status USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER intake_submissions_transicao BEFORE UPDATE ON context.intake_submissions
  FOR EACH ROW EXECUTE FUNCTION context.assert_intake_submission_transicao();

-- ---------------------------------------------------------------- RLS
-- Mesmo texto da política padrão da migration 14: o usuário só vê e escreve o
-- próprio escopo; o serviço, tudo.
ALTER TABLE context.intake_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE context.intake_submissions FORCE  ROW LEVEL SECURITY;
CREATE POLICY scope_isolation ON context.intake_submissions FOR ALL
  USING (core.is_service() OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service() OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE context.intake_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE context.intake_items FORCE  ROW LEVEL SECURITY;
CREATE POLICY scope_isolation ON context.intake_items FOR ALL
  USING (core.is_service() OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service() OR scope_id::text = current_setting('app.scope_id', true));

-- ---------------------------------------------------------------- purpose novo
-- Transcrição de áudio/arquivo é chamada de provedor com custo próprio; o valor
-- entra AGORA e o primeiro uso fica para a F21d (convenção 33: ADD VALUE sem
-- CAST/uso na mesma migration).
ALTER TYPE llm.call_purpose ADD VALUE IF NOT EXISTS 'transcricao';

-- ---------------------------------------------------------------- policy seed
-- Números do intake como DADO (config-first): teto de bytes, quota diária, teto de
-- itens por submissão e orçamento da chamada de extração. Nasce draft; aprovação é
-- ato humano de compliance (lista client-facing do ESTADO §5).
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'ONBOARDING_EXTRACAO', 1,
       '{"max_bytes_media": 10485760, "max_submissoes_por_dia_por_escopo": 20, '
       ' "max_itens_por_submissao": 12, "max_output_tokens": 6000, "temperatura": 0.0}'::jsonb,
       'draft', now()
WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'ONBOARDING_EXTRACAO');

COMMIT;
