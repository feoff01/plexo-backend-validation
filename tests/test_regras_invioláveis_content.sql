-- =============================================================================
-- SYNAPTA · testes das regras invioláveis — conteúdo educativo (T54–T57, 30_content_education_gate)
-- O Educador só ensina com conteúdo APROVADO por compliance: o banco expõe a view
-- content.v_education_approved e recusa aprovação sem revisor/trilha, despublicação sem trilha
-- e alteração de texto já aprovado. Cada teste prova que o BANCO recusa — não a aplicação.
-- Rodar com: python tools/db_runner.py tests
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

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixtures
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('54545454-0000-0000-0000-000000000001', 't54@synapta.com.br', 'Revisor Compliance', 'active');

-- quatro conteúdos: draft, pending_review, approved sem published_at, approved publicado
INSERT INTO content.education_contents (id, slug, title, body_md, level, tags)
VALUES ('54545454-0000-0000-0000-00000000000a', 't54-rascunho',  'Rascunho',  'texto', 'basico', ARRAY['t54']),
       ('54545454-0000-0000-0000-00000000000b', 't54-pendente',  'Pendente',  'texto', 'basico', ARRAY['t54']),
       ('54545454-0000-0000-0000-00000000000c', 't54-aprovado',  'Aprovado',  'texto', 'basico', ARRAY['t54']),
       ('54545454-0000-0000-0000-00000000000d', 't54-publicado', 'Publicado', 'texto', 'basico', ARRAY['t54']);

UPDATE content.education_contents SET review_status = 'pending_review'
 WHERE id = '54545454-0000-0000-0000-00000000000b';

-- trilha de compliance para os dois aprovados (mesma transação — exigência do gate)
INSERT INTO content.compliance_reviews (subject_kind, subject_id, decision, reviewer_id, notes)
VALUES ('education', '54545454-0000-0000-0000-00000000000c', 'approved', '54545454-0000-0000-0000-000000000001', 't54'),
       ('education', '54545454-0000-0000-0000-00000000000d', 'approved', '54545454-0000-0000-0000-000000000001', 't54');

UPDATE content.education_contents
   SET review_status = 'approved', reviewed_by = '54545454-0000-0000-0000-000000000001', reviewed_at = now()
 WHERE id = '54545454-0000-0000-0000-00000000000c';

UPDATE content.education_contents
   SET review_status = 'approved', reviewed_by = '54545454-0000-0000-0000-000000000001', reviewed_at = now(),
       published_at = now()
 WHERE id = '54545454-0000-0000-0000-00000000000d';

-- ================================================================ TESTE 54
-- A view só devolve o que está aprovado E publicado: draft, pendente e aprovado-sem-publicar ficam fora.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM content.v_education_approved WHERE 't54' = ANY (tags)
$sql$, 1, 'T54  view v_education_approved devolve só aprovado+publicado');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM content.v_education_approved WHERE slug = 't54-publicado'
$sql$, 1, 'T54b o publicado aparece na view');

-- ================================================================ TESTE 55
-- Aprovar exige revisor identificado e trilha em compliance_reviews na mesma transação.
SELECT pg_temp.expect_fail($sql$
  UPDATE content.education_contents SET review_status = 'approved'
   WHERE id = '54545454-0000-0000-0000-00000000000a';
$sql$, 'T55  aprovar sem reviewed_by/reviewed_at');

SELECT pg_temp.expect_fail($sql$
  UPDATE content.education_contents
     SET review_status = 'approved', reviewed_by = '54545454-0000-0000-0000-000000000001', reviewed_at = now()
   WHERE id = '54545454-0000-0000-0000-00000000000a';
$sql$, 'T55b aprovar sem linha em compliance_reviews');

-- INSERT direto já aprovado sem trilha também é recusado
SELECT pg_temp.expect_fail($sql$
  INSERT INTO content.education_contents (id, slug, title, body_md, review_status, reviewed_by, reviewed_at)
  VALUES ('54545454-0000-0000-0000-00000000000e', 't54-direto', 'Direto', 'texto', 'approved',
          '54545454-0000-0000-0000-000000000001', now());
$sql$, 'T55c INSERT já aprovado sem trilha');

-- ================================================================ TESTE 56
-- Conteúdo aprovado é imutável no que o cliente lê: alterar título/corpo é recusado;
-- sair de approved (despublicar) exige nova linha de trilha.
SELECT pg_temp.expect_fail($sql$
  UPDATE content.education_contents SET body_md = 'texto alterado sem revisão'
   WHERE id = '54545454-0000-0000-0000-00000000000d';
$sql$, 'T56  alterar body_md de conteúdo aprovado');

SELECT pg_temp.expect_fail($sql$
  UPDATE content.education_contents SET title = 'Título alterado sem revisão'
   WHERE id = '54545454-0000-0000-0000-00000000000d';
$sql$, 'T56b alterar title de conteúdo aprovado');

SELECT pg_temp.expect_fail($sql$
  UPDATE content.education_contents SET review_status = 'draft', published_at = NULL
   WHERE id = '54545454-0000-0000-0000-00000000000d';
$sql$, 'T56c despublicar (approved → draft) sem trilha');

-- caminho feliz: com trilha 'pending_review' a saída de approved é aceita e some da view
INSERT INTO content.compliance_reviews (subject_kind, subject_id, decision, reviewer_id, notes)
VALUES ('education', '54545454-0000-0000-0000-00000000000d', 'pending_review',
        '54545454-0000-0000-0000-000000000001', 't56 reabertura');
UPDATE content.education_contents SET review_status = 'pending_review', published_at = NULL
 WHERE id = '54545454-0000-0000-0000-00000000000d';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM content.v_education_approved WHERE slug = 't54-publicado'
$sql$, 0, 'T56d reaberto com trilha sai da view');

-- reaberto, o texto pode mudar
UPDATE content.education_contents SET body_md = 'texto revisado'
 WHERE id = '54545454-0000-0000-0000-00000000000d';
DO $$ BEGIN RAISE NOTICE 'ok   · T56e texto de conteúdo reaberto pode ser editado'; END $$;

-- ================================================================ TESTE 57
-- Caminho feliz completo: revisão → aprovação → publicação → visível na view; e o CHECK
-- original (published_at só com approved) continua valendo.
INSERT INTO content.compliance_reviews (subject_kind, subject_id, decision, reviewer_id, notes)
VALUES ('education', '54545454-0000-0000-0000-00000000000d', 'approved',
        '54545454-0000-0000-0000-000000000001', 't57 nova aprovação');
UPDATE content.education_contents
   SET review_status = 'approved', reviewed_by = '54545454-0000-0000-0000-000000000001',
       reviewed_at = now(), published_at = now()
 WHERE id = '54545454-0000-0000-0000-00000000000d';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM content.v_education_approved WHERE slug = 't54-publicado' AND body_md = 'texto revisado'
$sql$, 1, 'T57  reaprovado com trilha volta à view com o texto revisado');

SELECT pg_temp.expect_fail($sql$
  UPDATE content.education_contents SET published_at = now()
   WHERE id = '54545454-0000-0000-0000-00000000000b';
$sql$, 'T57b published_at em conteúdo não aprovado (CHECK de 09)');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Conteúdo educativo (30) concluído: o Educador só enxerga o que'
\echo ' compliance aprovou e publicou; aprovação e reabertura deixam trilha.'
\echo '================================================================'
