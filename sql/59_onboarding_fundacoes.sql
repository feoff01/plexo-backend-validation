-- =============================================================================
-- PLEXO · 59_onboarding_fundacoes.sql — fundações do onboarding obrigatório [F21a]
--
-- O QUE MUDA E POR QUÊ
--   Até aqui, "onboarding" era um wizard que promete e não cobra: identity.user_profiles
--   guarda trilha e respostas cruas (jsonb) desde a 01, mas nada no banco IMPEDIA marcar
--   onboarding_completed_at sem suitability, sem os fatos-núcleo confirmados ou até sem
--   nunca ter começado. O cliente concluía "no ar" e o resto do produto (perfil, projeção,
--   score) seguia lendo um cadastro capenga sem avisar ninguém.
--
--   Esta migration fecha essa porta com o mesmo padrão que já protege suitability (C21) e
--   fatos confirmados (C22a): o banco é a palavra final, não o formulário da tela.
--
-- GATE C59a — conclusão de onboarding
--   A linha só nasce (ou vira) concluída quando: (i) existe suitability VIGENTE do
--   usuário — não vencida, não superada; (ii) todo fato da lista `fatos_nucleo` da
--   política ONBOARDING_NUCLEO está CONFIRMADO (context.v_fact_current) num escopo do
--   próprio usuário. Fallback fail-closed documentado no próprio trigger (mesmo padrão de
--   identity.enforce_member_limit, 01_identity.sql:97-115) — sem a política vigente, o
--   núcleo mínimo é renda + despesa, nunca "nada". Uma vez concluído, o carimbo é
--   imutável: não se des-conclui, não muda de data — a regra-estrela da 21 sobre
--   suitability, aplicada aqui ao onboarding inteiro.
--
--   `onboarding_started_at`/`onboarding_track` ausentes já são recusados pelos CHECKs
--   simples (a); o trigger cuida só do que exige olhar OUTRA tabela.
--
-- POR QUE SUITABILITY GANHA DUAS TRAVAS NOVAS (C59b)
--   `identity.suitability_assessments` já garantia UMA vigente por usuário (índice
--   `suitability_one_current` desde a 01). Faltavam duas peças: nenhuma linha pode nascer
--   sem escopo (é o scope_id que a política `scope_isolation` usa para isolar o registro —
--   sem ele a RLS não tem o que comparar), e a linha vigente é imutável por completo — a
--   única mudança permitida é encerrar (superseded_at de NULL para agora), nunca reescrever
--   resultado, score ou respostas. Point-in-time regulatório (RCVM 30, comentário original
--   em sql/01_identity.sql:159-161): refazer é LINHA NOVA, nunca UPDATE.
--
-- O QUE NÃO MUDA
--   identity.user_profiles, identity.suitability_assessments e analytics.onboarding_steps
--   já existiam (01/12) com RLS completa (14_rls_partitions.sql) — nenhuma tabela nova,
--   nenhuma política de RLS nova. As duas primeiras têm 0 linhas em qualquer ambiente até
--   aqui (onboarding nunca foi exercitado em produção), então os CHECKs novos entram por
--   ALTER TABLE simples, sem backfill.
--
-- Depende de: 00_core, 01_identity, 02_engine (policy_versions), 12_analytics,
--             14_rls_partitions, 22_assertions, 38_fact_catalog (context.v_fact_current).
-- Testes: tests/test_regras_invioláveis_onboarding.sql (T138–T141), tests/test_f21_onboarding.py.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------- (a) CHECKs simples
-- Conclusão sem nunca ter começado ou sem trilha escolhida é forjada por natureza —
-- não precisa olhar outra tabela, então vira CHECK declarativo, não trigger.
ALTER TABLE identity.user_profiles
  ADD CONSTRAINT completed_needs_started CHECK (
    onboarding_completed_at IS NULL OR onboarding_started_at IS NOT NULL
  ),
  ADD CONSTRAINT completed_needs_track CHECK (
    onboarding_completed_at IS NULL OR onboarding_track IS NOT NULL
  );

COMMENT ON CONSTRAINT completed_needs_started ON identity.user_profiles IS
  '[F21a] Concluir sem onboarding_started_at é o carimbo de um wizard que nunca abriu.';
COMMENT ON CONSTRAINT completed_needs_track ON identity.user_profiles IS
  '[F21a] Concluir sem trilha (a_nao_investe | b_ja_investe) é um estado que a tela nunca produz — só forja.';

-- ---------------------------------------------------------------- (b) C59a — gate de conclusão
-- Roda sob o papel de quem está concluindo (plexo_app, com os GUCs do próprio usuário —
-- T138f prova isso): as leituras abaixo passam pela RLS do próprio escopo, o que já
-- restringe a busca ao que aquele usuário pode ver. SEM SECURITY DEFINER de propósito.
CREATE FUNCTION identity.assert_onboarding_conclusao() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_pol      jsonb;
  v_nucleo   text[];
  v_fato     text;
  v_faltando text[] := '{}';
BEGIN
  -- Carimbo de conclusão é de mão única: uma vez gravado, não se desfaz nem muda de data.
  IF TG_OP = 'UPDATE' AND OLD.onboarding_completed_at IS NOT NULL THEN
    IF NEW.onboarding_completed_at IS DISTINCT FROM OLD.onboarding_completed_at THEN
      RAISE EXCEPTION
        'C59a — o onboarding do usuário % já foi concluído em %: o carimbo é imutável, '
        'não se desfaz nem muda de valor.', NEW.user_id, OLD.onboarding_completed_at
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;

  -- Só valida quando a conclusão está NASCENDO agora (INSERT já completo, ou UPDATE que
  -- preenche onboarding_completed_at pela primeira vez). Qualquer outro UPDATE (progresso
  -- do wizard, respostas, trilha) segue sem tocar aqui.
  IF NEW.onboarding_completed_at IS NULL THEN
    RETURN NEW;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM identity.suitability_assessments
     WHERE user_id = NEW.user_id AND superseded_at IS NULL AND valid_until >= current_date
  ) THEN
    RAISE EXCEPTION
      'C59a — onboarding do usuário % não conclui sem suitability VIGENTE (ausente ou '
      'vencida): refazer o questionário é o próximo passo.', NEW.user_id
      USING ERRCODE = '23514';
  END IF;

  -- Config-first (mesmo padrão de identity.enforce_member_limit, 01_identity.sql:97-115):
  -- sem política vigente ou payload sem array, o núcleo mínimo é fail-closed, nunca "nada".
  SELECT payload -> 'fatos_nucleo' INTO v_pol
    FROM engine.policy_versions
   WHERE code = 'ONBOARDING_NUCLEO' AND effective_to IS NULL
   ORDER BY effective_from DESC LIMIT 1;

  IF v_pol IS NOT NULL AND jsonb_typeof(v_pol) = 'array' THEN
    v_nucleo := ARRAY(SELECT jsonb_array_elements_text(v_pol));
  ELSE
    v_nucleo := ARRAY['renda.mensal_liquida', 'despesa.total_mensal'];
  END IF;

  FOREACH v_fato IN ARRAY v_nucleo LOOP
    IF NOT EXISTS (
      SELECT 1 FROM context.v_fact_current f
      JOIN identity.scopes s ON s.id = f.scope_id
      WHERE s.owner_user_id = NEW.user_id AND f.fact_key = v_fato
    ) THEN
      v_faltando := v_faltando || v_fato;
    END IF;
  END LOOP;

  IF cardinality(v_faltando) > 0 THEN
    RAISE EXCEPTION
      'C59a — onboarding do usuário % não conclui: fato(s)-núcleo sem confirmação (%).',
      NEW.user_id, array_to_string(v_faltando, ', ')
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER user_profiles_onboarding_gate BEFORE INSERT OR UPDATE ON identity.user_profiles
  FOR EACH ROW EXECUTE FUNCTION identity.assert_onboarding_conclusao();

COMMENT ON FUNCTION identity.assert_onboarding_conclusao IS
  '[F21a] C59a — o gate de conclusão do onboarding: suitability vigente + fatos-núcleo '
  '(ONBOARDING_NUCLEO, fallback renda+despesa) confirmados, e o carimbo é imutável depois '
  'de gravado. Roda sob o papel de quem conclui — SEM SECURITY DEFINER — porque a leitura '
  'via RLS do próprio escopo já é a checagem que importa.';

-- ---------------------------------------------------------------- (c) C59b — suitability
CREATE FUNCTION identity.assert_suitability_needs_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.scope_id IS NULL THEN
    RAISE EXCEPTION
      'C59b — suitability sem escopo não se grava: é o scope_id que a política '
      '"scope_isolation" usa para isolar o registro; sem ele a RLS não tem o que comparar.'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER suitability_needs_scope BEFORE INSERT ON identity.suitability_assessments
  FOR EACH ROW EXECUTE FUNCTION identity.assert_suitability_needs_scope();

CREATE FUNCTION identity.assert_suitability_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- Linha já superada é imutável por inteiro — inclusive superseded_at, que não se
  -- reescreve nem se reencerra.
  IF OLD.superseded_at IS NOT NULL THEN
    RAISE EXCEPTION
      'C59b — suitability % já superada é imutável por inteiro: é registro point-in-time '
      '(RCVM 30); refazer é linha nova, nunca reescrever a antiga.', OLD.id
      USING ERRCODE = '23514';
  END IF;

  -- Enquanto vigente, a única mudança permitida é encerrar (superseded_at de NULL para
  -- agora) — todas as demais colunas precisam continuar idênticas.
  IF (NEW.id, NEW.user_id, NEW.scope_id, NEW.questionnaire_version, NEW.answers,
      NEW.result, NEW.score, NEW.taken_at, NEW.valid_until)
     IS DISTINCT FROM
     (OLD.id, OLD.user_id, OLD.scope_id, OLD.questionnaire_version, OLD.answers,
      OLD.result, OLD.score, OLD.taken_at, OLD.valid_until)
  THEN
    RAISE EXCEPTION
      'C59b — suitability vigente % é imutável: a única mudança permitida é superseded_at '
      '(de NULL para agora). Refazer o questionário é LINHA NOVA, nunca UPDATE do '
      'resultado.', OLD.id USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER suitability_immutable BEFORE UPDATE ON identity.suitability_assessments
  FOR EACH ROW EXECUTE FUNCTION identity.assert_suitability_immutable();

COMMENT ON FUNCTION identity.assert_suitability_needs_scope IS
  '[F21a] C59b — scope_id obrigatório: sem ele a política scope_isolation de '
  'identity.suitability_assessments (14_rls_partitions.sql) não isola nada.';
COMMENT ON FUNCTION identity.assert_suitability_immutable IS
  '[F21a] C59b — trilha point-in-time (RCVM 30): vigente só aceita encerrar '
  '(superseded_at), superada é imutável por inteiro. Refazer é sempre linha nova.';

-- =============================================================================
-- Políticas — config-first (padrão das migrations 21/38/48): número de negócio novo é
-- policy, nunca literal no código ou no trigger.
-- =============================================================================

-- ONBOARDING_NUCLEO — a lista mínima de fatos que o gate C59a exige confirmados. Guarda de
-- existência para a migration ficar reexecutável em segurança (não é o caminho normal —
-- migrations são append-only e rodam uma vez — mas custa nada e evita duplicar version=1).
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'ONBOARDING_NUCLEO', 1,
       '{
         "fatos_nucleo": ["renda.mensal_liquida", "despesa.total_mensal"],
         "nota": "[F21a] Lista mínima que identity.assert_onboarding_conclusao() (C59a) exige CONFIRMADA para liberar a conclusão do onboarding. Fallback do trigger, se esta política não estiver vigente: os mesmos dois fatos (renda + despesa) — nunca uma lista vazia."
       }'::jsonb,
       'draft'
 WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'ONBOARDING_NUCLEO');

-- SUITABILITY_QUESTIONARIO — perguntas, pontos e limiares do questionário v1. O payload é
-- lido por app.onboarding.suitability.pontuar(): "opcoes" é {id_da_opção: pontos} (a soma
-- decide o resultado pelos "limiares"); "texto"/"rotulos" são só para a tela, em português,
-- sem "recomendamos"/"melhor"/"garantido"/oportunidade" e sem exclamação (RCVM 19) — a
-- pontuação não lê essas duas chaves.
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'SUITABILITY_QUESTIONARIO', 1,
       '{
         "versao_questionario": "suit-plexo-v1",
         "validade_meses": 24,
         "limiares": {"conservador_max": 4, "moderado_max": 9},
         "nota": "[F21a] Lida por app.onboarding.suitability.pontuar(). id/opcoes/limiares/versao_questionario/validade_meses formam o contrato de pontuação; texto/rotulos são só apresentação.",
         "perguntas": [
           {
             "id": "reacao_queda",
             "texto": "Se o valor investido caísse 20% em um mês, qual seria sua reação mais provável?",
             "opcoes": {"vender_tudo": 0, "esperar_preocupado": 1, "manter": 2, "aportar_mais": 3},
             "rotulos": {
               "vender_tudo": "Vender tudo e sair da posição",
               "esperar_preocupado": "Ficar preocupado e esperar a recuperação",
               "manter": "Manter a posição como estava",
               "aportar_mais": "Aportar mais, aproveitando o preço mais baixo"
             }
           },
           {
             "id": "experiencia",
             "texto": "Qual seu nível de experiência com investimentos além da poupança?",
             "opcoes": {"nenhuma": 0, "iniciante": 1, "intermediaria": 2, "avancada": 3},
             "rotulos": {
               "nenhuma": "Nenhuma experiência",
               "iniciante": "Iniciante — já investi pouco ou há pouco tempo",
               "intermediaria": "Intermediária — invisto com regularidade há alguns anos",
               "avancada": "Avançada — acompanho o mercado de perto há muitos anos"
             }
           },
           {
             "id": "parcela_oscilacao",
             "texto": "Qual a maior queda temporária que você toleraria no valor total investido, sem mudar de estratégia?",
             "opcoes": {"ate_10": 0, "ate_30": 1, "ate_60": 2, "acima_60": 3},
             "rotulos": {
               "ate_10": "Até 10%",
               "ate_30": "Até 30%",
               "ate_60": "Até 60%",
               "acima_60": "Acima de 60%"
             }
           },
           {
             "id": "horizonte",
             "texto": "Em quanto tempo você pretende usar a maior parte deste dinheiro?",
             "opcoes": {"ate_2_anos": 0, "de_2_a_8": 1, "acima_8": 2},
             "rotulos": {
               "ate_2_anos": "Até 2 anos",
               "de_2_a_8": "De 2 a 8 anos",
               "acima_8": "Acima de 8 anos"
             }
           },
           {
             "id": "liquidez_12m",
             "texto": "Que parte do seu patrimônio total precisa continuar disponível para uso nos próximos 12 meses?",
             "opcoes": {"mais_da_metade": 0, "ate_metade": 1, "pouco": 2},
             "rotulos": {
               "mais_da_metade": "Mais da metade",
               "ate_metade": "Até a metade",
               "pouco": "Pouco ou nada"
             }
           }
         ]
       }'::jsonb,
       'draft'
 WHERE NOT EXISTS (SELECT 1 FROM engine.policy_versions WHERE code = 'SUITABILITY_QUESTIONARIO');

COMMIT;
