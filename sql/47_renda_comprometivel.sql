-- =============================================================================
-- PLEXO · 47_renda_comprometivel.sql — o piso da renda, e o elo que precisa de margem [F16]
--
-- DOIS DEFEITOS, OS DOIS ACHADOS LENDO O DIAGNÓSTICO DE UMA PERSONA
--
-- (1) O MOTOR JULGAVA SUSTENTABILIDADE PELA MÉDIA — contra regra explícita do projeto
--
--     A persona `autonomo_volatil` tem renda média de R$ 13.500 e PISO OBSERVADO de
--     R$ 4.200. Num mês de piso ela não cobre os R$ 8.900 de despesa. O motor devolvia
--     Fluxo 0,86 — "quase ótimo" — porque `fluxo.rigidez_orcamentaria` dividia o gasto fixo
--     contratado pela renda MÉDIA.
--
--     A migration 24 já tinha decidido isto, e em letras maiúsculas:
--
--       "A REGRA: não se compromete o que só aparece nos bons meses."
--       "O aporte recorrente, a parcela e o teto de dívida saem de committable_brl —
--        NUNCA de total_brl."
--       — COMMENT ON CONSTRAINT committable_within_floor
--
--     `budget.income_summaries.committable_brl` existe desde lá, com CHECK garantindo que
--     não passa de fixo + p10. Ninguém o lia. O indicador que mede QUANTO CHOQUE A PESSOA
--     ABSORVE é justamente o que não pode usar a média — é a diferença entre um planejador
--     e uma planilha otimista, e o motor estava do lado da planilha.
--
--     `fluxo.rigidez_orcamentaria` passa a exigir `renda.comprometivel`. `taxa_poupanca`
--     continua na renda total, de propósito: ela mede o que a pessoa DE FATO poupou, e para
--     isso a média é o número certo. São perguntas diferentes.
--
-- (2) "ELO MAIS FRACO" COM DIFERENÇA DESPREZÍVEL
--
--     `dependentes_sem_seguro` saiu com Proteção 0,76 e Fluxo 0,77, e a tela apontou
--     Proteção como "o que mais limita o seu rumo hoje". Um centésimo de diferença não
--     sustenta essa frase: é ruído apresentado como sinal, e manda o cliente agir sobre uma
--     distinção que o próprio motor não consegue justificar.
--
--     O elo passa a exigir MARGEM sobre o segundo colocado. Sem margem, não há elo — e a
--     tela não aponta nada, que é a leitura honesta de um empate.
--
-- Depende de: 24_income, 38_fact_catalog, 40_client_profile, 44, 46.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------- (1) o piso da renda
INSERT INTO context.fact_definitions
  (fact_key, subject_kind, attribute, family, display_name, pergunta, value_type, unit,
   source_precedence, allows_conversation_update, half_life_days,
   materiality_abs, materiality_rel, min_value, max_value,
   is_recurring_by_nature, requires_nature_check, notes)
VALUES
  ('renda.comprometivel', 'renda', 'renda_comprometivel', 'fluxo',
   'Renda que dá para comprometer',
   'Nos meses piores, com quanto você pode contar?', 'money_brl', 'BRL',
   ARRAY['inferencia_motor','formulario','conversa','onboarding','open_finance','upload','operador']::context.assertion_source[],
   true, 180, 500, 0.05, 0, 10000000, true, true,
   'Fixo + piso p10 do variável (budget.income_summaries.committable_brl). É o número que '
   'julga sustentabilidade: não se compromete o que só aparece nos bons meses (migration 24).')
ON CONFLICT (fact_key) DO NOTHING;

UPDATE diagnostics.indicator_definitions
   SET required_fact_keys = ARRAY['despesa.fixa_contratada',
                                  'renda.comprometivel']::core.slug[],
       display_name = 'Rigidez orçamentária sobre a renda do mês pior',
       notes = coalesce(notes, '') || ' [47] Passou a dividir pela renda COMPROMETÍVEL, não '
               'pela média: a persona autônoma saía com Fluxo 0,86 tendo piso de renda a um '
               'terço da média. Quem mede absorção de choque não pode usar o mês bom.'
 WHERE code = 'fluxo.rigidez_orcamentaria';

-- ---------------------------------------------------------------- (2) margem do elo
UPDATE engine.policy_versions SET effective_to = now()
 WHERE code = 'CLIENT_SCORES' AND effective_to IS NULL;

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'CLIENT_SCORES', 3,
       jsonb_set(
         payload || '{"margem_minima_do_elo": 0.05}'::jsonb,
         '{normalizacao,fluxo.rigidez_orcamentaria}',
         -- A curva se desloca junto com o denominador: gasto fixo sobre a renda do mês
         -- pior tolera menos que sobre a média. 100% do piso comprometido é o zero.
         '{"pontos": [[0.30,1.0],[0.60,0.70],[0.85,0.30],[1.00,0.0]], "clamp": true}'::jsonb)
       || '{"nota_47": "margem_minima_do_elo: diferença mínima entre o menor e o segundo menor score crítico para que o elo mais fraco seja apontado. Sem margem não há elo — empate técnico não vira próxima ação."}'::jsonb,
       'draft'
  FROM engine.policy_versions
 WHERE code = 'CLIENT_SCORES' AND version = 2;

CREATE OR REPLACE VIEW diagnostics.v_client_profile AS
WITH criticos AS (
  SELECT s.scope_id, s.as_of_date,
         min(s.value) FILTER (WHERE d.is_critical_family AND NOT s.is_disabled
                                    AND s.value IS NOT NULL) AS menor,
         -- o SEGUNDO menor: é contra ele que a margem se mede
         (array_agg(s.value ORDER BY s.value)
            FILTER (WHERE d.is_critical_family AND NOT s.is_disabled
                          AND s.value IS NOT NULL))[2]        AS segundo,
         count(*) FILTER (WHERE d.is_critical_family AND NOT s.is_disabled
                                AND s.value IS NOT NULL)      AS n_criticos
    FROM diagnostics.client_scores s
    JOIN diagnostics.score_definitions d ON d.code = s.score_code
   WHERE d.is_active
   GROUP BY s.scope_id, s.as_of_date
),
margem AS (
  SELECT coalesce((payload ->> 'margem_minima_do_elo')::numeric, 0)::numeric AS v
    FROM engine.policy_versions
   WHERE code = 'CLIENT_SCORES' AND effective_to IS NULL
)
SELECT s.scope_id,
       s.as_of_date,
       s.score_code,
       d.family,
       d.display_name,
       d.is_critical_family,
       s.value,
       s.coverage,
       s.confidence,
       s.is_disabled,
       s.disabled_reason,
       f.is_critical           AS fundacao_critica,
       f.overall_light         AS fundacao_semaforo,
       (s.value IS NOT NULL
        AND d.is_critical_family
        AND NOT s.is_disabled
        AND c.n_criticos >= 2
        AND s.value = c.menor
        -- [47] e com MARGEM sobre o segundo: um centésimo de diferença não sustenta
        -- "é isto que mais limita o seu rumo".
        AND c.segundo - c.menor >= (SELECT v FROM margem)) AS elo_mais_fraco,
       r.is_client_facing,
       (pv.compliance_status = 'approved') AS politica_aprovada
  FROM diagnostics.client_scores s
  JOIN diagnostics.score_definitions d ON d.code = s.score_code
  JOIN engine.runs r ON r.id = s.run_id
  JOIN engine.policy_versions pv ON pv.id = s.policy_version_id
  JOIN criticos c ON c.scope_id = s.scope_id AND c.as_of_date = s.as_of_date
  LEFT JOIN diagnostics.foundation_status f
         ON f.scope_id = s.scope_id AND f.as_of_date = s.as_of_date
 WHERE d.is_active;

COMMENT ON VIEW diagnostics.v_client_profile IS
  '[F14, corrigida na 44, 45 e 47] Perfil por família. `elo_mais_fraco` exige DUAS famílias '
  'críticas pontuadas e margem mínima entre a menor e a segunda — empate técnico não vira '
  'próxima ação. `is_client_facing` e `politica_aprovada` dizem se o número pode ser mostrado.';

COMMIT;
