-- =============================================================================
-- PLEXO · 46_insumos_da_lacuna.sql — a correção da 44, agora inteira [F16]
--
-- COMO ISTO FOI ACHADO
--   Pelos testes de propriedade da F16, na primeira execução deles. Duas propriedades
--   dispararam sobre o mesmo indicador:
--
--     "sem insumo REQUERIDO a fórmula não devolve número"
--       → `protecao.lacuna_seguro_vida` devolvia 630.000 sem `protecao.cobertura_vida`.
--
--     "insumo OPCIONAL que muda o resultado não é opcional"
--       → remover `divida.saldo_total` mudava 330.000 para 300.000.
--
-- O QUE ESTAVA ERRADO
--   A migration 44 corrigiu a lacuna de seguro no CATÁLOGO — `protecao.cobertura_vida`
--   passou de opcional a requerida — e a FÓRMULA continuou lendo a ausência como zero.
--   Como `calcular_perfil` confere a cobertura antes de calcular, o erro não aparecia no
--   fim a fim: o indicador saía indisponível pelo caminho certo, pela razão errada. A
--   função pura, que é o que os goldens travam e o que o próximo motor vai reusar,
--   continuava mentindo.
--
--   E `divida.saldo_total` tinha o mesmo defeito na direção oposta: dívida DESCONHECIDA
--   lida como dívida ZERO, o que SUBESTIMA a lacuna. Errar para menos aqui é pior que
--   errar para mais — subestimar uma lacuna de proteção é o silêncio que custa caro.
--
--   A derivação sempre produz `divida.saldo_total` (grava 0,0 quando consultou e não há
--   dívida — um fato, não uma suposição), então exigi-la não custa cobertura nenhuma na
--   prática. Custa apenas honestidade sobre o que se sabe.
--
--   `renda.tipo_vinculo` era insumo OPCIONAL de `fluxo.concentracao_renda` e a fórmula
--   nunca o leu. Intenção não entregue parada na configuração engana quem for calibrar:
--   sai da lista até que alguém a implemente.
--
-- Regressão: `tests/test_f16_propriedades.py`, famílias "completude" e "honestidade".
--
-- Depende de: 40_client_profile, 44_fidelidade_do_perfil.
-- =============================================================================

BEGIN;

UPDATE diagnostics.indicator_definitions
   SET required_fact_keys = ARRAY['protecao.dependentes_financeiros',
                                  'despesa.essencial_mensal',
                                  'protecao.cobertura_vida',
                                  'divida.saldo_total']::core.slug[],
       optional_fact_keys = '{}'::core.slug[],
       notes = notes || ' [46] `divida.saldo_total` também passou a REQUERIDO: dívida '
                        'desconhecida lida como zero SUBESTIMAVA a lacuna, e errar para '
                        'menos numa lacuna de proteção é o silêncio que custa caro.'
 WHERE code = 'protecao.lacuna_seguro_vida';

UPDATE diagnostics.indicator_definitions
   SET optional_fact_keys = '{}'::core.slug[],
       notes = coalesce(notes, '') || ' [46] `renda.tipo_vinculo` saiu dos opcionais: era '
                                      'declarado e nunca lido pela fórmula.'
 WHERE code = 'fluxo.concentracao_renda';

COMMIT;
