-- =============================================================================
-- PLEXO · 39_live_extraction.sql — Proposta ao vivo [F14b]
--
-- O QUE MUDA E POR QUÊ
--   A 21 fixou: "o Contexto não lê conversa aberta. Encerrou, virou registro; aí sim."
--   A regra estava certa para o que ela julgava — a extração em LOTE, que conclui
--   sobre um diálogo terminado, marca a conversa como processada e só pode acontecer
--   uma vez. Ela estava errada como proibição geral, porque proibia junto um ato
--   diferente: perguntar, no meio da conversa, sobre uma frase que acabou de ser dita.
--
--   "Passei a ganhar 10 mil" não precisa esperar a conversa acabar para virar pergunta.
--   Esperar é justamente o que faz o produto parecer desatento.
--
-- O QUE **NÃO** SE AFROUXOU (e é o que torna isto seguro)
--   · a cadeia run → sinal → evidência → proposta continua inteira: o run ao vivo
--     aponta as mensagens exatas do turno, e proposta sem sinal continua impossível;
--   · o gate de conversa encerrada continua valendo para 'pos_conversa';
--   · o sucesso único por conversa continua valendo para 'pos_conversa';
--   · marcar a conversa como processada continua sendo ato exclusivo do lote.
--
-- O QUE SE GANHOU DE GOVERNANÇA (C39c)
--   Teto SEMANAL de cards ao vivo, vindo de política. Um laço que pode falar a cada
--   turno precisa de um limite explícito, ou o produto que promete respeitar o tempo
--   do cliente passa a cutucá-lo — e uma proposta falsa custa desproporcionalmente
--   caro a uma marca cuja proposta inteira é integridade de sinal.
--
-- Depende de: 17_agents, 21_context, 22_assertions, 38_fact_catalog.
-- =============================================================================

BEGIN;

CREATE TYPE context.extraction_kind AS ENUM (
  'pos_conversa',  -- lote: conversa encerrada, uma vez, marca como processada
  'turno'          -- ao vivo: um turno da conversa aberta, quantas vezes precisar
);

ALTER TABLE context.extraction_runs
  ADD COLUMN kind context.extraction_kind NOT NULL DEFAULT 'pos_conversa';

COMMENT ON COLUMN context.extraction_runs.kind IS
  '[F14b] Separa os dois atos que a 21 tratava como um só. O default preserva o '
  'comportamento histórico: todo run existente é, e continua sendo, extração em lote.';

-- ---------------------------------------------------------------- C39a
-- O gate da 21, agora consciente de que existem dois atos.
CREATE OR REPLACE FUNCTION context.assert_conversation_ended() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_ended timestamptz;
BEGIN
  IF NEW.kind = 'turno' THEN
    RETURN NEW;   -- o card ao vivo trabalha justamente sobre a conversa em curso
  END IF;
  SELECT ended_at INTO v_ended FROM agents.conversations WHERE id = NEW.conversation_id;
  IF v_ended IS NULL THEN
    RAISE EXCEPTION 'Contexto não processa conversa aberta em lote (%)', NEW.conversation_id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

-- Sucesso único por conversa vale para o LOTE (concluir duas vezes sobre o mesmo
-- diálogo não faz sentido). Ao vivo, um run por turno é o desenho.
DROP INDEX context.extraction_one_success;
CREATE UNIQUE INDEX extraction_one_success
  ON context.extraction_runs (conversation_id)
  WHERE status = 'succeeded' AND kind = 'pos_conversa';

CREATE INDEX extraction_kind_idx
  ON context.extraction_runs (conversation_id, kind, started_at DESC);

-- ---------------------------------------------------------------- C39b
-- Um card no meio da conversa não a conclui. Só o lote marca 'processada'.
CREATE OR REPLACE FUNCTION context.mark_conversation_processed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.kind <> 'pos_conversa' THEN
    RETURN NULL;
  END IF;
  UPDATE agents.conversations
     SET status = 'processada', processed_at = now()
   WHERE id = NEW.conversation_id AND status = 'encerrada';
  RETURN NULL;
END;
$$;

-- =============================================================================
-- Propostas: origem derivada e teto semanal
-- =============================================================================
ALTER TABLE context.change_proposals
  ADD COLUMN origin context.extraction_kind;

COMMENT ON COLUMN context.change_proposals.origin IS
  '[F14b] DERIVADA do run que gerou o sinal, nunca declarada pelo chamador — senão '
  'bastaria a aplicação dizer "pos_conversa" para escapar do teto semanal de cards.';

CREATE FUNCTION context.derive_proposal_origin() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_kind context.extraction_kind;
BEGIN
  SELECT r.kind INTO v_kind
    FROM context.signals s
    JOIN context.extraction_runs r ON r.id = s.extraction_run_id
   WHERE s.id = NEW.signal_id;

  IF v_kind IS NULL THEN
    RAISE EXCEPTION 'Sinal % não tem run de extração — proposta sem proveniência', NEW.signal_id
      USING ERRCODE = '23503';
  END IF;
  IF NEW.origin IS NOT NULL AND NEW.origin <> v_kind THEN
    RAISE EXCEPTION
      'C39 — origem declarada (%) não é a do sinal (%). `origin` é derivada, não informada.',
      NEW.origin, v_kind USING ERRCODE = '23514';
  END IF;

  NEW.origin := v_kind;
  RETURN NEW;
END;
$$;
-- Nome escolhido para ordenar ANTES de proposals_worth_asking_gate (o PostgreSQL
-- dispara triggers do mesmo evento em ordem alfabética): o teto semanal precisa da
-- origem já preenchida.
CREATE TRIGGER proposals_derive_origin BEFORE INSERT ON context.change_proposals
  FOR EACH ROW EXECUTE FUNCTION context.derive_proposal_origin();

-- ---------------------------------------------------------------- C39c
-- O gate de nascimento da 38, agora com o teto semanal de cards ao vivo.
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
    v_max := (context.policy_payload('CONTEXT_FACT_CATALOG')
              ->> 'max_propostas_ao_vivo_por_semana')::int;
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

-- ---------------------------------------------------------------- C39d
-- A classificação mais importante do laço, com dentes: uma observação PONTUAL não
-- vira fato RECORRENTE. Sem esta regra, "ganhei 10k esse mês" entra no plano como
-- salário e contamina projeção, capacidade de aporte e score.
CREATE FUNCTION context.assert_nature_fits_fact() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d context.fact_definitions%ROWTYPE;
BEGIN
  IF NEW.fact_key IS NULL THEN RETURN NEW; END IF;

  SELECT * INTO d FROM context.fact_definitions WHERE fact_key = NEW.fact_key;
  IF NOT FOUND THEN RETURN NEW; END IF;

  IF NEW.nature = 'incerto' THEN
    RAISE EXCEPTION
      'C39d — "ainda não sei" não aplica nada. A proposta fica aberta até o cliente '
      'dizer se "%" passou a valer ou foi de uma vez só.', d.display_name
      USING ERRCODE = '23514';
  END IF;

  IF d.is_recurring_by_nature AND NEW.nature = 'pontual' THEN
    RAISE EXCEPTION
      'C39d — "%" é um fato recorrente e a observação foi classificada como pontual. '
      'Um bônus não vira salário: registre como entrada pontual, não como mudança do fato.',
      d.display_name USING ERRCODE = '23514';
  END IF;

  IF d.requires_nature_check AND NEW.nature IS NULL THEN
    RAISE EXCEPTION
      'C39d — aplicar "%" exige a natureza classificada.', d.display_name
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER proposals_nature_gate BEFORE UPDATE ON context.change_proposals
  FOR EACH ROW
  WHEN (NEW.status = 'aplicada' AND OLD.status IS DISTINCT FROM 'aplicada')
  EXECUTE FUNCTION context.assert_nature_fits_fact();

COMMENT ON FUNCTION context.assert_nature_fits_fact IS
  'C39d — o gate da natureza no momento da APLICAÇÃO (não do nascimento): é ali que '
  'a proposta deixa de ser pergunta e vira contexto do cliente.';

-- =============================================================================
-- Política: o teto semanal entra na CONTEXT_FACT_CATALOG (38), que é a política
-- de governança do catálogo. Nova versão, com a anterior encerrada — o caminho
-- config-first: premissa não muda por edição, muda por versão datada.
-- =============================================================================
UPDATE engine.policy_versions
   SET effective_to = now()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('CONTEXT_FACT_CATALOG', 2, '{
  "precedencia_padrao": ["open_finance","upload","formulario","onboarding","conversa","inferencia_motor","operador"],
  "min_confianca_para_propor": 0.75,
  "cobertura_minima_para_score": 0.6,
  "max_propostas_ao_vivo_por_semana": 3,
  "nota": "max_propostas_ao_vivo_por_semana é governança de ATENÇÃO: teto do que interrompe a conversa. O que passar do teto vai pela extração de fim de conversa. Curvas de normalização dos scores vivem em CLIENT_SCORES (migration 40)."
}'::jsonb, 'draft');

COMMIT;
