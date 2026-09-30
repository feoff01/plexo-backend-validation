-- =============================================================================
-- PLEXO · testes das regras invioláveis — Raio-X da carteira (T121–T126, 54)
--   T121 finding de tipo SEM produtor declarado (`implemented_at IS NULL`) é recusado
--   T122 tipo quantificável exige `quantification` — card sem número é ruído
--   T123 tipo NÃO quantificável entra sem quantificação (o outro lado da regra)
--   T124 `risco.exposicao_acima_do_fgc` existe, é do Free e é quantificável
--   T125 `RAIOX_LIMIARES` nasce em rascunho, e rascunho não vira número do cliente
--   T126 `finding_key` é único por escopo: recálculo ATUALIZA, não duplica
--
-- POR QUE ESTE ARQUIVO EXISTE
--   A taxonomia de findings está semeada desde a migration 15 — 21 tipos, cada um com
--   severidade, plano mínimo e atrito de execução. As tabelas, as views, a fila de ações
--   com os cinco blocos obrigatórios, a revelação estrutural do paywall: tudo pronto desde
--   a 06. E `diagnostics.findings` tinha ZERO linhas em 2026-08-30, porque **nenhuma linha
--   de Python jamais escreveu nela**.
--
--   É o mesmo achado da F16 com `diagnostics.foundation_status`, e a lição de lá vale
--   inteira: "um gate sem quem o alimente não é gate: é intenção". A diferença é que desta
--   vez a lição vira ESTRUTURA — `implemented_at` deixa de ser documentação e passa a ser
--   condição de existência. Um tipo de finding só produz linha depois que alguém escreveu o
--   produtor e declarou isso na migration. Taxonomia sem produtor não chega à tela por
--   acidente, e o catálogo passa a dizer a verdade sobre si mesmo.
--
--   A segunda regra é a mesma do `action_five_blocks` da 06, um degrau antes: "card sem
--   quantificação é ruído". A constraint existia na AÇÃO e não no FINDING — mas é o finding
--   que carrega `impact_brl_year` e alimenta `priority_score`. Um finding quantificável sem
--   `quantification` produz uma ação que precisa inventar o bloco de quantificação, ou um
--   alerta que diz "concentração alta" sem dizer quanto. As duas saídas são ruins.
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_raiox.sql [plexo_service]
-- Termina em ROLLBACK — não deixa resíduo.
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
END $$;

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

-- ---------------------------------------------------------------- fixture (prefixo 1121 = T121)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('11210000-0000-4000-8000-000000000001', 't121-titular@teste.local', 'Titular T121', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('11210000-0000-4000-8000-000000000002', 'personal', 'Pessoal T121',
        '11210000-0000-4000-8000-000000000001');

INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('11210000-0000-4000-8000-000000000003', '1.2.0', repeat('2', 40), repeat('f', 64));

INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date,
                         policy_version_ids, is_client_facing)
VALUES ('11210000-0000-4000-8000-000000000004', '11210000-0000-4000-8000-000000000002',
        'raiox', '11210000-0000-4000-8000-000000000003', repeat('d', 64), current_date, '{}', false);

-- ================================================================ TESTE 121
-- `alocacao.sem_exposicao_internacional` está na taxonomia desde a 15 e NÃO tem produtor:
-- é justamente o tipo de linha que aparecia na tela de um cliente sem que ninguém tivesse
-- escrito o código que a calcula. Agora o banco recusa.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.finding_types
   WHERE code = 'tributacao.prejuizo_nao_compensado' AND implemented_at IS NULL
$sql$, 1, 'T121a há tipo na taxonomia declaradamente sem produtor');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.findings
    (scope_id, finding_type_code, finding_key, severity, confidence, impact_brl_year,
     execution_friction, quantification, first_run_id, last_run_id)
  VALUES ('11210000-0000-4000-8000-000000000002', 'tributacao.prejuizo_nao_compensado',
          'tributacao.prejuizo_nao_compensado:scope:x', 'media', 0.8, 1000, 3,
          '{"valor": 1000}'::jsonb,
          '11210000-0000-4000-8000-000000000004', '11210000-0000-4000-8000-000000000004');
$sql$, 'T121 finding de tipo sem produtor declarado');

-- ================================================================ TESTE 122
-- `risco.concentracao_emissor` É implementado, então o único defeito aqui é a quantificação
-- vazia — uma asserção a um defeito de distância do caminho feliz.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.findings
    (scope_id, finding_type_code, finding_key, severity, confidence, impact_brl_year,
     execution_friction, first_run_id, last_run_id)
  VALUES ('11210000-0000-4000-8000-000000000002', 'risco.concentracao_emissor',
          'risco.concentracao_emissor:issuer:t121', 'alta', 0.9, 5000, 3,
          '11210000-0000-4000-8000-000000000004', '11210000-0000-4000-8000-000000000004');
$sql$, 'T122 finding quantificável com `quantification` vazia');

INSERT INTO diagnostics.findings
  (id, scope_id, finding_type_code, finding_key, severity, confidence, impact_brl_year,
   execution_friction, quantification, first_run_id, last_run_id)
VALUES ('11210000-0000-4000-8000-000000000010', '11210000-0000-4000-8000-000000000002',
        'risco.concentracao_emissor', 'risco.concentracao_emissor:issuer:t121', 'alta', 0.9,
        5000, 3, '{"exposicao_brl": 363840, "share_pct": 46.9, "limiar_pct": 20}'::jsonb,
        '11210000-0000-4000-8000-000000000004', '11210000-0000-4000-8000-000000000004');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.findings
   WHERE id = '11210000-0000-4000-8000-000000000010' AND priority_score > 0
$sql$, 1, 'T122b com quantificação, o finding entra e o score de prioridade é derivado');

-- ================================================================ TESTE 123
-- O outro lado: `alocacao.sem_exposicao_internacional` é `is_quantifiable = false` — não há
-- "quanto" a dizer, e exigir quantificação dele transformaria a regra em burocracia.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.finding_types
   WHERE code = 'alocacao.sem_exposicao_internacional'
     AND NOT is_quantifiable AND implemented_at IS NOT NULL
$sql$, 1, 'T123a o tipo não quantificável está implementado');

INSERT INTO diagnostics.findings
  (scope_id, finding_type_code, finding_key, severity, confidence, execution_friction,
   first_run_id, last_run_id)
VALUES ('11210000-0000-4000-8000-000000000002', 'alocacao.sem_exposicao_internacional',
        'alocacao.sem_exposicao_internacional:scope:t121', 'baixa', 0.9, 3,
        '11210000-0000-4000-8000-000000000004', '11210000-0000-4000-8000-000000000004');

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.findings
   WHERE finding_key = 'alocacao.sem_exposicao_internacional:scope:t121'
$sql$, 1, 'T123 finding não quantificável entra sem quantificação');

-- ================================================================ TESTE 124
-- O FGC é um cartão PRÓPRIO, não um detalhe da concentração: são duas leituras diferentes
-- do mesmo emissor. "40% do seu patrimônio está num banco" é risco de carteira; "R$ 270 mil
-- passam do teto de R$ 250 mil garantidos" é risco de crédito com um número exato e uma
-- ação óbvia. Juntar os dois num cartão só apaga o segundo.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.finding_types
   WHERE code = 'risco.exposicao_acima_do_fgc' AND family = 'risco'
     AND min_plan = 'free' AND is_quantifiable AND implemented_at IS NOT NULL
$sql$, 1, 'T124 o tipo do FGC existe, é do Free e é quantificável');

-- ================================================================ TESTE 125
-- Todo limiar do Raio-X é premissa versionada: a diferença entre "concentração acima de 20%"
-- e "acima de 30%" é a diferença entre alertar um cliente e não alertar, e essa decisão tem
-- dono e data. Nasce em rascunho pelo mesmo motivo que as premissas da F17.
-- O que se afirma sobre a política REAL é o que não muda: existir e declarar os limiares.
-- O `compliance_status` dela NÃO entra aqui de propósito — aprovar é ato operacional, feito
-- por gente com nome e data, e um teste que exigisse "ainda em rascunho" quebraria no dia da
-- aprovação, culpando quem fez a coisa certa. É a terceira vez que esta base aprende que
-- teste não deve depender de estado que outra execução muda.
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM engine.policy_versions
   WHERE code = 'RAIOX_LIMIARES' AND version = 1
     AND payload ? 'concentracao_emissor_max' AND payload ? 'teto_fgc_brl'
     AND payload ? 'iliquido_share_max' AND payload ? 'caixa_ocioso_multiplo_da_reserva'
$sql$, 1, 'T125 RAIOX_LIMIARES v1 existe e declara os limiares do motor');

-- E o INVARIANTE — rascunho não vira número do cliente — é provado sobre uma política da
-- própria fixture, que nasce e morre dentro da transação. O gate 29a recusa run
-- client-facing que declare política não aprovada, e é isso que segura o Raio-X enquanto os
-- limiares não tiverem parecer.
INSERT INTO engine.policy_versions (id, code, version, payload, compliance_status)
VALUES ('11210000-0000-4000-8000-000000000020', 'T125_LIMIARES_RASCUNHO', 1,
        '{"concentracao_emissor_max": 0.20}'::jsonb, 'draft');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO engine.runs (scope_id, kind, engine_version_id, input_hash, as_of_date,
                           policy_version_ids, is_client_facing)
  VALUES ('11210000-0000-4000-8000-000000000002', 'raiox',
          '11210000-0000-4000-8000-000000000003', repeat('e', 64), current_date,
          ARRAY['11210000-0000-4000-8000-000000000020'::uuid], true);
$sql$, 'T125b run client-facing sobre limiar em rascunho');

-- O mesmo run INTERNO passa: é assim que o motor roda em calibração sem publicar número.
INSERT INTO engine.runs (scope_id, kind, engine_version_id, input_hash, as_of_date,
                         policy_version_ids, is_client_facing)
VALUES ('11210000-0000-4000-8000-000000000002', 'raiox',
        '11210000-0000-4000-8000-000000000003', repeat('e', 64), current_date,
        ARRAY['11210000-0000-4000-8000-000000000020'::uuid], false);

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM engine.runs
   WHERE input_hash = repeat('e', 64) AND NOT is_client_facing
$sql$, 1, 'T125c o mesmo run INTERNO é aceito: calibração não publica número');

-- ================================================================ TESTE 126
-- `finding_key` estável por escopo é o que faz cooldown e supressão existirem (COMMENT da
-- 06): o recálculo diário precisa ATUALIZAR o finding, não criar outro. Se duplicasse, a
-- recusa do cliente ("não me mostre mais isso") seria esquecida na madrugada seguinte.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO diagnostics.findings
    (scope_id, finding_type_code, finding_key, severity, confidence, impact_brl_year,
     execution_friction, quantification, first_run_id, last_run_id)
  VALUES ('11210000-0000-4000-8000-000000000002', 'risco.concentracao_emissor',
          'risco.concentracao_emissor:issuer:t121', 'critica', 0.95, 9000, 3,
          '{"exposicao_brl": 400000}'::jsonb,
          '11210000-0000-4000-8000-000000000004', '11210000-0000-4000-8000-000000000004');
$sql$, 'T126 segundo finding com a mesma chave lógica no mesmo escopo');

UPDATE diagnostics.findings
   SET severity = 'critica', quantification = '{"exposicao_brl": 400000, "share_pct": 51.6}'::jsonb,
       last_detected_at = now()
 WHERE finding_key = 'risco.concentracao_emissor:issuer:t121';

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM diagnostics.findings
   WHERE finding_key = 'risco.concentracao_emissor:issuer:t121' AND severity = 'critica'
$sql$, 1, 'T126b o recálculo atualiza o finding existente, preservando a identidade lógica');

-- E a atualização também respeita a quantificação: esvaziá-la depois é o mesmo defeito.
SELECT pg_temp.expect_fail($sql$
  UPDATE diagnostics.findings SET quantification = '{}'::jsonb
   WHERE finding_key = 'risco.concentracao_emissor:issuer:t121';
$sql$, 'T126c esvaziar a quantificação de um finding já registrado');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Taxonomia sem produtor não vira linha: `implemented_at` deixou'
\echo ' de ser documentação e virou condição de existência. E finding'
\echo ' quantificável sem quantificação é o "card sem número" que a'
\echo ' migration 06 já proibia na ação — um degrau tarde demais.'
\echo '================================================================'
