# Checkpoint — FQ5.6 comparáveis por setor promoção GREEN

Data: 2026-10-03
Estado: **GREEN / pública / encerrada**

## Capability
- `quant.comparaveis_setor` 1.0.1;
- `exposed_to_llm=True`;
- subsetor = default;
- setor = opt-in;
- segmento não suportado nesta versão;
- comparação descritiva, sem ranking/recomendação/fair value.

## Fontes e universo
- classificação setorial: B3 oficial;
- universo operacional atual: IBrA B3 de 02/10/2026;
- 148 componentes no snapshot;
- coverage cruzada com classificação B3: 146/148 tickers e 142/144 company codes;
- gaps conhecidos: RIAA3 e SAUD3;
- snapshots atuais não são tratados como histórico retroativo.

## Reuso
A tool não possui matemática própria de valuation/crescimento:
- valuation = `quant.valor_mercado`;
- tendências = `quant.tendencias_fundamentais`;
- distribuição = `statistics.describe`;
- peers = loader setorial company-level.

## Performance
Baseline run #145:
- 2/8/20 peers = 38/98/218 queries.

Batch run #157:
- 2/8/20 peers = 10/10/10 queries;
- output ~4 KB;
- equivalência resolved/output contra preparadores canônicos GREEN;
- suíte 886 passed, 52 skipped, 19 warnings.

Regression gate:
- prepare_query_count <= 12;
- output_payload_bytes < 5000.

## Promoção
Run #170 / `37133499914`: success.
- gate explícito: 128 passed;
- benchmark: 3 passed;
- 2 peers: 10 queries / 4009 bytes;
- 8 peers: 10 queries / 4171 bytes;
- 20 peers: 10 queries / 4163 bytes;
- suíte completa: 889 passed, 52 skipped, 19 warnings, 0 failed;
- PostgreSQL 18/migrations/invariantes: verdes;
- prompts check: verde;
- tools sync --check: verde.

## Planner / apresentação
- planner direciona perguntas de comparação com pares para a tool;
- não usa a tool para escolher "melhor ação";
- bloco client-facing mostra alvo, mediana, diferença e N válido;
- mediana não é fair value;
- tabela completa de peers não vai ao bloco/LLM.

## Isolamento
Diff de promoção contra o estado batch GREEN altera somente:
- documentação .ai;
- planner;
- bloco;
- `quant.comparaveis_setor`;
- testes/gate da própria promoção.

Nenhuma outra tool teve código-fonte/dependências alterados nesta promoção.

## Próximo passo
FQ5.6 está encerrada. Antes da próxima capability, aplicar novamente o gate reuse-before-build.
