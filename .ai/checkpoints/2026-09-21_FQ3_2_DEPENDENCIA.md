# Checkpoint — FQ3.2 `quant.dependencia`

Data: 2026-09-21

## Entregue
- tool canônica `quant.dependencia`;
- ativo×ativo e ativo×índice/taxa;
- Pearson e Spearman;
- lag assinado em observações comuns;
- default de ativos em `adjusted_close`;
- output compacto + Evidencia;
- warnings para ativo desconhecido/fora de cobertura/índice desconhecido;
- source fingerprint cobrindo Data Foundation + Quant Core relevante.

## Decisões
- rolling/up-down-market não entram no schema inicial; ficam para FQ4;
- índice/taxa não recebe price basis;
- base dos ativos determina temporal semantics via Data Foundation;
- `as_of` usa o último par efetivamente utilizado após lag.

## Validação shadow
- 12/12 testes FQ3.2 verdes antes do cutover.

## Continuação
FQ3.3 promoveu a tool de `1.0.0` shadow para `1.0.1` exposta após validação.
