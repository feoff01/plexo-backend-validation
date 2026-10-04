-- =============================================================================
-- PLEXO · 51_orcamento_da_sintese.sql — o turno ficava sem tokens para redigir [F18]
--
-- O DEFEITO, MEDIDO NA CONVERSA REAL DE UM CLIENTE
--
-- Três vezes o Copiloto respondeu "Medi o que coube neste turno … mas não consegui redigir a
-- leitura". O guardrail `sintese_vazia` está gravado três vezes em `agents.guardrail_events`,
-- e sempre nos turnos com MAIS medições. Não era o modelo se recusando: era falta de orçamento.
--
--   `turn.py` pede cada chamada com `max_output_tokens = min(budget.tokens_restantes(), …)`,
--   e `tokens_restantes()` é `max_output_tokens_por_turno − o que já se gastou NO TURNO`.
--
--   O provedor é um modelo que RACIOCINA, e o `reasoning_content` conta como saída. Cada
--   chamada de parametrização de tool queima de mil a três mil tokens só pensando. Com quatro
--   tools em cadeia — que é o que a política permite —, os 4.000 originais (e mesmo os 6.000
--   da v3) acabam ANTES da última chamada, a que escreve a resposta.
--
--   Quem paga é sempre a síntese, porque ela é a última. O cliente faz a pergunta mais
--   difícil, o sistema mede quatro coisas para responder bem, e é exatamente aí que ele
--   emudece. Quanto melhor a pergunta, maior a chance de não haver resposta.
--
-- DUAS MUDANÇAS, E A SEGUNDA É A QUE IMPORTA
--
--   (1) `max_output_tokens_por_turno` sobe de 6.000 para 14.000. Quatro parametrizações com
--       raciocínio mais dois reparos mais a redação não cabem em seis mil.
--
--   (2) `reserva_para_sintese_tokens` — a parte estrutural. Subir o teto sozinho só empurra o
--       problema para a pergunta seguinte: qualquer teto acaba se o consumo anterior não tiver
--       limite. A reserva é um piso INTOCÁVEL: enquanto o turno está encadeando tools, o
--       orçamento oferecido a cada chamada é `restante − reserva`. A última chamada, a que
--       redige, recebe o restante inteiro — e a reserva garante que "o restante inteiro" nunca
--       seja zero.
--
--       É a mesma ideia de `budget.income_summaries.committable_brl`: não se compromete tudo
--       o que se tem, porque a última conta do mês ainda não chegou.
--
-- Depende de: 19_llm.
-- =============================================================================

BEGIN;

-- UMA instrução só, com CTE que modifica dados: `policy_one_current` garante uma vigente por
-- código, então fechar e abrir têm que acontecer no mesmo passo — e a CTE enxerga o retrato do
-- início da instrução, que é justamente o que permite ler a vigente enquanto ela é encerrada.
--
-- A primeira tentativa selecionava `version = 3`, que vem de `seeds/dev.sql` e NÃO de
-- migration. Num banco limpo o seed ainda não rodou quando o Alembic chega aqui: a v1 era
-- encerrada, nada era criado, e a política ficava sem versão vigente — todo turno morria em
-- seguida, e o CI acusou 50 falhas. **Migration não pode depender de linha que um seed cria
-- depois dela.**
WITH atual AS (
  SELECT payload, compliance_status, approved_by, approved_at
    FROM engine.policy_versions
   WHERE code = 'LLM_BUDGETS' AND effective_to IS NULL
), proxima AS (
  SELECT coalesce(max(version), 0) + 1 AS v
    FROM engine.policy_versions WHERE code = 'LLM_BUDGETS'
), fechada AS (
  UPDATE engine.policy_versions SET effective_to = now()
   WHERE code = 'LLM_BUDGETS' AND effective_to IS NULL
  RETURNING 1
)
INSERT INTO engine.policy_versions (code, version, payload, compliance_status,
                                    approved_by, approved_at)
SELECT 'LLM_BUDGETS', proxima.v,
       atual.payload
       || jsonb_build_object(
            'max_output_tokens_por_turno', 14000,
            -- Piso reservado para a redação final. Uma resposta do Assessor com diagnóstico,
            -- tabela e ressalvas fica entre 600 e 1.200 tokens; 2.500 cobre com folga o caso
            -- em que o modelo também raciocina antes de escrever.
            'reserva_para_sintese_tokens', 2500,
            '_nota_51',
            'A reserva é subtraída do orçamento oferecido às chamadas de PARAMETRIZAÇÃO de '
            'tool; a chamada de SÍNTESE recebe o restante inteiro. Sem ela, o turno com mais '
            'medições — o da pergunta mais difícil — era justamente o que ficava sem tokens '
            'para responder, e o cliente recebia "não consegui redigir a leitura".'),
       atual.compliance_status, atual.approved_by, atual.approved_at
  FROM atual, proxima
 WHERE EXISTS (SELECT 1 FROM fechada);

COMMIT;
