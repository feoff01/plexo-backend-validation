-- =============================================================================
-- seeds/persona.sql — cliente de DEMONSTRAÇÃO com patrimônio completo. Idempotente.
--   python -m app.cli seed persona
--
-- Por que existe: o escopo de `seed dev` tem renda e orçamento agregados e MAIS NADA — zero
-- posições, zero imóvel, zero objetivo, zero veto. `estate.v_net_worth` devolve investível 0 e
-- líquido −15.000 (só a dívida do cartão): o Assessor conversa com alguém tecnicamente falido.
-- Esta persona é o cliente que o produto promete atender, para dar o que medir aos evals.
--
-- ESCOPO PRÓPRIO (`0fe0a000-…`), nunca o de dev (`0de0a000-…`): nenhum teste, golden ou eval
-- existente muda de valor por causa deste arquivo.
--
-- NÃO é migration e NÃO é dado de cliente real. Sem BEGIN/COMMIT: a CLI executa dentro da
-- sessão de serviço (uma transação — ou entra inteiro, ou nada).
--
-- Idempotência: total no MESMO dia. Rodado noutro dia, as tabelas de SNAPSHOT datado
-- (`holdings_snapshots`, `portfolio_snapshots`, `estate.valuations`) ganham uma linha nova com
-- `as_of_date = current_date` e os mesmos valores — é o comportamento correto de série append-only,
-- e as views `v_latest_holdings`/`v_current_valuations` continuam devolvendo os mesmos números.
--
-- A ORDEM ABAIXO É OBRIGATÓRIA, imposta por constraints do banco:
--   membership antes do titular  (household.members_titular_gate)
--   dívida antes do imóvel       (estate.encumbered_needs_debt)
--   renda antes do imóvel alugado(estate.income_asset_needs_source)
--   veto bloqueante só com confirmação do próprio usuário (preferences C26b)
-- =============================================================================

-- ---------------------------------------------------------------- identidade
INSERT INTO identity.users (id, email, full_name, status, birth_date)
VALUES ('0fe0a000-0000-4000-8000-000000000001', 'marina@teste.local', 'Marina Duarte (persona)',
        'active', (date_trunc('year', current_date) - interval '42 years')::date)
ON CONFLICT (email) WHERE deleted_at IS NULL DO NOTHING;

INSERT INTO identity.scopes (id, kind, display_name, owner_user_id)
VALUES ('0fe0a000-0000-4000-8000-000000000002', 'personal', 'Pessoal Marina',
        '0fe0a000-0000-4000-8000-000000000001')
ON CONFLICT (id) DO NOTHING;

INSERT INTO identity.scope_members (scope_id, user_id, role, accepted_at)
SELECT '0fe0a000-0000-4000-8000-000000000002', '0fe0a000-0000-4000-8000-000000000001', 'owner', now()
WHERE NOT EXISTS (SELECT 1 FROM identity.scope_members
                  WHERE scope_id = '0fe0a000-0000-4000-8000-000000000002'
                    AND user_id  = '0fe0a000-0000-4000-8000-000000000001');

-- Plano pago. Sem esta linha `plano_do_escopo` cai no fallback 'free' (5 perguntas/mês ao
-- Assessor). `essential` dá 50/mês e mantém o paywall testável — não é ilimitado por acidente.
INSERT INTO billing.subscriptions (id, scope_id, payer_user_id, plan_code, interval, status,
                                   current_period_start, current_period_end)
VALUES ('0fe0a000-0000-4000-8000-000000000003', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000001', 'essential', 'monthly', 'active',
        date_trunc('month', now()), date_trunc('month', now()) + interval '1 month')
ON CONFLICT (id) DO NOTHING;

-- Suitability vigente: sem ela nenhuma decisão de carteira-alvo pode ser gravada (C27).
INSERT INTO identity.suitability_assessments (id, user_id, scope_id, questionnaire_version,
                                              answers, result, score, valid_until)
VALUES ('0fe0a000-0000-4000-8000-000000000004', '0fe0a000-0000-4000-8000-000000000001',
        '0fe0a000-0000-4000-8000-000000000002', 'suit-v1',
        '{"horizonte_anos": 18, "reacao_queda": "mantenho", "experiencia": "fundos_e_acoes",
          "objetivo_principal": "aposentadoria"}'::jsonb,
        'moderado', 62.00, (current_date + interval '2 years')::date)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------- núcleo familiar
-- O titular precisa de membership ativa (trigger members_titular_gate) — por isso vem depois.
INSERT INTO household.members (id, scope_id, user_id, relation, display_name, birth_year,
                               dependency, contributes_income, origin)
VALUES ('0fe0a000-0000-4000-8000-000000000011', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000001', 'titular', 'Marina',
        (extract(year from current_date) - 42)::smallint, 'nao', true, 'onboarding'),
       ('0fe0a000-0000-4000-8000-000000000012', '0fe0a000-0000-4000-8000-000000000002',
        NULL, 'conjuge', 'Paulo', (extract(year from current_date) - 44)::smallint,
        'parcial', true, 'onboarding'),
       ('0fe0a000-0000-4000-8000-000000000013', '0fe0a000-0000-4000-8000-000000000002',
        NULL, 'filho', 'Beatriz', (extract(year from current_date) - 14)::smallint,
        'total', false, 'onboarding'),
       ('0fe0a000-0000-4000-8000-000000000014', '0fe0a000-0000-4000-8000-000000000002',
        NULL, 'filho', 'Tomás', (extract(year from current_date) - 8)::smallint,
        'total', false, 'onboarding')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------- dívidas (antes dos imóveis)
INSERT INTO budget.debts (id, scope_id, kind, description, outstanding_brl, annual_rate,
                          monthly_payment_brl, remaining_installments, is_expensive, opened_on)
VALUES ('0fe0a000-0000-4000-8000-000000000021', '0fe0a000-0000-4000-8000-000000000002',
        'financiamento_imovel', 'Financiamento do apartamento (SAC)', 320000.00, 0.098,
        3400.00, 168, false, (current_date - interval '6 years')::date),
       ('0fe0a000-0000-4000-8000-000000000022', '0fe0a000-0000-4000-8000-000000000002',
        'cartao_rotativo', 'Cartão de crédito no rotativo', 9500.00, 0.85,
        1200.00, NULL, true, (current_date - interval '3 months')::date)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------- renda (antes do imóvel alugado)
-- Salário e comissão são LINHAS SEPARADAS (não uma linha com variable_share): estabilidades
-- diferentes, e é o que faz o piso p10 significar alguma coisa. 13º é fonte anual própria.
INSERT INTO budget.income_sources (id, scope_id, member_id, kind, stability, frequency,
                                   gross_amount_brl, net_amount_brl, variable_share,
                                   contract_kind, employer_name, started_on, confidence, origin)
VALUES ('0fe0a000-0000-4000-8000-000000000031', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000011', 'salario_clt', 'fixo', 'mensal',
        18000.00, 13200.00, 0, 'clt', 'Indústria Meridiano', (current_date - interval '7 years')::date,
        0.95, 'onboarding'),
       ('0fe0a000-0000-4000-8000-000000000032', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000011', 'comissao', 'variavel', 'mensal',
        7000.00, 5100.00, 1.0, 'clt', 'Indústria Meridiano', (current_date - interval '7 years')::date,
        0.60, 'onboarding'),
       ('0fe0a000-0000-4000-8000-000000000033', '0fe0a000-0000-4000-8000-000000000002',
        NULL, 'aluguel', 'fixo', 'mensal', 2800.00, 2520.00, 0, NULL, NULL,
        (current_date - interval '4 years')::date, 0.85, 'onboarding'),
       ('0fe0a000-0000-4000-8000-000000000034', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000011', 'decimo_terceiro', 'sazonal', 'anual',
        18000.00, 13200.00, 0, 'clt', 'Indústria Meridiano', NULL, 0.90, 'onboarding')
ON CONFLICT (id) DO NOTHING;

-- Agregado mensal. A regra do banco: committable <= fixed + variable_p10 (não se compromete o
-- que só aparece nos bons meses). fixo = 18.000 + 2.800; piso da comissão observado = 2.500.
INSERT INTO budget.income_summaries (scope_id, month, fixed_brl, variable_brl, variable_p10_brl,
                                     committable_brl, variable_share, months_observed, top_source_share)
VALUES ('0fe0a000-0000-4000-8000-000000000002', date_trunc('month', current_date)::date,
        20800.00, 7000.00, 2500.00, 20000.00, 0.2518, 12, 0.6475)
ON CONFLICT (scope_id, month) DO NOTHING;

-- ---------------------------------------------------------------- orçamento (12 meses fechados)
INSERT INTO budget.monthly_summaries (scope_id, month, income_brl, expense_brl,
                                      essential_expense_brl, savings_rate)
SELECT '0fe0a000-0000-4000-8000-000000000002',
       (date_trunc('month', current_date) - (m || ' month')::interval)::date,
       27800.00, 12400.00, 8200.00, 0.5540
FROM generate_series(1, 12) m
ON CONFLICT (scope_id, month) DO NOTHING;

INSERT INTO budget.reserve_settings (scope_id, target_months)
VALUES ('0fe0a000-0000-4000-8000-000000000002', 6.0)
ON CONFLICT (scope_id) DO NOTHING;

-- ---------------------------------------------------------------- bens não financeiros
INSERT INTO estate.assets (id, scope_id, owner_member_id, kind, label, ownership_share, liquidity,
                           acquired_on, acquisition_cost_brl, is_encumbered, linked_debt_id,
                           generates_income, income_source_id, is_primary_residence, origin)
VALUES ('0fe0a000-0000-4000-8000-000000000041', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000011', 'imovel_residencial', 'Apartamento onde mora',
        1.0, 'acima_12m', (current_date - interval '6 years')::date, 620000.00,
        true, '0fe0a000-0000-4000-8000-000000000021', false, NULL, true, 'onboarding'),
       ('0fe0a000-0000-4000-8000-000000000042', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000011', 'imovel_residencial', 'Apartamento alugado a terceiros',
        1.0, 'acima_12m', (current_date - interval '4 years')::date, 355000.00,
        false, NULL, true, '0fe0a000-0000-4000-8000-000000000033', false, 'onboarding'),
       ('0fe0a000-0000-4000-8000-000000000043', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000011', 'veiculo', 'Automóvel da família',
        1.0, 'ate_30d', (current_date - interval '3 years')::date, 128000.00,
        false, NULL, false, NULL, false, 'onboarding')
ON CONFLICT (id) DO NOTHING;

-- O valor NÃO fica em assets: fica em valuations, append-only e datado.
-- SEM `id` explícito, de propósito (corrigido em 2026-08-30). O `id` fixo entrava em
-- conflito com a PK quando o seed rodava num DIA diferente do anterior: a avaliação nova
-- tem `as_of_date` novo, então `ON CONFLICT (asset_id, as_of_date)` não casa e a chave
-- primária estoura. O seed se dizia idempotente no cabeçalho e era, mas só dentro do mesmo
-- dia — a série append-only é justamente o que muda de dia. `core.new_id()` resolve.
INSERT INTO estate.valuations (asset_id, scope_id, as_of_date, value_brl, method, confidence)
VALUES ('0fe0a000-0000-4000-8000-000000000041',
        '0fe0a000-0000-4000-8000-000000000002', current_date, 850000.00, 'declarado', 0.60),
       ('0fe0a000-0000-4000-8000-000000000042',
        '0fe0a000-0000-4000-8000-000000000002', current_date, 420000.00, 'declarado', 0.60),
       ('0fe0a000-0000-4000-8000-000000000043',
        '0fe0a000-0000-4000-8000-000000000002', current_date, 95000.00, 'tabela_referencia', 0.80)
ON CONFLICT (asset_id, as_of_date) DO NOTHING;

-- ---------------------------------------------------------------- instrumentos da carteira
-- PETR4/VALE3/BOVA11 podem já existir pelo `seed dev`; os demais nascem aqui. O casamento
-- posterior é por TICKER, então a persona não depende de o seed de dev ter rodado.
INSERT INTO market.instruments (kind, name, ticker, asset_class_code, is_in_universe, indexer, maturity_date)
VALUES ('tesouro', 'Tesouro IPCA+ 2035',            'TESIPCA2035', 'ipca',         false, 'ipca',   '2035-05-15'),
       ('cdb',     'CDB liquidez diária 102% CDI',  'CDBLIQ102',   'caixa',        false, 'cdi',    NULL),
       ('fii',     'FII de logística',              'HGLG11',      'fii',          false, NULL,     NULL),
       ('fundo',   'Fundo multimercado macro',      'FUNDOMM01',   'multimercado', false, NULL,     NULL),
       ('acao',    'Petróleo Brasileiro S.A.',      'PETR4',       'acoes_br',     true,  NULL,     NULL),
       ('acao',    'Vale S.A.',                     'VALE3',       'acoes_br',     true,  NULL,     NULL),
       ('etf',     'iShares Ibovespa Fundo de Índice', 'BOVA11',    'acoes_br',     true,  NULL,     NULL)
ON CONFLICT (ticker) WHERE ticker IS NOT NULL DO NOTHING;

-- ---------------------------------------------------------------- contas e posições
INSERT INTO wealth.accounts (id, scope_id, kind, label, institution_name, opened_at)
VALUES ('0fe0a000-0000-4000-8000-000000000051', '0fe0a000-0000-4000-8000-000000000002',
        'corretora', 'Corretora · conta principal', 'Corretora Demo',
        (current_date - interval '5 years')::date),
       ('0fe0a000-0000-4000-8000-000000000052', '0fe0a000-0000-4000-8000-000000000002',
        'banco', 'Banco · conta corrente', 'Banco Demo', (current_date - interval '9 years')::date)
ON CONFLICT (id) DO NOTHING;

-- R$ 486.000 investidos. `value_brl` é congelado de propósito (reprodutibilidade point-in-time);
-- a tabela é append-only: corrigir = linha nova em as_of_date novo, nunca UPDATE.
INSERT INTO wealth.holdings_snapshots (scope_id, account_id, instrument_id, as_of_date, value_brl, origin)
SELECT '0fe0a000-0000-4000-8000-000000000002', v.conta, i.id, current_date, v.valor, 'manual'
FROM (VALUES ('TESIPCA2035', '0fe0a000-0000-4000-8000-000000000051'::uuid, 140000.00),
             ('CDBLIQ102',   '0fe0a000-0000-4000-8000-000000000052'::uuid,  95000.00),
             ('PETR4',       '0fe0a000-0000-4000-8000-000000000051'::uuid,  42000.00),
             ('VALE3',       '0fe0a000-0000-4000-8000-000000000051'::uuid,  38000.00),
             ('BOVA11',      '0fe0a000-0000-4000-8000-000000000051'::uuid,  62000.00),
             ('HGLG11',      '0fe0a000-0000-4000-8000-000000000051'::uuid,  71000.00),
             ('FUNDOMM01',   '0fe0a000-0000-4000-8000-000000000051'::uuid,  38000.00)
     ) AS v(ticker, conta, valor)
JOIN market.instruments i ON i.ticker = v.ticker
WHERE NOT EXISTS (SELECT 1 FROM wealth.holdings_snapshots h
                  WHERE h.scope_id = '0fe0a000-0000-4000-8000-000000000002'
                    AND h.as_of_date = current_date AND h.instrument_id = i.id);

-- Rollup: é DAQUI que sai `estate.v_net_worth.investivel_brl`.
INSERT INTO wealth.portfolio_snapshots (scope_id, as_of_date, total_brl, invested_brl, cash_brl, by_asset_class, by_account)
VALUES ('0fe0a000-0000-4000-8000-000000000002', current_date, 486000.00, 391000.00, 95000.00,
        '{"ipca": 140000, "caixa": 95000, "acoes_br": 142000, "fii": 71000, "multimercado": 38000}'::jsonb,
        '{"corretora": 391000, "banco": 95000}'::jsonb)
ON CONFLICT (scope_id, as_of_date) DO NOTHING;

-- ---------------------------------------------------------------- objetivos
INSERT INTO planning.goals (id, scope_id, created_by, name, kind, target_amount_brl, target_date,
                            monthly_contribution_brl, priority, status)
VALUES ('0fe0a000-0000-4000-8000-000000000061', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000001', 'Aposentadoria aos 60', 'aposentadoria',
        2800000.00, (date_trunc('year', current_date) + interval '18 years')::date, 8000.00, 1, 'ativa'),
       ('0fe0a000-0000-4000-8000-000000000062', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000001', 'Faculdade da Beatriz', 'educacao',
        240000.00, (date_trunc('year', current_date) + interval '4 years')::date, 1500.00, 2, 'ativa')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------- vetos do cliente
-- Bloqueante nasce confirmado pelo PRÓPRIO cliente (C26b + self_confirmation_only): sem
-- confirmed_at/confirmed_by o banco recusa a linha.
INSERT INTO preferences.constraints (id, scope_id, user_id, kind, enforcement, origin,
                                     asset_class_code, reason, confirmed_at, confirmed_by)
VALUES ('0fe0a000-0000-4000-8000-000000000071', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000001', 'veto_classe', 'bloqueante', 'usuario',
        'cripto', 'Não quero exposição a cripto em nenhuma proporção', now(),
        '0fe0a000-0000-4000-8000-000000000001'),
       ('0fe0a000-0000-4000-8000-000000000072', '0fe0a000-0000-4000-8000-000000000002',
        '0fe0a000-0000-4000-8000-000000000001', 'sem_derivativos', 'bloqueante', 'usuario',
        NULL, 'Não opero derivativos nem produtos alavancados', now(),
        '0fe0a000-0000-4000-8000-000000000001')
ON CONFLICT (id) DO NOTHING;
