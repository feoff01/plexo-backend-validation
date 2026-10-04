-- =============================================================================
-- PLEXO · 38_fact_catalog.sql — Catálogo de fatos [F14a]
--
-- O PROBLEMA QUE ESTE ARQUIVO RESOLVE
--   Até a 37, `context.assertions.attribute` era um slug LIVRE. Nada impedia
--   `renda_mensal`, `salario` e `renda` coexistirem no mesmo escopo, cada um com
--   uma unidade diferente. Sem vocabulário fechado não existe:
--     · unidade canônica  — 18.000 do quê? BRL, USD, centavos?
--     · meia-vida por fato — renda apodrece em 6 meses; regime de bens, não
--     · materialidade      — 8.000 → 8.050 não pode virar pergunta ao cliente
--     · precedência        — extrato do banco e frase na conversa empatavam
--     · cobertura          — "o que ainda falta saber" era incontável
--   A camada epistêmica da 22 sabia dizer COM QUE FORÇA o sistema sabe. Faltava
--   dizer O QUE ele pode saber. Fato sem catálogo não é fato: é frase guardada.
--
-- AS DUAS REGRAS-ESTRELA DESTE ARQUIVO
--   (C38b) O que o Open Finance governa, a conversa NÃO sobrescreve — só marca
--          divergência. Vale também para tolerância a risco: perfil é registro
--          regulatório point-in-time (21), não se muda porque o cliente desabafou.
--   (C38d) Mudança que não é material não vira pergunta. O limiar é do catálogo,
--          não do código. Sem isto o card de confirmação vira spam — e um produto
--          cuja promessa é respeitar o tempo do cliente passa a cutucá-lo por R$ 50.
--
-- ONDE CADA NÚMERO VIVE (a divisão importa para a inspeção da CVM)
--   · catálogo (esta tabela)     — unidade, meia-vida, precedência, materialidade,
--                                  faixa de sanidade. Config POR FATO, table-driven,
--                                  mesmo padrão de diagnostics.finding_types.
--   · engine.policy_versions     — os limiares de governança (teto de propostas,
--                                  validade) e, na 40, as curvas de normalização.
--                                  É lá que mora a OPINIÃO; aqui mora a definição.
--
-- Depende de: 00_core, 01_identity, 02_engine (policy_versions), 21_context, 22_assertions.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Vocabulário
-- -----------------------------------------------------------------------------
CREATE TYPE context.fact_family AS ENUM (
  'fluxo',          -- o que entra e sai por mês
  'protecao',       -- o que segura o baque (reserva, seguro, dependentes)
  'estoque',        -- o que já foi acumulado (patrimônio, dívida)
  'destino',        -- objetivos e o esforço que exigem
  'comportamento',  -- só existe com tempo de casa
  'vida'            -- contexto que modula todo o resto
);

CREATE TYPE context.fact_value_type AS ENUM (
  'money_brl',   -- {"amount": 10000}   · unit = 'BRL'
  'numero',      -- {"amount": 2}
  'percentual',  -- {"amount": 0.145}   · unit = 'fracao' (0,145 = 14,5%)
  'meses',       -- {"amount": 6}
  'anos',        -- {"amount": 55}
  'booleano',    -- {"bool": true}
  'texto',       -- {"text": "clt"}
  'data'         -- {"date": "1988-04-12"}
);

-- "Ganhei 10k esse mês" ≠ "passei a ganhar 10k". É a classificação mais
-- importante do laço: sem ela, um bônus vira aumento salarial no plano.
CREATE TYPE context.fact_nature AS ENUM ('pontual', 'recorrente', 'incerto');

-- -----------------------------------------------------------------------------
-- context.fact_definitions — o vocabulário fechado do que o sistema pode saber
-- -----------------------------------------------------------------------------
CREATE TABLE context.fact_definitions (
  fact_key            core.slug PRIMARY KEY,          -- 'renda.mensal_liquida'
  subject_kind        context.subject_kind NOT NULL,
  attribute           core.slug NOT NULL,             -- casa com assertions.attribute
  family              context.fact_family NOT NULL,
  display_name        text NOT NULL,                  -- rótulo client-facing, pt-BR
  value_type          context.fact_value_type NOT NULL,
  unit                text,

  -- QUEM MANDA quando duas fontes discordam. Ordem = força (índice 1 é o mais forte).
  -- Não é global: para renda, a declaração explícita do cliente vale mais que o
  -- extrato (ele sabe do aumento antes do banco); para patrimônio, o inverso.
  source_precedence   context.assertion_source[] NOT NULL,
  allows_conversation_update boolean NOT NULL DEFAULT true,

  -- QUANDO APODRECE. NULL = não vence (regime de bens, data de nascimento).
  half_life_days      int,

  -- O QUE É MUDANÇA DE VERDADE. O limiar efetivo é o MAIOR dos dois:
  -- greatest(materiality_abs, materiality_rel × valor_atual).
  materiality_abs     numeric(18,4),
  materiality_rel     numeric(6,4),

  -- FAIXA DE SANIDADE — barra erro de digitação e alucinação de extrator.
  min_value           numeric(18,4),
  max_value           numeric(18,4),

  is_recurring_by_nature  boolean NOT NULL DEFAULT true,
  requires_nature_check   boolean NOT NULL DEFAULT false,
  is_active               boolean NOT NULL DEFAULT true,
  notes                   text,

  UNIQUE (subject_kind, attribute),

  CONSTRAINT precedence_not_empty CHECK (cardinality(source_precedence) > 0),
  CONSTRAINT value_range_ordered CHECK (
    min_value IS NULL OR max_value IS NULL OR min_value <= max_value
  ),
  CONSTRAINT half_life_positive CHECK (half_life_days IS NULL OR half_life_days > 0),
  CONSTRAINT materiality_non_negative CHECK (
    (materiality_abs IS NULL OR materiality_abs >= 0)
    AND (materiality_rel IS NULL OR (materiality_rel >= 0 AND materiality_rel <= 1))
  ),
  CONSTRAINT money_is_brl CHECK (value_type <> 'money_brl' OR unit = 'BRL'),
  CONSTRAINT qualitative_has_no_unit CHECK (
    value_type NOT IN ('booleano','texto','data') OR unit IS NULL
  ),
  -- Fato numérico SEM limiar é fato que gera spam. O banco recusa cadastrá-lo.
  CONSTRAINT numeric_needs_materiality CHECK (
    value_type NOT IN ('money_brl','numero','percentual','meses','anos')
    OR materiality_abs IS NOT NULL OR materiality_rel IS NOT NULL
  ),
  -- Fato que a conversa não pode atualizar não pode ter a conversa no topo.
  CONSTRAINT governed_fact_has_stronger_source CHECK (
    allows_conversation_update OR source_precedence[1] <> 'conversa'
  )
);
CREATE INDEX fact_definitions_family_idx ON context.fact_definitions (family) WHERE is_active;

COMMENT ON TABLE context.fact_definitions IS
  '[F14a] O vocabulário fechado do Contexto Pessoal. Antes desta tabela, `attribute` '
  'era slug livre e nenhuma junta fechava. É daqui que saem unidade canônica, '
  'meia-vida, precedência de fonte, materialidade e — via v_fact_coverage — a '
  'métrica de "o que ainda falta saber", que é a melhor mecânica de onboarding '
  'que existe: o dado que falta vira a próxima pergunta, não um formulário.';

COMMENT ON COLUMN context.fact_definitions.allows_conversation_update IS
  'C38b — false para o que outra fonte governa: patrimônio investido (Open Finance) '
  'e tolerância a risco (suitability, registro regulatório point-in-time). A conversa '
  'continua podendo REGISTRAR a divergência; o que ela não pode é confirmá-la.';

COMMENT ON COLUMN context.fact_definitions.source_precedence IS
  'Ordem de força das fontes PARA ESTE FATO. Não há precedência global: a pessoa '
  'sabe do próprio aumento antes do extrato mostrar, e o extrato sabe do saldo '
  'melhor que a memória dela.';

-- -----------------------------------------------------------------------------
-- Leitura canônica do jsonb — uma só, para catálogo, gates, views e motor
-- -----------------------------------------------------------------------------
CREATE FUNCTION context.fact_number(p_value jsonb) RETURNS numeric
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
           WHEN jsonb_typeof(p_value -> 'amount') = 'number' THEN (p_value ->> 'amount')::numeric
           WHEN jsonb_typeof(p_value -> 'valor')  = 'number' THEN (p_value ->> 'valor')::numeric
           ELSE NULL
         END
$$;

COMMENT ON FUNCTION context.fact_number IS
  'Único leitor do número dentro de context.assertions.value. Aceita `amount` '
  '(convenção desde a 22) e `valor`. Devolve NULL quando não há número — e é esse '
  'NULL que o gate do catálogo transforma em recusa.';

CREATE FUNCTION context.source_rank(p_fact_key core.slug, p_source context.assertion_source)
RETURNS int LANGUAGE sql STABLE AS $$
  SELECT coalesce(array_position(d.source_precedence, p_source), 999)
  FROM context.fact_definitions d WHERE d.fact_key = p_fact_key
$$;

COMMENT ON FUNCTION context.source_rank IS
  'Posição da fonte na precedência do fato: MENOR é mais forte. Fonte fora da '
  'lista devolve 999 — não empata com ninguém e nunca aposenta nada.';

-- Payload da política vigente. Config-first: sem política, não há default silencioso.
CREATE FUNCTION context.policy_payload(p_code core.config_code) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v jsonb;
BEGIN
  SELECT payload INTO v FROM engine.policy_versions
   WHERE code = p_code AND effective_to IS NULL;
  IF v IS NULL THEN
    RAISE EXCEPTION 'Política % não está vigente — premissa numérica não tem default no código', p_code
      USING ERRCODE = '23514';
  END IF;
  RETURN v;
END;
$$;

-- -----------------------------------------------------------------------------
-- Ligação com a camada epistêmica (22)
-- -----------------------------------------------------------------------------
ALTER TABLE context.assertions
  ADD COLUMN fact_key core.slug REFERENCES context.fact_definitions(fact_key);
CREATE INDEX assertions_fact_key_idx ON context.assertions (scope_id, fact_key)
  WHERE fact_key IS NOT NULL AND superseded_at IS NULL;

COMMENT ON COLUMN context.assertions.fact_key IS
  '[F14a] Aponta para o catálogo. NULL é permitido — a 22 nasceu sem catálogo e as '
  'asserções antigas continuam válidas —, mas tudo que o extrator escreve a partir '
  'da F14 é catalogado, e só o catalogado vira indicador e score.';

-- ---------------------------------------------------------------- C38a
-- Coerência com o catálogo. É este gate que impede `salario` de existir ao lado
-- de `renda_mensal_liquida`, e 18000 em USD de se passar por 18000 em BRL.
CREATE FUNCTION context.assert_fact_matches_catalog() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  d context.fact_definitions%ROWTYPE;
  v numeric;
BEGIN
  IF NEW.fact_key IS NULL THEN
    RETURN NEW;   -- asserção sem catálogo continua válida (compatibilidade com a 22)
  END IF;

  SELECT * INTO d FROM context.fact_definitions WHERE fact_key = NEW.fact_key;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Fato % não existe no catálogo', NEW.fact_key USING ERRCODE = '23503';
  END IF;
  IF NOT d.is_active THEN
    RAISE EXCEPTION 'Fato % está inativo no catálogo', NEW.fact_key USING ERRCODE = '23514';
  END IF;

  IF NEW.subject_kind <> d.subject_kind THEN
    RAISE EXCEPTION 'Fato % é sobre "%", não sobre "%"',
      NEW.fact_key, d.subject_kind, NEW.subject_kind USING ERRCODE = '23514';
  END IF;
  IF NEW.attribute <> d.attribute THEN
    RAISE EXCEPTION 'Fato % tem atributo "%" no catálogo, não "%" — vocabulário é fechado',
      NEW.fact_key, d.attribute, NEW.attribute USING ERRCODE = '23514';
  END IF;
  IF NEW.unit IS DISTINCT FROM d.unit THEN
    RAISE EXCEPTION 'Fato % é medido em "%", não em "%"',
      NEW.fact_key, coalesce(d.unit, '(sem unidade)'), coalesce(NEW.unit, '(sem unidade)')
      USING ERRCODE = '23514';
  END IF;

  -- forma do valor conforme o tipo declarado
  IF d.value_type IN ('money_brl','numero','percentual','meses','anos') THEN
    v := context.fact_number(NEW.value);
    IF v IS NULL THEN
      RAISE EXCEPTION 'Fato % é numérico (%): o valor precisa trazer {"amount": <número>}',
        NEW.fact_key, d.value_type USING ERRCODE = '23514';
    END IF;
    IF (d.min_value IS NOT NULL AND v < d.min_value)
       OR (d.max_value IS NOT NULL AND v > d.max_value) THEN
      RAISE EXCEPTION 'Fato % fora da faixa de sanidade do catálogo (% não está entre % e %)',
        NEW.fact_key, v, coalesce(d.min_value::text,'-inf'), coalesce(d.max_value::text,'+inf')
        USING ERRCODE = '23514';
    END IF;
  ELSIF d.value_type = 'booleano' AND jsonb_typeof(NEW.value -> 'bool') <> 'boolean' THEN
    RAISE EXCEPTION 'Fato % é booleano: o valor precisa trazer {"bool": true|false}', NEW.fact_key
      USING ERRCODE = '23514';
  ELSIF d.value_type = 'texto' AND jsonb_typeof(NEW.value -> 'text') <> 'string' THEN
    RAISE EXCEPTION 'Fato % é texto: o valor precisa trazer {"text": "..."}', NEW.fact_key
      USING ERRCODE = '23514';
  ELSIF d.value_type = 'data' AND (NEW.value ->> 'date') !~ '^\d{4}-\d{2}-\d{2}$' THEN
    RAISE EXCEPTION 'Fato % é data: o valor precisa trazer {"date": "AAAA-MM-DD"}', NEW.fact_key
      USING ERRCODE = '23514';
  END IF;

  -- meia-vida do catálogo vira validade concreta. Fato vencido não some: ele
  -- deixa de ser verdade operável e volta a ser pergunta (v_open_questions).
  IF NEW.valid_until IS NULL AND d.half_life_days IS NOT NULL THEN
    NEW.valid_until := NEW.valid_from + d.half_life_days;
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER assertions_catalog_gate BEFORE INSERT ON context.assertions
  FOR EACH ROW EXECUTE FUNCTION context.assert_fact_matches_catalog();

-- ---------------------------------------------------------------- C38b
-- O que outra fonte governa, a conversa não confirma. Ela registra a divergência
-- (a asserção entra e aparece em v_open_questions como conflito) — e para por aí.
CREATE FUNCTION context.assert_source_may_confirm() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d context.fact_definitions%ROWTYPE;
BEGIN
  IF NEW.fact_key IS NULL THEN RETURN NEW; END IF;

  SELECT * INTO d FROM context.fact_definitions WHERE fact_key = NEW.fact_key;
  IF FOUND AND NOT d.allows_conversation_update
     AND NEW.source IN ('conversa','inferencia_motor') THEN
    RAISE EXCEPTION
      'C38b — "%" é governado por % e não se confirma a partir de %. A conversa pode '
      'registrar a divergência; não pode sobrescrever a fonte que manda.',
      d.display_name, d.source_precedence[1], NEW.source
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER assertions_source_confirm_gate BEFORE UPDATE ON context.assertions
  FOR EACH ROW
  WHEN (NEW.status = 'confirmado' AND OLD.status IS DISTINCT FROM 'confirmado')
  EXECUTE FUNCTION context.assert_source_may_confirm();

-- ---------------------------------------------------------------- C38c
-- Conflito e supersessão passam a ser conscientes de precedência.
--
-- Antes: qualquer asserção nova com valor diferente demovia as vigentes para
-- 'conflitante', e qualquer confirmação aposentava todas as irmãs. Ou seja, um
-- PDF enviado à mão derrubava o dado do Open Finance sem que ninguém notasse.
-- Agora: fonte mais fraca não demove nem aposenta a mais forte — ela própria
-- entra como 'conflitante', e a divergência aparece como PERGUNTA.
CREATE OR REPLACE FUNCTION context.flag_conflicting_assertions() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_hits int;
BEGIN
  IF NEW.modality NOT IN ('fato','preferencia') THEN
    RETURN NULL;   -- hipóteses concorrentes convivem sem conflito
  END IF;

  -- (1) demove as vigentes que NÃO são de fonte mais forte que a nova
  UPDATE context.assertions a
     SET status = 'conflitante'
   WHERE a.id <> NEW.id
     AND a.scope_id     = NEW.scope_id
     AND a.subject_kind = NEW.subject_kind
     AND a.subject_ref IS NOT DISTINCT FROM NEW.subject_ref
     AND a.attribute    = NEW.attribute
     AND a.modality     = NEW.modality
     AND a.superseded_at IS NULL
     AND a.status IN ('declarado','inferido','confirmado')
     AND a.value <> NEW.value
     AND (NEW.fact_key IS NULL
          OR context.source_rank(NEW.fact_key, NEW.source)
             <= context.source_rank(NEW.fact_key, a.source));
  GET DIAGNOSTICS v_hits = ROW_COUNT;

  -- (2) a nova vira conflitante se DIVERGE de qualquer vigente — inclusive de uma
  -- mais forte, que ela não pôde demover. É esse ramo que faz a divergência com o
  -- Open Finance aparecer sem que o dado do banco seja rebaixado.
  IF v_hits > 0 OR EXISTS (
       SELECT 1 FROM context.assertions a
        WHERE a.id <> NEW.id
          AND a.scope_id     = NEW.scope_id
          AND a.subject_kind = NEW.subject_kind
          AND a.subject_ref IS NOT DISTINCT FROM NEW.subject_ref
          AND a.attribute    = NEW.attribute
          AND a.modality     = NEW.modality
          AND a.superseded_at IS NULL
          AND a.status IN ('declarado','inferido','confirmado')
          AND a.value <> NEW.value
     ) THEN
    UPDATE context.assertions SET status = 'conflitante' WHERE id = NEW.id;
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION context.supersede_siblings_on_confirm() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
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
     -- C38c: só aposenta quem é de fonte igual ou mais fraca que a que está confirmando
     AND (NEW.fact_key IS NULL
          OR context.source_rank(NEW.fact_key, NEW.source)
             <= context.source_rank(NEW.fact_key, a.source));
  RETURN NULL;
END;
$$;

-- ---------------------------------------------------------------- imutabilidade
-- `fact_key` entra na tupla imutável da 22: trocar o catálogo de uma asserção
-- gravada reescreveria a que fato ela se refere — mesma classe de fraude que
-- trocar a unidade (corrigido na v1.2 da onda 22).
CREATE OR REPLACE FUNCTION context.assert_assertion_content_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.scope_id, NEW.user_id, NEW.subject_kind, NEW.attribute,
      NEW.value, NEW.modality, NEW.source, NEW.likelihood, NEW.observed_at,
      NEW.valid_from, NEW.source_ref, NEW.evidence_message_ids)
     IS DISTINCT FROM
     (OLD.scope_id, OLD.user_id, OLD.subject_kind, OLD.attribute,
      OLD.value, OLD.modality, OLD.source, OLD.likelihood, OLD.observed_at,
      OLD.valid_from, OLD.source_ref, OLD.evidence_message_ids)
     OR NEW.subject_ref IS DISTINCT FROM OLD.subject_ref
     OR NEW.unit        IS DISTINCT FROM OLD.unit
     OR NEW.signal_id   IS DISTINCT FROM OLD.signal_id
     OR NEW.fact_key    IS DISTINCT FROM OLD.fact_key
  THEN
    RAISE EXCEPTION
      'Conteúdo de asserção é imutável (%). Mudança é linha NOVA + superseded_by — '
      'senão o histórico do cliente vira ficção.', OLD.id
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;

-- =============================================================================
-- Propostas: as regras que até aqui viviam SÓ na aplicação (pendências da F3)
-- =============================================================================
ALTER TABLE context.change_proposals
  ADD COLUMN fact_key              core.slug REFERENCES context.fact_definitions(fact_key),
  ADD COLUMN nature                context.fact_nature,
  ADD COLUMN rejection_reason_code core.slug,
  ADD COLUMN proposal_hash core.hash_hex
    GENERATED ALWAYS AS (core.canonical_hash(proposed_value)) STORED;

COMMENT ON COLUMN context.change_proposals.nature IS
  '[F14a] "Ganhei 10k esse mês" ≠ "passei a ganhar 10k". Quando o catálogo marca '
  'requires_nature_check, a proposta não nasce sem esta classificação — e a melhor '
  'versão do card é justamente perguntá-la, porque a pergunta é útil e não parece vigilância.';

COMMENT ON COLUMN context.change_proposals.rejection_reason_code IS
  '[F14a] Recusa é informação: "não, foi bônus" diz que existe renda variável não '
  'recorrente. Guardar só `false` joga fora o fato que a recusa revelou.';

-- C38e — a mesma proposta pendente não volta. Sem isto, cada turno repete o card.
CREATE UNIQUE INDEX proposals_idempotent_idx
  ON context.change_proposals (scope_id, fact_key, proposal_hash)
  WHERE status = 'proposta' AND fact_key IS NOT NULL;

-- ---------------------------------------------------------------- C38d + C38f + C38g + C38h
CREATE FUNCTION context.assert_proposal_is_worth_asking() RETURNS trigger
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
BEGIN
  -- C38f — proposta NASCE 'proposta'. Confirmação e aplicação são atos posteriores,
  -- com ator identificado. Era regra só da aplicação até aqui.
  IF NEW.status <> 'proposta' THEN
    RAISE EXCEPTION
      'C38f — proposta nasce "proposta", nunca "%". Confirmar é um segundo ato, '
      'do próprio cliente.', NEW.status USING ERRCODE = '23514';
  END IF;

  v_pol := context.policy_payload('CONTEXT_EXTRACTION');

  -- C38h — validade vem da política, não do chamador esquecido.
  IF NEW.expires_at IS NULL THEN
    NEW.expires_at := current_date + (v_pol ->> 'validade_proposta_dias')::int;
  END IF;

  -- C38g — teto de propostas pendentes por escopo. Governança de ATENÇÃO é
  -- config, não bom senso: é o que impede o produto de virar cutucão.
  v_max := (v_pol ->> 'max_propostas_pendentes_por_escopo')::int;
  SELECT count(*) INTO v_pend
    FROM context.change_proposals
   WHERE scope_id = NEW.scope_id AND status = 'proposta';
  IF v_pend >= v_max THEN
    RAISE EXCEPTION
      'C38g — o escopo já tem % proposta(s) pendente(s) (teto %). Resolver as '
      'abertas vem antes de abrir mais uma.', v_pend, v_max USING ERRCODE = '23514';
  END IF;

  IF NEW.fact_key IS NULL THEN
    RETURN NEW;   -- proposta sem catálogo (compatibilidade com a 21)
  END IF;

  SELECT * INTO d FROM context.fact_definitions WHERE fact_key = NEW.fact_key;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Fato % não existe no catálogo', NEW.fact_key USING ERRCODE = '23503';
  END IF;

  -- natureza obrigatória onde o catálogo exige
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

    -- C38d — materialidade. Fato NOVO (sem valor atual) não tem delta: é sempre
    -- material. O limiar efetivo é o MAIOR entre o absoluto e o relativo.
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
CREATE TRIGGER proposals_worth_asking_gate BEFORE INSERT ON context.change_proposals
  FOR EACH ROW EXECUTE FUNCTION context.assert_proposal_is_worth_asking();

COMMENT ON FUNCTION context.assert_proposal_is_worth_asking IS
  'C38d/f/g/h — o gate único de nascimento de proposta: nasce pendente, com validade '
  'da política, dentro do teto do escopo, com natureza classificada quando o catálogo '
  'exige e apenas quando a mudança é MATERIAL. Uma proposta falsa custa desproporcional '
  'a uma marca cuja proposta inteira é integridade de sinal.';

-- ---------------------------------------------------------------- C38h (parte 2)
-- Proposta vencida não se confirma. `expires_at` era decoração para o job `expirar`.
CREATE FUNCTION context.assert_proposal_not_expired() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.expires_at IS NOT NULL AND OLD.expires_at < current_date THEN
    RAISE EXCEPTION
      'C38h — proposta % venceu em % e não pode mais ser confirmada. O contexto '
      'mudou desde então; a pergunta precisa ser refeita.', OLD.id, OLD.expires_at
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER proposals_expiry_gate BEFORE UPDATE ON context.change_proposals
  FOR EACH ROW
  WHEN (NEW.status IN ('confirmada','aplicada') AND OLD.status = 'proposta')
  EXECUTE FUNCTION context.assert_proposal_not_expired();

CREATE FUNCTION context.expire_stale_proposals(p_as_of date DEFAULT current_date)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE v_n int;
BEGIN
  UPDATE context.change_proposals
     SET status = 'expirada'
   WHERE status = 'proposta'
     AND expires_at IS NOT NULL
     AND expires_at < p_as_of;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END;
$$;

COMMENT ON FUNCTION context.expire_stale_proposals IS
  'Par de context.expire_stale_assertions(): chamada pelo job diário `expirar`. '
  'Proposta velha morre, não assombra.';

-- =============================================================================
-- Views — o que o motor, a API e a tela leem
-- =============================================================================

-- O fato vigente, UM por chave, resolvido por precedência e depois por recência.
CREATE VIEW context.v_fact_current WITH (security_invoker = true) AS
SELECT DISTINCT ON (a.scope_id, a.fact_key)
       a.id, a.scope_id, a.user_id,
       a.fact_key, d.family, d.display_name, d.value_type, d.unit,
       a.subject_kind, a.subject_ref, a.attribute, a.value,
       context.fact_number(a.value) AS numero,
       a.modality, a.source, a.confidence,
       context.source_rank(a.fact_key, a.source) AS source_rank,
       a.observed_at, a.valid_from, a.valid_until, a.confirmed_at,
       (a.valid_until IS NOT NULL
        AND a.valid_until <= current_date + 30) AS vence_em_breve
  FROM context.assertions a
  JOIN context.fact_definitions d ON d.fact_key = a.fact_key
 WHERE a.status = 'confirmado'
   AND a.superseded_at IS NULL
   AND (a.valid_until IS NULL OR a.valid_until >= current_date)
   AND d.is_active
 ORDER BY a.scope_id, a.fact_key,
          context.source_rank(a.fact_key, a.source),
          a.observed_at DESC;

COMMENT ON VIEW context.v_fact_current IS
  '[F14a] O `fact_current` do desenho: um fato por chave, escolhido por precedência '
  'de fonte e, no empate, pelo mais recente. É a entrada do motor de indicadores (40) '
  'e o que o Copiloto compara quando o cliente diz um número novo.';

-- O que ainda falta saber. Vira progresso mensurável, não formulário.
CREATE VIEW context.v_fact_coverage WITH (security_invoker = true) AS
SELECT s.id AS scope_id,
       count(*)                                        AS fatos_no_catalogo,
       count(f.fact_key)                               AS fatos_presentes,
       round(count(f.fact_key)::numeric
             / nullif(count(*), 0), 4)                 AS cobertura,
       count(*) FILTER (WHERE f.vence_em_breve)        AS vencendo,
       array_agg(d.fact_key ORDER BY d.family, d.fact_key)
         FILTER (WHERE f.fact_key IS NULL)             AS faltando
  FROM identity.scopes s
 CROSS JOIN context.fact_definitions d
  LEFT JOIN context.v_fact_current f
         ON f.scope_id = s.id AND f.fact_key = d.fact_key
 WHERE d.is_active
 GROUP BY s.id;

COMMENT ON VIEW context.v_fact_coverage IS
  '[F14a] Cobertura por escopo. Duas funções de uma vez: é a rede de compliance '
  '(score não sai sem base — ver 40) e é a mecânica de onboarding, porque o dado '
  'que falta vira a próxima pergunta do Copiloto em vez de um campo em branco.';

-- =============================================================================
-- Privilégios — tabela nova em schema existente (o padrão da 28 é por schema)
-- =============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON context.fact_definitions TO plexo_app, plexo_service;

-- =============================================================================
-- Política de governança do catálogo. Nasce draft, como todo seed client-facing.
-- =============================================================================
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('CONTEXT_FACT_CATALOG', 1, '{
  "precedencia_padrao": ["open_finance","upload","formulario","onboarding","conversa","inferencia_motor","operador"],
  "min_confianca_para_propor": 0.75,
  "cobertura_minima_para_score": 0.6,
  "nota": "Curvas de normalização dos scores vivem em CLIENT_SCORES (migration 40)."
}'::jsonb, 'draft');

-- =============================================================================
-- O catálogo v1 — 36 fatos nas seis famílias.
--
-- Precedências usadas (a ordem é a força; o índice 1 manda):
--   DECLARADO   formulario > conversa > onboarding > open_finance > upload > motor > operador
--               (renda, despesa, objetivo: a pessoa sabe do aumento antes do extrato)
--   MEDIDO      open_finance > upload > formulario > onboarding > conversa > motor > operador
--               (patrimônio, dívida: o extrato sabe do saldo melhor que a memória)
--   REGULATORIO formulario > onboarding > operador  (suitability: nem conversa nem motor)
-- =============================================================================
INSERT INTO context.fact_definitions
  (fact_key, subject_kind, attribute, family, display_name, value_type, unit,
   source_precedence, allows_conversation_update, half_life_days,
   materiality_abs, materiality_rel, min_value, max_value,
   is_recurring_by_nature, requires_nature_check, notes)
VALUES
-- ---------------------------------------------------------------- fluxo
('renda.mensal_liquida','renda','renda_mensal_liquida','fluxo','Renda mensal líquida','money_brl','BRL',
 ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
 true, 180, 500, 0.05, 0, 10000000, true, true,
 'O fato mais citado em conversa. requires_nature_check porque bônus e aumento chegam com a mesma frase.'),
('renda.mensal_bruta','renda','renda_mensal_bruta','fluxo','Renda mensal bruta','money_brl','BRL',
 ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
 true, 180, 500, 0.05, 0, 10000000, true, true, NULL),
('renda.fontes_ativas','renda','renda_fontes_ativas','fluxo','Número de fontes de renda','numero',NULL,
 ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
 true, 365, 1, NULL, 0, 20, true, false,
 'Concentração de renda é risco tanto quanto concentração de emissor — e ninguém mede.'),
('renda.tipo_vinculo','renda','renda_tipo_vinculo','fluxo','Tipo de vínculo','texto',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, 'clt | pj | servidor | autonomo | socio | aposentado'),
('renda.tem_decimo_terceiro','renda','renda_tem_decimo_terceiro','fluxo','Recebe 13º','booleano',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, NULL),
('despesa.total_mensal','despesa','despesa_total_mensal','fluxo','Despesa mensal total','money_brl','BRL',
 ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
 true, 180, 300, 0.10, 0, 10000000, true, true, NULL),
('despesa.essencial_mensal','despesa','despesa_essencial_mensal','fluxo','Despesa essencial mensal','money_brl','BRL',
 ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
 true, 180, 300, 0.10, 0, 10000000, true, true,
 'Base da reserva de emergência: é sobre ela que se contam os meses de cobertura, não sobre a despesa total.'),
('despesa.fixa_contratada','despesa','despesa_fixa_contratada','fluxo','Despesa fixa contratada','money_brl','BRL',
 ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
 true, 180, 300, 0.10, 0, 10000000, true, false,
 'Numerador da rigidez orçamentária: quanto choque a pessoa absorve sem quebrar contrato.'),
('fluxo.aporte_mensal','despesa','aporte_mensal','fluxo','Aporte mensal','money_brl','BRL',
 ARRAY['formulario','conversa','onboarding','open_finance','upload','inferencia_motor','operador']::context.assertion_source[],
 true, 180, 200, 0.10, 0, 10000000, true, true, NULL),

-- ---------------------------------------------------------------- protecao
('protecao.reserva_atual','patrimonio','protecao_reserva_atual','protecao','Reserva de emergência','money_brl','BRL',
 ARRAY['open_finance','upload','formulario','onboarding','conversa','inferencia_motor','operador']::context.assertion_source[],
 true, 90, 1000, 0.05, 0, 100000000, true, false, NULL),
('protecao.cobertura_vida','patrimonio','protecao_cobertura_vida','protecao','Capital segurado — vida','money_brl','BRL',
 ARRAY['upload','formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, 10000, 0.10, 0, 100000000, true, false,
 'A lacuna que nenhum robô-advisor brasileiro olha. Fee-only puro: a Plexo não vende apólice.'),
('protecao.cobertura_invalidez','patrimonio','protecao_cobertura_invalidez','protecao','Capital segurado — invalidez','money_brl','BRL',
 ARRAY['upload','formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, 10000, 0.10, 0, 100000000, true, false, NULL),
('protecao.tem_plano_saude','contexto_vida','protecao_tem_plano_saude','protecao','Tem plano de saúde','booleano',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, NULL),
('protecao.tem_seguro_residencial','contexto_vida','protecao_tem_seguro_residencial','protecao','Tem seguro residencial','booleano',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, NULL),
('protecao.dependentes_financeiros','titular','dependentes_financeiros','protecao','Dependentes financeiros','numero',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, 1, NULL, 0, 20, true, false,
 'Quem depende desta renda — diferente de quem mora na casa.'),

-- ---------------------------------------------------------------- estoque
('patrimonio.investido','patrimonio','patrimonio_investido','estoque','Patrimônio investido','money_brl','BRL',
 ARRAY['open_finance','upload','formulario','onboarding','conversa','inferencia_motor','operador']::context.assertion_source[],
 false, NULL, 1000, 0.02, 0, 1000000000, true, false,
 'C38b — governado pelo Open Finance. A conversa registra divergência; não sobrescreve.'),
('patrimonio.imobilizado','patrimonio','patrimonio_imobilizado','estoque','Patrimônio imobilizado','money_brl','BRL',
 ARRAY['upload','formulario','conversa','onboarding','inferencia_motor','operador']::context.assertion_source[],
 true, 365, 10000, 0.05, 0, 1000000000, true, false, 'Imóvel, empresa, veículo — o que estate.assets guarda.'),
('patrimonio.liquido','patrimonio','patrimonio_liquido','estoque','Patrimônio líquido','money_brl','BRL',
 ARRAY['open_finance','upload','formulario','onboarding','conversa','inferencia_motor','operador']::context.assertion_source[],
 false, NULL, 1000, 0.02, -1000000000, 1000000000, true, false,
 'Derivado de estate.v_net_worth. Patrimônio líquido negativo existe e precisa caber.'),
('divida.saldo_total','divida','divida_saldo_total','estoque','Saldo devedor total','money_brl','BRL',
 ARRAY['open_finance','upload','formulario','onboarding','conversa','inferencia_motor','operador']::context.assertion_source[],
 true, 90, 500, 0.05, 0, 1000000000, true, false, NULL),
('divida.custo_medio','divida','divida_custo_medio','estoque','Custo médio da dívida','percentual','fracao',
 ARRAY['open_finance','upload','formulario','onboarding','conversa','inferencia_motor','operador']::context.assertion_source[],
 true, 90, 0.005, 0.10, 0, 10, true, false,
 'É o spread contra o retorno esperado que decide quitar vs. investir. Rotativo e consignado não cabem no mesmo número.'),
('divida.parcela_mensal','divida','divida_parcela_mensal','estoque','Parcela mensal de dívidas','money_brl','BRL',
 ARRAY['open_finance','upload','formulario','onboarding','conversa','inferencia_motor','operador']::context.assertion_source[],
 true, 90, 200, 0.05, 0, 10000000, true, false, NULL),

-- ---------------------------------------------------------------- destino
('objetivo.valor_alvo','objetivo','objetivo_valor_alvo','destino','Valor do objetivo','money_brl','BRL',
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, 5000, 0.05, 0, 1000000000, true, false, NULL),
('objetivo.prazo_meses','objetivo','objetivo_prazo_meses','destino','Prazo do objetivo','meses','meses',
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, 3, 0.10, 0, 960, true, false, NULL),
('objetivo.prioridade','objetivo','objetivo_prioridade','destino','Prioridade do objetivo','numero',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, 1, NULL, 1, 10, true, false, NULL),
('destino.idade_aposentadoria','titular','idade_aposentadoria_alvo','destino','Idade-alvo de aposentadoria','anos','anos',
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, 1, NULL, 30, 100, true, false,
 'A pergunta que o Assessor existe para responder: "posso parar de trabalhar aos 55?".'),

-- ---------------------------------------------------------------- comportamento
('comportamento.aporte_regular','contexto_vida','comportamento_aporte_regular','comportamento','Aporta com regularidade','booleano',NULL,
 ARRAY['inferencia_motor','formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 180, NULL, NULL, NULL, NULL, true, false, NULL),
('comportamento.reacao_queda','preferencia','comportamento_reacao_queda','comportamento','Reação a queda de mercado','texto',NULL,
 ARRAY['inferencia_motor','formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, 'vendeu | manteve | aportou | nao_observado'),
('comportamento.experiencia_investimento','titular','experiencia_investimento','comportamento','Experiência com investimentos','texto',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 730, NULL, NULL, NULL, NULL, true, false, 'nenhuma | iniciante | intermediaria | avancada'),
('comportamento.nivel_conhecimento','titular','nivel_conhecimento','comportamento','Nível de conhecimento','texto',NULL,
 ARRAY['inferencia_motor','formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false,
 'Lido pelo Educador desde a F4 — era o único atributo com nome combinado e sem catálogo.'),

-- ---------------------------------------------------------------- vida
('vida.data_nascimento','titular','data_nascimento','vida','Data de nascimento','data',NULL,
 ARRAY['formulario','onboarding','conversa','operador']::context.assertion_source[],
 true, NULL, NULL, NULL, NULL, NULL, true, false, 'Não vence: idade se deriva, não se redeclara.'),
('vida.estado_civil','titular','estado_civil','vida','Estado civil','texto',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, 'solteiro | casado | uniao_estavel | divorciado | viuvo'),
('vida.regime_bens','titular','regime_bens','vida','Regime de bens','texto',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 730, NULL, NULL, NULL, NULL, true, false, 'comunhao_parcial | comunhao_universal | separacao_total | participacao_final'),
('vida.profissao','titular','profissao','vida','Profissão','texto',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, NULL),
('vida.estabilidade_emprego','titular','estabilidade_emprego','vida','Estabilidade do vínculo','texto',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, 'estavel | ciclica | precaria'),
('vida.moradia','contexto_vida','moradia','vida','Situação de moradia','texto',NULL,
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, NULL, NULL, NULL, NULL, true, false, 'proprio_quitado | proprio_financiado | alugado | cedido'),
('vida.tolerancia_risco_declarada','preferencia','tolerancia_risco_declarada','vida','Tolerância a risco declarada','texto',NULL,
 ARRAY['formulario','onboarding','operador']::context.assertion_source[],
 false, 730, NULL, NULL, NULL, NULL, true, false,
 'C38b — perfil é registro regulatório point-in-time (RCVM 30). Mudança exige REFAZER o '
 'suitability, como a regra-estrela da 21 já exige para aplicar a proposta. Nem conversa nem motor.'),
('vida.liquidez_minima_meses','preferencia','liquidez_minima_meses','vida','Liquidez mínima exigida','meses','meses',
 ARRAY['formulario','conversa','onboarding','operador']::context.assertion_source[],
 true, 365, 1, NULL, 0, 120, true, false, NULL);

COMMIT;
