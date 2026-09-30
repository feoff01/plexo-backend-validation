-- =============================================================================
-- PLEXO · 57_isencoes_de_rls_declaradas.sql — a isenção vira dado, não silêncio
--
-- POR QUE ESTA MIGRATION EXISTE, E POR QUE ELA É PEQUENA
--
-- O T134 (migration 56) afirma: toda tabela dos schemas de dado de cliente OU tem RLS, OU
-- carrega no COMMENT o marcador `[sem RLS por desenho]` com o motivo. Ele acusou nove, e as
-- nove estão certas em não ter RLS — são catálogos COMPARTILHADOS, sem coluna de dono:
--
--   agents.agent_definitions            os agentes do produto
--   budget.categories                   taxonomia de despesa (12 linhas, `code` é a chave)
--   context.fact_definitions            o vocabulário fechado do Contexto
--   diagnostics.finding_types           os tipos de achado do Raio-X
--   diagnostics.indicator_definitions   as fórmulas do perfil
--   diagnostics.score_definitions       as famílias de score
--   planning.model_portfolios           carteiras modelo — produto, não do cliente
--   planning.model_portfolio_versions   a versão publicada de cada uma
--   planning.model_portfolio_holdings   os pesos de cada versão
--
-- O ponto do T134 não é forçar RLS onde ela não cabe: é fazer a AUSÊNCIA ser uma afirmação
-- que alguém escreveu, em vez de um silêncio que se confunde com esquecimento. Foi o silêncio
-- que deixou 58 tabelas passarem ao mesmo tempo pelo T49 e pelo validador — os dois estavam
-- olhando o formato da coluna, e catálogo e esquecimento têm o mesmo formato.
--
-- A partir daqui, tabela nova nesses schemas tem duas saídas e nenhuma é o silêncio: política,
-- ou este marcador com o motivo.
--
-- Depende de: 56_rls_particoes_e_filhas (o T134 que a torna necessária).
-- Testes: tests/test_regras_invioláveis_rls_completa.sql (T134).
-- =============================================================================

BEGIN;

COMMENT ON TABLE agents.agent_definitions IS
  '[sem RLS por desenho] Catálogo dos agentes do produto (código, prompt vigente, famílias de '
  'tools, plano mínimo). Não tem dono: é a mesma linha para todo cliente, e é lida a cada turno '
  'para montar as tool definitions.';

COMMENT ON TABLE budget.categories IS
  '[sem RLS por desenho] Taxonomia de categoria de despesa, chaveada por `code`. Compartilhada: '
  'quem classifica gasto do cliente é `budget.recurring_items`/`monthly_summaries`, que têm '
  'scope_id e RLS. Categoria própria de cliente não existe hoje; se existir, nasce com dono e '
  'com política, e este comentário sai.';

COMMENT ON TABLE context.fact_definitions IS
  '[sem RLS por desenho] O vocabulário FECHADO do Contexto Pessoal (36 fatos, 6 famílias). É o '
  'catálogo do que a plataforma sabe registrar, não o que ela registrou: o dado do cliente vive '
  'em `context.assertions`, que tem scope_id e RLS. [F14a]';

COMMENT ON TABLE diagnostics.finding_types IS
  '[sem RLS por desenho] A taxonomia de achados do Raio-X (22 tipos). O achado DE UM CLIENTE '
  'vive em `diagnostics.findings`, com scope_id e RLS. Ver `implemented_at`: desde a migration '
  '54, tipo sem produtor declarado não produz finding nenhum.';

COMMENT ON TABLE diagnostics.indicator_definitions IS
  '[sem RLS por desenho] As fórmulas do perfil (`formula_ref` casa com `@formula` em '
  'app/engine/indicadores.py). O VALOR calculado para um cliente vive em `client_indicators`, '
  'com scope_id e RLS.';

COMMENT ON TABLE diagnostics.score_definitions IS
  '[sem RLS por desenho] As famílias de score, seus pesos e a cobertura mínima. O score DE UM '
  'cliente vive em `client_scores`, com scope_id e RLS.';

COMMENT ON TABLE planning.model_portfolios IS
  '[sem RLS por desenho] Carteiras modelo são PRODUTO, iguais para todos — esconder por escopo '
  'seria esconder o catálogo de quem pode adotá-lo. A adoção por um cliente vive em '
  '`planning.model_adoptions`, que tem scope_id e RLS.';

COMMENT ON TABLE planning.model_portfolio_versions IS
  '[sem RLS por desenho] Versão publicada de uma carteira modelo. O `run_id` aqui é PROVENIÊNCIA '
  '— qual execução do motor a publicou —, não dono: por isso ela ficou de fora das oito filhas '
  'que ganharam política na 56.';

COMMENT ON TABLE planning.model_portfolio_holdings IS
  '[sem RLS por desenho] Os pesos de uma versão de carteira modelo. Mesmo raciocínio da tabela '
  'mãe: produto compartilhado, sem dono.';

COMMIT;
