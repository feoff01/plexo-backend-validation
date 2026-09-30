-- =============================================================================
-- PLEXO · 61_acervo_de_mercado.sql — o Analista deixa de enxergar cinco ativos [F22, 1ª onda]
--
-- POR QUE ESTA MIGRATION EXISTE
--
-- A F5 entregou o Analista e declarou, por escrito, do que ele dependia: *"depende de fonte de
-- preços (não existe)"* (PLANO §2.3). O que existe hoje no banco são 5 instrumentos e os pregões
-- de 2026 — e três limitações registradas como desvio da própria F5:
--
--   (b) só o fechamento entra em `market.prices`; sem proventos, toda data-ex vira queda artificial
--   (c) o benchmark é `BOVA11` porque o Ibovespa em pontos não vinha de nenhuma fonte
--   (g) o calendário de pregões é derivado dos próprios preços — não há tabela de feriados
--
-- Esta migration abre espaço para o acervo do mercado brasileiro (B3 desde 1986, CVM, ANBIMA,
-- Tesouro) e fecha as três. Ela NÃO carrega dado: cria a estrutura e as regras que a carga terá
-- de respeitar. A carga vem na onda seguinte, por `plexo mercado importar`.
--
-- CINCO DECISÕES, E O MOTIVO DE CADA UMA
--
--   (a) TUDO EM `market`, SEM SCHEMA NOVO. `market` já é o schema de mercado e já é "referência
--       global, sem scope_id/user_id" por declaração escrita (31, linha 20). Um schema novo
--       exigiria CREATE SCHEMA, os cinco GRANT à mão (o loop da 28 tem lista literal), entrada em
--       PROJECT_SCHEMAS e no validador — e criaria dois lugares para procurar dado de mercado.
--
--   (b) APPEND-ONLY, COMO AS SÉRIES DA 31. Dado público corrigido é linha nova, de outro lote,
--       nunca reescrita. É o que faz `tools.tool_executions.input_hash` valer como promessa de
--       reprodutibilidade: se a série muda por baixo, o mesmo hash devolve outro número.
--       Trigger incondicional + REVOKE derivado do catálogo — nem o serviço tem UPDATE/DELETE.
--
--   (c) PREÇO AJUSTADO É CALCULADO NA LEITURA, NUNCA GRAVADO. O fator acumulado de ontem MUDA
--       quando um provento é anunciado hoje. Materializá-lo em `market.prices` seria reescrever
--       série — exatamente o que o T58 proíbe. Ficam duas views: `v_fatores_ajuste` (o produto
--       dos fatores dos eventos POSTERIORES a cada data, ~25 mil linhas) e `v_precos_ajustados`.
--       Sem isto, o retorno sai errado em toda data-ex: na PETR4 de 2024 a diferença medida pelo
--       coletor foi de 17 pontos percentuais — de −4,21% para +13,35%, e a conclusão se inverte.
--
--   (d) UNIDADE É CONSTRAINT, NÃO CONVENÇÃO. A F16 gastou meia sessão num defeito onde
--       `index_values` guardava percentual (14,0) e `budget.debts.annual_rate` guardava fração
--       (0,145): comparados sem conversão, um rotativo a 400% ao ano pareceu mais barato que o
--       CDI e o semáforo saiu VERDE. A curva de juros repete a armadilha em outra forma — 4,4 em
--       252 dias úteis e 4,4 em 360 corridos não são o mesmo número. Por isso `day_count` é enum
--       NOT NULL, e a coluna da taxa se chama `rate_pct`: a unidade está no nome.
--
--   (e) FUNDAMENTO É POINT-IN-TIME OU NÃO É FUNDAMENTO. `availability_date` é a data em que a CVM
--       recebeu o documento, e é NOT NULL. Sem ela, um backtest usa balanço antes de ele ter sido
--       publicado — o erro mais caro em análise de fundamento. A constraint vai além do NOT NULL:
--       disponível antes do fim do período é impossível, e o banco recusa.
--
-- E DUAS COISAS QUE NÃO SÃO TABELA
--
--   · PARTIÇÕES ANUAIS PARA O PASSADO. `market.prices` cobre 2016-08 → 2027-08 em partições
--     mensais. O acervo começa em 1995 (antes disso são quatro trocas de moeda e uma série nominal
--     incomparável, que o coletor não deflaciona). Mensal até 1995 custaria 259 partições novas;
--     anual para 1995–2015 custa 21. O nó da Aiven tem 1 GB de RAM, e dado velho não muda.
--
--   · `pg_trgm` + `unaccent`. O Copiloto precisa resolver "aquele fundo do BTG" para um CNPJ entre
--     ~60 mil fundos, e um ticker entre ~6,5 mil papéis. Hoje `dados.resolver_instrumento` faz
--     `ilike '%termo%'`, e tanto o glossário quanto `contexto.documento_oficial` filtram em Python
--     com o comentário "o banco não tem unaccent". Isto resolve os três. NÃO é embedding: com esta
--     cardinalidade, similaridade trigrama é determinística, explicável e suficiente — e número
--     com proveniência não se busca por aproximação.
--
-- Depende de: 00_core (domains, forbid_update_delete, proteger_particao), 04_market (instruments,
--   index_definitions, data_sources, prices), 28_roles_grants (o padrão trigger+REVOKE),
--   31_market_immutability (append-only das séries), 56_rls_particoes_e_filhas (proteger_particao).
-- Testes: tests/test_regras_invioláveis_market.sql (T146–T150).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Extensões de busca textual
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm  WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;

-- `unaccent` é STABLE (o dicionário pode ser recarregado), e índice de expressão exige IMMUTABLE.
-- Este invólucro é o contorno documentado do PostgreSQL: fixa o dicionário pelo nome qualificado e
-- assume que ele não muda. É uma afirmação, não um descuido — trocar o dicionário `public.unaccent`
-- exige REINDEX das duas GIN abaixo.
CREATE FUNCTION market.texto_busca(t text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS
$fn$ SELECT lower(public.unaccent('public.unaccent'::regdictionary, t)) $fn$;

COMMENT ON FUNCTION market.texto_busca(text) IS
  '[F22] Normalização para busca por similaridade: minúsculas sem acento. IMMUTABLE por decisão '
  '(o dicionário public.unaccent é tratado como fixo) para poder indexar — trocar o dicionário '
  'exige REINDEX de instruments_nome_trgm e instruments_ticker_trgm.';

CREATE INDEX instruments_nome_trgm
  ON market.instruments USING gin (market.texto_busca(name) gin_trgm_ops);
CREATE INDEX instruments_ticker_trgm
  ON market.instruments USING gin (market.texto_busca(ticker) gin_trgm_ops)
  WHERE ticker IS NOT NULL;

-- -----------------------------------------------------------------------------
-- (g) Calendário de pregões — o que a F5 derivava dos próprios preços
-- -----------------------------------------------------------------------------
CREATE TABLE market.trading_calendar (
  calendar_name      core.slug NOT NULL,               -- 'anbima', 'b3'
  calendar_date      date NOT NULL,
  is_business_day    boolean NOT NULL,
  holiday_name       text,
  source_code        core.slug NOT NULL REFERENCES market.data_sources(code),
  ingestion_batch_id uuid REFERENCES market.ingestion_batches(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (calendar_name, calendar_date),
  -- Fim de semana é dia não útil SEM nome; feriado tem nome. O que não pode existir é um dia
  -- batizado de feriado e contado como pregão — seria dia útil a mais na base 252.
  CONSTRAINT feriado_nao_e_dia_util CHECK (holiday_name IS NULL OR NOT is_business_day)
);
CREATE INDEX trading_calendar_uteis_idx
  ON market.trading_calendar (calendar_name, calendar_date) WHERE is_business_day;

COMMENT ON TABLE market.trading_calendar IS
  '[F22] Calendário oficial de pregão (ANBIMA/B3). A F5 declarou como desvio (g) que o calendário '
  'era "dias com fechamento de qualquer ativo do universo" — o que confunde feriado com papel sem '
  'negócio. É a base da contagem de dias úteis 252, que a curva de juros e as gregas exigem.';

-- -----------------------------------------------------------------------------
-- Classificação setorial — com data, porque a B3 reclassifica
-- -----------------------------------------------------------------------------
CREATE TABLE market.sector_classification (
  instrument_id      uuid NOT NULL REFERENCES market.instruments(id) ON DELETE CASCADE,
  source_code        core.slug NOT NULL REFERENCES market.data_sources(code),
  reference_date     date NOT NULL,
  economic_sector    text,
  subsector          text,
  segment            text,
  listing_segment    text,                             -- NM, N1, N2, MB, básico
  ingestion_batch_id uuid REFERENCES market.ingestion_batches(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (instrument_id, source_code, reference_date)
);
CREATE INDEX sector_classification_setor_idx
  ON market.sector_classification (economic_sector, reference_date DESC);

COMMENT ON TABLE market.sector_classification IS
  '[F22] Setor, subsetor e segmento de listagem por DATA. Sem `reference_date` na chave, uma '
  'reclassificação da B3 reescreveria o passado — e o setor de uma empresa em 2015 viraria o de '
  'hoje em toda análise histórica. O vigente numa data é o último `reference_date` anterior a ela.';

-- -----------------------------------------------------------------------------
-- (c) Carteira teórica dos índices — é ela que define o universo de forma objetiva
-- -----------------------------------------------------------------------------
CREATE TABLE market.index_weights (
  index_code         core.slug NOT NULL REFERENCES market.index_definitions(code),
  reference_date     date NOT NULL,
  instrument_id      uuid NOT NULL REFERENCES market.instruments(id),
  weight_pct         numeric(9,6) NOT NULL CHECK (weight_pct >= 0 AND weight_pct <= 100),
  theoretical_qty    numeric(24,4),
  ingestion_batch_id uuid REFERENCES market.ingestion_batches(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (index_code, reference_date, instrument_id)
);
CREATE INDEX index_weights_instrumento_idx
  ON market.index_weights (instrument_id, reference_date DESC);

COMMENT ON TABLE market.index_weights IS
  '[F22] Carteira teórica dos índices B3 (IBOV, IBrX-100, IFIX, SMLL…) com peso. Serve a duas '
  'coisas: comparar carteira do cliente com o mercado, e definir `instruments.is_in_universe` por '
  'REGRA em vez de por lista escolhida à mão — a cobertura passa a ser auditável.';

-- -----------------------------------------------------------------------------
-- (d) Curva de juros — com a base de contagem declarada na linha
-- -----------------------------------------------------------------------------
CREATE TYPE market.day_count AS ENUM ('du_252', 'dc_360', 'dc_365');

CREATE TABLE market.yield_curve (
  curve_name         core.slug NOT NULL,               -- 'pre', 'dic', 'doc', 'ettj_pre'
  reference_date     date NOT NULL,
  business_days      integer NOT NULL CHECK (business_days > 0),
  calendar_days      integer CHECK (calendar_days IS NULL OR calendar_days > 0),
  rate_pct           numeric(12,6) NOT NULL,           -- % a.a. — a unidade está no nome
  day_count          market.day_count NOT NULL,
  source_code        core.slug NOT NULL REFERENCES market.data_sources(code),
  ingestion_batch_id uuid REFERENCES market.ingestion_batches(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (curve_name, reference_date, business_days, source_code)
);
CREATE INDEX yield_curve_data_idx ON market.yield_curve (reference_date DESC, curve_name);

COMMENT ON COLUMN market.yield_curve.day_count IS
  '[F22] PRE e DIC são base 252 dias úteis; DOC é 360 corridos. Guardar a taxa sem a base é '
  'repetir, em outra forma, o defeito de unidade que a F16 mediu: dois números iguais que '
  'significam coisas diferentes.';

-- -----------------------------------------------------------------------------
-- (e) Fundamentos point-in-time
-- -----------------------------------------------------------------------------
CREATE TABLE market.fundamentals (
  id                 uuid PRIMARY KEY DEFAULT core.new_id(),
  company_cnpj       char(14) NOT NULL,
  instrument_id      uuid REFERENCES market.instruments(id),   -- ticker primário, quando houver
  reference_date     date NOT NULL,                    -- fim do período contábil
  availability_date  date NOT NULL,                    -- quando a CVM recebeu o documento
  document_type      text NOT NULL CHECK (document_type IN ('DFP','ITR')),
  scope              text NOT NULL CHECK (scope IN ('consolidated','standalone')),
  period_label       text NOT NULL CHECK (length(btrim(period_label)) > 0),
  metric             core.slug NOT NULL,               -- 'net_income', 'ebitda_derived', …
  value              numeric(24,6) NOT NULL,
  is_derived         boolean NOT NULL DEFAULT false,
  source_code        core.slug NOT NULL REFERENCES market.data_sources(code),
  ingestion_batch_id uuid REFERENCES market.ingestion_batches(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  -- Demonstração não fica disponível antes de o período que ela mede terminar.
  CONSTRAINT fundamento_disponivel_depois_do_periodo
    CHECK (availability_date >= reference_date),
  -- A reapresentação é uma linha NOVA, com outra data de disponibilidade: o vintage anterior
  -- continua existindo, que é o que torna o backtest sem look-ahead possível.
  CONSTRAINT fundamentals_vintage_uk
    UNIQUE (company_cnpj, reference_date, document_type, scope, period_label, metric, availability_date)
);
CREATE INDEX fundamentals_pit_idx
  ON market.fundamentals (company_cnpj, metric, availability_date, reference_date DESC);
CREATE INDEX fundamentals_instrumento_idx
  ON market.fundamentals (instrument_id, metric, availability_date) WHERE instrument_id IS NOT NULL;

COMMENT ON TABLE market.fundamentals IS
  '[F22] Métricas contábeis da CVM por VERSÃO. `availability_date` (DT_RECEB) é o que separa '
  'análise de adivinhação: filtrar por ela é a diferença entre usar um balanço e usar um balanço '
  'que ainda não existia. Sufixo `_derived` na métrica marca o que foi calculado a partir das '
  'contas, não lido da demonstração.';

-- -----------------------------------------------------------------------------
-- (b) e (c) Preço ajustado — CALCULADO, nunca gravado
-- -----------------------------------------------------------------------------
-- Convenção do mercado, a mesma do coletor:
--   · provento em dinheiro na data-ex D:  f = (P_{D-1} − valor) / P_{D-1}
--   · desdobramento/grupamento de razão r: f = 1 / r
--   · cum_factor(t) = produto de f de TODOS os eventos com data-ex > t
-- A observação mais recente sempre tem fator 1, e o fator cresce conforme se volta no tempo.
CREATE VIEW market.v_fatores_ajuste WITH (security_invoker = true) AS
WITH evento AS (
  SELECT ca.instrument_id,
         ca.ex_date,
         CASE
           WHEN ca.kind IN ('desdobramento','grupamento','bonificacao')
             THEN CASE WHEN ca.factor IS NULL OR ca.factor <= 0 THEN 1.0 ELSE 1.0 / ca.factor END
           WHEN ca.amount_per_unit IS NULL OR ca.amount_per_unit <= 0 THEN 1.0
           -- Sem fechamento da véspera não há como calcular o fator; a linha entra neutra e a
           -- ausência aparece como lacuna na evidência da tool, não como número inventado.
           WHEN vespera.value IS NULL OR vespera.value <= ca.amount_per_unit THEN 1.0
           ELSE (vespera.value - ca.amount_per_unit) / vespera.value
         END AS fator
    FROM market.corporate_actions ca
    LEFT JOIN LATERAL (
      SELECT p.value
        FROM market.prices p
       WHERE p.instrument_id = ca.instrument_id
         AND p.kind = 'close'
         AND p.price_date < ca.ex_date
       ORDER BY p.price_date DESC
       LIMIT 1
    ) vespera ON true
),
por_data AS (
  SELECT instrument_id, ex_date, exp(sum(ln(fator))) AS fator
    FROM evento
   WHERE fator > 0
   GROUP BY instrument_id, ex_date
)
SELECT instrument_id,
       ex_date,
       exp(sum(ln(fator)) OVER (PARTITION BY instrument_id ORDER BY ex_date DESC
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS cum_factor
  FROM por_data;

COMMENT ON VIEW market.v_fatores_ajuste IS
  '[F22] Fator acumulado por (instrumento, data-ex) — piecewise constante entre eventos, o que '
  'faz ~25 mil linhas cobrirem milhões de pregões. É view e não tabela porque o fator de ontem '
  'muda quando um provento é anunciado hoje: gravá-lo violaria o append-only de market.prices.';

CREATE VIEW market.v_precos_ajustados WITH (security_invoker = true) AS
SELECT p.instrument_id,
       i.ticker,
       p.price_date,
       p.value                              AS close,
       COALESCE(f.cum_factor, 1.0)          AS cum_factor,
       p.value * COALESCE(f.cum_factor, 1.0) AS close_adj,
       p.currency,
       p.source_code
  FROM market.prices p
  LEFT JOIN market.instruments i ON i.id = p.instrument_id
  LEFT JOIN LATERAL (
    SELECT fa.cum_factor
      FROM market.v_fatores_ajuste fa
     WHERE fa.instrument_id = p.instrument_id
       AND fa.ex_date > p.price_date
     ORDER BY fa.ex_date
     LIMIT 1
  ) f ON true
 WHERE p.kind = 'close';

COMMENT ON VIEW market.v_precos_ajustados IS
  '[F22] Fechamento ajustado por proventos e desdobramentos. É esta, e não market.prices, que '
  'deve alimentar qualquer cálculo de retorno: sem o ajuste, toda data-ex vira queda artificial. '
  'Medido pelo coletor na PETR4 de 2024: −4,21% no preço bruto contra +13,35% no ajustado.';

-- -----------------------------------------------------------------------------
-- Partições do passado — anuais, porque dado velho não muda e RAM é escassa
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.ensure_year_partitions(parent regclass, from_year int, years int)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
  v_year   int;
  v_name   text;
  v_schema text;
  v_table  text;
  v_pai_protege boolean;
BEGIN
  SELECT n.nspname, c.relname, c.relrowsecurity
    INTO v_schema, v_table, v_pai_protege
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE c.oid = parent;

  FOR i IN 0 .. years - 1 LOOP
    v_year := from_year + i;
    v_name := format('%s_%s', v_table, v_year);
    IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = v_name AND n.nspname = v_schema) THEN
      EXECUTE format('CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
        v_schema, v_name, v_schema, v_table,
        make_date(v_year, 1, 1), make_date(v_year + 1, 1, 1));
      PERFORM core.proteger_particao(v_schema, v_name, v_pai_protege);
    END IF;
  END LOOP;
END;
$fn$;

COMMENT ON FUNCTION core.ensure_year_partitions IS
  '[F22] Irmã anual de core.ensure_month_partitions, para o passado que não muda mais. O acervo '
  'da B3 vai a 1995; mensal custaria 259 partições novas, anual custa 21 — e o nó tem 1 GB de RAM. '
  'Nome da filha: <tabela>_AAAA (4 dígitos), contra <tabela>_AAAAMM (6) da mensal.';

-- 1995–2015 anual; 2016 mensal para emendar com o que a 31 já criou (2016-08 em diante).
-- As duas funções pulam o que já existe, então isto é idempotente.
SELECT core.ensure_year_partitions('market.prices', 1995, 21);
SELECT core.ensure_month_partitions('market.prices', DATE '2016-01-01', 12);

-- -----------------------------------------------------------------------------
-- (b) Append-only: trigger incondicional + REVOKE derivado do catálogo
-- -----------------------------------------------------------------------------
CREATE TRIGGER trading_calendar_append_only BEFORE UPDATE OR DELETE ON market.trading_calendar
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
CREATE TRIGGER sector_classification_append_only BEFORE UPDATE OR DELETE ON market.sector_classification
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
CREATE TRIGGER index_weights_append_only BEFORE UPDATE OR DELETE ON market.index_weights
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
CREATE TRIGGER yield_curve_append_only BEFORE UPDATE OR DELETE ON market.yield_curve
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
CREATE TRIGGER fundamentals_append_only BEFORE UPDATE OR DELETE ON market.fundamentals
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();

-- Mesmo mecanismo da 28 e da 31, restrito a `market`: onde o trigger é incondicional, nem o
-- serviço tem UPDATE/DELETE. Roda DEPOIS das partições novas, para alcançar o trigger clonado
-- nelas — sem isto, escrever direto em market.prices_1998 passaria por fora do append-only.
DO $rev$
DECLARE t record;
BEGIN
  FOR t IN
    SELECT n.nspname, c.relname,
           bool_or((tg.tgtype & 16) > 0) AS upd,
           bool_or((tg.tgtype &  8) > 0) AS del
    FROM pg_trigger tg
    JOIN pg_class     c ON c.oid = tg.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE tg.tgfoid = 'core.forbid_update_delete'::regproc
      AND NOT tg.tgisinternal
      AND tg.tgqual IS NULL
      AND n.nspname = 'market'
    GROUP BY 1, 2
  LOOP
    IF t.upd THEN EXECUTE format('REVOKE UPDATE ON %I.%I FROM plexo_app, plexo_service', t.nspname, t.relname); END IF;
    IF t.del THEN EXECUTE format('REVOKE DELETE ON %I.%I FROM plexo_app, plexo_service', t.nspname, t.relname); END IF;
  END LOOP;
END $rev$;

-- -----------------------------------------------------------------------------
-- Fontes do acervo — licença declarada, como em docs.sources
-- -----------------------------------------------------------------------------
INSERT INTO market.data_sources (code, display_name, cadence, base_url, license_note) VALUES
  ('tesouro_direto', 'Tesouro Direto', 'diaria',
   'https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto',
   'Preços e taxas do Tesouro Direto — dado público do Tesouro Nacional; uso conforme os termos do provedor.')
ON CONFLICT (code) DO NOTHING;

UPDATE market.data_sources
   SET base_url = 'https://dados.cvm.gov.br/dados/FI/CAD/DADOS/',
       license_note = 'Portal de Dados Abertos da CVM — dado público; uso conforme os termos do provedor.'
 WHERE code = 'cvm_fundos' AND license_note IS NULL;

UPDATE market.data_sources
   SET base_url = 'https://www.anbima.com.br/informacoes/',
       license_note = 'ANBIMA — feriados nacionais, ETTJ e taxas indicativas; uso conforme os termos da ANBIMA, sem redistribuição.'
 WHERE code = 'anbima' AND license_note IS NULL;

-- -----------------------------------------------------------------------------
-- Índices de mercado que o acervo passa a preencher (a `c` da F5)
-- -----------------------------------------------------------------------------
INSERT INTO market.index_definitions (code, display_name, unit, source_code) VALUES
  ('ibrx100', 'IBrX-100', 'pontos', 'b3'),
  ('ifix',    'IFIX',     'pontos', 'b3'),
  ('smll',    'Small Cap (SMLL)', 'pontos', 'b3')
ON CONFLICT (code) DO NOTHING;

COMMIT;
