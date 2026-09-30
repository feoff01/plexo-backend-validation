-- =============================================================================
-- PLEXO · 45_perfil_client_facing.sql — o gate C40d também na LEITURA [F15]
--
-- O BURACO
--   A migration 40 criou o gate certo: score client-facing exige política aprovada por
--   compliance (C40d). Ele protege a ESCRITA — e vazava na LEITURA.
--
--     engine.runs.is_client_facing = false  +  CLIENT_SCORES em 'draft'
--       → C40d deixa gravar (é run interno, de calibração)
--       → `diagnostics.v_client_profile` devolvia esse score
--       → `GET /perfil` mostrava o número ao cliente
--
--   Ou seja: bastava calibrar sobre rascunho para o número aparecer na tela. Verificado no
--   escopo de dev: `score.estoque = 0,29`, run interno, política em rascunho, visível.
--
--   Um gate que só vale na escrita não é gate: é convenção. E este em particular é o que
--   sustenta a promessa de que todo número que o cliente lê saiu de premissa que compliance
--   aprovou (RCVM 19).
--
-- A CORREÇÃO
--   A view passa a expor `is_client_facing` (do run) e `politica_aprovada` (da política que
--   produziu o score). Quem monta a tela filtra por eles; quem calibra continua enxergando
--   tudo pela tabela. A distinção fica no dado, não na disciplina de quem consulta.
--
--   Deliberadamente NÃO se filtra dentro da view: `v_client_profile` também serve à operação
--   (comparar calibração com o publicado), e uma view que esconde metade das linhas conforme
--   um estado invisível é pior que uma coluna explícita.
--
-- Depende de: 40_client_profile, 44_fidelidade_do_perfil.
-- =============================================================================

BEGIN;

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
       (s.value IS NOT NULL
        AND d.is_critical_family
        AND NOT s.is_disabled
        AND count(*) FILTER (WHERE d.is_critical_family AND NOT s.is_disabled
                                   AND s.value IS NOT NULL)
              OVER (PARTITION BY s.scope_id, s.as_of_date) >= 2
        AND s.value = min(s.value) FILTER (WHERE d.is_critical_family AND NOT s.is_disabled)
                        OVER (PARTITION BY s.scope_id, s.as_of_date)) AS elo_mais_fraco,
       -- [45] O par que fecha o gate na LEITURA: o cliente só pode ver número de run
       -- client-facing cuja política de normalização compliance aprovou. Vão no FIM porque
       -- CREATE OR REPLACE VIEW só admite coluna acrescentada ao final.
       r.is_client_facing,
       (pv.compliance_status = 'approved') AS politica_aprovada
  FROM diagnostics.client_scores s
  JOIN diagnostics.score_definitions d ON d.code = s.score_code
  JOIN engine.runs r ON r.id = s.run_id
  JOIN engine.policy_versions pv ON pv.id = s.policy_version_id
  LEFT JOIN diagnostics.foundation_status f
         ON f.scope_id = s.scope_id AND f.as_of_date = s.as_of_date
 WHERE d.is_active;

COMMENT ON VIEW diagnostics.v_client_profile IS
  '[F14, corrigida na 44 e na 45] O perfil por família com o elo mais fraco entre as críticas '
  '(quando há duas para comparar). `is_client_facing` e `politica_aprovada` dizem se aquele '
  'número pode ser MOSTRADO ao cliente: o gate C40d vale na escrita e, por estas colunas, '
  'também na leitura. Score de calibração continua visível para a operação — só não vai à tela.';

COMMIT;
