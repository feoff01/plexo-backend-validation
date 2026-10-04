-- =============================================================================
-- SYNAPTA · 30_content_education_gate.sql — [4ª onda] O Educador só ensina com conteúdo aprovado
-- -----------------------------------------------------------------------------
-- content.education_contents (09) já tinha review_status e o CHECK "published_at só com approved".
-- Faltava o que o Educador (F4) exige do BANCO, não da aplicação:
--   (a) uma superfície única do que pode chegar ao cliente: content.v_education_approved
--       (approved E published_at) — as tools `educacao.*` leem SÓ esta view;
--   (b) aprovar exige revisor identificado (reviewed_by/reviewed_at) e trilha em
--       content.compliance_reviews (subject_kind='education') NA MESMA TRANSAÇÃO — o mesmo padrão
--       "approved ⇔ approved_at" dos prompts (19) e das políticas (02);
--   (c) sair de approved (despublicar/reabrir) também exige trilha;
--   (d) texto já aprovado é imutável no que o cliente lê: title/body_md só mudam depois de reabrir.
-- Índices para a busca do glossário (tags GIN; parcial sobre o que está publicado).
-- Sem RLS: conteúdo educativo é referência global (sem scope_id/user_id), como agent_definitions.
-- =============================================================================
BEGIN;

CREATE INDEX education_contents_tags_gin ON content.education_contents USING gin (tags);
CREATE INDEX education_contents_published_idx ON content.education_contents (level, slug)
  WHERE review_status = 'approved' AND published_at IS NOT NULL;

-- A única janela do Educador para o conteúdo. security_invoker por convenção (28), embora a
-- tabela-base não tenha RLS.
CREATE VIEW content.v_education_approved WITH (security_invoker = true) AS
SELECT id, slug, title, body_md, level, tags, reviewed_at, published_at, updated_at
FROM content.education_contents
WHERE review_status = 'approved' AND published_at IS NOT NULL;

-- REGRA INVIOLÁVEL: aprovação e reabertura de conteúdo educativo deixam trilha; texto aprovado
-- não muda por baixo do cliente.
CREATE OR REPLACE FUNCTION content.assert_education_review() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_mudou_status boolean := (TG_OP = 'INSERT') OR (OLD.review_status IS DISTINCT FROM NEW.review_status);
  v_era_aprovado boolean := (TG_OP = 'UPDATE') AND OLD.review_status = 'approved';
BEGIN
  -- (a) approved exige revisor identificado
  IF NEW.review_status = 'approved' AND (NEW.reviewed_by IS NULL OR NEW.reviewed_at IS NULL) THEN
    RAISE EXCEPTION 'Conteúdo educativo % aprovado sem revisor identificado (reviewed_by/reviewed_at)', NEW.slug
      USING ERRCODE = '23514';
  END IF;

  -- (d) texto aprovado é imutável: reabra (com trilha) antes de editar
  IF v_era_aprovado AND NOT v_mudou_status
     AND (OLD.title IS DISTINCT FROM NEW.title OR OLD.body_md IS DISTINCT FROM NEW.body_md) THEN
    RAISE EXCEPTION 'Conteúdo educativo % está aprovado: reabra a revisão antes de alterar título ou corpo', NEW.slug
      USING ERRCODE = '23514';
  END IF;

  -- (b)/(c) entrar ou sair de approved exige linha de trilha nesta transação com a mesma decisão
  IF v_mudou_status AND (NEW.review_status = 'approved' OR v_era_aprovado) THEN
    IF NOT EXISTS (
      SELECT 1 FROM content.compliance_reviews r
      WHERE r.subject_kind = 'education' AND r.subject_id = NEW.id
        AND r.decision = NEW.review_status
        AND r.decided_at >= transaction_timestamp()
    ) THEN
      RAISE EXCEPTION 'Conteúdo educativo % → % sem trilha em content.compliance_reviews nesta transação',
        NEW.slug, NEW.review_status USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER education_contents_review_gate BEFORE INSERT OR UPDATE ON content.education_contents
  FOR EACH ROW EXECUTE FUNCTION content.assert_education_review();

COMMENT ON VIEW content.v_education_approved IS
  '[4ª onda] Conteúdo educativo aprovado por compliance E publicado — única fonte das tools educacao.*.';
COMMENT ON FUNCTION content.assert_education_review() IS
  '[4ª onda] Gate: aprovar/reabrir conteúdo educativo exige revisor e trilha na mesma transação; texto aprovado é imutável.';

COMMIT;
