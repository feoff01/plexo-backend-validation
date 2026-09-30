-- =============================================================================
-- PLEXO · 34_docs.sql — Camada documental [F13a — evidência `documentary`]
-- -----------------------------------------------------------------------------
-- `analysis.evidence_findings.kind` aceita 'documentary' desde a 20 e o gate de relatório
-- fundamentado (32) já o conta como evidência material — mas NENHUMA linha de código jamais
-- escreveu esse kind: faltava de onde tirar o documento. Este arquivo cria essa origem.
--
--   · docs.sources           — quem publica, com a licença declarada (o que pode ser redistribuído)
--   · docs.documents         — o documento com TEXTO INTEGRAL congelado e hash. Guardar o texto é o
--                              que torna a evidência reproduzível: um relatório de hoje continua
--                              conferível quando o site do emissor mudar. `body_text` é anulável
--                              para fonte cuja licença proíba armazenar (metadados + link).
--   · docs.document_reviews  — trilha append-only de quem aprovou o quê, e quando
--   · docs.v_documentos_citaveis — a ÚNICA janela do agente: só documento aprovado
--   · docs.assert_document_review() — aprovar exige revisor + trilha na mesma transação; texto
--                              aprovado é imutável. Mesmo padrão do Educador (30) e dos prompts (19).
--
-- Vocabulário (RCVM 19): documento de terceiro é o único texto externo que pode chegar ao cliente.
-- `vocabulario_achados` guarda os termos vetados encontrados na ingestão e o CHECK impede aprovar
-- o que tem achado — a compliance é do BANCO, não do parser.
--
-- Também aqui: família de tool `contexto`, que Analista e Assessor podem invocar (uma tool só,
-- sem alargar o Assessor às tools quantitativas do Analista).
--
-- Sem RLS: documento oficial é referência global, sem scope_id/user_id — como market (31) e
-- content (30). Reusa market.ingestion_batches como lote imutável e idempotente por hash.
--
-- ATENÇÃO — `docs` é o PRIMEIRO schema criado depois da 28_roles_grants.sql. A lista de schemas
-- daquela migration é literal e o DO $$ dela já rodou: os GRANT/ALTER DEFAULT PRIVILEGES e os
-- REVOKE de append-only precisam ser emitidos aqui, à mão. Não há de onde herdar.
-- =============================================================================
BEGIN;

CREATE SCHEMA docs;

CREATE TYPE docs.review_status  AS ENUM ('pendente', 'aprovado', 'rejeitado');
CREATE TYPE docs.document_kind  AS ENUM ('comunicado', 'ata', 'nota', 'deliberacao', 'outro');

-- ---------------------------------------------------------------- fontes
CREATE TABLE docs.sources (
  code          core.slug PRIMARY KEY,          -- 'bacen_copom'
  display_name  text NOT NULL,
  publisher     text NOT NULL,                  -- quem assina o documento (atribuição da licença)
  base_url      text,
  license_note  text NOT NULL,                  -- o que a licença permite; sem isto não se cita
  is_official   boolean NOT NULL DEFAULT true,  -- órgão público vs. imprensa/terceiro
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE docs.sources IS
  '[F13a] Origem de documento citável. `license_note` é obrigatória: sem licença declarada, não se redistribui trecho.';

-- ---------------------------------------------------------------- documentos
CREATE TABLE docs.documents (
  id                  uuid PRIMARY KEY DEFAULT core.new_id(),
  source_code         core.slug NOT NULL REFERENCES docs.sources(code),
  kind                docs.document_kind NOT NULL,
  external_id         text NOT NULL,            -- id no emissor (ex.: nro_reuniao do Copom)
  title               text NOT NULL,
  published_on        date NOT NULL,            -- data DO DOCUMENTO, nunca a do relógio da ingestão
  url                 text,
  body_text           text,                     -- NULL = licença não permite armazenar
  body_sha256         core.hash_hex,
  lang                char(2) NOT NULL DEFAULT 'pt',
  ingestion_batch_id  uuid REFERENCES market.ingestion_batches(id),
  review_status       docs.review_status NOT NULL DEFAULT 'pendente',
  reviewed_by         uuid REFERENCES identity.users(id),
  reviewed_at         timestamptz,
  vocabulario_achados text[] NOT NULL DEFAULT '{}',   -- termos vetados (RCVM 19) achados no texto
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT documents_natural_uk UNIQUE (source_code, kind, external_id),
  -- texto guardado sem hash não é evidência: não há como provar que não mudou
  CONSTRAINT body_has_hash CHECK (body_text IS NULL OR body_sha256 IS NOT NULL),
  -- RCVM 19: o que tem termo vetado não vira material citável, nem com revisor e trilha
  CONSTRAINT aprovado_sem_vocabulario_vetado CHECK (
    review_status <> 'aprovado' OR cardinality(vocabulario_achados) = 0
  )
);
CREATE INDEX documents_fonte_data_idx ON docs.documents (source_code, published_on DESC);
CREATE INDEX documents_citavel_idx ON docs.documents (published_on DESC)
  WHERE review_status = 'aprovado';
COMMENT ON TABLE docs.documents IS
  '[F13a] Documento externo com texto congelado e hash — a origem dos findings `documentary`. Aprovado é imutável.';
COMMENT ON COLUMN docs.documents.published_on IS
  '[F13a] Data do DOCUMENTO (as_of), nunca a da ingestão — é ela que vai para a citação do cliente.';

-- ---------------------------------------------------------------- trilha de revisão
CREATE TABLE docs.document_reviews (
  id          uuid PRIMARY KEY DEFAULT core.new_id(),
  document_id uuid NOT NULL REFERENCES docs.documents(id) ON DELETE CASCADE,
  decision    docs.review_status NOT NULL,
  reviewer_id uuid REFERENCES identity.users(id),
  notes       text,
  decided_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX document_reviews_doc_idx ON docs.document_reviews (document_id, decided_at DESC);
CREATE TRIGGER document_reviews_append_only BEFORE UPDATE OR DELETE ON docs.document_reviews
  FOR EACH ROW EXECUTE FUNCTION core.forbid_update_delete();
COMMENT ON TABLE docs.document_reviews IS
  '[F13a] Trilha append-only de curadoria: quem decidiu, o quê e quando. Espelha content.compliance_reviews.';

-- ---------------------------------------------------------------- a janela do agente
CREATE VIEW docs.v_documentos_citaveis WITH (security_invoker = true) AS
SELECT d.id, d.source_code, s.display_name AS fonte, s.publisher, s.license_note,
       d.kind, d.external_id, d.title, d.published_on, d.url, d.body_text, d.lang, d.reviewed_at
FROM docs.documents d
JOIN docs.sources s ON s.code = d.source_code
WHERE d.review_status = 'aprovado' AND s.is_active;
COMMENT ON VIEW docs.v_documentos_citaveis IS
  '[F13a] Documento aprovado de fonte ativa — única fonte da tool `contexto.documento_oficial`.';

-- ---------------------------------------------------------------- REGRA INVIOLÁVEL (T73–T77)
CREATE OR REPLACE FUNCTION docs.assert_document_review() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_mudou_status boolean := (TG_OP = 'INSERT') OR (OLD.review_status IS DISTINCT FROM NEW.review_status);
  v_era_aprovado boolean := (TG_OP = 'UPDATE') AND OLD.review_status = 'aprovado';
BEGIN
  -- (a) aprovar exige revisor identificado
  IF NEW.review_status = 'aprovado' AND (NEW.reviewed_by IS NULL OR NEW.reviewed_at IS NULL) THEN
    RAISE EXCEPTION 'Documento % aprovado sem revisor identificado (reviewed_by/reviewed_at)', NEW.external_id
      USING ERRCODE = '23514';
  END IF;

  -- (b) texto aprovado é imutável: o cliente não lê hoje algo diferente do que foi aprovado
  IF v_era_aprovado AND NOT v_mudou_status
     AND (OLD.title IS DISTINCT FROM NEW.title
          OR OLD.body_text IS DISTINCT FROM NEW.body_text
          OR OLD.url IS DISTINCT FROM NEW.url) THEN
    RAISE EXCEPTION 'Documento % está aprovado: reabra a revisão antes de alterar título, corpo ou url', NEW.external_id
      USING ERRCODE = '23514';
  END IF;

  -- (c) entrar OU sair de aprovado exige trilha nesta transação, com a mesma decisão
  IF v_mudou_status AND (NEW.review_status = 'aprovado' OR v_era_aprovado) THEN
    IF NOT EXISTS (
      SELECT 1 FROM docs.document_reviews r
      WHERE r.document_id = NEW.id
        AND r.decision = NEW.review_status
        AND r.decided_at >= transaction_timestamp()
    ) THEN
      RAISE EXCEPTION 'Documento % → % sem trilha em docs.document_reviews nesta transação',
        NEW.external_id, NEW.review_status USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER documents_review_gate BEFORE INSERT OR UPDATE ON docs.documents
  FOR EACH ROW EXECUTE FUNCTION docs.assert_document_review();
COMMENT ON FUNCTION docs.assert_document_review() IS
  '[F13a] Gate: aprovar/reabrir documento exige revisor e trilha na mesma transação; texto aprovado é imutável.';

-- ---------------------------------------------------------------- família de tool `contexto`
-- O valor novo do enum NÃO é usado nesta transação (allowed_tool_families é text[]); quem o usa é
-- o `tools sync`, depois do commit. Fosse usado aqui, o PostgreSQL recusaria.
ALTER TYPE tools.tool_family ADD VALUE IF NOT EXISTS 'contexto';

UPDATE agents.agent_definitions
   SET allowed_tool_families = allowed_tool_families || ARRAY['contexto']
 WHERE code IN ('analista', 'assessor')
   AND NOT ('contexto' = ANY(allowed_tool_families));

-- ---------------------------------------------------------------- seeds de fonte
INSERT INTO docs.sources (code, display_name, publisher, base_url, license_note, is_official)
VALUES ('bacen_copom', 'Banco Central · Copom', 'Banco Central do Brasil',
        'https://www.bcb.gov.br/api/servico/sitebcb/copom',
        'Portal de Dados Abertos do BCB — Open Data Commons Open Database License (ODbL): '
        'uso, redistribuição e trecho permitidos com atribuição à fonte.', true)
ON CONFLICT (code) DO NOTHING;

-- lote de ingestão reusa market.ingestion_batches, cujo source_code aponta para market.data_sources
INSERT INTO market.data_sources (code, display_name, cadence, base_url, license_note)
VALUES ('bacen_copom', 'Banco Central · Copom (documentos)', 'eventual',
        'https://www.bcb.gov.br/api/servico/sitebcb/copom',
        'Dados abertos do BCB sob ODbL; atribuição obrigatória.')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------- privilégios
-- Primeiro schema depois da 28: os cinco statements que aquele DO $$ faria são emitidos aqui.
GRANT USAGE ON SCHEMA docs TO plexo_app, plexo_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA docs TO plexo_app, plexo_service;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA docs TO plexo_app, plexo_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA docs
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO plexo_app, plexo_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA docs
  GRANT USAGE, SELECT ON SEQUENCES TO plexo_app, plexo_service;

-- O REVOKE derivado do catálogo (28:71-88) também já rodou: append-only novo se fecha à mão.
REVOKE UPDATE, DELETE ON docs.document_reviews FROM plexo_app, plexo_service;
-- A API lê documento; quem escreve e cura é o serviço (ingestão e CLI).
REVOKE INSERT, UPDATE, DELETE ON docs.documents FROM plexo_app;
REVOKE INSERT, UPDATE, DELETE ON docs.sources   FROM plexo_app;

COMMIT;
