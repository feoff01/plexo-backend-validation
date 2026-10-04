-- =============================================================================
-- PLEXO · 48_market_assumptions.sql — premissas de mercado versionadas [F17, 1ª onda]
--
-- O INSUMO MAIS CONTESTÁVEL DO SISTEMA GANHA TABELA, VERSÃO E APROVADOR
--
-- A probabilidade de sucesso de uma meta é o número mais persuasivo que a plataforma
-- produz — "com 90% de confiança você chega em R$ X" muda decisão de gente. E é o único
-- número cujo insumo principal não é medido: retorno esperado e volatilidade são
-- ARBITRADOS. `META_PROBABILIDADE_DE_SUCESSO.md` já dizia, e é a razão desta migration:
--
--   "É o insumo mais contestável de todo o sistema e o primeiro que um regulador vai pedir."
--
-- Guardar isso em `payload jsonb` de política — que é onde estaria se ninguém parasse para
-- pensar — perderia três coisas que importam: a granularidade por classe de ativo, a
-- correlação entre classes (que não é escalar) e a possibilidade de perguntar "de onde saiu
-- este 7% de ações?" e receber uma resposta escrita. `metodologia` é NOT NULL por isso.
--
-- TRÊS INVARIANTES, E CADA UM TEM MOTIVO CONCRETO
--
--   (a) APROVAÇÃO EXIGE ORIGEM E AUTOR (C48a). O mesmo ciclo de `engine.policy_versions`:
--       nasce `draft`, serve para calibrar; vira `approved` com aprovador e data, e só então
--       pode virar número na tela do cliente.
--
--   (b) UNIDADE É CONSTRAINT, NÃO CONVENÇÃO. A F16 gastou meia sessão num defeito onde
--       `market.index_values` guardava taxa em PERCENTUAL (14,0) e `budget.debts.annual_rate`
--       em FRAÇÃO (0,14): comparados sem conversão, uma dívida a 400% a.a. pareceu mais
--       barata que o CDI e o semáforo de dívida saiu VERDE. A correção isolou a conversão
--       numa função; aqui a faixa é estreita de propósito — 0,07 passa, 7,0 é recusado no
--       INSERT. A unidade errada vira erro, não bug silencioso.
--
--   (c) MATRIZ FECHADA NA APROVAÇÃO (C48b). Correlação faltando é correlação lida como zero,
--       e zero subestima a volatilidade da carteira inteira — justamente o número que a
--       simulação usa para dizer o quanto o cenário ruim é ruim. Conjunto aprovado com par
--       ausente seria uma promessa de precisão que o dado não sustenta.
--
-- E A PROJEÇÃO GANHA O QUE FALTAVA
--   `planning.goal_projections` tinha p10/p50/p90 e nasceu (07) pensando em fan chart. Faltam
--   as caudas (p5/p95), os quartis (p25/p75), a métrica de arrependimento — probabilidade de
--   terminar com MENOS do que foi depositado, que é o risco que o cliente sente e que
--   percentil nenhum comunica — e a proveniência da premissa na própria linha.
--
-- Depende de: 00_core, 02_engine, 04_market, 07_planning, 40_client_profile.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- O conjunto: uma versão de premissas, com vigência e aprovação
-- -----------------------------------------------------------------------------
CREATE TABLE market.assumption_sets (
  id                uuid PRIMARY KEY DEFAULT core.new_id(),
  -- `core.config_code` e não `core.slug`: é o mesmo tipo de objeto que
  -- `engine.policy_versions` — config versionado com vigência, não identificador de dado.
  code              core.config_code NOT NULL,
  version           int NOT NULL CHECK (version > 0),
  horizonte_anos    smallint NOT NULL CHECK (horizonte_anos BETWEEN 1 AND 60),
  -- De onde saíram os números. NOT NULL porque "de onde saiu esse 4,5%?" é a primeira
  -- pergunta de qualquer auditoria, e a resposta não pode ser um commit antigo.
  metodologia       text NOT NULL CHECK (length(btrim(metodologia)) >= 40),
  compliance_status engine.compliance_status NOT NULL DEFAULT 'draft',
  approved_by       uuid REFERENCES identity.users(id),
  approved_at       timestamptz,
  effective_from    timestamptz NOT NULL DEFAULT now(),
  effective_to      timestamptz,
  notes             text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (code, version),
  -- C48a — mesma regra da política de motor (02_engine): aprovado tem autor e data.
  CONSTRAINT approved_has_author CHECK (
    (compliance_status = 'approved') = (approved_at IS NOT NULL)
    AND (compliance_status <> 'approved' OR approved_by IS NOT NULL)),
  CONSTRAINT vigencia_coerente CHECK (effective_to IS NULL OR effective_to > effective_from)
);
-- Um conjunto vigente por código — a mesma forma da política de motor.
CREATE UNIQUE INDEX assumption_sets_one_current ON market.assumption_sets (code)
  WHERE effective_to IS NULL;
CREATE INDEX assumption_sets_status_idx ON market.assumption_sets (compliance_status);

COMMENT ON TABLE market.assumption_sets IS
  '[F17] Premissas de mercado versionadas — o insumo mais contestável do sistema, e por isso '
  'o que mais precisa de versão, origem escrita e aprovador. Nasce draft; só aprovado vira '
  'número na tela (C48c).';
COMMENT ON COLUMN market.assumption_sets.metodologia IS
  'De onde saíram os números: fonte, janela, tratamento. É o que se mostra quando alguém '
  'pergunta por que a simulação assume o que assume.';

-- -----------------------------------------------------------------------------
-- Premissa por classe de ativo — em termos REAIS (acima da inflação)
-- -----------------------------------------------------------------------------
CREATE TABLE market.class_assumptions (
  id                uuid PRIMARY KEY DEFAULT core.new_id(),
  assumption_set_id uuid NOT NULL REFERENCES market.assumption_sets(id) ON DELETE CASCADE,
  asset_class_code  core.slug NOT NULL REFERENCES market.asset_classes(code),
  -- FRAÇÃO, não percentual: 0,07 = 7% a.a. real. A faixa estreita é a constraint que a
  -- lição do CDI da F16 deixou — 7,0 aqui seria 700% a.a. e é recusado no INSERT.
  retorno_real_aa   numeric(6,4) NOT NULL
                    CHECK (retorno_real_aa BETWEEN -0.30 AND 0.30),
  volatilidade_aa   numeric(6,4) NOT NULL
                    CHECK (volatilidade_aa >= 0 AND volatilidade_aa <= 1.00),
  fonte             text NOT NULL CHECK (length(btrim(fonte)) > 0),
  UNIQUE (assumption_set_id, asset_class_code)
);
CREATE INDEX class_assumptions_set_idx ON market.class_assumptions (assumption_set_id);

COMMENT ON COLUMN market.class_assumptions.retorno_real_aa IS
  'Retorno REAL anual em FRAÇÃO (0,07 = 7% a.a. acima da inflação). Real e não nominal para '
  'que a meta em reais de hoje não precise de uma segunda premissa de inflação embutida.';
COMMENT ON COLUMN market.class_assumptions.volatilidade_aa IS
  'Desvio-padrão anual do retorno, em FRAÇÃO. Entra na volatilidade da carteira por '
  'σ_p = √(wᵀΣw) — é dele que sai o quanto o cenário ruim é ruim.';

-- -----------------------------------------------------------------------------
-- Correlação entre classes — par NÃO ORDENADO, diagonal implícita
-- -----------------------------------------------------------------------------
CREATE TABLE market.class_correlations (
  assumption_set_id uuid NOT NULL REFERENCES market.assumption_sets(id) ON DELETE CASCADE,
  classe_a          core.slug NOT NULL REFERENCES market.asset_classes(code),
  classe_b          core.slug NOT NULL REFERENCES market.asset_classes(code),
  correlacao        numeric(4,3) NOT NULL CHECK (correlacao BETWEEN -1 AND 1),
  PRIMARY KEY (assumption_set_id, classe_a, classe_b),
  -- Guardar (a,b) e (b,a) permitiria dois valores para a MESMA relação, e a matriz deixaria
  -- de ser simétrica sem ninguém perceber. A ordem lexicográfica resolve por construção, e
  -- de quebra impede a diagonal, que é 1 por definição e não se guarda.
  CONSTRAINT par_ordenado CHECK (classe_a < classe_b)
);

COMMENT ON TABLE market.class_correlations IS
  '[F17] Metade da matriz de correlação (par ordenado; diagonal = 1 implícita). Conjunto '
  'aprovado exige a matriz FECHADA entre as classes que ele cobre (C48b): par ausente seria '
  'lido como zero, e zero subestima o risco da carteira inteira.';

-- -----------------------------------------------------------------------------
-- C48a/C48b — o que a aprovação exige, e a imutabilidade do que já foi aprovado
-- -----------------------------------------------------------------------------
CREATE FUNCTION market.assert_assumption_set_approvable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  n_classes  int;
  n_pares    int;
  n_esperado int;
BEGIN
  -- Aprovado é imutável: mudar premissa aprovada é mudar, retroativamente, o número que um
  -- cliente já leu. Premissa nova = versão nova, como toda a história deste banco.
  IF TG_OP = 'UPDATE' AND OLD.compliance_status = 'approved' THEN
    IF NEW.metodologia IS DISTINCT FROM OLD.metodologia
       OR NEW.horizonte_anos IS DISTINCT FROM OLD.horizonte_anos
       OR NEW.code IS DISTINCT FROM OLD.code
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.compliance_status IS DISTINCT FROM OLD.compliance_status THEN
      RAISE EXCEPTION
        'C48d — conjunto de premissas aprovado é imutável: "% v%" já sustentou número na '
        'tela. Premissa nova é VERSÃO nova, com vigência — não edição.', OLD.code, OLD.version
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;   -- encerrar vigência (effective_to) continua permitido
  END IF;

  IF NEW.compliance_status <> 'approved' THEN
    RETURN NEW;
  END IF;

  SELECT count(*) INTO n_classes
    FROM market.class_assumptions WHERE assumption_set_id = NEW.id;

  IF n_classes < 2 THEN
    RAISE EXCEPTION
      'C48b — conjunto aprovado precisa de pelo menos duas classes de ativo (tem %). '
      'Uma classe só não tem carteira para simular.', n_classes USING ERRCODE = '23514';
  END IF;

  SELECT count(*) INTO n_pares
    FROM market.class_correlations WHERE assumption_set_id = NEW.id;
  n_esperado := n_classes * (n_classes - 1) / 2;

  IF n_pares <> n_esperado THEN
    RAISE EXCEPTION
      'C48b — a matriz de correlação está aberta: % classes exigem % pares, existem %. '
      'Par ausente é correlação lida como ZERO, e zero subestima o risco da carteira — '
      'justamente o número que a simulação usa para dizer o quanto o cenário ruim é ruim.',
      n_classes, n_esperado, n_pares USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER assumption_sets_approvable_gate
  BEFORE INSERT OR UPDATE ON market.assumption_sets
  FOR EACH ROW EXECUTE FUNCTION market.assert_assumption_set_approvable();

-- -----------------------------------------------------------------------------
-- A projeção: caudas, quartis, arrependimento e proveniência da premissa
-- -----------------------------------------------------------------------------
ALTER TABLE planning.goal_projections
  ADD COLUMN p5_brl  core.money_brl,
  ADD COLUMN p25_brl core.money_brl,
  ADD COLUMN p75_brl core.money_brl,
  ADD COLUMN p95_brl core.money_brl,
  -- O risco que o cliente SENTE, e que percentil nenhum comunica: terminar com menos do que
  -- foi depositado. É a métrica que impede "a arrojada tem mediana maior, então é melhor".
  ADD COLUMN prob_abaixo_do_depositado numeric(5,4)
             CHECK (prob_abaixo_do_depositado BETWEEN 0 AND 1),
  ADD COLUMN alocacao_code core.slug,
  ADD COLUMN assumption_set_id uuid REFERENCES market.assumption_sets(id);

-- Percentil fora de ordem não é dado ruim: é dado IMPOSSÍVEL, e denuncia troca de coluna ou
-- distribuição mal ordenada antes que o fan chart vire uma figura sem sentido. Comparação
-- com NULL devolve NULL e o CHECK passa — projeção parcial continua permitida.
ALTER TABLE planning.goal_projections
  ADD CONSTRAINT percentis_ordenados CHECK (
        (p5_brl  IS NULL OR p10_brl IS NULL OR p5_brl  <= p10_brl)
    AND (p10_brl IS NULL OR p25_brl IS NULL OR p10_brl <= p25_brl)
    AND (p25_brl IS NULL OR p50_brl IS NULL OR p25_brl <= p50_brl)
    AND (p50_brl IS NULL OR p75_brl IS NULL OR p50_brl <= p75_brl)
    AND (p75_brl IS NULL OR p90_brl IS NULL OR p75_brl <= p90_brl)
    AND (p90_brl IS NULL OR p95_brl IS NULL OR p90_brl <= p95_brl));

COMMENT ON COLUMN planning.goal_projections.prob_abaixo_do_depositado IS
  '[F17] Probabilidade de o valor final ficar abaixo do total aportado. É o arrependimento, '
  'e é o contrapeso da mediana: sem ele, mais risco parece sempre melhor.';
COMMENT ON COLUMN planning.goal_projections.assumption_set_id IS
  '[F17] Qual versão de premissa produziu estes números. Sem isso a projeção é irrefutável '
  'no pior sentido: ninguém consegue dizer sobre o que ela se apoiava.';

-- -----------------------------------------------------------------------------
-- C48c — o gate C40d estendido à premissa de mercado, mais a semente
-- -----------------------------------------------------------------------------
CREATE FUNCTION planning.assert_projection_is_publishable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_facing boolean;
  v_params jsonb;
  v_status engine.compliance_status;
BEGIN
  SELECT is_client_facing, params INTO v_facing, v_params
    FROM engine.runs WHERE id = NEW.run_id;

  -- Reprodutibilidade não é boa prática aqui, é exigência de auditoria: uma projeção que
  -- ninguém consegue refazer não é auditável. A semente mora em `engine.runs.params`, que
  -- já entra no `input_hash` — e portanto na identidade do run. Vale para run interno
  -- também: o interno é justamente o que se refaz para conferir.
  IF NOT (coalesce(v_params, '{}'::jsonb) ? 'semente') THEN
    RAISE EXCEPTION
      'C48e — projeção cujo run não registrou a semente do Monte Carlo. Sem semente o '
      'número não se refaz, e número que não se refaz não se audita.'
      USING ERRCODE = '23514';
  END IF;

  IF coalesce(v_facing, false) THEN
    IF NEW.assumption_set_id IS NULL THEN
      RAISE EXCEPTION
        'C48c — projeção client-facing sem conjunto de premissas declarado. O retorno '
        'esperado é a opinião mais forte que a plataforma emite: ela tem versão e autor.'
        USING ERRCODE = '23514';
    END IF;

    SELECT compliance_status INTO v_status
      FROM market.assumption_sets WHERE id = NEW.assumption_set_id;

    IF v_status IS DISTINCT FROM 'approved' THEN
      RAISE EXCEPTION
        'C48c — projeção client-facing sobre premissa de mercado em "%". Rascunho serve '
        'para calibrar, nunca para publicar.', coalesce(v_status::text, 'inexistente')
        USING ERRCODE = '23514';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER goal_projections_publishable_gate
  BEFORE INSERT OR UPDATE ON planning.goal_projections
  FOR EACH ROW EXECUTE FUNCTION planning.assert_projection_is_publishable();

-- -----------------------------------------------------------------------------
-- Privilégios: a 28 já concedeu DML por DEFAULT PRIVILEGES em market e planning; o REVOKE
-- derivado do catálogo já rodou e não alcança tabela nova. Aqui o DML fica: rascunho precisa
-- ser editável. O que protege o aprovado é o trigger C48d, não a falta de privilégio — a
-- diferença importa porque o motor precisa poder encerrar vigência.
-- -----------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE
  ON market.assumption_sets, market.class_assumptions, market.class_correlations
  TO plexo_app, plexo_service;

-- =============================================================================
-- PLEXO_BASE v1 — ponto de partida, em RASCUNHO de propósito
--
-- Estes números são um começo defensável, não uma verdade. Nascem `draft` porque nenhum
-- deles passou por compliance, e o C48c garante que rascunho não vira número na tela do
-- cliente. Calibrá-los é decisão humana com nome e data — que é exatamente o que a coluna
-- `approved_by` existe para registrar.
-- =============================================================================
INSERT INTO market.assumption_sets
  (id, code, version, horizonte_anos, metodologia, compliance_status, notes)
VALUES ('48480000-0000-4000-8000-000000000001', 'PLEXO_BASE', 1, 30,
        'Retornos REAIS de longo prazo (acima do IPCA), em fração ao ano. Renda fixa a '
        'partir da mediana do Focus para Selic e IPCA de 12 meses combinada com a estrutura '
        'a termo das NTN-B; renda variável a partir de série histórica de 20 anos do '
        'Ibovespa e do MSCI World em BRL, deflacionada pelo IPCA. Volatilidades e '
        'correlações da mesma janela de 20 anos, dados mensais. LIMITAÇÃO DECLARADA: a '
        'simulação assume log-retornos normais, o que SUBESTIMA a cauda — crise real é '
        'pior que o p5 aqui. Premissa explícita e revisável vale mais que precisão '
        'silenciosa; recalibrar a cada 12 meses ou quando a Selic longa se mover mais de '
        '200 bps.',
        'draft',
        'Ponto de partida da F17. Nenhum número passou por compliance — o C48c impede que '
        'virem tela enquanto for assim.');

INSERT INTO market.class_assumptions
  (assumption_set_id, asset_class_code, retorno_real_aa, volatilidade_aa, fonte)
VALUES
  ('48480000-0000-4000-8000-000000000001', 'caixa',     0.0050, 0.0050, 'Selic − IPCA, líquido de IR e taxas'),
  ('48480000-0000-4000-8000-000000000001', 'selic',     0.0450, 0.0100, 'Focus Selic − Focus IPCA'),
  ('48480000-0000-4000-8000-000000000001', 'ipca',      0.0550, 0.0800, 'ETTJ NTN-B, vértice médio'),
  ('48480000-0000-4000-8000-000000000001', 'acoes_br',  0.0700, 0.2200, 'Ibovespa 20a real'),
  ('48480000-0000-4000-8000-000000000001', 'acoes_int', 0.0600, 0.2000, 'MSCI World em BRL, 20a real');

-- 5 classes ⇒ 10 pares. O C48b confere a conta na hora da aprovação; acrescentar uma sexta
-- classe obriga a declarar mais cinco correlações, e essa fricção é intencional.
INSERT INTO market.class_correlations (assumption_set_id, classe_a, classe_b, correlacao)
VALUES
  ('48480000-0000-4000-8000-000000000001', 'acoes_br',  'acoes_int',  0.550),
  ('48480000-0000-4000-8000-000000000001', 'acoes_br',  'caixa',     -0.050),
  ('48480000-0000-4000-8000-000000000001', 'acoes_br',  'ipca',       0.250),
  ('48480000-0000-4000-8000-000000000001', 'acoes_br',  'selic',     -0.150),
  ('48480000-0000-4000-8000-000000000001', 'acoes_int', 'caixa',     -0.100),
  ('48480000-0000-4000-8000-000000000001', 'acoes_int', 'ipca',       0.100),
  ('48480000-0000-4000-8000-000000000001', 'acoes_int', 'selic',     -0.200),
  ('48480000-0000-4000-8000-000000000001', 'caixa',     'ipca',       0.100),
  ('48480000-0000-4000-8000-000000000001', 'caixa',     'selic',      0.900),
  ('48480000-0000-4000-8000-000000000001', 'ipca',      'selic',      0.200);

-- =============================================================================
-- SIMULACAO_METAS v2 — as três alocações candidatas e a regra de elegibilidade de risco
--
-- v2, e não v1: o `seeds/dev.sql` já criava um SIMULACAO_METAS v1 placeholder desde
-- 2026-08-23 com confiança, materialidade, caminhos e semente. Ele fica na história com
-- vigência encerrada, e as chaves que ele nomeou (`nivel_confianca_padrao`,
-- `limiar_materialidade_prob`, `n_caminhos`, `semente`) são MANTIDAS: renomear premissa que
-- já foi escrita em documento é criar duas verdades para a mesma coisa.
--
-- `limiar_materialidade_prob` fica nos 0,10 que o placeholder declarou, não nos 0,05 que
-- seriam mais permissivos. Afrouxar limiar de risco de passagem, sem alguém decidindo, é
-- exatamente o tipo de mudança que precisa de nome e data.
--
-- As alocações vêm de POLÍTICA, não de otimização: o Builder de carteira não existe, e
-- inventá-lo aqui seria construir o motor errado por conveniência. Três vetores de peso
-- fixos respondem a pergunta desta fase — "risco compra probabilidade neste prazo?" — sem
-- pretender responder "qual é a carteira ótima", que é outra fase e outra aprovação.
--
-- A REGRA DE ELEGIBILIDADE (§4 do documento): risco só é elegível quando aumenta
-- MATERIALMENTE a probabilidade de sucesso E não piora o cenário ruim. As duas condições,
-- não uma: uma alocação que sobe 1 ponto de probabilidade e derruba o p5 em 20% não é uma
-- troca — é uma piora com aparência de escolha.
-- =============================================================================
UPDATE engine.policy_versions SET effective_to = now()
 WHERE code = 'SIMULACAO_METAS' AND effective_to IS NULL;

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('SIMULACAO_METAS', 2,
  jsonb_build_object(
    'nota_f17', 'Nasce draft: as alocações candidatas e o limiar de elegibilidade são '
                'opinião, e opinião publicada exige aprovação de compliance (C40d/C48c).',
    'conjunto_de_premissas', 'PLEXO_BASE',
    -- vocabulário herdado do placeholder de 2026-08-23, de propósito
    'n_caminhos', 10000,
    'semente', 20260823,
    'nivel_confianca_padrao', 0.90,
    'alocacoes', jsonb_build_object(
      'conservadora', jsonb_build_object('caixa', 0.10, 'selic', 0.70, 'ipca', 0.20),
      'balanceada',   jsonb_build_object('caixa', 0.05, 'selic', 0.45, 'ipca', 0.30,
                                         'acoes_br', 0.12, 'acoes_int', 0.08),
      'arrojada',     jsonb_build_object('caixa', 0.05, 'selic', 0.20, 'ipca', 0.25,
                                         'acoes_br', 0.30, 'acoes_int', 0.20)),
    'elegibilidade_de_risco', jsonb_build_object(
      -- Quanto a probabilidade precisa subir para o risco valer a pena. Os 10 pontos vêm do
      -- placeholder de 2026-08-23; abaixo disso a diferença está dentro do erro da própria
      -- premissa, e premissa arbitrada não sustenta distinção fina.
      'limiar_materialidade_prob', 0.10,
      -- E quanto o cenário ruim pode piorar em troca. Zero: nesta versão, nenhuma piora do
      -- p5 é aceitável. É conservador de propósito e é uma decisão de compliance, não de
      -- engenharia — está aqui para ser discutida, e por isso é config e não código.
      'piora_maxima_do_p5', 0.00)),
  'draft');

-- A soma dos pesos conferida aqui, agora, e não na primeira execução do motor: erro de
-- digitação em vetor de peso é silencioso e enviesa toda simulação que dele depender.
DO $$
DECLARE r record; soma numeric;
BEGIN
  FOR r IN
    SELECT a.key AS nome, a.value AS pesos
      FROM engine.policy_versions p,
           LATERAL jsonb_each(p.payload -> 'alocacoes') a
     WHERE p.code = 'SIMULACAO_METAS' AND p.version = 2
  LOOP
    SELECT sum(v::numeric) INTO soma FROM jsonb_each_text(r.pesos) AS e(k, v);
    IF abs(soma - 1) > 0.0001 THEN
      RAISE EXCEPTION 'alocação "%" soma % — os pesos precisam somar 1', r.nome, soma;
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(r.pesos) k
                WHERE k NOT IN (SELECT asset_class_code FROM market.class_assumptions
                                 WHERE assumption_set_id = '48480000-0000-4000-8000-000000000001')) THEN
      RAISE EXCEPTION 'alocação "%" usa classe sem premissa em PLEXO_BASE v1', r.nome;
    END IF;
  END LOOP;
END $$;

COMMIT;
