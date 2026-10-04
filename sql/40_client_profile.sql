-- =============================================================================
-- PLEXO · 40_client_profile.sql — Indicadores e scores do cliente [F14c]
--
-- O QUE ESTE ARQUIVO ACRESCENTA
--   A 06 já sabia pontuar a CARTEIRA (`diagnostics.portfolio_scores`) e já tinha a
--   disciplina certa: quando a Fundação está crítica, o score não é baixo — ele é
--   DESATIVADO (D11). Faltava a mesma coisa para a PESSOA, que é onde a disciplina
--   importa mais, porque a pessoa não tem como conferir a conta.
--
-- OS TRÊS DEGRAUS, SEPARADOS DE PROPÓSITO
--   fato ──► indicador ──► score ──► gate / próxima ação
--   O indicador é objetivo e tem unidade ("a reserva cobre 4,2 meses de despesa
--   essencial"). O score é o juízo ("4,2 meses = 0,62 NESTA política"). Separá-los dá
--   três coisas: trocar a política sem tocar em cálculo; mostrar o indicador em vez
--   do score (o Livro da Marca é explícito — independência aparece como número, e
--   "4,2 meses" convence enquanto "0,62" não diz nada); e compliance revisar a
--   normalização, que é onde mora a opinião, sem revisar a matemática.
--
-- POR QUE NÃO EXISTE UM SCORE ÚNICO AQUI
--   Não há tabela de score composto, e a ausência é a decisão. Média ponderada deixa
--   uma falha crítica ser escondida por forças: rotativo aberto com carteira bem
--   montada sairia 0,72 — e 0,72 parece "razoável". O desenho é: GATE da Fundação,
--   depois um score por família, depois o elo mais fraco entre as críticas escolhendo
--   a próxima ação (v_client_profile).
--
-- TRÊS NÚMEROS, NUNCA UM
--   Todo score publica valor · cobertura · confiança. Abaixo da cobertura mínima ele
--   não sai: sai "indisponível — falta despesa essencial mensal". É a rede de
--   compliance e, ao mesmo tempo, a melhor mecânica de onboarding do produto, porque
--   o dado que falta vira a próxima pergunta em vez de um campo em branco.
--
-- Depende de: 01_identity, 02_engine, 03_billing, 06_diagnostics, 38_fact_catalog.
-- =============================================================================

BEGIN;

-- O motor do perfil é um run como qualquer outro: input_hash, engine_version,
-- policy_version_ids e output_hash. O label novo NÃO é usado nesta transação
-- (PostgreSQL recusaria) — quem o usa é o motor, depois do commit. Mesmo caminho
-- da família de tool `contexto` na 34.
ALTER TYPE engine.run_kind ADD VALUE IF NOT EXISTS 'client_profile';

-- -----------------------------------------------------------------------------
-- Catálogo de indicadores — o contrato de "de que fatos eu dependo"
-- -----------------------------------------------------------------------------
CREATE TABLE diagnostics.indicator_definitions (
  code                core.slug PRIMARY KEY,
  family              context.fact_family NOT NULL,
  display_name        text NOT NULL,
  unit                text,
  value_type          context.fact_value_type NOT NULL,
  higher_is_better    boolean NOT NULL,
  -- É desta lista que a COBERTURA sai. Sem ela, "score com dado faltando" seria
  -- indistinguível de "score com dado ruim".
  required_fact_keys  core.slug[] NOT NULL,
  optional_fact_keys  core.slug[] NOT NULL DEFAULT '{}',
  formula_ref         text NOT NULL,   -- função determinística do motor (auditoria RCVM 19)
  min_plan            billing.plan_code NOT NULL DEFAULT 'free',
  is_active           boolean NOT NULL DEFAULT true,
  notes               text,
  CONSTRAINT indicator_needs_inputs CHECK (cardinality(required_fact_keys) > 0)
);
CREATE INDEX indicator_definitions_family_idx
  ON diagnostics.indicator_definitions (family) WHERE is_active;

COMMENT ON COLUMN diagnostics.indicator_definitions.formula_ref IS
  'Nome da função determinística que calcula o indicador. O LLM nunca calcula: ele '
  'lê o resultado e explica. RCVM 19 art. 17 pede código inspecionável — este é o ponteiro.';

-- C40c — os fatos declarados existem no catálogo (array não aceita FK).
CREATE FUNCTION diagnostics.assert_indicator_facts_exist() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_faltando text[];
BEGIN
  SELECT array_agg(k) INTO v_faltando
    FROM unnest(NEW.required_fact_keys || NEW.optional_fact_keys) AS k
   WHERE NOT EXISTS (SELECT 1 FROM context.fact_definitions d WHERE d.fact_key = k);
  IF v_faltando IS NOT NULL THEN
    RAISE EXCEPTION
      'Indicador % depende de fato(s) fora do catálogo: %. Sem catálogo não há '
      'cobertura, e sem cobertura o score não sabe o que não sabe.',
      NEW.code, array_to_string(v_faltando, ', ') USING ERRCODE = '23503';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER indicator_facts_gate
  BEFORE INSERT OR UPDATE ON diagnostics.indicator_definitions
  FOR EACH ROW EXECUTE FUNCTION diagnostics.assert_indicator_facts_exist();

-- -----------------------------------------------------------------------------
-- Catálogo de scores — normalização e pesos vivem em POLÍTICA, não aqui
-- -----------------------------------------------------------------------------
CREATE TABLE diagnostics.score_definitions (
  code                core.slug PRIMARY KEY,
  family              context.fact_family NOT NULL,
  display_name        text NOT NULL,
  indicator_codes     core.slug[] NOT NULL,
  -- Família crítica é a que não pode ser compensada por força alheia. É entre elas
  -- que o elo mais fraco escolhe a próxima ação.
  is_critical_family  boolean NOT NULL DEFAULT false,
  min_coverage        numeric(5,4) NOT NULL DEFAULT 0.6
                      CHECK (min_coverage >= 0 AND min_coverage <= 1),
  policy_code         core.config_code NOT NULL DEFAULT 'CLIENT_SCORES',
  min_plan            billing.plan_code NOT NULL DEFAULT 'free',
  is_active           boolean NOT NULL DEFAULT true,
  notes               text,
  CONSTRAINT score_needs_indicators CHECK (cardinality(indicator_codes) > 0),
  -- 'vida' é contexto que MODULA o resto (idade, regime de bens, moradia). Virar
  -- score faria a plataforma pontuar a biografia do cliente.
  CONSTRAINT score_family_is_scoreable CHECK (family <> 'vida')
);

CREATE FUNCTION diagnostics.assert_score_indicators_exist() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_faltando text[];
BEGIN
  SELECT array_agg(k) INTO v_faltando
    FROM unnest(NEW.indicator_codes) AS k
   WHERE NOT EXISTS (SELECT 1 FROM diagnostics.indicator_definitions i WHERE i.code = k);
  IF v_faltando IS NOT NULL THEN
    RAISE EXCEPTION 'Score % aponta indicador(es) inexistente(s): %',
      NEW.code, array_to_string(v_faltando, ', ') USING ERRCODE = '23503';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER score_indicators_gate
  BEFORE INSERT OR UPDATE ON diagnostics.score_definitions
  FOR EACH ROW EXECUTE FUNCTION diagnostics.assert_score_indicators_exist();

-- -----------------------------------------------------------------------------
-- Séries calculadas
-- -----------------------------------------------------------------------------
CREATE TABLE diagnostics.client_indicators (
  scope_id           uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date         date NOT NULL,
  indicator_code     core.slug NOT NULL REFERENCES diagnostics.indicator_definitions(code),
  run_id             uuid NOT NULL REFERENCES engine.runs(id),
  value              numeric(18,6),
  unit               text,
  coverage           numeric(5,4) NOT NULL CHECK (coverage BETWEEN 0 AND 1),
  confidence         core.confidence NOT NULL,
  inputs             jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {fact_key: {value, as_of, source}}
  is_unavailable     boolean NOT NULL DEFAULT false,
  unavailable_reason text CHECK (unavailable_reason IN
                       ('cobertura_insuficiente','dados_insuficientes','motor_ausente','fato_vencido')),
  computed_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_id, as_of_date, indicator_code),
  CONSTRAINT indicator_unavailable_xor_value CHECK (
    (is_unavailable AND value IS NULL AND unavailable_reason IS NOT NULL)
    OR (NOT is_unavailable AND value IS NOT NULL AND unavailable_reason IS NULL)
  )
);
CREATE INDEX client_indicators_scope_idx
  ON diagnostics.client_indicators (scope_id, as_of_date DESC);

COMMENT ON CONSTRAINT indicator_unavailable_xor_value ON diagnostics.client_indicators IS
  'Indisponível não é zero, e zero não é indisponível. Um indicador que falta precisa '
  'DIZER que falta e por quê — é isso que vira a próxima pergunta do Copiloto.';

CREATE TABLE diagnostics.client_scores (
  scope_id          uuid NOT NULL REFERENCES identity.scopes(id),
  as_of_date        date NOT NULL,
  score_code        core.slug NOT NULL REFERENCES diagnostics.score_definitions(code),
  run_id            uuid NOT NULL REFERENCES engine.runs(id),
  value             numeric(5,4) CHECK (value BETWEEN 0 AND 1),
  coverage          numeric(5,4) NOT NULL CHECK (coverage BETWEEN 0 AND 1),
  confidence        core.confidence NOT NULL,
  is_disabled       boolean NOT NULL DEFAULT false,
  disabled_reason   text CHECK (disabled_reason IN
                      ('fundacao_critica','cobertura_insuficiente','dados_insuficientes')),
  components        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {indicator_code: {bruto, normalizado, peso}}
  policy_version_id uuid NOT NULL REFERENCES engine.policy_versions(id),
  computed_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_id, as_of_date, score_code),
  CONSTRAINT score_disabled_xor_value CHECK (
    (is_disabled AND value IS NULL AND disabled_reason IS NOT NULL)
    OR (NOT is_disabled AND value IS NOT NULL AND disabled_reason IS NULL)
  )
);
CREATE INDEX client_scores_scope_idx ON diagnostics.client_scores (scope_id, as_of_date DESC);

COMMENT ON TABLE diagnostics.client_scores IS
  '[F14c] Um score POR FAMÍLIA. Não existe tabela de score composto, e a ausência é a '
  'decisão: média ponderada permitiria que uma falha crítica fosse escondida por força '
  'em outra família. O que a tela mostra é o perfil e o elo mais fraco (v_client_profile).';

-- ---------------------------------------------------------------- C40a + C40b + C40d
CREATE FUNCTION diagnostics.assert_client_score_is_publishable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  d           diagnostics.score_definitions%ROWTYPE;
  v_critica   boolean;
  v_status    engine.compliance_status;
  v_facing    boolean;
BEGIN
  SELECT * INTO d FROM diagnostics.score_definitions WHERE code = NEW.score_code;

  -- C40a — D11 estendida ao cliente. Fundação crítica DESATIVA; não rebaixa.
  SELECT is_critical INTO v_critica
    FROM diagnostics.foundation_status
   WHERE scope_id = NEW.scope_id AND as_of_date = NEW.as_of_date;

  IF coalesce(v_critica, false) THEN
    IF NOT NEW.is_disabled THEN
      RAISE EXCEPTION
        'C40a — a Fundação está crítica em %: o score "%" fica DESATIVADO, não baixo. '
        'Reserva e dívida cara vêm antes de qualquer pontuação (D11).',
        NEW.as_of_date, d.display_name USING ERRCODE = '23514';
    END IF;
    IF NEW.disabled_reason <> 'fundacao_critica' THEN
      RAISE EXCEPTION
        'C40a — com a Fundação crítica, o motivo da desativação é "fundacao_critica" '
        '(veio "%"). Outro motivo esconderia a causa real do cliente.', NEW.disabled_reason
        USING ERRCODE = '23514';
    END IF;
  END IF;

  -- C40b — cobertura abaixo do mínimo não vira número imputado em silêncio.
  IF NEW.coverage < d.min_coverage AND NOT NEW.is_disabled THEN
    RAISE EXCEPTION
      'C40b — cobertura % está abaixo do mínimo % para "%": o score não sai com valor, '
      'sai indisponível dizendo o que falta.', NEW.coverage, d.min_coverage, d.display_name
      USING ERRCODE = '23514';
  END IF;

  -- C40d — número que o cliente lê sai de premissa aprovada (RCVM 19).
  SELECT is_client_facing INTO v_facing FROM engine.runs WHERE id = NEW.run_id;
  IF coalesce(v_facing, false) THEN
    SELECT compliance_status INTO v_status
      FROM engine.policy_versions WHERE id = NEW.policy_version_id;
    IF v_status IS DISTINCT FROM 'approved' THEN
      RAISE EXCEPTION
        'C40d — score client-facing sobre política em "%". A curva de normalização é '
        'onde mora a opinião: ela precisa de aprovação de compliance antes de virar '
        'número na tela.', coalesce(v_status::text, 'inexistente') USING ERRCODE = '23514';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;
CREATE TRIGGER client_scores_publishable_gate
  BEFORE INSERT OR UPDATE ON diagnostics.client_scores
  FOR EACH ROW EXECUTE FUNCTION diagnostics.assert_client_score_is_publishable();

-- -----------------------------------------------------------------------------
-- A view que a tela e o Copiloto leem: perfil por família + elo mais fraco
-- -----------------------------------------------------------------------------
CREATE VIEW diagnostics.v_client_profile WITH (security_invoker = true) AS
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
       -- Elo mais fraco: o MENOR score ativo entre as famílias CRÍTICAS. Score
       -- desativado não concorre — ausência de medida não é fraqueza medida.
       (s.value IS NOT NULL
        AND d.is_critical_family
        AND s.value = min(s.value) FILTER (WHERE d.is_critical_family AND NOT s.is_disabled)
                        OVER (PARTITION BY s.scope_id, s.as_of_date)) AS elo_mais_fraco
  FROM diagnostics.client_scores s
  JOIN diagnostics.score_definitions d ON d.code = s.score_code
  LEFT JOIN diagnostics.foundation_status f
         ON f.scope_id = s.scope_id AND f.as_of_date = s.as_of_date
 WHERE d.is_active;

COMMENT ON VIEW diagnostics.v_client_profile IS
  '[F14c] O perfil como ele deve ser lido: gate da Fundação acima, um score por '
  'família, e o elo mais fraco entre as críticas marcado. É do elo que sai a próxima '
  'ação — nunca de uma média, que deixaria a falha crítica desaparecer na conta.';

-- -----------------------------------------------------------------------------
-- RLS — as duas séries carregam scope_id (o padrão da 14 e da 21)
-- -----------------------------------------------------------------------------
ALTER TABLE diagnostics.client_indicators ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnostics.client_indicators FORCE  ROW LEVEL SECURITY;
CREATE POLICY client_indicators_isolation ON diagnostics.client_indicators FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE diagnostics.client_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnostics.client_scores FORCE  ROW LEVEL SECURITY;
CREATE POLICY client_scores_isolation ON diagnostics.client_scores FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

-- -----------------------------------------------------------------------------
-- Privilégios (tabelas novas em schema existente)
-- -----------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE
  ON diagnostics.indicator_definitions, diagnostics.score_definitions,
     diagnostics.client_indicators, diagnostics.client_scores
  TO plexo_app, plexo_service;

-- =============================================================================
-- Catálogo v1 de indicadores. Os fact_key referenciados são os da 38.
-- =============================================================================
INSERT INTO diagnostics.indicator_definitions
  (code, family, display_name, unit, value_type, higher_is_better,
   required_fact_keys, optional_fact_keys, formula_ref, notes)
VALUES
-- ---------------------------------------------------------------- fluxo
('fluxo.taxa_poupanca','fluxo','Taxa de poupança','fracao','percentual',true,
 ARRAY['renda.mensal_liquida','despesa.total_mensal']::core.slug[], '{}'::core.slug[],
 'taxa_poupanca', 'O número-herói do Orçamento: (renda − despesa) / renda.'),
('fluxo.rigidez_orcamentaria','fluxo','Rigidez orçamentária','fracao','percentual',false,
 ARRAY['despesa.fixa_contratada','renda.mensal_liquida']::core.slug[], '{}'::core.slug[],
 'rigidez_orcamentaria',
 'Quanto choque a pessoa absorve sem quebrar contrato. É o que o quadro chamava de "perfil de gastos".'),
('fluxo.concentracao_renda','fluxo','Concentração da renda','fracao','percentual',false,
 ARRAY['renda.fontes_ativas']::core.slug[], ARRAY['renda.tipo_vinculo']::core.slug[],
 'concentracao_renda',
 '100% num único empregador é risco de carteira tanto quanto 40% num único emissor.'),
('fluxo.inflacao_estilo_vida','fluxo','Inflação de estilo de vida','fracao','percentual',false,
 ARRAY['renda.mensal_liquida','despesa.total_mensal']::core.slug[], '{}'::core.slug[],
 'inflacao_estilo_vida',
 'Δdespesa ÷ Δrenda em 12 meses. Diz se um aumento vira patrimônio ou vira custo fixo novo — '
 'é o que separa progresso de esteira. Exige histórico: sem ele, sai indisponível.'),

-- ---------------------------------------------------------------- protecao
('protecao.cobertura_reserva','protecao','Cobertura da reserva','meses','meses',true,
 ARRAY['protecao.reserva_atual','despesa.essencial_mensal']::core.slug[], '{}'::core.slug[],
 'cobertura_reserva_meses',
 'O indicador que se mostra em vez do score: "4,2 meses" convence; "0,62" não diz nada.'),
('protecao.lacuna_seguro_vida','protecao','Lacuna de seguro de vida','BRL','money_brl',false,
 ARRAY['protecao.dependentes_financeiros','despesa.essencial_mensal']::core.slug[],
 ARRAY['protecao.cobertura_vida','divida.saldo_total']::core.slug[],
 'lacuna_seguro_vida',
 'Dois dependentes, financiamento aberto e nenhum seguro é um buraco maior que qualquer '
 'erro de alocação — e praticamente nenhum robô-advisor brasileiro olha. Fee-only puro: '
 'a Plexo não vende apólice.'),
('protecao.vulnerabilidade_choque','protecao','Autonomia com renda reduzida','meses','meses',true,
 ARRAY['protecao.reserva_atual','despesa.essencial_mensal','renda.mensal_liquida']::core.slug[],
 '{}'::core.slug[], 'vulnerabilidade_choque_meses',
 'Quantos meses de autonomia com a renda 40% menor.'),

-- ---------------------------------------------------------------- estoque
('estoque.independencia','estoque','Patrimônio em meses de despesa','meses','meses',true,
 ARRAY['patrimonio.liquido','despesa.essencial_mensal']::core.slug[], '{}'::core.slug[],
 'patrimonio_meses_despesa', NULL),
('estoque.custo_da_divida','estoque','Custo médio da dívida','fracao','percentual',false,
 ARRAY['divida.custo_medio']::core.slug[], ARRAY['divida.saldo_total']::core.slug[],
 'custo_medio_divida',
 'É o spread contra o retorno esperado que decide quitar vs. investir — rotativo e '
 'consignado nunca podem cair no mesmo número.'),
('estoque.comprometimento_divida','estoque','Comprometimento com dívidas','fracao','percentual',false,
 ARRAY['divida.parcela_mensal','renda.mensal_liquida']::core.slug[], '{}'::core.slug[],
 'comprometimento_divida', NULL),

-- ---------------------------------------------------------------- destino
('destino.esforco_requerido','destino','Esforço requerido pelo objetivo','fracao','percentual',false,
 ARRAY['objetivo.valor_alvo','objetivo.prazo_meses','fluxo.aporte_mensal']::core.slug[],
 '{}'::core.slug[], 'esforco_requerido',
 'Aporte necessário ÷ superávit disponível. Acima de 1,0 o plano é infactível, e dizer '
 'isso cedo é a coisa mais fiduciária que o produto faz.'),
('destino.horizonte_aposentadoria','destino','Horizonte até a aposentadoria','anos','anos',true,
 ARRAY['destino.idade_aposentadoria','vida.data_nascimento']::core.slug[], '{}'::core.slug[],
 'horizonte_aposentadoria', NULL),

-- ---------------------------------------------------------------- comportamento
('comportamento.regularidade_aporte','comportamento','Regularidade de aporte','fracao','percentual',true,
 ARRAY['comportamento.aporte_regular']::core.slug[], '{}'::core.slug[],
 'regularidade_aporte', 'Só existe com tempo de casa: sem histórico, sai indisponível.'),
('comportamento.disciplina_na_queda','comportamento','Disciplina na queda','fracao','percentual',true,
 ARRAY['comportamento.reacao_queda']::core.slug[], '{}'::core.slug[],
 'disciplina_na_queda', NULL);

-- =============================================================================
-- Scores v1 — cinco famílias, nenhuma agregação acima delas
-- =============================================================================
INSERT INTO diagnostics.score_definitions
  (code, family, display_name, indicator_codes, is_critical_family, min_coverage, notes)
VALUES
('score.fluxo','fluxo','Fluxo',
 ARRAY['fluxo.taxa_poupanca','fluxo.rigidez_orcamentaria','fluxo.concentracao_renda',
       'fluxo.inflacao_estilo_vida']::core.slug[], true, 0.6,
 'Crítica: sem sobra recorrente, nenhuma outra família se sustenta.'),
('score.protecao','protecao','Proteção',
 ARRAY['protecao.cobertura_reserva','protecao.lacuna_seguro_vida',
       'protecao.vulnerabilidade_choque']::core.slug[], true, 0.6,
 'Crítica: é a família cuja falha nenhuma força alheia compensa.'),
('score.estoque','estoque','Estoque',
 ARRAY['estoque.independencia','estoque.custo_da_divida',
       'estoque.comprometimento_divida']::core.slug[], false, 0.6, NULL),
('score.destino','destino','Destino',
 ARRAY['destino.esforco_requerido','destino.horizonte_aposentadoria']::core.slug[], false, 0.5,
 'Cobertura mínima menor porque objetivo é declarado, não medido.'),
('score.comportamento','comportamento','Comportamento',
 ARRAY['comportamento.regularidade_aporte','comportamento.disciplina_na_queda']::core.slug[],
 false, 0.5, 'Nasce indisponível para cliente novo — e isso é honesto, não uma falha.');

-- =============================================================================
-- CLIENT_SCORES — onde mora a OPINIÃO. Curvas lineares por partes + pesos.
-- Trocar 6 meses por 4 vira versão nova com vigência, não commit.
-- Nasce draft: até compliance aprovar, só run interno pode usá-la (C40d).
-- =============================================================================
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('CLIENT_SCORES', 1, '{
  "normalizacao": {
    "fluxo.taxa_poupanca":              {"pontos": [[0,0.0],[0.05,0.30],[0.15,0.70],[0.30,1.0]], "clamp": true},
    "fluxo.rigidez_orcamentaria":       {"pontos": [[0.30,1.0],[0.50,0.70],[0.70,0.30],[0.90,0.0]], "clamp": true},
    "fluxo.concentracao_renda":         {"pontos": [[0.40,1.0],[0.70,0.70],[1.0,0.35]], "clamp": true},
    "fluxo.inflacao_estilo_vida":       {"pontos": [[0.0,1.0],[0.50,0.70],[1.0,0.30],[1.50,0.0]], "clamp": true},
    "protecao.cobertura_reserva":       {"pontos": [[0,0.0],[3,0.50],[6,0.85],[12,1.0]], "clamp": true},
    "protecao.lacuna_seguro_vida":      {"pontos": [[0,1.0],[100000,0.60],[500000,0.20],[1000000,0.0]], "clamp": true},
    "protecao.vulnerabilidade_choque":  {"pontos": [[0,0.0],[3,0.45],[6,0.80],[12,1.0]], "clamp": true},
    "estoque.independencia":            {"pontos": [[0,0.0],[24,0.40],[120,0.80],[300,1.0]], "clamp": true},
    "estoque.custo_da_divida":          {"pontos": [[0.0,1.0],[0.10,0.75],[0.25,0.35],[0.60,0.0]], "clamp": true},
    "estoque.comprometimento_divida":   {"pontos": [[0.0,1.0],[0.15,0.70],[0.30,0.35],[0.50,0.0]], "clamp": true},
    "destino.esforco_requerido":        {"pontos": [[0.0,1.0],[0.50,0.80],[1.0,0.40],[1.50,0.0]], "clamp": true},
    "destino.horizonte_aposentadoria":  {"pontos": [[0,0.0],[10,0.55],[25,0.90],[40,1.0]], "clamp": true},
    "comportamento.regularidade_aporte":{"pontos": [[0.0,0.0],[0.50,0.55],[1.0,1.0]], "clamp": true},
    "comportamento.disciplina_na_queda":{"pontos": [[0.0,0.0],[0.50,0.55],[1.0,1.0]], "clamp": true}
  },
  "pesos": {
    "score.fluxo":         {"fluxo.taxa_poupanca": 0.45, "fluxo.rigidez_orcamentaria": 0.25, "fluxo.concentracao_renda": 0.15, "fluxo.inflacao_estilo_vida": 0.15},
    "score.protecao":      {"protecao.cobertura_reserva": 0.45, "protecao.lacuna_seguro_vida": 0.30, "protecao.vulnerabilidade_choque": 0.25},
    "score.estoque":       {"estoque.independencia": 0.40, "estoque.custo_da_divida": 0.35, "estoque.comprometimento_divida": 0.25},
    "score.destino":       {"destino.esforco_requerido": 0.65, "destino.horizonte_aposentadoria": 0.35},
    "score.comportamento": {"comportamento.regularidade_aporte": 0.60, "comportamento.disciplina_na_queda": 0.40}
  },
  "meia_vida_confianca_dias": 180,
  "nota": "Curva linear por partes: interpola entre pontos, satura fora deles quando clamp. Peso de indicador indisponível é redistribuido entre os presentes e derruba a cobertura — nunca é imputado."
}'::jsonb, 'draft');

COMMIT;
