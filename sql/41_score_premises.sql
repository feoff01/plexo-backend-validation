-- =============================================================================
-- PLEXO · 41_score_premises.sql — Premissas dos indicadores [F14c]
--
-- POR QUE ESTA MIGRATION EXISTE (e por que ela é pequena de propósito)
--   Três indicadores da 40 precisam de premissa numérica que a 40 não trouxe:
--     · protecao.lacuna_seguro_vida     — quantos anos de despesa cobrir por dependente
--     · protecao.vulnerabilidade_choque — qual queda de renda o cenário simula
--     · destino.esforco_requerido       — que retorno real usar no aporte necessário
--   Escrever qualquer um desses números no Python violaria config-first e a exigência
--   de inspeção regulatória: a CVM revisa a premissa, não o commit. E editar a 40, que
--   já está aplicada, violaria o append-only. Então: versão nova da política, com a
--   anterior encerrada e datada. É este o caminho — premissa não muda por edição.
--
-- Depende de: 02_engine, 40_client_profile.
-- =============================================================================

BEGIN;

UPDATE engine.policy_versions
   SET effective_to = now()
 WHERE code = 'CLIENT_SCORES' AND effective_to IS NULL;

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'CLIENT_SCORES', 2,
       payload || '{
  "premissas_indicadores": {
    "anos_de_despesa_por_dependente": 5,
    "queda_de_renda_no_choque": 0.40,
    "retorno_real_mensal_para_esforco": 0.0035,
    "nota": "anos_de_despesa_por_dependente é a janela de sustento que a lacuna de seguro cobre; queda_de_renda_no_choque é o cenário de vulnerabilidade (o mesmo −40% da demo do Copiloto); retorno_real_mensal_para_esforco entra no aporte necessário do objetivo — zero real superestimaria o esforço e assustaria sem motivo."
  }
}'::jsonb,
       'draft'
  FROM engine.policy_versions
 WHERE code = 'CLIENT_SCORES' AND version = 1;

COMMIT;
