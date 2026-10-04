-- =============================================================================
-- PLEXO · 58_canario_do_card.sql — Canário do card ao vivo + rótulo do extrator [F20]
--
-- O QUE MUDA E POR QUÊ
--   O card ao vivo (F14b, migration 39) nasce hoje para QUALQUER escopo que dispare o
--   sinal certo. A F20 aperta essa porta: até a precisão do extrator estar medida, só
--   escopos CANÁRIO — dev, personas, contas de demonstração — recebem o card que
--   INTERROMPE a conversa. Fora da allowlist (ou sem allowlist nenhuma na política), o
--   card não nasce: a mudança continua sendo capturada pela extração de fim de
--   conversa, que não fala com ninguém, só registra.
--
--   A segunda peça é a régua que decide quando um escopo pode sair do canário: toda
--   resposta do cliente ("foi isso mesmo" / "não, foi diferente") é um rótulo de
--   medição. `nature_do_extrator` congela o que o extrator PROPÔS no nascimento —
--   `nature` continua sendo o que VALE (o cliente pode reclassificar) — e
--   `context.v_precisao_extrator` compara os dois por classe.
--
-- POR QUE FAIL-CLOSED (C58)
--   Chave ausente na política ou payload que não é array: NINGUÉM é canário. O custo de
--   um card falso (interromper a conversa por engano) é maior, para a marca, que o custo
--   de nenhum card. Nenhum escopo é canário por omissão.
--
-- POR QUE O RÓTULO É IMUTÁVEL (C58b)
--   Se `nature_do_extrator` pudesse ser reescrito, a métrica de precisão mediria a
--   última edição, não a proposta original — o mesmo raciocínio que torna imutável o
--   conteúdo de `context.assertions` (22/38) e o registro de entrega de
--   `decisions.records` (27). Reclassificar é ato do cliente sobre `nature`;
--   `nature_do_extrator` é ato do extrator, encerrado no nascimento.
--
-- O QUE NÃO MUDA
--   A cadeia run → sinal → evidência → proposta continua inteira. O caminho em lote
--   ('pos_conversa') não é gateado pelo canário — ele nunca interrompeu ninguém, e o
--   canário existe para governar o que interrompe.
--
-- Depende de: 38_fact_catalog, 39_live_extraction.
-- Testes: tests/test_regras_invioláveis_perfil_vivo.sql (T135–T137), tests/test_f20_canario.py.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------- C58
-- O gate de nascimento da 39 (que já trazia o teto semanal, C39c), agora também com o
-- canário do card ao vivo. Corpo idêntico ao de 39_live_extraction.sql:128-228, com o
-- bloco novo logo após o teto semanal — mesmo precedente da 39 sobre a 38.
CREATE OR REPLACE FUNCTION context.assert_proposal_is_worth_asking() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  d          context.fact_definitions%ROWTYPE;
  v_novo     numeric;
  v_atual    numeric;
  v_delta    numeric;
  v_limiar   numeric;
  v_pol      jsonb;
  v_max      int;
  v_pend     int;
  v_semana   int;
  v_pol_cat  jsonb;
  v_canario  jsonb;
BEGIN
  -- C38f — proposta NASCE 'proposta'.
  IF NEW.status <> 'proposta' THEN
    RAISE EXCEPTION
      'C38f — proposta nasce "proposta", nunca "%". Confirmar é um segundo ato, '
      'do próprio cliente.', NEW.status USING ERRCODE = '23514';
  END IF;

  v_pol := context.policy_payload('CONTEXT_EXTRACTION');

  -- C38h — validade vem da política.
  IF NEW.expires_at IS NULL THEN
    NEW.expires_at := current_date + (v_pol ->> 'validade_proposta_dias')::int;
  END IF;

  -- C38g — teto de propostas pendentes por escopo.
  v_max := (v_pol ->> 'max_propostas_pendentes_por_escopo')::int;
  SELECT count(*) INTO v_pend
    FROM context.change_proposals
   WHERE scope_id = NEW.scope_id AND status = 'proposta';
  IF v_pend >= v_max THEN
    RAISE EXCEPTION
      'C38g — o escopo já tem % proposta(s) pendente(s) (teto %). Resolver as '
      'abertas vem antes de abrir mais uma.', v_pend, v_max USING ERRCODE = '23514';
  END IF;

  -- C39c — teto SEMANAL do que INTERROMPE. A extração em lote não entra na conta:
  -- ela não fala no meio da conversa, aparece quando o cliente volta.
  IF NEW.origin = 'turno' THEN
    v_pol_cat := context.policy_payload('CONTEXT_FACT_CATALOG');
    v_max := (v_pol_cat ->> 'max_propostas_ao_vivo_por_semana')::int;
    SELECT count(*) INTO v_semana
      FROM context.change_proposals
     WHERE scope_id = NEW.scope_id
       AND origin = 'turno'
       AND proposed_at >= now() - interval '7 days';
    IF v_semana >= v_max THEN
      RAISE EXCEPTION
        'C39c — já foram % cards ao vivo nesta semana (teto %). O que sobrar vai '
        'pela extração de fim de conversa, sem interromper.', v_semana, v_max
        USING ERRCODE = '23514';
    END IF;

    -- C58 — canário do card ao vivo [F20]: o card INTERROMPE a conversa do cliente, e
    -- só pode fazer isso por escopo explicitamente listado na política. Chave ausente
    -- ou payload que não é array => fail-closed, ninguém é canário.
    v_canario := v_pol_cat -> 'escopos_canario_card_ao_vivo';
    IF v_canario IS NULL OR jsonb_typeof(v_canario) <> 'array' THEN
      RAISE EXCEPTION
        'C58 — sem a allowlist "escopos_canario_card_ao_vivo" na política '
        'CONTEXT_FACT_CATALOG, o card ao vivo não nasce para nenhum escopo (fail-closed).'
        USING ERRCODE = '23514';
    END IF;
    IF NOT (v_canario ? NEW.scope_id::text) THEN
      RAISE EXCEPTION
        'C58 — escopo % fora da allowlist do canário: o card ao vivo não nasce aqui (a '
        'mudança continua sendo capturada na extração de fim de conversa).', NEW.scope_id
        USING ERRCODE = '23514';
    END IF;
  END IF;

  IF NEW.fact_key IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT * INTO d FROM context.fact_definitions WHERE fact_key = NEW.fact_key;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Fato % não existe no catálogo', NEW.fact_key USING ERRCODE = '23503';
  END IF;

  IF d.requires_nature_check AND NEW.nature IS NULL THEN
    RAISE EXCEPTION
      'C38d — "%" exige classificar a natureza (pontual/recorrente/incerto) antes '
      'de virar proposta: um bônus não é um aumento.', d.display_name
      USING ERRCODE = '23514';
  END IF;

  IF d.value_type IN ('money_brl','numero','percentual','meses','anos') THEN
    v_novo := context.fact_number(NEW.proposed_value);
    IF v_novo IS NULL THEN
      RAISE EXCEPTION 'Proposta para % precisa trazer {"amount": <número>}', NEW.fact_key
        USING ERRCODE = '23514';
    END IF;
    IF (d.min_value IS NOT NULL AND v_novo < d.min_value)
       OR (d.max_value IS NOT NULL AND v_novo > d.max_value) THEN
      RAISE EXCEPTION 'Valor proposto para % está fora da faixa de sanidade (%)',
        NEW.fact_key, v_novo USING ERRCODE = '23514';
    END IF;

    v_atual := context.fact_number(NEW.current_value);
    IF v_atual IS NOT NULL THEN
      v_delta  := abs(v_novo - v_atual);
      v_limiar := greatest(coalesce(d.materiality_abs, 0),
                           coalesce(d.materiality_rel, 0) * abs(v_atual));
      IF v_limiar > 0 AND v_delta < v_limiar THEN
        RAISE EXCEPTION
          'C38d — variação de % em "%" está abaixo do limiar de % : não é mudança '
          'material e não vira pergunta ao cliente.', v_delta, d.display_name, v_limiar
          USING ERRCODE = '23514';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

-- =============================================================================
-- Rótulo do extrator — nature_do_extrator espelha `nature` no nascimento e nunca mais
-- muda: é o que o extrator PROPÔS, para comparar com o que o cliente CONFIRMOU
-- (`nature`, que segue livre para reclassificar). Sem os dois, medir precisão é medir
-- a última edição, não o palpite original.
-- =============================================================================
ALTER TABLE context.change_proposals
  ADD COLUMN nature_do_extrator context.fact_nature;

COMMENT ON COLUMN context.change_proposals.nature_do_extrator IS
  '[F20] Espelho de `nature` no nascimento da proposta, imutável (C58b). É o rótulo que '
  'context.v_precisao_extrator compara com a resposta do cliente (`nature`, que pode ser '
  'reclassificada) para medir a precisão do extrator por classe.';

CREATE FUNCTION context.proposals_capture_extractor_nature() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.nature_do_extrator := coalesce(NEW.nature_do_extrator, NEW.nature);
  RETURN NEW;
END;
$$;
CREATE TRIGGER proposals_capture_extractor_nature BEFORE INSERT ON context.change_proposals
  FOR EACH ROW EXECUTE FUNCTION context.proposals_capture_extractor_nature();

-- Backfill ANTES do gate de imutabilidade existir (senão o próprio backfill seria
-- recusado): só em 'proposta' — nas já respondidas, o palpite original do extrator é
-- irrecuperável e fica NULL, e a proposta some da leitura de v_precisao_extrator
-- (WHERE nature_do_extrator IS NOT NULL) em vez de mentir uma precisão que não existe.
UPDATE context.change_proposals
   SET nature_do_extrator = nature
 WHERE status = 'proposta';

-- ---------------------------------------------------------------- C58b
-- O rótulo é imutável depois do nascimento — reescrevê-lo apagaria a medição que ele
-- existe para produzir (mesmo espírito de context.assert_assertion_content_immutable, 22/38).
CREATE FUNCTION context.assert_extractor_nature_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.nature_do_extrator IS DISTINCT FROM OLD.nature_do_extrator THEN
    RAISE EXCEPTION
      'C58b — nature_do_extrator da proposta % é imutável: é o rótulo do extrator, e '
      'reescrevê-lo apagaria a comparação com a resposta do cliente.', OLD.id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER proposals_extractor_nature_immutable BEFORE UPDATE ON context.change_proposals
  FOR EACH ROW EXECUTE FUNCTION context.assert_extractor_nature_immutable();

-- =============================================================================
-- context.v_precisao_extrator — precisão por classe proposta, a régua que decide quando
-- um escopo pode sair do canário (limiar em CONTEXT_FACT_CATALOG.precisao_minima_publicacao)
-- =============================================================================
CREATE VIEW context.v_precisao_extrator WITH (security_invoker = true) AS
SELECT scope_id,
       nature_do_extrator::text AS classe,
       count(*) FILTER (
         WHERE status IN ('confirmada','aplicada','rejeitada'))                    AS n_respondidas,
       count(*) FILTER (
         WHERE status IN ('confirmada','aplicada')
           AND nature IS NOT DISTINCT FROM nature_do_extrator)                     AS n_mesma_classe,
       count(*) FILTER (
         WHERE status IN ('confirmada','aplicada')
           AND nature IS DISTINCT FROM nature_do_extrator)                         AS n_reclassificadas,
       count(*) FILTER (WHERE status = 'rejeitada')                                AS n_rejeitadas,
       count(*) FILTER (WHERE status IN ('proposta','expirada'))                   AS n_sem_rotulo,
       round(
         count(*) FILTER (
           WHERE status IN ('confirmada','aplicada')
             AND nature IS NOT DISTINCT FROM nature_do_extrator)::numeric
         / nullif(count(*) FILTER (
             WHERE status IN ('confirmada','aplicada','rejeitada')), 0), 4)         AS precisao
  FROM context.change_proposals
 WHERE origin = 'turno' AND nature_do_extrator IS NOT NULL
 GROUP BY scope_id, nature_do_extrator;

COMMENT ON VIEW context.v_precisao_extrator IS
  '[F20] Precisão do extrator por escopo e classe proposta (nature_do_extrator): quantas '
  'respostas do cliente confirmaram a classe (n_mesma_classe), quantas reclassificaram, '
  'quantas foram rejeitadas — e a razão que diz se o card pode sair do canário.';

-- =============================================================================
-- Política: allowlist do canário + limiar de publicação. Mesmo padrão da 39/43 — nova
-- versão draft, a anterior encerrada, payload HERDADO (não hardcoded de novo). Só uma
-- versão nasce nesta transação, então now() não colide com o CHECK
-- effective_to > effective_from (o risco descrito no plano é só entre duas versões
-- criadas na MESMA transação — não é o caso aqui).
-- =============================================================================
UPDATE engine.policy_versions
   SET effective_to = now()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'CONTEXT_FACT_CATALOG', coalesce(max(version), 0) + 1,
       (SELECT payload FROM engine.policy_versions
         WHERE code = 'CONTEXT_FACT_CATALOG' ORDER BY version DESC LIMIT 1)
       || jsonb_build_object(
            'escopos_canario_card_ao_vivo', jsonb_build_array(
              '0de0a000-0000-4000-8000-000000000002',  -- escopo de dev (seeds/dev.sql)
              '0fe0a000-0000-4000-8000-000000000002',  -- persona Marina (seed personas)
              'f619feed-4b65-561c-b091-ff1c90540803'    -- Helena, conta de demonstração completa
            ),
            'precisao_minima_publicacao', 0.95,
            'nota_canario',
            'F20 — decisão da F16 (§18.1 do PLANO): card silencioso não gera rótulo, então '
            'shadow mode virou allowlist explícita. Só os escopos aqui recebem o card que '
            'interrompe a conversa; o resto do produto continua sendo capturado pela '
            'extração de fim de conversa. context.v_precisao_extrator mede a precisão por '
            'classe; um escopo só sai do canário quando a precisão medida alcançar '
            'precisao_minima_publicacao.'
          ),
       'draft'
  FROM engine.policy_versions WHERE code = 'CONTEXT_FACT_CATALOG';

COMMIT;
