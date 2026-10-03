# Decisão de policy — rolling volatility de quant.risco_retorno 1.2.0

Data: 2026-10-03
Estado: **implementada / GREEN em CI**
Policy: `ANALISE_PARAMS.risco_janela_movel_observacoes`

## Valor inicial governado

`risco_janela_movel_observacoes = 21`.

A unidade é **observações de retorno**, não dias corridos.

## Racional

- representa aproximadamente um mês de pregões sem converter datas civis em uma falsa quantidade de observações;
- é menor que o `min_observacoes=30` padrão atual, portanto a capability geral continua exigindo uma base histórica mais ampla do que uma única janela rolling;
- mantém sensibilidade suficiente para perguntas de evolução histórica sem transformar o default em uma janela longa escondida;
- é policy client-facing e pode ser recalibrada/versionada sem deploy.

Esse número **não é verdade estatística universal, forecast nem limiar de recomendação**. É somente o default operacional quando o cliente pede evolução de volatilidade sem informar uma janela.

## Precedência

1. Se o usuário informar `janela_volatilidade_observacoes`, usar exatamente o valor informado.
2. Se pedir evolução e omitir a janela, ler `ANALISE_PARAMS.risco_janela_movel_observacoes`.
3. Se não pedir evolução, não calcular rolling e não consumir a policy como premissa adicional.
4. Nunca converter automaticamente dias corridos em observações.

## Compliance

- o seed `ANALISE_PARAMS` passa a carregar o campo com valor 21;
- em banco descartável de CI, `tools/preparar_ambiente.py` aprova `ANALISE_PARAMS` pelo fluxo já existente;
- em produção, alteração/aprovação da policy continua sendo ato explícito de compliance; este commit não substitui aprovação humana de produção.

## Gate

Com esta decisão congelada, o cutover 1.2.0 pode prosseguir:
- replay 1.1.0 em módulo legacy;
- contrato canônico aditivo;
- planner/bloco/evals;
- PostgreSQL 18 + payload/readiness + full suite;
- promoção somente após GREEN.

## Resultado

Implementada na `quant.risco_retorno` 1.2.0 e validada no run #334 / `37162747600`.
