-- =============================================================================
-- PLEXO · 53_reconciliacao_da_carteira.sql — o agregado não pode mentir sobre o detalhe [F19]
--
-- O DEFEITO QUE ORIGINOU ESTA MIGRATION
--
-- Em 2026-08-30, na conta de demonstração, a pergunta "devo vender alguma das minhas ações?"
-- produziu duas afirmações incompatíveis dentro do MESMO turno:
--
--   · o prompt do agente recebia "Patrimônio — investível: R$ 780.000,00", montado por
--     `app/tools/context_pack.py` a partir de `estate.v_net_worth`, que por sua vez lê
--     `wealth.portfolio_snapshots`;
--   · a tool `planejamento.composicao_patrimonio` devolvia "não há posição registrada no
--     escopo", porque `wealth.holdings_snapshots` estava vazia para aquele escopo.
--
-- Dois caminhos para o mesmo fato — quanto o cliente tem investido — e nada, em lugar nenhum,
-- obrigando os dois a concordarem. O modelo teve de administrar a contradição sozinho, e não
-- havia resposta certa a dar: um dos dois números estava errado e o sistema não sabia qual.
--
-- A REGRA: HAVENDO DETALHE, O AGREGADO É O DETALHE
--
-- `portfolio_snapshots` é, pelo próprio COMMENT da 05, um ROLLUP — existe para a Barra de Rumo
-- não varrer partição de holdings a cada page load. Rollup que discorda da fonte que resume
-- não é uma imprecisão de cache: é um número que chega ao prompt do agente e à tela do cliente
-- afirmando algo que a carteira não diz.
--
-- A recíproca NÃO vale, e é isso que mantém o repositório inteiro válido: um escopo pode
-- declarar o total sem ter aberto a carteira ainda. É como vivem as seis personas da F16 e
-- como viveu a conta de demonstração até aqui. A regra é "havendo detalhe, o agregado é o
-- detalhe" — nunca "todo agregado exige detalhe", que seria proibir o cliente de dizer quanto
-- tem antes de listar onde está.
--
-- POR QUE NO BANCO, E NÃO NO SERVIÇO
--
-- Porque o único escritor de `holdings_snapshots` do repositório hoje é um arquivo de seed, e
-- o próximo será um importador de extrato — mais um caminho de escrita, e depois o Open
-- Finance, e depois um script de suporte. É o mesmo argumento do `action_five_blocks` da 06:
-- regra que vive só no serviço vaza no primeiro backfill.
--
-- Efeito colateral desejado: quem escreve passa a ser OBRIGADO a inserir as posições antes do
-- rollup, como `household.members_titular_gate` já obriga membership antes do titular. A ordem
-- deixa de ser convenção de seed e passa a ser imposta.
--
-- SOBRE A TOLERÂNCIA DE UM CENTAVO
--
-- `value_brl` é `core.money_brl` = numeric(18,2) e `total_brl` também. A soma de duas colunas
-- de duas casas é exata em numeric — não há erro de ponto flutuante a absorver. O centavo
-- existe só para o caso de o produtor arredondar a soma antes de gravar, e é deliberadamente
-- pequeno: dois centavos já são recusados, porque a diferença que importa aqui não é de
-- magnitude, é de procedência. Um total que ninguém consegue refazer somando a carteira é um
-- total sem origem.
--
-- Depende de: 05_wealth (holdings_snapshots, portfolio_snapshots).
-- Testes: tests/test_regras_invioláveis_carteira.sql (T117–T120).
-- =============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION wealth.assert_rollup_bate_com_posicoes() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_soma  numeric(18,2);
  v_itens bigint;
BEGIN
  -- Uma varredura só, pelo índice (scope_id, as_of_date DESC) que a 05 já criou.
  SELECT coalesce(sum(h.value_brl), 0), count(*)
    INTO v_soma, v_itens
    FROM wealth.holdings_snapshots h
   WHERE h.scope_id = NEW.scope_id
     AND h.as_of_date = NEW.as_of_date;

  -- Sem detalhe no dia, o agregado é a única fonte e vale como declarado.
  IF v_itens = 0 THEN
    RETURN NEW;
  END IF;

  IF abs(NEW.total_brl - v_soma) > 0.01 THEN
    RAISE EXCEPTION
      'Rollup do escopo % em % afirma R$ % mas as % posição(ões) registradas somam R$ %',
      NEW.scope_id, NEW.as_of_date, NEW.total_brl, v_itens, v_soma
      USING ERRCODE = 'check_violation',
            HINT = 'O agregado resume o detalhe: grave as posições primeiro e derive o total delas.';
  END IF;

  RETURN NEW;
END $$;

COMMENT ON FUNCTION wealth.assert_rollup_bate_com_posicoes() IS
  '[F19] Havendo posição para (scope_id, as_of_date), `portfolio_snapshots.total_brl` tem de '
  'ser a soma delas. Nasceu do defeito de 2026-08-30, em que o prompt do agente recebia '
  '"investível R$ 780.000" e a tool de composição, no mesmo turno, respondia "não há posição '
  'registrada no escopo". A recíproca não vale: agregado sem detalhe continua válido.';

CREATE TRIGGER portfolio_snapshots_reconciliacao
  BEFORE INSERT OR UPDATE ON wealth.portfolio_snapshots
  FOR EACH ROW EXECUTE FUNCTION wealth.assert_rollup_bate_com_posicoes();

COMMIT;
