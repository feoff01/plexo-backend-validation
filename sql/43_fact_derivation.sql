-- =============================================================================
-- PLEXO · 43_fact_derivation.sql — A janela operável do motor [F15]
--
-- O PROBLEMA QUE ESTE ARQUIVO RESOLVE
--   A F14 entregou o laço inteiro e a verificação expôs que ele não tinha carga: a persona
--   de demonstração tem 4 fontes de renda, 12 meses de orçamento, 2 dívidas, 3 bens, 4
--   membros e 2 objetivos — R$ 1,52 milhão — e **0% de cobertura**, porque nada ligava
--   `budget.*`, `estate.*` e `household.*` ao catálogo de fatos. O motor respondia
--   "dados_insuficientes" sobre um cliente cujos dados o banco já guardava inteiros.
--
-- A PERGUNTA QUE A DERIVAÇÃO LEVANTA, E A RESPOSTA DESTE ARQUIVO
--   Um fato que o MOTOR deduziu vale o mesmo que um que o cliente CONFIRMOU? Não. E a
--   diferença não pode virar uma flag que alguém esquece de checar: ela vira duas janelas.
--
--     context.v_fact_current    contrato do AGENTE — só 'confirmado'. NÃO muda.
--     context.v_fact_operavel   contrato do MOTOR  — 'confirmado' + 'inferido', com o
--                                confirmado SEMPRE na frente e nunca rebaixado pelo derivado.
--
--   Assim o score passa a existir e nada é apresentado ao cliente como se ele tivesse
--   confirmado. A alternativa — o derivado nascer 'confirmado' — resolveria a cobertura mais
--   rápido e custaria o gate epistêmico inteiro da migration 22, que existe exatamente para
--   impedir que algo não confirmado vire verdade operável.
--
--   `context.assertions.confidence` continua carregando a diferença em número: a derivação
--   grava com o fator de `CONTEXT_FACT_CATALOG.fator_confianca_derivado`, e é ele que faz o
--   score de um perfil derivado sair com confiança menor que o de um perfil confirmado.
--
-- E A PERGUNTA
--   `display_name` ("Despesa essencial mensal") é rótulo de tela, não pergunta. O que falta
--   só vira a próxima conversa se o catálogo souber COMO perguntar — por isso a coluna
--   `pergunta`, obrigatória para todo fato que a conversa pode atualizar.
--
-- Depende de: 22_assertions, 38_fact_catalog, 42_supersede_on_user_confirm.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- A pergunta que o Copiloto faz quando o fato falta
-- -----------------------------------------------------------------------------
ALTER TABLE context.fact_definitions ADD COLUMN pergunta text;

COMMENT ON COLUMN context.fact_definitions.pergunta IS
  '[F15] Como este fato é perguntado ao cliente, em pt-BR e em uma frase. Obrigatória para '
  'todo fato que a conversa pode atualizar: é dela que sai a mecânica de onboarding sem '
  'formulário — o dado que falta vira a próxima pergunta, não um campo em branco.';

UPDATE context.fact_definitions SET pergunta = v.pergunta
FROM (VALUES
  ('renda.mensal_liquida',            'Quanto você recebe por mês, já líquido?'),
  ('renda.mensal_bruta',              'Qual é a sua renda mensal bruta?'),
  ('renda.fontes_ativas',             'De quantas fontes vem a sua renda hoje?'),
  ('renda.tipo_vinculo',              'Você é CLT, PJ, servidor, autônomo ou sócio?'),
  ('renda.tem_decimo_terceiro',       'Você recebe 13º?'),
  ('despesa.total_mensal',            'Quanto sai por mês, somando tudo?'),
  ('despesa.essencial_mensal',        'E só do essencial — moradia, comida, transporte, saúde — quanto sai por mês?'),
  ('despesa.fixa_contratada',         'Quanto dos seus gastos é fixo e contratado (aluguel, parcelas, mensalidades)?'),
  ('fluxo.aporte_mensal',             'Quanto você consegue guardar por mês hoje?'),
  ('protecao.reserva_atual',          'Quanto você tem guardado para emergência?'),
  ('protecao.cobertura_vida',         'Você tem seguro de vida? De quanto é o capital segurado?'),
  ('protecao.cobertura_invalidez',    'Você tem cobertura para invalidez? De quanto?'),
  ('protecao.tem_plano_saude',        'Você tem plano de saúde?'),
  ('protecao.tem_seguro_residencial', 'Você tem seguro do imóvel onde mora?'),
  ('protecao.dependentes_financeiros','Quantas pessoas dependem financeiramente de você?'),
  ('patrimonio.imobilizado',          'Você tem imóvel, veículo ou participação em empresa? Quanto valem, somados?'),
  ('divida.saldo_total',              'Quanto você deve hoje, somando tudo?'),
  ('divida.custo_medio',              'Qual é a taxa de juros das suas dívidas?'),
  ('divida.parcela_mensal',           'Quanto das suas parcelas de dívida sai por mês?'),
  ('objetivo.valor_alvo',             'De quanto você precisa para realizar esse objetivo?'),
  ('objetivo.prazo_meses',            'Em quanto tempo você quer chegar lá?'),
  ('objetivo.prioridade',             'Entre os seus objetivos, onde esse entra?'),
  ('destino.idade_aposentadoria',     'Com que idade você gostaria de poder parar de trabalhar?'),
  ('comportamento.aporte_regular',    'Você consegue guardar todo mês ou varia bastante?'),
  ('comportamento.reacao_queda',      'Na última vez que o mercado caiu forte, o que você fez?'),
  ('comportamento.experiencia_investimento', 'Há quanto tempo você investe?'),
  ('comportamento.nivel_conhecimento','Como você descreveria o seu conhecimento sobre investimentos?'),
  ('vida.data_nascimento',            'Qual é a sua data de nascimento?'),
  ('vida.estado_civil',               'Qual é o seu estado civil?'),
  ('vida.regime_bens',                'Qual é o regime de bens do seu casamento?'),
  ('vida.profissao',                  'Em que você trabalha?'),
  ('vida.estabilidade_emprego',       'Como você vê a estabilidade do seu trabalho hoje?'),
  ('vida.moradia',                    'Você mora em imóvel próprio, financiado ou alugado?'),
  ('vida.liquidez_minima_meses',      'Quantos meses de despesa você quer sempre poder resgatar rápido?')
) AS v(fact_key, pergunta)
WHERE context.fact_definitions.fact_key = v.fact_key;

-- ---------------------------------------------------------------- C43a
-- Fato que a conversa pode atualizar TEM que saber como ser perguntado. Sem isto, a fila
-- de "o que ainda falta saber" saberia o que falta e não saberia como pedir.
-- `patrimonio.investido`, `patrimonio.liquido` e `vida.tolerancia_risco_declarada` ficam de
-- fora por desenho: ninguém pergunta o que outra fonte governa.
ALTER TABLE context.fact_definitions
  ADD CONSTRAINT askable_has_question
  CHECK (NOT allows_conversation_update OR pergunta IS NOT NULL);

-- -----------------------------------------------------------------------------
-- A janela operável — o que o MOTOR pode calcular com
-- -----------------------------------------------------------------------------
CREATE VIEW context.v_fact_operavel WITH (security_invoker = true) AS
SELECT DISTINCT ON (a.scope_id, a.fact_key)
       a.id, a.scope_id, a.user_id,
       a.fact_key, d.family, d.display_name, d.value_type, d.unit,
       a.subject_kind, a.subject_ref, a.attribute, a.value,
       context.fact_number(a.value) AS numero,
       a.modality, a.source, a.status,
       (a.status = 'confirmado') AS confirmado,
       a.confidence,
       context.source_rank(a.fact_key, a.source) AS source_rank,
       a.observed_at, a.valid_from, a.valid_until, a.confirmed_at,
       (a.valid_until IS NOT NULL
        AND a.valid_until <= current_date + 30) AS vence_em_breve
  FROM context.assertions a
  JOIN context.fact_definitions d ON d.fact_key = a.fact_key
 WHERE a.status IN ('confirmado', 'inferido')
   AND a.superseded_at IS NULL
   AND (a.valid_until IS NULL OR a.valid_until >= current_date)
   AND d.is_active
 ORDER BY a.scope_id, a.fact_key,
          -- É esta linha que garante que derivar nunca sobrepõe o que o cliente disse.
          (a.status = 'confirmado') DESC,
          context.source_rank(a.fact_key, a.source),
          a.observed_at DESC;

COMMENT ON VIEW context.v_fact_operavel IS
  '[F15] O que o MOTOR pode calcular com: fato confirmado pelo cliente E fato derivado da '
  'estrutura que o próprio banco já guarda (budget, estate, household, planning). O confirmado '
  'vem sempre na frente; `confirmado` diz de qual dos dois se trata, e `confidence` carrega a '
  'diferença em número. Quem quer só a verdade do cliente lê context.v_fact_current — é ela '
  'que o agente enxerga, e ela não mudou.';

-- Cobertura passa a medir o que o motor CONSEGUE usar. Antes contava só o confirmado, o que
-- fazia a persona aparecer com 0% enquanto o banco já sabia quase tudo sobre ela.
CREATE OR REPLACE VIEW context.v_fact_coverage AS
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
  LEFT JOIN context.v_fact_operavel f
         ON f.scope_id = s.id AND f.fact_key = d.fact_key
 WHERE d.is_active
 GROUP BY s.id;

COMMENT ON VIEW context.v_fact_coverage IS
  '[F14, ampliada na F15] Cobertura por escopo sobre a janela OPERÁVEL: é ela que diz o que dá '
  'para calcular, e `faltando` é a fila de perguntas do Copiloto. Duas funções de uma vez — rede '
  'de compliance (score não sai sem base) e mecânica de onboarding sem formulário.';

-- -----------------------------------------------------------------------------
-- Política: quanto vale um fato derivado
-- -----------------------------------------------------------------------------
UPDATE engine.policy_versions
   SET effective_to = now()
 WHERE code = 'CONTEXT_FACT_CATALOG' AND effective_to IS NULL;

INSERT INTO engine.policy_versions (code, version, payload, compliance_status)
SELECT 'CONTEXT_FACT_CATALOG', 3,
       payload || '{
  "fator_confianca_derivado": 0.7,
  "max_perguntas_sugeridas": 4,
  "nota_derivacao": "fator_confianca_derivado multiplica a confiança do fato que o motor deduziu da estrutura (budget/estate/household/planning). Não é desconfiança do dado — é o registro de que ninguém o confirmou, e é o que faz o score de um perfil derivado sair com confiança menor que o de um perfil confirmado. max_perguntas_sugeridas limita a fila de o-que-ainda-falta-saber: a pergunta é útil, o interrogatório não."
}'::jsonb,
       'draft'
  FROM engine.policy_versions
 WHERE code = 'CONTEXT_FACT_CATALOG' AND version = 2;

COMMIT;
