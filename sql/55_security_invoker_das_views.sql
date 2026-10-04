-- =============================================================================
-- PLEXO · 55_security_invoker_das_views.sql — a regra nº 1 desfeita por uma cláusula omitida
--
-- O DEFEITO
--
-- `diagnostics.v_client_profile` e `context.v_fact_coverage` nasceram CERTAS:
--   40_client_profile.sql:251  CREATE VIEW diagnostics.v_client_profile WITH (security_invoker = true)
--   38_fact_catalog.sql:590    CREATE VIEW context.v_fact_coverage      WITH (security_invoker = true)
--
-- Depois foram reescritas — a primeira três vezes (44, 45, 47), a segunda uma (43) — sempre
-- assim:
--   CREATE OR REPLACE VIEW diagnostics.v_client_profile AS ...
--
-- **sem repetir a cláusula.** E o caminho de REPLACE do PostgreSQL SUBSTITUI as reloptions em
-- vez de mesclá-las: cada reescrita apagou a flag, em silêncio, quatro vezes ao todo.
--
-- View sem `security_invoker` executa com os direitos do DONO. O dono aqui é o `avnadmin`,
-- que tem BYPASSRLS — o próprio `CLAUDE.md` avisa disso para testes. Resultado medido no
-- banco real em 2026-08-30, antes desta migration, sob `plexo_app` com `app.scope_id` de UM
-- cliente:
--
--   diagnostics.v_client_profile   →  9 escopos visíveis
--   context.v_fact_coverage        → 22 escopos visíveis
--   diagnostics.client_scores      →  1 escopo (a TABELA sempre esteve certa)
--
-- A RLS nunca falhou. As views a contornavam. `v_fact_coverage` é a pior das duas: ela faz
-- CROSS JOIN com `identity.scopes`, então enumerava o que FALTA saber sobre cada cliente da
-- base — o mapa das lacunas de todo mundo, para qualquer sessão autenticada.
--
-- POR QUE NINGUÉM VIU
--
-- `tools/validador.py` casava `CREATE (MATERIALIZED )?VIEW` e não `CREATE OR REPLACE VIEW`,
-- então as reescritas passavam sem checagem. E `test_rls_papeis.sql` prova a RLS das
-- TABELAS, que estava certa o tempo todo. Os dois gates olhavam para o lado certo do
-- problema errado.
--
-- Esta migration conserta as duas views. O que impede a próxima é a rede, não o remendo:
--   · T129 (`tests/test_regras_invioláveis_views.sql`) afirma a propriedade sobre TODAS as
--     views dos schemas de dado de cliente, não sobre estas duas;
--   · `tools/validador.py` passou a recusar `CREATE OR REPLACE VIEW` sem a cláusula.
--
-- `ALTER VIEW ... SET` em vez de recriar: o corpo das duas está correto e recriá-lo aqui
-- duplicaria 80 linhas de SQL que a 47 e a 43 já definem — e seria mais uma chance de a
-- cláusula cair de novo.
--
-- Depende de: 38_fact_catalog, 40_client_profile, 43_fact_derivation, 47_renda_comprometivel.
-- Testes: tests/test_regras_invioláveis_views.sql (T127–T129).
-- =============================================================================

BEGIN;

ALTER VIEW diagnostics.v_client_profile SET (security_invoker = true);
ALTER VIEW context.v_fact_coverage      SET (security_invoker = true);

COMMENT ON VIEW diagnostics.v_client_profile IS
  '[F19] Perfil do cliente como a OPERAÇÃO lê (mostra o que está em calibração). '
  'security_invoker RESTAURADO pela migration 55: as reescritas 44/45/47 usaram '
  '`CREATE OR REPLACE VIEW` sem a cláusula, e o REPLACE do PostgreSQL substitui as '
  'reloptions em vez de mesclá-las — a view passou a rodar com BYPASSRLS do dono e devolvia '
  '9 escopos para uma sessão de um cliente só. Quem reescrever esta view PRECISA repetir '
  '`WITH (security_invoker = true)`.';

COMMENT ON VIEW context.v_fact_coverage IS
  '[F19] Cobertura do catálogo de fatos por escopo. security_invoker RESTAURADO pela '
  'migration 55 (mesmo defeito da 43). Esta view faz CROSS JOIN com identity.scopes: sem a '
  'flag, ela enumera as lacunas de contexto de TODOS os clientes para qualquer sessão. Quem '
  'a reescrever PRECISA repetir `WITH (security_invoker = true)`.';

COMMIT;
