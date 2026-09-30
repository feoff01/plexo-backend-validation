-- =============================================================================
-- PLEXO · 54_raio_x_da_carteira.sql — a taxonomia ganha produtor, e o banco cobra [F19]
--
-- O QUE ESTA MIGRATION FECHA
--
-- `diagnostics.finding_types` tem 21 tipos semeados desde a migration 15. `findings`,
-- `finding_observations`, `actions` com os cinco blocos obrigatórios, `v_action_queue`,
-- `coverage_reports`, `gate_reveals`, `v_issuer_concentration` consolidando conglomerado:
-- tudo desenhado desde a 06/15. Em 2026-08-30, `diagnostics.findings` tinha ZERO linhas —
-- nenhuma linha de Python jamais escreveu nela. `engine.run_kind` já continha 'raiox' e
-- 'coverage' desde a 02, esperando.
--
-- É o terceiro achado do mesmo tipo nesta base. `diagnostics.foundation_status` (F16) era
-- uma regra imposta por CHECK, por trigger e por teste de sabotagem em três arquivos, que
-- nunca disparou por falta de produtor. `plano` no arquétipo era campo que ninguém escrevia.
-- A conclusão da F16 vale: "um gate sem quem o alimente não é gate: é intenção".
--
-- DUAS REGRAS NOVAS, E POR QUE ELAS SÃO ESTRUTURA E NÃO CONVENÇÃO
--
-- (1) `implemented_at` deixa de ser documentação e vira CONDIÇÃO DE EXISTÊNCIA. A coluna
--     está na 06 desde sempre, inteiramente NULL. Agora, finding de tipo sem `implemented_at`
--     é recusado. O efeito é que o catálogo passa a dizer a verdade sobre si mesmo: quem
--     ler `finding_types` sabe, por consulta, o que roda e o que é intenção. E ninguém
--     consegue fazer um tipo não implementado aparecer na tela de um cliente por acidente —
--     um INSERT de suporte, um backfill, um teste que virou script.
--
-- (2) Tipo `is_quantifiable` exige `quantification` não vazia. É a mesma regra do
--     `action_five_blocks` da 06 ("card sem quantificação é ruído"), um degrau antes. A
--     constraint existia na AÇÃO e não no FINDING — mas é o finding que carrega
--     `impact_brl_year` e alimenta `priority_score`. Um finding quantificável sem
--     `quantification` produz ou uma ação que precisa inventar o bloco de quantificação, ou
--     um alerta que diz "concentração alta" sem dizer quanto. As duas saídas são ruins, e a
--     segunda é a que chega ao cliente.
--
-- O TIPO NOVO: `risco.exposicao_acima_do_fgc`
--
-- A taxonomia foi desenhada para crescer por INSERT ("ir de 20 para 45/90 é INSERT", 06), e
-- este é o primeiro acréscimo. Ele é separado de `risco.concentracao_emissor` de propósito:
-- são duas leituras diferentes do mesmo emissor. "40% do seu patrimônio está num banco" é
-- risco de carteira, e a resposta é diversificar. "R$ 270 mil passam do teto de R$ 250 mil
-- garantidos" é risco de crédito, tem número exato, e a resposta é mover o excedente. Num
-- cartão só, a segunda desaparece atrás da primeira.
--
-- Atrito 1 (o menor da tabela): mover o excedente para outro emissor não exige mudar de
-- estratégia, vender nada com prejuízo nem pagar imposto — é a coisa mais fácil de executar
-- em toda a taxonomia, e o `priority_score` divide pelo atrito justamente para que o barato
-- e certo suba na fila.
--
-- OS LIMIARES: `RAIOX_LIMIARES`, e por que nascem em rascunho
--
-- A diferença entre "concentração acima de 20%" e "acima de 30%" é a diferença entre alertar
-- um cliente e não alertar. Isso é opinião com consequência, e opinião com consequência tem
-- dono e data nesta base desde a 02. Nasce `draft`: enquanto não houver parecer, o motor roda
-- em run INTERNO e nada disso vira número na tela — é o mesmo gate que segurou `PLEXO_BASE`
-- na F17, e ele está funcionando como projetado.
--
-- Depende de: 06_diagnostics, 15_taxonomia.
-- Testes: tests/test_regras_invioláveis_raiox.sql (T121–T126).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- (a) O tipo novo — o FGC como cartão próprio
-- -----------------------------------------------------------------------------
INSERT INTO diagnostics.finding_types
  (code, family, display_name, default_severity, min_plan, is_quantifiable, execution_friction, notes)
VALUES ('risco.exposicao_acima_do_fgc', 'risco', 'Exposição acima do limite do FGC',
        'alta', 'free', true, 1,
        '[F19] Soma dos instrumentos GARANTIDOS (CDB, LCI/LCA, poupança) por instituição, '
        'consolidando conglomerado por parent_issuer_id, contra o teto por CPF/instituição. '
        'A cobertura é do INSTRUMENTO e não do emissor: ação de banco associado não entra.')
ON CONFLICT (code) DO NOTHING;

-- -----------------------------------------------------------------------------
-- (b) Quem tem produtor a partir de agora — `app/engine/raiox.py`
-- -----------------------------------------------------------------------------
UPDATE diagnostics.finding_types
   SET implemented_at = current_date
 WHERE code IN ('risco.concentracao_emissor',
                'risco.exposicao_acima_do_fgc',
                'risco.concentracao_classe',
                'alocacao.caixa_parado_excessivo',
                'liquidez.resgate_longo_excessivo',
                'custo.taxa_fundo_alta',
                'alocacao.sem_exposicao_internacional');

COMMENT ON COLUMN diagnostics.finding_types.implemented_at IS
  '[F19] Data em que o produtor deste tipo entrou no ar. NULL significa "está na taxonomia, '
  'mas nada o calcula" — e o trigger `findings_exigem_produtor` RECUSA finding desse tipo. '
  'Deixou de ser anotação e virou condição de existência porque a taxonomia inteira passou '
  'da migration 15 até a F19 sem uma única linha produzida, e nada no banco dizia isso.';

-- -----------------------------------------------------------------------------
-- (c) Os dois gates
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION diagnostics.assert_finding_publicavel() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE t record;
BEGIN
  SELECT implemented_at, is_quantifiable, display_name
    INTO t
    FROM diagnostics.finding_types
   WHERE code = NEW.finding_type_code;

  IF t.implemented_at IS NULL THEN
    RAISE EXCEPTION
      'Tipo de finding "%" não tem produtor declarado (implemented_at IS NULL)',
      NEW.finding_type_code
      USING ERRCODE = 'check_violation',
            HINT = 'Escreva o produtor em app/engine/raiox.py e declare implemented_at numa migration.';
  END IF;

  -- `quantification = '{}'` é o default da coluna: o caminho de quem simplesmente não
  -- preencheu. É esse que o gate pega.
  IF t.is_quantifiable AND NEW.quantification = '{}'::jsonb THEN
    RAISE EXCEPTION
      'Finding "%" é quantificável e veio sem quantificação', NEW.finding_type_code
      USING ERRCODE = 'check_violation',
            HINT = 'Card sem quantificação é ruído: grave em quantification o que foi medido e contra qual limiar.';
  END IF;

  RETURN NEW;
END $$;

COMMENT ON FUNCTION diagnostics.assert_finding_publicavel() IS
  '[F19] Duas condições para um finding existir: o tipo tem produtor declarado, e o que se '
  'diz quantificável traz o número. A segunda é o `action_five_blocks` da 06 um degrau '
  'antes — é o finding, não a ação, que carrega impact_brl_year e priority_score.';

CREATE TRIGGER findings_exigem_produtor
  BEFORE INSERT OR UPDATE ON diagnostics.findings
  FOR EACH ROW EXECUTE FUNCTION diagnostics.assert_finding_publicavel();

-- -----------------------------------------------------------------------------
-- (d) Os limiares — config-first, zero número no motor
-- -----------------------------------------------------------------------------
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('RAIOX_LIMIARES', 1, '{
  "concentracao_emissor_max": 0.20,
  "concentracao_classe_max": 0.50,
  "teto_fgc_brl": 250000,
  "caixa_ocioso_multiplo_da_reserva": 1.0,
  "iliquido_dias_min": 30,
  "iliquido_share_max": 0.10,
  "taxa_fundo_folga_sobre_referencia": 0.005,
  "impacto_padrao_confianca": 0.80,
  "_nota": "PONTO DE PARTIDA, não verdade. Cada limiar decide se um cliente é alertado ou não: 20% de concentração por emissor segue a prática de private banking, o teto do FGC é o valor legal por CPF e instituição, e a folga de 0,5 p.p. sobre a referência de classe existe para não alertar por diferença de arredondamento. Calibrar e aprovar com compliance antes de virar tela."
}'::jsonb, 'draft')
ON CONFLICT (code, version) DO NOTHING;

COMMIT;
