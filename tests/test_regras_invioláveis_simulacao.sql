-- =============================================================================
-- PLEXO · testes das regras invioláveis — premissas de mercado e projeção (T111–T116, 48)
--   T111 conjunto aprovado exige metodologia, aprovador e matriz de correlação completa
--   T111e conjunto aprovado é imutável; só a vigência pode ser encerrada
--   T112 correlação vive em [-1,1], sem par duplicado nem invertido
--   T113 retorno e volatilidade vivem em faixa REAL — número em percentual é recusado
--   T114 projeção client-facing exige conjunto de premissas aprovado (C40d nas premissas)
--   T115 percentis fora de ordem são recusados
--   T116 probabilidade vive em [0,1]; projeção sem semente registrada é recusada
--
-- POR QUE ESTE ARQUIVO EXISTE
--   A probabilidade de sucesso de uma meta é o número mais persuasivo que a plataforma
--   produz — e o único cujo insumo é inteiramente opinião. Retorno esperado e volatilidade
--   não são medidos: são arbitrados. `META_PROBABILIDADE_DE_SUCESSO.md` chama a premissa de
--   mercado de "o insumo mais contestável de todo o sistema e o primeiro que um regulador
--   vai pedir", e é por isso que ela não pode viver em `payload jsonb` de política nem,
--   pior, em constante de código.
--
--   As três regras que mais importam aqui:
--     (a) premissa sem origem declarada não vira número do cliente (T111) — `metodologia` é
--         NOT NULL e a aprovação exige aprovador, do mesmo jeito que `policy_versions`;
--     (b) UNIDADE é constraint, não convenção (T113). A F16 perdeu meia sessão com o CDI
--         guardado em percentual sendo lido como fração: 14,0 comparado com 0,14 fez uma
--         dívida a 400% a.a. parecer mais barata que o CDI. A faixa aqui é estreita de
--         propósito — 0,14 passa, 14,0 não entra;
--     (c) correlação faltando é correlação lida como zero, e zero subestima o risco da
--         carteira inteira. Conjunto aprovado exige a matriz FECHADA (T111c).
--
-- Rodar com: python tools/db_runner.py tests test_regras_invioláveis_simulacao.sql [plexo_service]
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

-- ---------------------------------------------------------------- fixture (prefixo 1111 = T111)
INSERT INTO identity.users (id, email, full_name, status)
VALUES ('11110000-0000-4000-8000-000000000001', 't111-titular@teste.local', 'Titular T111', 'active');

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('11110000-0000-4000-8000-000000000002', 'personal', 'Pessoal T111',
        '11110000-0000-4000-8000-000000000001');

INSERT INTO engine.engine_versions (id, semver, git_sha, source_sha256)
VALUES ('11110000-0000-4000-8000-000000000003', '1.1.0', repeat('1', 40), repeat('e', 64));

INSERT INTO engine.policy_versions (id, code, version, payload, compliance_status,
                                    approved_by, approved_at)
VALUES ('11110000-0000-4000-8000-000000000004', 'T111_APROVADA', 1, '{}'::jsonb,
        'approved', '11110000-0000-4000-8000-000000000001', now());

-- run client-facing COM semente, run interno SEM semente: o par que o T114/T116 usa
INSERT INTO engine.runs (id, scope_id, kind, engine_version_id, input_hash, as_of_date,
                         is_client_facing, params)
VALUES ('11110000-0000-4000-8000-000000000005', '11110000-0000-4000-8000-000000000002',
        'projection', '11110000-0000-4000-8000-000000000003', repeat('a', 64), current_date,
        true, '{"semente": 20260829, "caminhos": 10000}'::jsonb),
       ('11110000-0000-4000-8000-000000000006', '11110000-0000-4000-8000-000000000002',
        'projection', '11110000-0000-4000-8000-000000000003', repeat('b', 64), current_date,
        false, '{"caminhos": 10000}'::jsonb);

INSERT INTO planning.goals (id, scope_id, name, kind, target_amount_brl, target_date,
                            monthly_contribution_brl)
VALUES ('11110000-0000-4000-8000-000000000007', '11110000-0000-4000-8000-000000000002',
        'Entrada do apartamento', 'imovel', 120000, current_date + 1095, 2500);

-- ================================================================ TESTE 111
-- Premissa de mercado é opinião com autor. Sem metodologia declarada não existe linha —
-- nem em rascunho: o campo é NOT NULL porque "de onde saiu esse 4,5%?" é a primeira
-- pergunta de qualquer auditoria, e a resposta não pode ser um commit antigo.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.assumption_sets (code, version, horizonte_anos, metodologia)
  VALUES ('T111_SEM_ORIGEM', 1, 30, NULL);
$sql$, 'T111 conjunto de premissas sem metodologia declarada');

INSERT INTO market.assumption_sets
  (id, code, version, horizonte_anos, metodologia, compliance_status)
VALUES ('11110000-0000-4000-8000-000000000010', 'T111_RASCUNHO', 1, 30,
        'Retornos reais de longo prazo a partir do relatório Focus e de série histórica do '
        'IMA-B e do Ibovespa deflacionada pelo IPCA, janela de 20 anos.', 'draft');

-- ORDEM IMPORTA AQUI, e a primeira versão deste teste errou nela: o trigger C48b roda
-- ANTES do CHECK `approved_has_author`, então um conjunto sem classe nenhuma é recusado
-- pela falta de classe e o teste do aprovador passaria sem nunca tocar no aprovador. Cada
-- asserção precisa estar a UM defeito de distância do caminho feliz — senão ela prova a
-- regra errada, e a suíte fica verde sobre uma regra que ninguém exercitou.
INSERT INTO market.class_assumptions
  (assumption_set_id, asset_class_code, retorno_real_aa, volatilidade_aa, fonte)
VALUES ('11110000-0000-4000-8000-000000000010', 'selic', 0.0450, 0.0100, 'Focus + IPCA'),
       ('11110000-0000-4000-8000-000000000010', 'acoes_br', 0.0700, 0.2200, 'Ibovespa 20a real');
INSERT INTO market.class_correlations (assumption_set_id, classe_a, classe_b, correlacao)
VALUES ('11110000-0000-4000-8000-000000000010', 'acoes_br', 'selic', -0.150);

SELECT pg_temp.expect_fail($sql$
  UPDATE market.assumption_sets
     SET compliance_status = 'approved'
   WHERE id = '11110000-0000-4000-8000-000000000010';
$sql$, 'T111b aprovar conjunto completo, mas sem aprovador registrado');

-- Correlação faltante é correlação lida como zero, e zero subestima o risco da carteira.
-- Conjunto à parte, com as duas classes e a matriz ABERTA: aqui o único defeito é o par
-- que falta, e o aprovador está no lugar.
INSERT INTO market.assumption_sets
  (id, code, version, horizonte_anos, metodologia, compliance_status)
VALUES ('11110000-0000-4000-8000-000000000012', 'T111_MATRIZ_ABERTA', 1, 30,
        'Mesmo método do conjunto irmão, com a matriz de correlação ainda por fechar — '
        'existe para provar que aprovar assim é recusado.', 'draft');
INSERT INTO market.class_assumptions
  (assumption_set_id, asset_class_code, retorno_real_aa, volatilidade_aa, fonte)
VALUES ('11110000-0000-4000-8000-000000000012', 'selic', 0.0450, 0.0100, 'Focus + IPCA'),
       ('11110000-0000-4000-8000-000000000012', 'acoes_br', 0.0700, 0.2200, 'Ibovespa 20a real');

SELECT pg_temp.expect_fail($sql$
  UPDATE market.assumption_sets
     SET compliance_status = 'approved',
         approved_by = '11110000-0000-4000-8000-000000000001', approved_at = now()
   WHERE id = '11110000-0000-4000-8000-000000000012';
$sql$, 'T111c aprovar conjunto com a matriz de correlação incompleta');

-- E uma classe só não tem carteira para simular: o outro lado do C48b.
INSERT INTO market.assumption_sets
  (id, code, version, horizonte_anos, metodologia, compliance_status)
VALUES ('11110000-0000-4000-8000-000000000013', 'T111_UMA_CLASSE', 1, 30,
        'Conjunto com uma única classe de ativo — existe para provar que não se aprova '
        'premissa de carteira sem carteira.', 'draft');
INSERT INTO market.class_assumptions
  (assumption_set_id, asset_class_code, retorno_real_aa, volatilidade_aa, fonte)
VALUES ('11110000-0000-4000-8000-000000000013', 'selic', 0.0450, 0.0100, 'Focus + IPCA');

SELECT pg_temp.expect_fail($sql$
  UPDATE market.assumption_sets
     SET compliance_status = 'approved',
         approved_by = '11110000-0000-4000-8000-000000000001', approved_at = now()
   WHERE id = '11110000-0000-4000-8000-000000000013';
$sql$, 'T111c2 aprovar conjunto com uma única classe de ativo');

UPDATE market.assumption_sets
   SET compliance_status = 'approved',
       approved_by = '11110000-0000-4000-8000-000000000001', approved_at = now()
 WHERE id = '11110000-0000-4000-8000-000000000010';

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.assumption_sets
   WHERE id = '11110000-0000-4000-8000-000000000010' AND compliance_status = 'approved'
$sql$, 1, 'T111d com origem, aprovador e matriz fechada, o conjunto é aprovado');

-- Aprovado é imutável: mudar premissa aprovada é mudar, retroativamente, o número que um
-- cliente já leu. É a mesma lógica do append-only do ledger, aplicada à opinião.
SELECT pg_temp.expect_fail($sql$
  UPDATE market.assumption_sets
     SET metodologia = 'Método reescrito depois da aprovação, o que não pode acontecer.'
   WHERE id = '11110000-0000-4000-8000-000000000010';
$sql$, 'T111e editar a metodologia de um conjunto já aprovado');

-- Encerrar a VIGÊNCIA continua permitido: é assim que uma versão nova sucede a anterior.
-- O `+ 1 hour` não é enfeite: `now()` é constante dentro da transação, e `vigencia_coerente`
-- exige duração positiva — uma vigência de zero segundo nunca esteve em vigor. Fora do teste
-- a sucessão sempre acontece em outra transação, então a aresta é só daqui.
UPDATE market.assumption_sets SET effective_to = now() + interval '1 hour'
 WHERE id = '11110000-0000-4000-8000-000000000010';
SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM market.assumption_sets
   WHERE id = '11110000-0000-4000-8000-000000000010' AND effective_to IS NOT NULL
$sql$, 1, 'T111f encerrar vigência de conjunto aprovado é permitido — é a sucessão');

-- ================================================================ TESTE 112
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.class_correlations (assumption_set_id, classe_a, classe_b, correlacao)
  VALUES ('11110000-0000-4000-8000-000000000010', 'caixa', 'ipca', 1.400);
$sql$, 'T112 correlação fora de [-1, 1]');

-- O par é NÃO ORDENADO: guardar (a,b) e (b,a) permitiria dois valores para a mesma relação,
-- e a matriz deixaria de ser simétrica sem ninguém perceber.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.class_correlations (assumption_set_id, classe_a, classe_b, correlacao)
  VALUES ('11110000-0000-4000-8000-000000000010', 'selic', 'acoes_br', 0.300);
$sql$, 'T112b par invertido da mesma relação');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.class_correlations (assumption_set_id, classe_a, classe_b, correlacao)
  VALUES ('11110000-0000-4000-8000-000000000010', 'acoes_br', 'selic', 0.300);
$sql$, 'T112c par duplicado');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.class_correlations (assumption_set_id, classe_a, classe_b, correlacao)
  VALUES ('11110000-0000-4000-8000-000000000010', 'selic', 'selic', 1.000);
$sql$, 'T112d correlação de uma classe consigo mesma (a diagonal é implícita)');

-- ================================================================ TESTE 113
-- A lição do CDI da F16, agora como constraint. `market.index_values` guarda taxa em
-- PERCENTUAL e `budget.debts.annual_rate` em FRAÇÃO; a confusão entre as duas fez uma
-- dívida a 400% a.a. parecer mais barata que o CDI e o semáforo sair verde. Aqui a faixa
-- é estreita: 0,07 passa, 7,0 não entra — a unidade vira erro no INSERT, não bug silencioso.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.class_assumptions
    (assumption_set_id, asset_class_code, retorno_real_aa, volatilidade_aa, fonte)
  VALUES ('11110000-0000-4000-8000-000000000010', 'fii', 7.0, 0.1800, 'em percentual, errado');
$sql$, 'T113 retorno real em percentual em vez de fração');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.class_assumptions
    (assumption_set_id, asset_class_code, retorno_real_aa, volatilidade_aa, fonte)
  VALUES ('11110000-0000-4000-8000-000000000010', 'fii', 0.0600, -0.0100, 'vol negativa');
$sql$, 'T113b volatilidade negativa');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.class_assumptions
    (assumption_set_id, asset_class_code, retorno_real_aa, volatilidade_aa, fonte)
  VALUES ('11110000-0000-4000-8000-000000000010', 'fii', 0.0600, 0.1800, NULL);
$sql$, 'T113c premissa de classe sem fonte');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO market.class_assumptions
    (assumption_set_id, asset_class_code, retorno_real_aa, volatilidade_aa, fonte)
  VALUES ('11110000-0000-4000-8000-000000000010', 'selic', 0.0500, 0.0100, 'duplicata');
$sql$, 'T113d duas premissas para a mesma classe no mesmo conjunto');

-- ================================================================ TESTE 114
-- O mesmo gate C40d, agora sobre a premissa de mercado: o número que o cliente lê sai de
-- premissa que compliance aprovou. Um rascunho serve para calibrar, nunca para publicar.
INSERT INTO market.assumption_sets
  (id, code, version, horizonte_anos, metodologia, compliance_status)
VALUES ('11110000-0000-4000-8000-000000000011', 'T111_NAO_APROVADO', 1, 30,
        'Cenário alternativo em calibração, ainda sem revisão de compliance.', 'draft');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.goal_projections
    (goal_id, scope_id, run_id, as_of_date, assumption_set_id,
     success_prob, p5_brl, p10_brl, p25_brl, p50_brl, p75_brl, p90_brl, p95_brl)
  VALUES ('11110000-0000-4000-8000-000000000007', '11110000-0000-4000-8000-000000000002',
          '11110000-0000-4000-8000-000000000005', current_date,
          '11110000-0000-4000-8000-000000000011',
          0.7200, 80000, 88000, 99000, 118000, 140000, 165000, 180000);
$sql$, 'T114 projeção client-facing sobre premissa de mercado em rascunho');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.goal_projections
    (goal_id, scope_id, run_id, as_of_date,
     success_prob, p5_brl, p10_brl, p25_brl, p50_brl, p75_brl, p90_brl, p95_brl)
  VALUES ('11110000-0000-4000-8000-000000000007', '11110000-0000-4000-8000-000000000002',
          '11110000-0000-4000-8000-000000000005', current_date,
          0.7200, 80000, 88000, 99000, 118000, 140000, 165000, 180000);
$sql$, 'T114b projeção client-facing sem conjunto de premissas nenhum');

-- ================================================================ TESTE 115
-- Percentil fora de ordem não é dado ruim: é dado impossível, e denuncia troca de coluna
-- ou distribuição mal ordenada antes que o fan chart vire uma figura sem sentido.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.goal_projections
    (goal_id, scope_id, run_id, as_of_date, assumption_set_id,
     success_prob, p5_brl, p10_brl, p25_brl, p50_brl, p75_brl, p90_brl, p95_brl)
  VALUES ('11110000-0000-4000-8000-000000000007', '11110000-0000-4000-8000-000000000002',
          '11110000-0000-4000-8000-000000000005', current_date,
          '11110000-0000-4000-8000-000000000010',
          0.7200, 130000, 88000, 99000, 118000, 140000, 165000, 180000);
$sql$, 'T115 p5 acima da mediana');

SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.goal_projections
    (goal_id, scope_id, run_id, as_of_date, assumption_set_id,
     success_prob, p5_brl, p10_brl, p25_brl, p50_brl, p75_brl, p90_brl, p95_brl)
  VALUES ('11110000-0000-4000-8000-000000000007', '11110000-0000-4000-8000-000000000002',
          '11110000-0000-4000-8000-000000000005', current_date,
          '11110000-0000-4000-8000-000000000010',
          0.7200, 80000, 88000, 99000, 118000, 140000, 200000, 180000);
$sql$, 'T115b p95 abaixo do p90');

-- ================================================================ TESTE 116
SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.goal_projections
    (goal_id, scope_id, run_id, as_of_date, assumption_set_id,
     success_prob, prob_abaixo_do_depositado,
     p5_brl, p10_brl, p25_brl, p50_brl, p75_brl, p90_brl, p95_brl)
  VALUES ('11110000-0000-4000-8000-000000000007', '11110000-0000-4000-8000-000000000002',
          '11110000-0000-4000-8000-000000000005', current_date,
          '11110000-0000-4000-8000-000000000010',
          0.7200, 1.3000, 80000, 88000, 99000, 118000, 140000, 165000, 180000);
$sql$, 'T116 probabilidade de arrependimento fora de [0,1]');

-- Reprodutibilidade não é boa prática aqui, é exigência: uma projeção que ninguém consegue
-- refazer não é auditável, e a semente é o que a torna refazível. Ela mora em
-- `engine.runs.params`, que já entra no `input_hash` — e portanto na identidade do run.
SELECT pg_temp.expect_fail($sql$
  INSERT INTO planning.goal_projections
    (goal_id, scope_id, run_id, as_of_date, assumption_set_id,
     success_prob, p5_brl, p10_brl, p25_brl, p50_brl, p75_brl, p90_brl, p95_brl)
  VALUES ('11110000-0000-4000-8000-000000000007', '11110000-0000-4000-8000-000000000002',
          '11110000-0000-4000-8000-000000000006', current_date,
          '11110000-0000-4000-8000-000000000010',
          0.7200, 80000, 88000, 99000, 118000, 140000, 165000, 180000);
$sql$, 'T116b projeção cujo run não registrou a semente');

-- caminho feliz: premissa aprovada, percentis em ordem, semente no run
INSERT INTO planning.goal_projections
  (goal_id, scope_id, run_id, as_of_date, assumption_set_id,
   success_prob, prob_abaixo_do_depositado,
   p5_brl, p10_brl, p25_brl, p50_brl, p75_brl, p90_brl, p95_brl)
VALUES ('11110000-0000-4000-8000-000000000007', '11110000-0000-4000-8000-000000000002',
        '11110000-0000-4000-8000-000000000005', current_date,
        '11110000-0000-4000-8000-000000000010',
        0.7200, 0.0400, 80000, 88000, 99000, 118000, 140000, 165000, 180000);

SELECT pg_temp.expect_count($sql$
  SELECT 1 FROM planning.goal_projections
   WHERE goal_id = '11110000-0000-4000-8000-000000000007' AND success_prob = 0.7200
$sql$, 1, 'T116c com premissa aprovada e semente registrada, a projeção entra');

ROLLBACK;

\echo ''
\echo '================================================================'
\echo ' Premissa de mercado é opinião com autor: metodologia declarada,'
\echo ' aprovação de compliance e matriz de correlação fechada. Unidade'
\echo ' é constraint — 0,07 passa, 7,0 não. E projeção sem semente não'
\echo ' é projeção: é um número que ninguém consegue refazer.'
\echo '================================================================'
