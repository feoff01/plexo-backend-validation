# Checkpoint — FQ5.7 Yield Curve Foundation GREEN

Data: 2026-10-03
Estado: **GREEN / fundação shadow / sem tool pública**

## Implementação
- `app/market/yield_curve_ingest.py`: ingestão semântica append-only da ETTJ ANBIMA;
- curvas canônicas: `ettj_pre`, `ettj_ipca`, `inflacao_implicita`;
- source fixa: `anbima`;
- dataset: `anbima.yield_curve.ettj@1`;
- `business_days = vertice_du`;
- `day_count = du_252`;
- `calendar_days = NULL`;
- taxas normalizadas à precisão `numeric(12,6)` antes do gate de idempotência/conflito;
- `app/market/yield_curves.py`: loader latest/reference_date com strict PIT por lote `succeeded` + `finished_at`;
- sem interpolação, extrapolação, transformação de day-count, slope, DV01 ou tool pública;
- sem migration nova e sem cliente HTTP/OAuth.

## Gates
Commit validado: `bbb0ae0be7c01ffbd693c441188bd7363ca3d0d5`
Run: #192 / `37135247818`
Conclusão: success

- gate explícito: **135 passed**;
- benchmark FQ5.6 preservado: 10/10/10 queries para 2/8/20 peers;
- suíte completa: **896 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: verde;
- tools sync --check: verde;
- 35 tools inalteradas.

## Correção durante o gate
Run #191 falhou em um teste FQ5.7 porque o teste consultava strict PIT com cutoff em 2026-10-02, enquanto o lote havia sido finalizado pelo CI em 2026-10-03.

A implementação estava correta: uma curva histórica só pode aparecer depois de `finished_at`. O teste foi corrigido para consultar o mesmo `reference_date=2026-10-02` com cutoff em 2026-10-03. Nenhuma regra de domínio foi afrouxada.

## Estado funcional
A fundação de curva está pronta para receber payload físico autorizado, mas não existe capability pública de curva ainda.

Próximo gate:
1. localizar/materializar payload real ANBIMA ou export oficial equivalente já fornecido/autorizado;
2. congelar o adapter físico contra bytes reais;
3. medir cobertura histórica efetiva;
4. só então decidir primeira intenção client-facing sob reuse-before-build.
