-- =============================================================================
-- PLEXO · testes das regras invioláveis — intake do onboarding (T142–T145, 60_intake_do_onboarding)
--   T142 submission coerente por tipo: texto exige corpo e proíbe mídia; arquivo/áudio exigem
--        mídia+mime+sha256; teto de bytes e quota diária vêm da policy ONBOARDING_EXTRACAO
--   T143 item extraído tem o MESMO gate epistêmico do resto do sistema: nasce 'proposto'
--        (nunca confirmado), só o PRÓPRIO usuário confirma, payload é imutável, fato exige
--        fact_key do catálogo, rejeitado/confirmado são terminais carimbados
--   T144 RLS por escopo em submissions e itens sob plexo_app
--   T145 submission: transição de status válida só para frente; mídia e corpo imutáveis
--        (transcrição só PREENCHE body_text quando NULL, nunca troca)
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_intake.sql [plexo_service]
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

CREATE OR REPLACE FUNCTION pg_temp.expect_count(p_sql text, p_expected bigint, p_label text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v bigint;
BEGIN
  EXECUTE 'SELECT count(*) FROM (' || p_sql || ') q' INTO v;
  IF v <> p_expected THEN
    RAISE EXCEPTION 'FALHOU: "%" — esperado % linha(s), papel enxergou %', p_label, p_expected, v;
  END IF;
  RAISE NOTICE 'ok   · % (% linha(s), como esperado)', p_label, v;
END;
$$;

BEGIN;
SET LOCAL app.role = 'service';   -- fixtures como serviço/administrador

-- ---------------------------------------------------------------- fixtures
INSERT INTO identity.users (id, email, full_name, status) VALUES
  ('14200000-0000-4000-8000-000000000001', 'u1-t142@plexo.local', 'Titular Intake', 'active'),
  ('14200000-0000-4000-8000-000000000002', 'u2-t142@plexo.local', 'Vizinho',        'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id) VALUES
  ('14200000-0000-4000-8000-0000000000a1', 'personal', 'S1', '14200000-0000-4000-8000-000000000001'),
  ('14200000-0000-4000-8000-0000000000a2', 'personal', 'S2', '14200000-0000-4000-8000-000000000002');

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at) VALUES
  ('14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001', 'owner', now()),
  ('14200000-0000-4000-8000-0000000000a2', '14200000-0000-4000-8000-000000000002', 'owner', now());

-- A quota e o teto de bytes são CONFIG: publica-se uma versão apertada da policy para
-- sabotar barato (mesmo padrão do T138i com ONBOARDING_NUCLEO e do conftest com o canário).
UPDATE engine.policy_versions SET effective_to = clock_timestamp()
 WHERE code = 'ONBOARDING_EXTRACAO' AND effective_to IS NULL;
INSERT INTO engine.policy_versions (code, version, payload, compliance_status, effective_from)
SELECT 'ONBOARDING_EXTRACAO', coalesce(max(version), 0) + 1,
       '{"max_bytes_media": 64, "max_submissoes_por_dia_por_escopo": 2}'::jsonb,
       'draft', clock_timestamp()
  FROM engine.policy_versions WHERE code = 'ONBOARDING_EXTRACAO';

-- ================================================================ TESTE 142 (submission)
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_submissions (scope_id, user_id, passo, kind)
  VALUES ('14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001',
          'objetivos', 'texto');
$sql$, 'T142a submission de texto sem body_text é rejeitada');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_submissions (scope_id, user_id, passo, kind, body_text, media, media_mime, media_sha256)
  VALUES ('14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001',
          'objetivos', 'texto', 'quero comprar um carro', '\x00'::bytea, 'audio/webm', repeat('a', 64));
$sql$, 'T142b submission de texto com mídia anexada é rejeitada');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_submissions (scope_id, user_id, passo, kind)
  VALUES ('14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001',
          'objetivos', 'audio');
$sql$, 'T142c submission de áudio sem mídia é rejeitada');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_submissions (scope_id, user_id, passo, kind, media, media_mime)
  VALUES ('14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001',
          'objetivos', 'audio', '\x0102'::bytea, 'audio/webm');
$sql$, 'T142d mídia sem sha256 não é evidência — rejeitada');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_submissions (scope_id, user_id, passo, kind, media, media_mime, media_sha256)
  VALUES ('14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001',
          'objetivos', 'audio', decode(repeat('00', 65), 'hex'), 'audio/webm', repeat('b', 64));
$sql$, 'T142e mídia acima do teto de bytes da policy é rejeitada');

-- felizes (contam para a quota diária = 2)
INSERT INTO context.intake_submissions (id, scope_id, user_id, passo, kind, body_text)
VALUES ('14200000-0000-4000-8000-0000000000b1', '14200000-0000-4000-8000-0000000000a1',
        '14200000-0000-4000-8000-000000000001', 'objetivos', 'texto',
        'Quero comprar um carro de 80 mil em dois anos e tenho uma dívida de 12 mil.');
INSERT INTO context.intake_submissions (id, scope_id, user_id, passo, kind, media, media_mime, media_sha256)
VALUES ('14200000-0000-4000-8000-0000000000b2', '14200000-0000-4000-8000-0000000000a1',
        '14200000-0000-4000-8000-000000000001', 'dividas', 'audio',
        '\x010203'::bytea, 'audio/webm', repeat('c', 64));

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_submissions (scope_id, user_id, passo, kind, body_text)
  VALUES ('14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001',
          'patrimonio', 'texto', 'terceira do dia');
$sql$, 'T142f a terceira submissão do dia estoura a quota da policy');

-- ================================================================ TESTE 143 (item = gate epistêmico)
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_items (submission_id, scope_id, user_id, seq, kind, payload, status,
                                    confirmed_at, confirmed_by)
  VALUES ('14200000-0000-4000-8000-0000000000b1', '14200000-0000-4000-8000-0000000000a1',
          '14200000-0000-4000-8000-000000000001', 1, 'objetivo',
          '{"nome": "Carro", "valor": 80000, "prazo_meses": 24}'::jsonb, 'confirmado',
          now(), '14200000-0000-4000-8000-000000000001');
$sql$, 'T143a item nasce "proposto" — nunca confirmado no INSERT');

INSERT INTO context.intake_items (id, submission_id, scope_id, user_id, seq, kind, payload)
VALUES ('14200000-0000-4000-8000-0000000000c1', '14200000-0000-4000-8000-0000000000b1',
        '14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001',
        1, 'objetivo', '{"nome": "Carro", "tipo": "outro", "valor": 80000, "prazo_meses": 24, "prioridade": 2}'::jsonb);
INSERT INTO context.intake_items (id, submission_id, scope_id, user_id, seq, kind, payload)
VALUES ('14200000-0000-4000-8000-0000000000c2', '14200000-0000-4000-8000-0000000000b1',
        '14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000001',
        2, 'divida', '{"tipo": "emprestimo_pessoal", "saldo": 12000, "taxa_aa_percentual": 32, "parcela": 600}'::jsonb);

SELECT pg_temp.expect_fail($sql$
  UPDATE context.intake_items SET status = 'confirmado'
   WHERE id = '14200000-0000-4000-8000-0000000000c1';
$sql$, 'T143b confirmar sem carimbo (confirmed_at/confirmed_by) é rejeitado');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.intake_items
     SET status = 'confirmado', confirmed_at = now(),
         confirmed_by = '14200000-0000-4000-8000-000000000002'
   WHERE id = '14200000-0000-4000-8000-0000000000c1';
$sql$, 'T143c terceiro não confirma o contexto alheio (self-confirmation)');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.intake_items SET payload = '{"nome": "Iate", "valor": 9000000}'::jsonb
   WHERE id = '14200000-0000-4000-8000-0000000000c1';
$sql$, 'T143d payload extraído é imutável — o que se confirma é o que a IA propôs');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_items (submission_id, scope_id, user_id, seq, kind, payload)
  VALUES ('14200000-0000-4000-8000-0000000000b1', '14200000-0000-4000-8000-0000000000a1',
          '14200000-0000-4000-8000-000000000001', 3, 'fato', '{"valor": 1500}'::jsonb);
$sql$, 'T143e item de fato sem fact_key é rejeitado');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_items (submission_id, scope_id, user_id, seq, kind, fact_key, payload)
  VALUES ('14200000-0000-4000-8000-0000000000b1', '14200000-0000-4000-8000-0000000000a1',
          '14200000-0000-4000-8000-000000000001', 3, 'fato', 'fato.inexistente',
          '{"valor": 1500}'::jsonb);
$sql$, 'T143f fact_key fora do catálogo é rejeitado (vocabulário fechado)');

DO $$
DECLARE n int;
BEGIN
  UPDATE context.intake_items
     SET status = 'confirmado', confirmed_at = now(),
         confirmed_by = '14200000-0000-4000-8000-000000000001'
   WHERE id = '14200000-0000-4000-8000-0000000000c1';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FALHOU T143g: o próprio usuário deveria confirmar o item'; END IF;
  UPDATE context.intake_items SET status = 'rejeitado', rejected_at = now()
   WHERE id = '14200000-0000-4000-8000-0000000000c2';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FALHOU T143h: rejeitar item proposto deveria funcionar'; END IF;
  RAISE NOTICE 'ok   · T143g/h o próprio usuário confirma e rejeita';
END $$;

SELECT pg_temp.expect_fail($sql$
  UPDATE context.intake_items SET status = 'proposto', confirmed_at = NULL, confirmed_by = NULL
   WHERE id = '14200000-0000-4000-8000-0000000000c1';
$sql$, 'T143i confirmado é terminal — não volta a proposto');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.intake_items
     SET status = 'confirmado', confirmed_at = now(),
         confirmed_by = '14200000-0000-4000-8000-000000000001'
   WHERE id = '14200000-0000-4000-8000-0000000000c2';
$sql$, 'T143j rejeitado é terminal — não vira confirmado');

-- ================================================================ TESTE 144 (RLS sob plexo_app)
SET LOCAL ROLE plexo_app;
SET LOCAL app.role = 'user';
SET LOCAL app.user_id = '14200000-0000-4000-8000-000000000002';
SET LOCAL app.scope_id = '14200000-0000-4000-8000-0000000000a2';

SELECT pg_temp.expect_count($sql$ SELECT 1 FROM context.intake_submissions $sql$, 0,
  'T144a o vizinho não vê submissão nenhuma do escopo alheio');
SELECT pg_temp.expect_count($sql$ SELECT 1 FROM context.intake_items $sql$, 0,
  'T144b nem os itens');
SELECT pg_temp.expect_fail($sql$
  INSERT INTO context.intake_submissions (scope_id, user_id, passo, kind, body_text)
  VALUES ('14200000-0000-4000-8000-0000000000a1', '14200000-0000-4000-8000-000000000002',
          'objetivos', 'texto', 'invasão');
$sql$, 'T144c submissão em escopo alheio é rejeitada pela RLS');
DO $$
DECLARE n int;
BEGIN
  UPDATE context.intake_items
     SET status = 'confirmado', confirmed_at = now(),
         confirmed_by = '14200000-0000-4000-8000-000000000002'
   WHERE id = '14200000-0000-4000-8000-0000000000c2';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 0 THEN RAISE EXCEPTION 'FALHOU T144d: RLS deveria esconder o item alheio (0 linhas), atingiu %', n; END IF;
  RAISE NOTICE 'ok   · T144d UPDATE em item alheio atinge 0 linhas (RLS filtra, não erra)';
END $$;

RESET ROLE;
SET LOCAL app.role = 'service';

-- ================================================================ TESTE 145 (transições da submission)
SELECT pg_temp.expect_fail($sql$
  UPDATE context.intake_submissions SET body_text = 'texto trocado depois do fato'
   WHERE id = '14200000-0000-4000-8000-0000000000b1';
$sql$, 'T145a body_text preenchido não se troca (evidência congelada)');

SELECT pg_temp.expect_fail($sql$
  UPDATE context.intake_submissions SET media = '\x0909'::bytea
   WHERE id = '14200000-0000-4000-8000-0000000000b2';
$sql$, 'T145b mídia é imutável');

DO $$
DECLARE n int;
BEGIN
  -- transcrição legítima: body_text NULO ganha texto, status avança
  UPDATE context.intake_submissions
     SET body_text = 'tenho uma divida de doze mil', status = 'extraido', extracted_at = now()
   WHERE id = '14200000-0000-4000-8000-0000000000b2';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FALHOU T145c: transcrição deveria preencher body_text nulo'; END IF;
  RAISE NOTICE 'ok   · T145c transcrição preenche body_text quando NULL e avança o status';
END $$;

SELECT pg_temp.expect_fail($sql$
  UPDATE context.intake_submissions SET status = 'recebido'
   WHERE id = '14200000-0000-4000-8000-0000000000b2';
$sql$, 'T145d status não anda para trás (extraido → recebido)');

RESET ROLE;
ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Intake do onboarding: cada "ok" acima é um caminho de item'
\echo ' confirmado à revelia, payload adulterado, quota furada ou'
\echo ' evidência trocada que o banco recusa.'
\echo '================================================================'
