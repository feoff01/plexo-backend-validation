-- =============================================================================
-- PLEXO · 44_fidelidade_do_perfil.sql — Duas correções achadas ao RODAR [F15]
--
-- Nenhuma das duas é bug de encanamento: as duas são de FIDELIDADE, o tipo que só aparece
-- quando os números reais de um cliente real passam pelo motor. Apareceram na primeira
-- derivação da persona.
--
-- (1) A LACUNA DE SEGURO AFIRMAVA O QUE NÃO SABIA
--     `protecao.lacuna_seguro_vida` publicou uma lacuna de R$ 1.805.500 para uma cliente de
--     quem o sistema NÃO SABE se tem seguro. A cobertura estava como insumo OPCIONAL, e a
--     fórmula lia ausência como `coalesce(..., 0)` — ou seja, "não informado" virava
--     "não tem", que é uma afirmação, não uma ausência.
--
--     É exatamente o erro que o resto desta camada foi construída para não cometer: indicador
--     sem base não sai com número, sai indisponível dizendo o que falta. A cobertura do seguro
--     passa a ser REQUERIDA; sem ela o indicador fica `dados_insuficientes` e "você tem seguro
--     de vida?" vira a próxima pergunta — que é o comportamento útil, e o honesto.
--
-- (2) "ELO MAIS FRACO" DE UM CONJUNTO DE UM
--     Com só uma família crítica pontuada, ela era marcada como elo mais fraco por ser o
--     mínimo de si mesma. A persona saiu com "Fluxo 1,00 ← elo mais fraco", que é ruído com
--     cara de diagnóstico. Elo mais fraco é uma COMPARAÇÃO: exige no mínimo duas famílias
--     críticas com valor. Sem isso, ninguém é o elo — e a tela não aponta nada.
--
-- Depende de: 40_client_profile.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------- (1)
UPDATE diagnostics.indicator_definitions
   SET required_fact_keys = ARRAY['protecao.dependentes_financeiros',
                                  'despesa.essencial_mensal',
                                  'protecao.cobertura_vida']::core.slug[],
       optional_fact_keys = ARRAY['divida.saldo_total']::core.slug[],
       notes = notes || ' [44] A cobertura passou de opcional para REQUERIDA: sem saber se '
                        'existe seguro, "lacuna" seria afirmação sobre o que não se sabe.'
 WHERE code = 'protecao.lacuna_seguro_vida';

-- ---------------------------------------------------------------- (2)
CREATE OR REPLACE VIEW diagnostics.v_client_profile AS
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
       -- Elo mais fraco: o MENOR score ativo entre as famílias CRÍTICAS — e só quando há
       -- pelo menos DUAS delas pontuadas. Score desativado não concorre (ausência de medida
       -- não é fraqueza medida), e o mínimo de um conjunto de um não é comparação nenhuma.
       (s.value IS NOT NULL
        AND d.is_critical_family
        AND NOT s.is_disabled
        AND count(*) FILTER (WHERE d.is_critical_family AND NOT s.is_disabled
                                   AND s.value IS NOT NULL)
              OVER (PARTITION BY s.scope_id, s.as_of_date) >= 2
        AND s.value = min(s.value) FILTER (WHERE d.is_critical_family AND NOT s.is_disabled)
                        OVER (PARTITION BY s.scope_id, s.as_of_date)) AS elo_mais_fraco
  FROM diagnostics.client_scores s
  JOIN diagnostics.score_definitions d ON d.code = s.score_code
  LEFT JOIN diagnostics.foundation_status f
         ON f.scope_id = s.scope_id AND f.as_of_date = s.as_of_date
 WHERE d.is_active;

COMMENT ON VIEW diagnostics.v_client_profile IS
  '[F14, corrigida na 44] O perfil como ele deve ser lido: gate da Fundação acima, um score '
  'por família, e o elo mais fraco entre as CRÍTICAS — quando há duas delas para comparar. '
  'É do elo que sai a próxima ação; nunca de uma média, que deixaria a falha crítica '
  'desaparecer na conta.';

COMMIT;
