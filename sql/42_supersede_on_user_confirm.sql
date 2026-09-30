-- =============================================================================
-- PLEXO · 42_supersede_on_user_confirm.sql — correção da regra de supersessão [F14]
--
-- O BUG QUE ESTA MIGRATION CORRIGE (achado por teste, não por leitura)
--   A 38 tornou a supersessão consciente de precedência: uma asserção só aposenta as
--   irmãs de fonte igual ou mais fraca. A intenção estava certa — um PDF enviado à mão
--   não pode derrubar o dado do Open Finance. A regra, porém, ficou larga demais e
--   atropelou o caminho principal do produto:
--
--     renda registrada no onboarding (source='formulario', precedência 1)
--     cliente diz "passei a ganhar 10 mil" e CONFIRMA o card (source='conversa', 2)
--       → 2 <= 1 é falso → a nova NÃO aposentava a antiga
--       → v_fact_current continuava devolvendo 8.000
--
--   Ou seja: o cliente confirmava, o banco gravava, e o contexto não mudava. Um laço de
--   confirmação que não muda nada é pior que não perguntar — ele gasta a atenção do
--   cliente e mente sobre o efeito.
--
-- A REGRA CORRIGIDA, e por que ela continua segura
--   Quem protege o dado medido NÃO é a precedência: é `allows_conversation_update`. Essa
--   coluna já diz, por fato, o que a conversa não pode tocar (patrimônio investido, que o
--   Open Finance governa; tolerância a risco, que é registro regulatório). Onde ela é
--   `false`, C38b impede a confirmação por conversa ANTES de chegar aqui, e a precedência
--   segue mandando entre as fontes automáticas.
--
--   Onde ela é `true`, a confirmação EXPLÍCITA do cliente vence — porque é ela o dado mais
--   fresco que existe: a pessoa sabe do próprio aumento antes de qualquer extrato.
--
--   `v_fact_current` continua resolvendo por precedência os casos em que duas fontes
--   coexistem sem que ninguém tenha confirmado nada.
--
-- Regressão: `test_confirmar_aplica_e_atualiza_o_contexto` (tests/test_f14_perfil.py) e
-- T82 (que continua provando que upload não derruba open_finance).
--
-- Depende de: 22_assertions, 38_fact_catalog.
-- =============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION context.supersede_siblings_on_confirm() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_conversa_manda boolean;
BEGIN
  -- Fato que a conversa pode atualizar: a confirmação do cliente é o dado mais fresco
  -- que existe e aposenta as irmãs. Fato governado por outra fonte: só a precedência decide
  -- (e C38b já impediu que uma asserção de conversa chegasse confirmada até aqui).
  SELECT coalesce(d.allows_conversation_update, false) INTO v_conversa_manda
    FROM context.fact_definitions d WHERE d.fact_key = NEW.fact_key;

  UPDATE context.assertions a
     SET status        = 'obsoleto',
         superseded_at = now(),
         superseded_by = NEW.id
   WHERE a.id <> NEW.id
     AND a.scope_id     = NEW.scope_id
     AND a.subject_kind = NEW.subject_kind
     AND a.subject_ref IS NOT DISTINCT FROM NEW.subject_ref
     AND a.attribute    = NEW.attribute
     AND a.modality     = NEW.modality
     AND a.superseded_at IS NULL
     AND a.status <> 'refutado'   -- refutado morreu refutado; não vira "obsoleto"
     AND (NEW.fact_key IS NULL
          OR coalesce(v_conversa_manda, false)
          OR context.source_rank(NEW.fact_key, NEW.source)
             <= context.source_rank(NEW.fact_key, a.source));
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION context.supersede_siblings_on_confirm IS
  'C38c (corrigida na 42) — confirmar aposenta as irmãs. Em fato governado por outra fonte '
  '(allows_conversation_update = false), só aposenta quem for de precedência igual ou mais '
  'fraca; nos demais, a confirmação explícita do cliente vence, porque senão confirmar não '
  'muda nada e o card vira teatro.';

COMMIT;
