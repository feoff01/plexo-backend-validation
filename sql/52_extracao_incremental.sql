-- =============================================================================
-- PLEXO · 52_extracao_incremental.sql — a conversa que volta a ser escrita [F18]
--
-- O QUE MUDOU NO PRODUTO, E O QUE ISSO QUEBRAVA AQUI
--
-- Até agora uma conversa encerrada era só-leitura para sempre: escrever nela devolvia erro, e
-- não havia caminho de reabertura em lugar nenhum. Trinta minutos de silêncio bastavam para o
-- job de inatividade fechá-la, então quem voltasse no dia seguinte para continuar de onde
-- parou recomeçava do zero — perdendo o contexto que a conversa carregava.
--
-- Escrever passa a REABRIR. E isso quebra uma premissa desta camada: o índice
-- `extraction_one_success` garante UM lote bem-sucedido por conversa, porque "concluir duas
-- vezes sobre o mesmo diálogo não faz sentido" (39). Verdade — mas uma conversa reaberta e
-- continuada não é mais o mesmo diálogo. Com a regra antiga, tudo o que fosse dito depois da
-- reabertura NUNCA seria lido pela extração em lote: o cliente contaria uma mudança de vida e
-- o contexto não saberia. Silenciosamente, que é a pior forma.
--
-- A CORREÇÃO: O RUN PASSA A DIZER ATÉ ONDE LEU
--
-- `ate_seq` registra a última mensagem coberta. A unicidade deixa de ser "um sucesso por
-- conversa" e passa a ser "um sucesso por TRECHO" — reprocessar o mesmo trecho continua
-- proibido, e ler o que veio depois passa a ser possível. É a mesma ideia de um marcador de
-- página: o livro pode crescer; o que já foi lido não se relê.
--
-- Depende de: 21_context, 39_live_extraction.
-- =============================================================================

BEGIN;

ALTER TABLE context.extraction_runs
  ADD COLUMN ate_seq int CHECK (ate_seq IS NULL OR ate_seq >= 0);

COMMENT ON COLUMN context.extraction_runs.ate_seq IS
  '[F18] Última `agents.messages.seq` coberta por este run. NULL nos runs anteriores à '
  'reabertura de conversas, que por definição cobriram o diálogo inteiro até então.';

-- Um sucesso por TRECHO, não por conversa. `ate_seq` NULL preserva a regra antiga para o
-- histórico: aqueles runs cobriram tudo o que existia, e continuam sendo únicos.
DROP INDEX context.extraction_one_success;
CREATE UNIQUE INDEX extraction_one_success
  ON context.extraction_runs (conversation_id, coalesce(ate_seq, -1))
  WHERE status = 'succeeded' AND kind = 'pos_conversa';

COMMENT ON INDEX context.extraction_one_success IS
  '[F18] Reprocessar o mesmo trecho continua proibido; ler o que foi dito DEPOIS de uma '
  'reabertura passa a ser possível. Antes, tudo o que viesse após reabrir ficava invisível '
  'para a extração em lote — e o contexto do cliente parava de aprender sem avisar ninguém.';

COMMIT;
