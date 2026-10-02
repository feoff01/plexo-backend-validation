# Checkpoint — FQ5.6 IBrA universe GREEN

Data: 2026-10-02
Estado: **GREEN / universo operacional atual**

## Fonte observada
- `IBRADia_02-10-26.csv`: 148 componentes, peso total 100,000%, quantidade teórica total 107.192.487.383;
- referência explícita: 2026-10-02;
- `AcoesIndices_2026-10-02.csv` e o XLSX multiíndice confirmam exatamente os mesmos 148 componentes;
- arquivos são snapshots atuais, não histórico.

## Implementação
- migration 0064 registra `ibra`;
- parser fail-closed do CSV diário B3;
- ingestão append-only em `market.index_weights`;
- matching exato de ticker e proibição de snapshot parcial succeeded;
- projeção auditável de `is_in_universe` somente para `kind='acao'`;
- ETFs/FIIs/BDRs não são alterados;
- membership histórico fica em `index_weights`; booleano é apenas estado operacional atual.

## Coverage externa observada
Contra o XLSX oficial de classificação setorial B3:
- 146/148 tickers IBrA classificados = 98,65%;
- 142/144 company codes classificados = 98,61%;
- gaps: `RIAA3` e `SAUD3`;
- gaps não são imputados por Economatica.

## CI
Código corrigido: `3d0a0f849ab32a8e58f031096890a69d4151a2bc`
Run #131 / `37067155192`: success.
- migration 0064 do zero: verde;
- validador/invariantes admin/service: verdes;
- gate explícito: 124 passed;
- suíte completa: 882 passed, 52 skipped, 19 warnings, 0 failed;
- prompts check: verde;
- tools sync --check: verde;
- 35 tools inalteradas.

Run #130 falhou apenas porque o audit trail tentou gravar uma chave textual em `audit.activity_log.object_id` UUID. A correção deixou `object_id=NULL` e manteve índice/data/batches em details; nenhuma regra de domínio mudou.

## Próximo gate
Benchmark de performance/payload de `quant.comparaveis_setor`. A tool continua shadow até esse gate e o fechamento de promoção.
