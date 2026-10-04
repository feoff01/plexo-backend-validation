-- =============================================================================
-- SYNAPTA · 15_taxonomia.sql
-- (a) Seed das POLÍTICAS versionadas — todas nascem DRAFT (C6: o primeiro
--     deploy client-facing trava até compliance aprovar; é intencional).
-- (b) Taxonomia inicial de findings (~20 tipos) — ir de 20 para 45/90 é INSERT.
-- (c) Views de produto e a métrica-mãe (materialized view).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- (a) Políticas — payloads são PONTO DE PARTIDA para revisão, não verdade
-- -----------------------------------------------------------------------------
INSERT INTO engine.policy_versions (code, version, payload, compliance_status) VALUES
  ('RISK_BANDS_SYNAPTA', 1, '{
     "conservador": {"rv_max": 0.15, "cripto_max": 0.00},
     "moderado":    {"rv_max": 0.40, "cripto_max": 0.03},
     "arrojado":    {"rv_max": 0.70, "cripto_max": 0.05},
     "_nota": "placeholder — calibrar com comitê antes de aprovar"
   }'::jsonb, 'draft'),
  ('TIER_CONFIG', 1, '{
     "_nota": "espelho para o motor; a verdade de produto é billing.entitlements",
     "free": {"findings_visiveis": 3, "objetivos": 1}
   }'::jsonb, 'draft'),
  ('CONVICTION', 1, '{"tilt_max_por_classe": 0.05}'::jsonb, 'draft'),
  ('GESTOR_VIEW', 1, '{"fonte": "comite_interno", "validade_dias": 90}'::jsonb, 'draft'),
  ('ASSET_CLASSES', 1, '{
     "ordem": ["caixa","selic","prefixado","ipca","credito_privado","acoes_br",
               "acoes_int","fii","multimercado","cripto","previdencia","outros"]
   }'::jsonb, 'draft'),
  ('CORR_DEFAULT', 1, '{"metodo": "ledoit_wolf", "janela_dias": 756}'::jsonb, 'draft'),
  ('PREMISSAS_FALLBACK', 1, '{
     "retorno_real_rf": 0.04, "retorno_real_rv": 0.07, "inflacao_aa": 0.04,
     "_nota": "usadas quando faltar série; todo uso é gravado em run_inputs"
   }'::jsonb, 'draft'),
  ('FOUNDATION_THRESHOLDS', 1, '{
     "reserva_meses_min": 3, "reserva_meses_alvo": 6,
     "divida_cara_spread_sobre_cdi": 0.06
   }'::jsonb, 'draft'),
  ('FAMILY_LIMITS', 1, '{"max_members": 5}'::jsonb, 'draft'),
  ('DRIFT_BANDS', 1, '{"abs": 0.05, "rel": 0.25}'::jsonb, 'draft'),
  ('FINDING_SCORING', 1, '{"formula": "(impacto_brl_ano * confianca) / atrito_execucao"}'::jsonb, 'draft'),
  ('ACTION_GOVERNANCE', 1, '{"cooldown_days": 90, "max_dismissals": 2}'::jsonb, 'draft'),
  ('NOTIFICATION_LIMITS', 1, '{"max_push_per_week": 2}'::jsonb, 'draft');

-- -----------------------------------------------------------------------------
-- (b) Taxonomia inicial de findings — Free vê Top-3 curado; min_plan gata o resto
-- -----------------------------------------------------------------------------
INSERT INTO diagnostics.finding_types
  (code, family, display_name, default_severity, min_plan, is_quantifiable, execution_friction) VALUES
  -- Fundação (sempre visível: sem fundação, o resto não importa)
  ('fundacao.sem_reserva',            'fundacao', 'Sem reserva de emergência',            'critica', 'free', true,  2),
  ('fundacao.reserva_insuficiente',   'fundacao', 'Reserva abaixo do alvo',               'alta',    'free', true,  2),
  ('fundacao.divida_cara',            'fundacao', 'Dívida mais cara que o rendimento',    'critica', 'free', true,  3),
  -- Custo
  ('custo.taxa_fundo_alta',           'custo',    'Fundo com taxa acima do equivalente',  'alta',    'free',      true, 2),
  ('custo.fundo_prateleira_espelho',  'custo',    'Fundo espelho mais caro que o original','media',  'essential', true, 2),
  ('custo.previdencia_taxa_alta',     'custo',    'Previdência com custo excessivo',      'alta',    'essential', true, 4),
  ('custo.caixa_em_produto_caro',     'custo',    'Liquidez estacionada em produto caro', 'media',   'free',      true, 1),
  -- Risco
  ('risco.concentracao_emissor',      'risco',    'Concentração em um único emissor',     'alta',    'free',      true, 3),
  ('risco.concentracao_classe',       'risco',    'Concentração em uma classe de ativos', 'media',   'essential', true, 3),
  ('risco.concentracao_familiar',     'risco',    'Concentração cruzada da família',      'alta',    'advanced',  true, 3),
  ('risco.acima_do_perfil',           'risco',    'Risco acima do perfil declarado',      'alta',    'essential', false,3),
  -- Tributação
  ('tributacao.come_cotas_proximo',   'tributacao','Come-cotas se aproximando',           'media',   'essential', true, 2),
  ('tributacao.prejuizo_nao_compensado','tributacao','Prejuízo acumulado sem compensar',  'media',   'advanced',  true, 3),
  -- Alocação
  ('alocacao.desvio_do_alvo',         'alocacao', 'Carteira desviada do alvo (5/25)',     'media',   'essential', true, 2),
  ('alocacao.caixa_parado_excessivo', 'alocacao', 'Caixa parado além da reserva',         'alta',    'free',      true, 1),
  ('alocacao.sem_exposicao_internacional','alocacao','Sem diversificação internacional',  'baixa',   'essential', false,3),
  -- Planejamento
  ('planejamento.sem_objetivo_definido','planejamento','Nenhum objetivo definido',        'baixa',   'free',      false,1),
  ('planejamento.aporte_insuficiente','planejamento','Aporte insuficiente para o objetivo','media',  'essential', true, 2),
  -- Estrutura e liquidez
  ('estrutura.produto_incompativel_perfil','estrutura','Produto incompatível com o perfil','alta',   'essential', false,4),
  ('liquidez.resgate_longo_excessivo','liquidez', 'Parcela excessiva em D+30 ou mais',    'media',   'advanced',  true, 3);

-- -----------------------------------------------------------------------------
-- (c) Views
-- -----------------------------------------------------------------------------

-- Última foto de cada escopo (base das demais views)
CREATE VIEW wealth.v_latest_holdings WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT h.*
FROM wealth.holdings_snapshots h
JOIN (SELECT scope_id, max(as_of_date) AS as_of_date
        FROM wealth.holdings_snapshots GROUP BY scope_id) last
  USING (scope_id, as_of_date);

-- Concentração por emissor, consolidando CONGLOMERADO (parent_issuer_id) e,
-- para escopos familiares, agregando os escopos-membro (§4.12).
-- Marido 22% + esposa 19% no mesmo emissor: cada um ok sozinho, 41% em família.
CREATE VIEW diagnostics.v_issuer_concentration WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
WITH visao AS (
  -- cada escopo visto por si mesmo...
  SELECT s.id AS scope_id, s.id AS member_scope_id FROM identity.scopes s
  UNION ALL
  -- ...e o escopo familiar enxergando os membros
  SELECT f.id, m.id
  FROM identity.scopes f
  JOIN identity.scopes m ON m.parent_scope_id = f.id
  WHERE f.kind = 'family'
),
exposicao AS (
  SELECT v.scope_id,
         coalesce(iss.parent_issuer_id, iss.id) AS issuer_root_id,
         h.value_brl
  FROM visao v
  JOIN wealth.v_latest_holdings h ON h.scope_id = v.member_scope_id
  JOIN market.instruments i ON i.id = h.instrument_id
  JOIN market.issuers iss   ON iss.id = i.issuer_id
)
SELECT e.scope_id,
       e.issuer_root_id,
       ri.name AS issuer_name,
       sum(e.value_brl)::core.money_brl AS exposure_brl,
       (sum(sum(e.value_brl)) OVER (PARTITION BY e.scope_id))::core.money_brl AS scope_total_brl,
       round(sum(e.value_brl)
             / nullif(sum(sum(e.value_brl)) OVER (PARTITION BY e.scope_id), 0), 6) AS concentration_pct
FROM exposicao e
JOIN market.issuers ri ON ri.id = e.issuer_root_id
GROUP BY e.scope_id, e.issuer_root_id, ri.name;

-- Fila de ações: Fundação primeiro, cooldown e supressão respeitados.
-- queue_rank = 1 é a ÚNICA exibida (§16.5).
CREATE VIEW diagnostics.v_action_queue WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT a.id AS action_id,
       a.scope_id,
       a.finding_id,
       a.state,
       a.blocks,
       a.impact_brl_year,
       ft.family,   -- [validação PG real] family vive em finding_types, não em findings
       f.severity,
       f.priority_score,
       row_number() OVER (
         PARTITION BY a.scope_id
         ORDER BY (ft.family = 'fundacao') DESC,
                  f.priority_score DESC NULLS LAST,
                  a.created_at
       ) AS queue_rank
FROM diagnostics.actions a
JOIN diagnostics.findings f ON f.id = a.finding_id
JOIN diagnostics.finding_types ft ON ft.code = f.finding_type_code
WHERE a.state IN ('nova','vista','em_andamento')
  AND f.is_current
  AND NOT f.permanently_suppressed
  AND (f.cooldown_until IS NULL OR f.cooldown_until <= current_date);

-- Funil do paywall: conversão por preço exibido × impacto revelado (P01)
CREATE VIEW analytics.v_paywall_funnel WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT gate_code,
       plan_shown,
       interval_shown,
       price_shown_cents,
       experiment_variant,
       count(*)                                              AS impressions,
       count(*) FILTER (WHERE clicked)                       AS clicks,
       count(*) FILTER (WHERE checkout_started_at IS NOT NULL) AS checkouts,
       count(*) FILTER (WHERE converted_at IS NOT NULL)      AS conversions,
       round(count(*) FILTER (WHERE clicked)::numeric / nullif(count(*), 0), 4) AS ctr,
       round(avg(hidden_impact_brl_year), 2)                 AS avg_hidden_impact_brl_year
FROM analytics.paywall_impressions
GROUP BY gate_code, plan_shown, interval_shown, price_shown_cents, experiment_variant;

-- Carteira-alvo ativa com alocações — o que drift e aporte leem
CREATE VIEW planning.v_active_target WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT tp.scope_id,
       tp.id AS target_portfolio_id,
       tp.origin,
       tp.activated_at,
       ta.asset_class_code,
       ta.weight,
       ta.band_lower,
       ta.band_upper
FROM planning.target_portfolios tp
JOIN planning.target_allocations ta ON ta.target_portfolio_id = tp.id
WHERE tp.status = 'active';

-- Totais do Ledger por escopo — a Barra de Valor
CREATE VIEW ledger.v_scope_totals WITH (security_invoker = true) AS  -- [validação PG real] RLS de quem consulta, não do dono
SELECT scope_id,
       sum(amount_brl)::core.money_brl AS total_brl,
       sum(amount_brl) FILTER (
         WHERE occurred_on >= date_trunc('year', current_date)::date
       )::core.money_brl AS ytd_brl,
       count(*) AS entries_count,
       max(occurred_on) AS last_entry_on
FROM ledger.value_entries
GROUP BY scope_id;

-- A MÉTRICA-MÃE (§4.13): % de escopos com ≥1 ação concluída em D+14,
-- por coorte semanal. REFRESH MATERIALIZED VIEW CONCURRENTLY no job diário.
CREATE MATERIALIZED VIEW analytics.mv_activation_d14 AS
SELECT date_trunc('week', s.created_at)::date AS cohort_week,
       count(*) AS scopes,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM diagnostics.actions a
         WHERE a.scope_id = s.id
           AND a.completed_at IS NOT NULL
           AND a.completed_at <= s.created_at + interval '14 days'
       )) AS activated,
       round(
         count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM diagnostics.actions a
           WHERE a.scope_id = s.id
             AND a.completed_at IS NOT NULL
             AND a.completed_at <= s.created_at + interval '14 days'
         ))::numeric / nullif(count(*), 0), 4
       ) AS activation_rate
FROM identity.scopes s
WHERE s.kind = 'personal'
GROUP BY 1;
CREATE UNIQUE INDEX mv_activation_d14_uk ON analytics.mv_activation_d14 (cohort_week);

COMMENT ON MATERIALIZED VIEW analytics.mv_activation_d14 IS
  '§4.13 — a métrica-mãe do produto. O índice único permite REFRESH CONCURRENTLY.';

COMMIT;
