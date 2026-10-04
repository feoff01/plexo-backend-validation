-- =============================================================================
-- SYNAPTA · 24_income.sql
-- Renda destrinchada. Estende o schema `budget` (08).
--
-- O PROBLEMA
--   identity.user_profiles.monthly_income_brl é UM número. Duas pessoas com
--   R$ 20 mil/mês têm situações opostas se uma é CLT com 100% fixo e a outra
--   é comissionada com 70% variável. Aporte recorrente, capacidade de dívida,
--   tamanho da reserva e horizonte mudam TODOS — e o banco não sabia diferenciar.
--
-- A PERGUNTA QUE ESTE ARQUIVO RESPONDE
--   "Quanto desta renda dá para comprometer?" — não é a renda média,
--   é fixo + o piso observado do variável. Um mês bom não é uma promessa.
--
-- REGRAS INVIOLÁVEIS
--   · stability='fixo' ⇒ variable_share = 0 (CHECK).
--   · stability='variavel' ⇒ variable_share > 0 (CHECK).
--   · committable_brl ≤ fixed_brl + variable_p10_brl (CHECK) — o compromisso
--     nunca é dimensionado sobre o bônus que pode não vir.
--   · 13º e férias são FONTES próprias com frequency='anual', não um
--     multiplicador escondido no salário. O que é eventual aparece como eventual.
--
-- Depende de: 00_core, 01_identity, 02_engine (runs), 08_budget, 23_household,
--             22_assertions.
-- =============================================================================

BEGIN;

CREATE TYPE budget.income_kind AS ENUM (
  'salario_clt', 'pro_labore', 'servidor', 'autonomo', 'comissao',
  'bonus_ppr', 'decimo_terceiro', 'ferias', 'dividendos_empresa',
  'aluguel', 'aposentadoria_inss', 'previdencia_privada', 'pensao',
  'beneficio_governo', 'rendimento_investimentos', 'freelance',
  'royalties', 'outro'
);

CREATE TYPE budget.income_stability AS ENUM (
  'fixo',      -- entra todo mês, mesmo valor
  'variavel',  -- entra todo mês, valor incerto (comissão)
  'sazonal',   -- entra em meses previsíveis (13º, safra)
  'eventual'   -- pode não entrar (bônus, freela)
);

CREATE TYPE budget.income_frequency AS ENUM (
  'mensal', 'quinzenal', 'semanal', 'bimestral',
  'trimestral', 'semestral', 'anual', 'irregular'
);

CREATE TYPE budget.contract_kind AS ENUM (
  'clt', 'pj', 'servidor', 'autonomo', 'socio', 'aposentado',
  'sem_vinculo', 'outro'
);

-- -----------------------------------------------------------------------------
-- Fontes de renda — uma linha por origem de dinheiro, por pessoa
-- -----------------------------------------------------------------------------
CREATE TABLE budget.income_sources (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  scope_id           uuid NOT NULL REFERENCES identity.scopes(id),
  member_id          uuid REFERENCES household.members(id),  -- NULL = renda do escopo
  kind               budget.income_kind NOT NULL,
  stability          budget.income_stability NOT NULL,
  frequency          budget.income_frequency NOT NULL DEFAULT 'mensal',

  gross_amount_brl   core.money_brl NOT NULL CHECK (gross_amount_brl >= 0),
  net_amount_brl     core.money_brl CHECK (net_amount_brl >= 0),
  -- fração do BRUTO desta fonte que é variável (salário + comissão na mesma linha)
  variable_share     core.weight NOT NULL DEFAULT 0,

  -- [validação PG real] frações exatas (divisão numeric), não constantes
  -- truncadas: 0.083333 × 120 mil dava 9.999,96/mês — e é número que o cliente
  -- lê. O arredondamento a centavos acontece uma única vez, no domain money_brl.
  -- 'semanal' = 4,345 semanas/mês é convenção (365 ÷ 7 ÷ 12), mantida.
  monthly_gross_brl  core.money_brl GENERATED ALWAYS AS (
    gross_amount_brl * CASE frequency
      WHEN 'mensal'     THEN 1.0
      WHEN 'quinzenal'  THEN 2.0
      WHEN 'semanal'    THEN 4.345
      WHEN 'bimestral'  THEN 1.0 / 2
      WHEN 'trimestral' THEN 1.0 / 3
      WHEN 'semestral'  THEN 1.0 / 6
      WHEN 'anual'      THEN 1.0 / 12
      ELSE 0.0
    END
  ) STORED,

  is_taxable         boolean NOT NULL DEFAULT true,
  contract_kind      budget.contract_kind,
  employer_name      text,
  category_code      core.slug REFERENCES budget.categories(code),

  started_on         date,
  expected_end_on    date,                  -- contrato com prazo, benefício que cessa

  confidence         core.confidence NOT NULL DEFAULT 0.6,
  assertion_id       uuid REFERENCES context.assertions(id),
  origin             text NOT NULL DEFAULT 'usuario'
                     CHECK (origin IN ('usuario','onboarding','open_finance',
                                       'import','confirmacao_contexto','estimado')),
  is_active          boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  ended_at           timestamptz,

  CONSTRAINT fixed_has_no_variable_part CHECK (
    stability <> 'fixo' OR variable_share = 0
  ),
  CONSTRAINT variable_has_variable_part CHECK (
    stability <> 'variavel' OR variable_share > 0
  ),
  CONSTRAINT net_not_above_gross CHECK (
    net_amount_brl IS NULL OR net_amount_brl <= gross_amount_brl
  ),
  CONSTRAINT income_period_ordered CHECK (
    expected_end_on IS NULL OR started_on IS NULL OR expected_end_on >= started_on
  )
);
CREATE INDEX income_sources_scope_idx ON budget.income_sources (scope_id)
  WHERE is_active AND ended_at IS NULL;
CREATE INDEX income_sources_member_idx ON budget.income_sources (member_id)
  WHERE member_id IS NOT NULL;

CREATE TRIGGER income_sources_touch BEFORE UPDATE ON budget.income_sources
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER income_sources_assertion_gate
  BEFORE INSERT OR UPDATE ON budget.income_sources
  FOR EACH ROW EXECUTE FUNCTION context.assert_assertion_confirmed('assertion_id');

COMMENT ON TABLE budget.income_sources IS
  'Substitui identity.user_profiles.monthly_income_brl como fonte de verdade. '
  'O número agregado continua existindo para o onboarding rápido; quando há '
  'fontes cadastradas, elas mandam.';

COMMENT ON COLUMN budget.income_sources.variable_share IS
  'Fração variável DENTRO da própria fonte — o vendedor com base fixa de R$ 5 mil '
  'e comissão média de R$ 15 mil é UMA linha com variable_share = 0,75, não duas.';

-- Membro tem que ser do mesmo escopo. Sem isso, "renda da casa" some.
CREATE OR REPLACE FUNCTION budget.assert_member_same_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_scope uuid;
BEGIN
  IF NEW.member_id IS NULL THEN RETURN NEW; END IF;
  SELECT scope_id INTO v_scope FROM household.members WHERE id = NEW.member_id;
  IF v_scope IS DISTINCT FROM NEW.scope_id THEN
    RAISE EXCEPTION 'Membro % não pertence ao escopo %', NEW.member_id, NEW.scope_id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER income_sources_member_scope
  BEFORE INSERT OR UPDATE ON budget.income_sources
  FOR EACH ROW EXECUTE FUNCTION budget.assert_member_same_scope();

-- -----------------------------------------------------------------------------
-- Resumo mensal de renda — o número que a Fundação e o Builder consomem
-- -----------------------------------------------------------------------------
CREATE TABLE budget.income_summaries (
  scope_id           uuid NOT NULL REFERENCES identity.scopes(id),
  month              date NOT NULL,
  fixed_brl          core.money_brl NOT NULL DEFAULT 0,
  variable_brl       core.money_brl NOT NULL DEFAULT 0,
  total_brl          core.money_brl GENERATED ALWAYS AS (fixed_brl + variable_brl) STORED,
  variable_share     numeric(6,4),          -- variavel / total; NULL quando total = 0
  variable_p10_brl   core.money_brl NOT NULL DEFAULT 0,  -- piso observado do variável
  months_observed    smallint NOT NULL DEFAULT 0,
  -- O NÚMERO: quanto dá para comprometer sem depender de mês bom.
  committable_brl    core.money_brl NOT NULL DEFAULT 0,
  top_source_share   numeric(6,4),          -- concentração de renda numa fonte só
  run_id             uuid REFERENCES engine.runs(id),
  computed_at        timestamptz NOT NULL DEFAULT now(),

  PRIMARY KEY (scope_id, month),
  CONSTRAINT income_month_is_month_start CHECK (month = date_trunc('month', month)::date),
  CONSTRAINT amounts_non_negative CHECK (
    fixed_brl >= 0 AND variable_brl >= 0 AND variable_p10_brl >= 0 AND committable_brl >= 0
  ),
  -- NOTA: não existe CHECK p10 <= variable_brl de propósito. O p10 é o piso
  -- HISTÓRICO; o mês corrente pode legitimamente vir abaixo dele — e é
  -- justamente esse mês que mais precisa ser gravado.
  -- A REGRA: não se compromete o que só aparece nos bons meses.
  CONSTRAINT committable_within_floor CHECK (
    committable_brl <= fixed_brl + variable_p10_brl
  ),
  CONSTRAINT shares_are_fractions CHECK (
    (variable_share IS NULL OR variable_share BETWEEN 0 AND 1)
    AND (top_source_share IS NULL OR top_source_share BETWEEN 0 AND 1)
  )
);

COMMENT ON CONSTRAINT committable_within_floor ON budget.income_summaries IS
  'A diferença entre um planejador e uma planilha otimista. O aporte recorrente, '
  'a parcela e o teto de dívida saem de committable_brl — nunca de total_brl.';

COMMENT ON COLUMN budget.income_summaries.top_source_share IS
  'Concentração de renda. 100% num único empregador é risco de carteira tanto '
  'quanto 40% num único emissor — e ninguém mede.';

-- -----------------------------------------------------------------------------
-- View — a quebra que a tela e os agentes leem, direto das fontes ativas
-- -----------------------------------------------------------------------------
CREATE VIEW budget.v_income_breakdown WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
WITH base AS (
  SELECT s.scope_id,
         s.id,
         s.member_id,
         s.stability,
         s.monthly_gross_brl,
         (s.monthly_gross_brl * (1 - s.variable_share))::numeric AS fixed_part,
         (s.monthly_gross_brl * s.variable_share)::numeric       AS variable_part
  FROM budget.income_sources s
  WHERE s.is_active AND s.ended_at IS NULL
)
SELECT scope_id,
       count(*)                                                        AS sources_count,
       count(DISTINCT member_id) FILTER (WHERE member_id IS NOT NULL)  AS earners_count,
       sum(monthly_gross_brl)::core.money_brl                          AS monthly_gross_brl,
       sum(CASE WHEN stability IN ('fixo','sazonal')
                THEN fixed_part ELSE 0 END)::core.money_brl            AS fixed_brl,
       sum(CASE WHEN stability IN ('fixo','sazonal')
                THEN variable_part ELSE monthly_gross_brl END)::core.money_brl
                                                                       AS variable_brl,
       CASE WHEN sum(monthly_gross_brl) > 0
            THEN round(sum(CASE WHEN stability IN ('fixo','sazonal')
                               THEN variable_part ELSE monthly_gross_brl END)
                       / sum(monthly_gross_brl), 4)
       END                                                             AS variable_share,
       CASE WHEN sum(monthly_gross_brl) > 0
            THEN round(max(monthly_gross_brl) / sum(monthly_gross_brl), 4)
       END                                                             AS top_source_share
FROM base
GROUP BY scope_id;

COMMENT ON VIEW budget.v_income_breakdown IS
  'Leitura ao vivo das fontes ativas. budget.income_summaries é a versão '
  'point-in-time, gravada por run — é ela que entra em decisions.inputs (27).';

-- -----------------------------------------------------------------------------
-- RLS
-- -----------------------------------------------------------------------------
ALTER TABLE budget.income_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget.income_sources FORCE  ROW LEVEL SECURITY;
CREATE POLICY income_sources_isolation ON budget.income_sources FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

ALTER TABLE budget.income_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget.income_summaries FORCE  ROW LEVEL SECURITY;
CREATE POLICY income_summaries_isolation ON budget.income_summaries FOR ALL
  USING (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true))
  WITH CHECK (core.is_service()
         OR scope_id::text = current_setting('app.scope_id', true));

-- -----------------------------------------------------------------------------
-- Policy — o deságio do variável. Nasce draft; muda sem deploy.
-- -----------------------------------------------------------------------------
INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
VALUES ('INCOME_HAIRCUT', 1, '{
  "meses_minimos_para_p10": 6,
  "haircut_variavel_sem_historico": 0.0,
  "haircut_por_estabilidade": {
    "fixo": 0.0,
    "variavel": 0.5,
    "sazonal": 0.3,
    "eventual": 1.0
  },
  "alerta_top_source_share": 0.9
}'::jsonb, 'draft');

COMMIT;
