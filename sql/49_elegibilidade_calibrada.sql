-- =============================================================================
-- PLEXO · 49_elegibilidade_calibrada.sql — a tolerância que faltava ao p5 [F17, 2ª onda]
--
-- UMA REGRA QUE DÁ SEMPRE A MESMA RESPOSTA NÃO É REGRA
--
-- A 48 semeou `SIMULACAO_METAS` v2 com `piora_maxima_do_p5 = 0,00`: nenhuma piora do
-- cenário ruim seria tolerada em troca de probabilidade. Parecia a escolha conservadora.
-- Rodar o motor mostrou que é outra coisa — é um veto universal.
--
-- Mais risco quase sempre baixa o p5 para um mesmo aporte: é o que "mais risco" SIGNIFICA.
-- Com tolerância zero, a condição (2) engole a condição (1) e a regra do §4 do
-- `META_PROBABILIDADE_DE_SUCESSO.md` colapsa em "nunca tome risco", inclusive onde o
-- documento usa o caso oposto como demonstração. Medido, com as premissas da PLEXO_BASE:
--
--   meta de  24 meses · aporte 2.200 · alvo 60k
--     conservadora  p5  58.924   prob 0,677
--     balanceada    p5  57.037   prob 0,634   ← p5 −3%, e a probabilidade CAI 4 pontos
--
--   meta de 240 meses · aporte 2.500 · alvo 1,2 mi
--     conservadora  p5 966.741   prob 0,007
--     balanceada    p5 910.427   prob 0,356   ← p5 −6%, e a probabilidade SOBE 35 pontos
--     arrojada      p5 752.419   prob 0,480   ← p5 −22% por mais 12 pontos
--
-- Com zero de tolerância, as duas metas recebiam o mesmo veredito e pelo mesmo motivo. A
-- meta longa é exatamente o caso em que risco compra probabilidade, e vetá-lo ali não
-- protege ninguém: empurra o cliente para um plano que a própria simulação diz que não
-- chega (0,7% de chance) sem nunca lhe mostrar por quê.
--
-- A TOLERÂNCIA, E POR QUE 10%
--   O p5 continua sendo guarda — só deixa de ser veto automático. Dez por cento do cenário
--   ruim da carteira conservadora é a faixa em que a perda de piso ainda é comparável ao
--   erro da PRÓPRIA premissa (as volatilidades da PLEXO_BASE vêm de uma janela de 20 anos e
--   não têm precisão melhor que isso). Acima disso a piora é maior que a incerteza da conta
--   que a mediu, e aí ela é real.
--
--   Com 10%: a meta curta é vetada por MATERIALIDADE — a mensagem informativa, a que diz
--   que risco não compra probabilidade naquele prazo —, e a meta longa para na balanceada,
--   com a arrojada recusada pelos 22% de piora do piso. Os dois vereditos citam o número
--   que os decidiu, que é o que os torna contestáveis.
--
-- Isto é DECISÃO DE COMPLIANCE, não de engenharia: continua `draft` e continua precisando
-- de aprovação com nome e data antes de virar número na tela (C40d/C48c). O que esta
-- migration faz é dar a ela um valor que pelo menos deixa a regra funcionar como escrita.
--
-- Depende de: 48_market_assumptions.
-- =============================================================================

BEGIN;

UPDATE engine.policy_versions SET effective_to = now()
 WHERE code = 'SIMULACAO_METAS' AND effective_to IS NULL;

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'SIMULACAO_METAS', 3,
       jsonb_set(payload, '{elegibilidade_de_risco,piora_maxima_do_p5}', '0.10'::jsonb)
       || jsonb_build_object(
            'nota_49',
            'piora_maxima_do_p5 saiu de 0,00 para 0,10 (fração do p5 da carteira '
            'conservadora). Em 0,00 a regra vetava risco em TODA meta, inclusive nas longas '
            'em que a probabilidade sobe 35 pontos — a condição do cenário ruim engolia a da '
            'materialidade e o §4 virava "nunca tome risco". O p5 continua guarda; deixou de '
            'ser veto automático.'),
       'draft'
  FROM engine.policy_versions
 WHERE code = 'SIMULACAO_METAS' AND version = 2;

COMMIT;
