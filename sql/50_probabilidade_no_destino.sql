-- =============================================================================
-- PLEXO · 50_probabilidade_no_destino.sql — o indicador que a F14 adiou [F17, 3ª onda]
--
-- O INDICADOR QUE FALTAVA PORQUE FALTAVA O MOTOR
--
-- A F14 montou `score.destino` com dois indicadores — esforço requerido e horizonte de
-- aposentadoria — e registrou que faltava o terceiro, o mais direto de todos: a CHANCE de o
-- cliente chegar onde quer chegar. Ele ficou de fora por um motivo honesto: ninguém sabia
-- calcular a probabilidade, e um indicador sem motor é um gate sem produtor — passa sempre,
-- e todos os testes ficam verdes (a lição mais cara da F16).
--
-- Agora existe motor (`app/engine/projecao.py`), e o indicador entra.
--
-- QUAL PROBABILIDADE, QUANDO HÁ VÁRIOS OBJETIVOS
--   A MENOR entre os objetivos ativos. É o mesmo princípio do elo mais fraco: o Destino de
--   alguém é tão firme quanto o objetivo que ele tem menos chance de alcançar. Usar a média
--   deixaria um objetivo inalcançável desaparecer atrás de dois fáceis, que é exatamente o
--   que o projeto recusou quando decidiu não ter score único.
--
-- POR QUE 0,90 VALE 1,0 NA CURVA
--   Porque 0,90 é o `nivel_confianca_padrao` da própria política de simulação: é o nível em
--   que o sistema considera um plano "fechado". Acima disso, mais probabilidade não é mais
--   saúde — é aporte a mais que poderia estar sendo vivido. A curva satura ali de propósito,
--   pela mesma razão que 20 meses de reserva não valem mais que 12.
--
-- ORDEM DE EXECUÇÃO — E ELA IMPORTA
--   O fato `objetivo.probabilidade_sucesso` é DERIVADO pela projeção. Quem calcular o perfil
--   sem ter projetado antes vai encontrar o indicador indisponível, com o motivo dizendo
--   qual fato falta — que é o comportamento correto e honesto, não uma falha. O `plexo
--   objetivo projetar` roda antes do `plexo perfil derivar`.
--
-- Depende de: 38_fact_catalog, 40_client_profile, 43_fact_derivation, 48, 49.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------- o fato derivado
INSERT INTO context.fact_definitions
  (fact_key, subject_kind, attribute, family, display_name, pergunta, value_type, unit,
   source_precedence, allows_conversation_update, half_life_days,
   materiality_abs, materiality_rel, min_value, max_value,
   is_recurring_by_nature, requires_nature_check, notes)
VALUES
  ('objetivo.probabilidade_sucesso', 'objetivo', 'objetivo_probabilidade_sucesso', 'destino',
   'Chance de alcançar o objetivo',
   -- `pergunta` NULL, e o CHECK `askable_has_question` aceita porque o fato não é askable:
   -- ninguém pergunta a probabilidade ao cliente. Ela é calculada, ou não existe.
   NULL,
   -- `percentual` + unit `fracao` é o par que o catálogo já usa para taxa (38): 0,72 = 72%.
   'percentual', 'fracao',
   ARRAY['inferencia_motor','operador']::context.assertion_source[],
   false,
   -- meia-vida curta: probabilidade envelhece rápido, porque muda com aporte, prazo e
   -- premissa de mercado. Um número de seis meses atrás não descreve o plano de hoje.
   45, 0.05, 0.10, 0, 1, true, false,
   'MENOR probabilidade entre os objetivos ativos, do run de projeção mais recente. Derivado '
   'por app/engine/projecao.py — o fato não existe antes de a projeção rodar, e o indicador '
   'sai indisponível dizendo isso.')
ON CONFLICT (fact_key) DO NOTHING;

-- ---------------------------------------------------------------- o indicador
INSERT INTO diagnostics.indicator_definitions
  (code, family, display_name, unit, value_type, higher_is_better,
   required_fact_keys, optional_fact_keys, formula_ref, notes)
VALUES
  ('destino.probabilidade_meta', 'destino', 'Chance de alcançar o objetivo',
   'fracao', 'percentual', true,
   ARRAY['objetivo.probabilidade_sucesso']::core.slug[], '{}'::core.slug[],
   'probabilidade_meta',
   '[F17] O indicador mais direto do Destino, adiado na F14 por falta de motor. Vem do Monte '
   'Carlo (engine.runs kind=projection) e carrega a limitação declarada da simulação: '
   'log-retornos normais subestimam a cauda.')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------- entra no score de Destino
UPDATE diagnostics.score_definitions
   SET indicator_codes = ARRAY['destino.probabilidade_meta',
                               'destino.esforco_requerido',
                               'destino.horizonte_aposentadoria']::core.slug[],
       notes = coalesce(notes, '') || ' [50] Ganhou a probabilidade de alcançar o objetivo, '
               'que é o número mais direto desta família e o que faltava desde a F14. '
               'Cliente sem projeção calculada continua com o indicador indisponível, e a '
               'cobertura cai — não vira zero.'
 WHERE code = 'score.destino';

-- ---------------------------------------------------------------- curva e pesos
UPDATE engine.policy_versions SET effective_to = now()
 WHERE code = 'CLIENT_SCORES' AND effective_to IS NULL;

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'CLIENT_SCORES', 4,
       jsonb_set(
         jsonb_set(payload,
           '{normalizacao,destino.probabilidade_meta}',
           -- 0,90 é o `nivel_confianca_padrao` da SIMULACAO_METAS: é ali que o plano se
           -- considera fechado, e é ali que a curva satura.
           '{"pontos": [[0.0,0.0],[0.50,0.35],[0.75,0.70],[0.90,1.0]], "clamp": true}'::jsonb),
         '{pesos,score.destino}',
         '{"destino.probabilidade_meta": 0.45,
           "destino.esforco_requerido": 0.35,
           "destino.horizonte_aposentadoria": 0.20}'::jsonb)
       || '{"nota_50": "score.destino passou a considerar a chance de alcançar o objetivo, com o maior peso da família: é a pergunta que o cliente realmente faz. Esforço requerido e horizonte continuam porque respondem COMO chegar, não SE chega."}'::jsonb,
       'draft'
  FROM engine.policy_versions
 WHERE code = 'CLIENT_SCORES' AND version = 3;

COMMIT;
