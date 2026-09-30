-- PLEXO · testes das regras invioláveis — camada documental (T73–T77, 34_docs.sql)
--   T73  documento aprovado sem revisor identificado é recusado
--   T74  entrar/sair de `aprovado` sem trilha na mesma transação é recusado
--   T75  texto aprovado é imutável: título/corpo só mudam depois de reabrir a revisão
--   T76  docs.v_documentos_citaveis não expõe pendente nem rejeitado
--   T77  documento com vocabulário vetado (RCVM 19) não pode ser aprovado
--
-- Por que este arquivo existe: o texto que a camada documental guarda é de TERCEIRO, e é o único
-- texto de terceiro que pode chegar ao cliente. O gate é o mesmo que o Educador já tem para
-- conteúdo aprovado (30_content_education_gate.sql) — aqui ele é provado para documento externo.
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_docs.sql [plexo_service]
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
    RAISE EXCEPTION 'FALHOU: "%" — esperado % linha(s), papel enxergou %', p_label, p_expected, v;
  END IF;
  RAISE NOTICE 'ok   · % (% linha(s), como esperado)', p_label, v;
END $$;

BEGIN;
SET LOCAL app.role = 'service';

-- ---------------------------------------------------------------- fixture (prefixo 7373 = T73)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('73730000-0000-4000-8000-000000000001', 't73-revisor@teste.local', 'Revisor T73', 'active');

INSERT INTO docs.sources (code, display_name, publisher, base_url, license_note)
VALUES ('t73_fonte', 'Fonte de teste T73', 'Emissor de teste',
        'https://exemplo.invalido', 'Somente teste — não redistribuir.');

-- documento pendente, texto limpo
INSERT INTO docs.documents (id, source_code, kind, external_id, title, published_on, url, body_text, body_sha256)
VALUES ('73730000-0000-4000-8000-000000000011', 't73_fonte', 'comunicado', 'T73-001',
        'Comunicado de teste', current_date - 1, 'https://exemplo.invalido/1',
        'O comitê decidiu manter a taxa básica de juros.', repeat('a', 64));

-- documento pendente, texto com termo VETADO pela RCVM 19
INSERT INTO docs.documents (id, source_code, kind, external_id, title, published_on, body_text, body_sha256, vocabulario_achados)
VALUES ('73730000-0000-4000-8000-000000000012', 't73_fonte', 'nota', 'T73-002',
        'Nota com vocabulário vetado', current_date - 1,
        'Este é o melhor investimento do mercado.', repeat('b', 64), ARRAY['melhor investimento']);

-- ================================================================ TESTE 73
-- Aprovar exige revisor identificado — o mesmo que o Educador exige (30:38-41).
SELECT pg_temp.expect_fail($sql$
  UPDATE docs.documents SET review_status = 'aprovado'
   WHERE id = '73730000-0000-4000-8000-000000000011';
$sql$, 'T73  documento aprovado sem reviewed_by/reviewed_at');

SELECT pg_temp.expect_fail($sql$
  UPDATE docs.documents SET review_status = 'aprovado',
         reviewed_by = '73730000-0000-4000-8000-000000000001'
   WHERE id = '73730000-0000-4000-8000-000000000011';
$sql$, 'T73b revisor sem reviewed_at também é recusado');

-- ================================================================ TESTE 74
-- Entrar em `aprovado` exige trilha em docs.document_reviews NESTA transação.
SELECT pg_temp.expect_fail($sql$
  UPDATE docs.documents SET review_status = 'aprovado',
         reviewed_by = '73730000-0000-4000-8000-000000000001', reviewed_at = now()
   WHERE id = '73730000-0000-4000-8000-000000000011';
$sql$, 'T74  aprovação sem trilha em document_reviews');

-- caminho feliz: com trilha, aprova
INSERT INTO docs.document_reviews (document_id, decision, reviewer_id, notes)
VALUES ('73730000-0000-4000-8000-000000000011', 'aprovado',
        '73730000-0000-4000-8000-000000000001', 'fonte oficial, texto conferido');
UPDATE docs.documents SET review_status = 'aprovado',
       reviewed_by = '73730000-0000-4000-8000-000000000001', reviewed_at = now()
 WHERE id = '73730000-0000-4000-8000-000000000011';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM docs.documents WHERE id = '73730000-0000-4000-8000-000000000011'
                                AND review_status = 'aprovado'
$sql$, 1, 'T74b com trilha na mesma transação, a aprovação passa');

-- sair de aprovado também exige trilha
SELECT pg_temp.expect_fail($sql$
  UPDATE docs.documents SET review_status = 'rejeitado'
   WHERE id = '73730000-0000-4000-8000-000000000011';
$sql$, 'T74c despublicar sem trilha');

-- ================================================================ TESTE 75
-- Texto aprovado é imutável: o cliente não pode ler hoje algo diferente do que foi aprovado.
SELECT pg_temp.expect_fail($sql$
  UPDATE docs.documents SET body_text = 'texto trocado por baixo do cliente'
   WHERE id = '73730000-0000-4000-8000-000000000011';
$sql$, 'T75  corpo de documento aprovado é imutável');

SELECT pg_temp.expect_fail($sql$
  UPDATE docs.documents SET title = 'título trocado'
   WHERE id = '73730000-0000-4000-8000-000000000011';
$sql$, 'T75b título de documento aprovado é imutável');

-- ================================================================ TESTE 76
-- A view é a única janela do agente. Pendente e rejeitado não existem para ele.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM docs.v_documentos_citaveis WHERE source_code = 't73_fonte'
$sql$, 1, 'T76  v_documentos_citaveis expõe só o aprovado (1 de 2)');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM docs.v_documentos_citaveis
   WHERE id = '73730000-0000-4000-8000-000000000012'
$sql$, 0, 'T76b documento pendente não é citável');

-- ================================================================ TESTE 77
-- RCVM 19: texto de terceiro com termo vetado não vira material citável, nem com revisor e trilha.
INSERT INTO docs.document_reviews (document_id, decision, reviewer_id, notes)
VALUES ('73730000-0000-4000-8000-000000000012', 'aprovado',
        '73730000-0000-4000-8000-000000000001', 'tentativa de aprovar texto vetado');
SELECT pg_temp.expect_fail($sql$
  UPDATE docs.documents SET review_status = 'aprovado',
         reviewed_by = '73730000-0000-4000-8000-000000000001', reviewed_at = now()
   WHERE id = '73730000-0000-4000-8000-000000000012';
$sql$, 'T77  documento com vocabulário vetado não pode ser aprovado');

-- ================================================================ trilha é append-only
SELECT pg_temp.expect_fail($sql$
  UPDATE docs.document_reviews SET decision = 'rejeitado'
   WHERE document_id = '73730000-0000-4000-8000-000000000011';
$sql$, 'T77b trilha de revisão é append-only (UPDATE)');

SELECT pg_temp.expect_fail($sql$
  DELETE FROM docs.document_reviews
   WHERE document_id = '73730000-0000-4000-8000-000000000011';
$sql$, 'T77c trilha de revisão é append-only (DELETE)');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Camada documental: o único texto de TERCEIRO que chega ao'
\echo ' cliente passa por revisor, trilha e vocabulário — e, uma vez'
\echo ' aprovado, não muda por baixo de quem já leu.'
\echo '================================================================'
